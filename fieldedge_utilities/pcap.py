"""A utility to parse and generate relevant metrics for analysis of a PCAP file.

Uses the `pyshark` package for capture and analysis.

* Goal is WAN data reduction, focus is on packet size and application type.
* Ignore/filter out local traffic e.g. ARP
* Identify repeating patterns based on size and application protocol
to derive an interval...can it be done less frequently or by proxy?
e.g. DNS cache, local NTP
* If payload can be read (unencrypted) does it change often...could threshold
report by exception be used with a less frequent update pushed?

"""
import asyncio
import json
import logging
import os
from multiprocessing import Queue
from datetime import datetime
from enum import Enum

import pyshark
from pyshark.packet.packet import Packet as SharkPacket

from fieldedge_utilities.logger import get_wrapping_logger
from fieldedge_utilities.path import clean_path


# Ethernet packet types
class EthernetProtocol(Enum):
    """Mappings for Ethernet packet types."""
    ETH_TYPE_EDP = 0x00bb  # Extreme Networks Discovery Protocol
    ETH_TYPE_PUP = 0x0200  # PUP protocol
    ETH_TYPE_IP = 0x0800  # IP protocol
    ETH_TYPE_ARP = 0x0806  # address resolution protocol
    ETH_TYPE_AOE = 0x88a2  # AoE protocol
    ETH_TYPE_CDP = 0x2000  # Cisco Discovery Protocol
    ETH_TYPE_DTP = 0x2004  # Cisco Dynamic Trunking Protocol
    ETH_TYPE_REVARP = 0x8035  # reverse addr resolution protocol
    ETH_TYPE_8021Q = 0x8100  # IEEE 802.1Q VLAN tagging
    ETH_TYPE_8021AD = 0x88a8  # IEEE 802.1ad
    ETH_TYPE_QINQ1 = 0x9100  # Legacy QinQ
    ETH_TYPE_QINQ2 = 0x9200  # Legacy QinQ
    ETH_TYPE_IPX = 0x8137  # Internetwork Packet Exchange
    ETH_TYPE_IP6 = 0x86DD  # IPv6 protocol
    ETH_TYPE_PPP = 0x880B  # PPP
    ETH_TYPE_MPLS = 0x8847  # MPLS
    ETH_TYPE_MPLS_MCAST = 0x8848  # MPLS Multicast
    ETH_TYPE_PPPOE_DISC = 0x8863  # PPP Over Ethernet Discovery Stage
    ETH_TYPE_PPPOE = 0x8864  # PPP Over Ethernet Session Stage
    ETH_TYPE_LLDP = 0x88CC  # Link Layer Discovery Protocol
    ETH_TYPE_TEB = 0x6558  # Transparent Ethernet Bridging

# Common/registered IP protocol ports
class ApplicationPort(Enum):
    """Mappings for application layer ports."""
    TCP_PORT_SMTP = 25
    TCP_PORT_HTTP = 80
    TCP_PORT_HTTPS = 443
    TCP_PORT_DNS = 53
    TCP_PORT_FTP = 20
    TCP_PORT_FTPC = 21
    TCP_PORT_TELNET = 23
    TCP_PORT_IMAP = 143
    TCP_PORT_RDP = 3389
    TCP_PORT_SSH = 22
    TCP_PORT_HTTP2 = 8080
    TCP_PORT_MODBUS = 502
    TCP_PORT_MODBUSSEC = 802
    TCP_PORT_MQTT = 1883
    TCP_PORT_MQTTS = 8883
    TCP_PORT_DOCKERAPI = 2375
    TCP_PORT_DOCKERAPISSL = 2376
    TCP_PORT_SRCP = 4303
    TCP_PORT_COAP = 5683
    TCP_PORT_COAPS = 5684
    TCP_PORT_DNP2 = 19999
    TCP_PORT_DNP = 20000
    TCP_PORT_IEC60870 = 2404
    UDP_PORT_SNMP = 161
    UDP_PORT_DNS = 53
    UDP_PORT_DHCPQ = 67
    UDP_PORT_DHCPR = 68
    UDP_PORT_NTP = 123


def _get_src_dst(packet: SharkPacket) -> tuple:
    """Returns the packet source and destination hosts as a tuple.
    
    Args:
        packet: A pyshark Packet
    
    Returns:
        A tuple with (source, destination) IP addresses
    """
    if hasattr(packet, 'arp'):
        return (packet.arp.src_proto_ipv4, packet.arp.dst_proto_ipv4)
    elif hasattr(packet, 'ip'):
        return (packet.ip.src, packet.ip.dst)
    else:
        raise NotImplementedError(f'Unable to determine src/dst'
                                  f' for {packet.highest_layer}')


def _get_ports(packet: SharkPacket) -> tuple:
    """Returns the transport source and destination ports as a tuple.
    
    Args:
        packet: A pyshark Packet

    Returns:
        A tuple with (source, destination) ports (TCP or UDP)
    """
    transport_layer = packet[packet.transport_layer]
    return (int(transport_layer.srcport), int(transport_layer.dstport))


def _shorthand(const_name: str) -> str:
    """Converts a long-form name from constants module to tshark protocol name.
    
    Args:
        const_name: The long form name from the constants module.
    
    Returns:
        A shorthand name e.g. `MQTT`
    """
    lowername = const_name.lower()
    if 'mqtt' in lowername:
        return 'MQTT'
    return lowername.split('_')[2].upper()


def _get_application(packet: SharkPacket) -> str:
    """Returns the application layer descriptor.
    
    If the port is a registered port it will return a caps string.

    Args:
        packet: A pyshark Packet

    Returns:
        A string with the application layer protocol e.g. `TCP_PORT_MQTTS`
    """
    if hasattr(packet[packet.highest_layer], 'app_data_proto'):
        return str(packet[packet.highest_layer].app_data_proto).upper()
    else:
        (srcport, dstport) = _get_ports(packet)
        known_ports = tuple(item.value for item in ApplicationPort)
        if srcport in known_ports:
            return _shorthand(ApplicationPort(srcport).name)
        if dstport in known_ports:
            return _shorthand(ApplicationPort(dstport).name)
        return str(packet.highest_layer).upper()


def is_valid_ip(ip_addr: str) -> bool:
    """Returns true if the string represents a valid IPv4 address.
    
    Args:
        ip_addr: The IP address being qualified
    
    Returns:
        True if it has 4 parts separated by `.` with each part in range 0..255
    """
    if not(isinstance(ip_addr, str)):
        return False
    if (len(ip_addr.split('.')) == 4 and
        (int(x) in range (0,256) for x in ip_addr.split('.'))):
        return True
    return False


def is_private_ip(ip_addr: str) -> bool:
    """Returns true if the IPv4 address is in the private range.
    
    Args:
        ip_addr: The IP address being qualified
    
    Returns:
        True if the address is in the private range(s)
    
    Raises:
        ValueError if the address is invalid
    """
    if not is_valid_ip(ip_addr):
        raise ValueError(f'IP address must be a valid IPv4 x.x.x.x')
    if (ip_addr.startswith('10.') or
        (ip_addr.startswith('172.') and
        int(ip_addr.split('.')[1]) in range(16, 32)) or
        ip_addr.startswith('192.168.')):
        return True
    return False


def _is_local_traffic(packet: SharkPacket) -> bool:
    """Returns true if the source and destination addresses are on the LAN.
    
    Args:
        packet: A pyshark Packet capture
    
    Returns:
        True if both addresses are in the LAN range 192.168.x.y 
    """
    src, dst = _get_src_dst(packet)
    if ((src.startswith('192.168.') and dst.startswith('192.168.'))):
        return True
    return False


class SimplePacket:
    """A simplified packet representation.
    
    Attributes:
        a_b (bool): Direction of travel relative to parent conversation
        application (str): The analysis-derived application
        highest_layer (str): The highest Wireshark-derived packet layer
        timestamp (float): The unix timestamp of the capture to 3 decimal places
        size (int): Size in bytes
        transport (str): The transport type
        src (str): Source IP address
        dst (str): Destination IP address
        srcport (int): Source port
        dstport (int): Destination port

    """
    def __init__(self, packet: SharkPacket, parent_hosts: tuple) -> None:
        self._parent_hosts = parent_hosts
        self.timestamp = round(float(packet.sniff_timestamp), 3)
        self.size = int(packet.length)
        self.transport = packet.transport_layer
        self.src, self.dst = _get_src_dst(packet)
        self.srcport = int(packet[self.transport].srcport)
        self.dstport = int(packet[self.transport].dstport)
        self.highest_layer = str(packet.highest_layer).upper()
        self.application = _get_application(packet)
        self.a_b = True if self.src == self._parent_hosts[0] else False


class Conversation:
    """Encapsulates all traffic between two endpoints.
    
    Attributes:
        application: The dominant application layer
        hosts: A tuple of IP addresses (host A, host B)
        a_b: The count of transactions from host A to host B
        b_a: The count of transactions from host B to host A
        stream_id: The stream ID from the tshark capture
        transport: The transport used e.g. TCP, UDP
        ports: A list of transport ports used e.g. [1883]
        packets: A list of all the packets summarized
        packet_count: The size of the packets list
        byte_count: The total number of bytes in the conversation

    """
    def __init__(self, packet: SharkPacket = None, log: logging.Logger = None):
        self._log = log or get_wrapping_logger()
        self.application: str = None
        self.hosts: tuple = None
        self.a_b: int = 0
        self.b_a: int = 0
        self.stream_id: str = None
        self.transport: str = None
        self.ports: list = []
        self.packets: list = []
        self.packet_count: int = 0
        self.byte_count: int = 0
        if packet is not None:
            self.packet_add(packet)
    
    def __repr__(self) -> str:
        return json.dumps(vars(self), indent=2)

    def is_packet_in_flow(self, packet: SharkPacket) -> bool:
        """Returns True if the packet is between the object's hosts.
        
        Args:
            packet: A pyshark Packet capture
        
        Returns:
            True if the packet source and destination are the hosts.
        """
        if self.hosts is None:
            return False
        (src, dst) = _get_src_dst(packet)
        transport = packet.transport_layer
        stream_id = packet[transport].stream
        if (src in self.hosts and dst in self.hosts and
            stream_id == self.stream_id):
            return True
        return False
    
    def packet_add(self, packet: SharkPacket) -> bool:
        """Adds the packet summary and metadata to the Conversation.
        
        Args:
            packet: A pyshark Packet capture
        
        Returns:
            True if the packet was added to the Conversation.
        
        Raises:
            ValueError if the packet is missing transport_layer or has a
                different transport or stream ID than the conversation.

        """
        if not(isinstance(packet, SharkPacket)):
            raise ValueError('packet is not a valid pyshark Packet')
        if self.hosts is None:
            self.hosts = _get_src_dst(packet)
        elif not(self.is_packet_in_flow(packet)):
            return False
        (src, dst) = _get_src_dst(packet)
        del dst   #:Unused
        if src == self.hosts[0]:
            self.a_b += 1
        else:
            self.b_a += 1
        if self.transport is None:
            if packet.transport_layer is None:
                err = f'Packet missing transport_layer'
                self._log.error(err)
                raise ValueError(err)
            self.transport = packet.transport_layer
        elif packet.transport_layer != self.transport:
            err = (f'Expected transport {self.transport}'
                f' got {packet.transport_layer}')
            self._log.error(err)
            raise ValueError(err)
        srcport = int(packet[self.transport].srcport)
        if srcport not in self.ports:
            self.ports.append(srcport)
        dstport = int(packet[self.transport].dstport)
        if dstport not in self.ports:
            self.ports.append(dstport)
        stream_id = packet[self.transport].stream
        if self.stream_id is None:
            self.stream_id = stream_id
        elif stream_id != self.stream_id:
            err = (f'Expected stream {self.stream_id}'
                f' got {packet[self.transport].stream}')
            self._log.error(err)
            raise ValueError(err)
        self.packet_count += 1
        self.byte_count += int(packet.length)
        try:
            simple_packet = SimplePacket(packet, self.hosts)
            self.packets.append(simple_packet)
            if self.application is None:
                self.application = simple_packet.application
            elif self.application != simple_packet.application:
                self._log.warning(f'Expected {self.application} packet'
                    f' but got {simple_packet.application}')
            return True
        except Exception as e:
            self._log.exception(e)
            raise e
        
    @staticmethod
    def _get_intervals_by_length(packets_by_size: dict) -> dict:
        intervals = {}
        for packet_size in packets_by_size:
            packet_list = packets_by_size[packet_size]
            intervals[packet_size] = None
            if len(packet_list) == 1:
                application = packet_list[0].application
                application += f'_{packet_size}B'
                intervals[application] = None
                del intervals[packet_size]
                continue
            is_same_application = True   # starting assumption
            for i, packet in enumerate(packet_list):
                if i == 0:
                    # skip the first one since we are looking for time between
                    continue
                if (packet_list[i - 1].application != packet.application):
                    is_same_application = False
                this_interval = (
                    packet.timestamp - packet_list[i - 1].timestamp
                )
                if intervals[packet_size] is None:
                    intervals[packet_size] = this_interval
                else:
                    intervals[packet_size] = (round((intervals[packet_size] +
                                              this_interval) / 2, 3))
            if is_same_application:
                application = packet_list[0].application
            else:
                application = 'mixed'
            application += f'_{packet_size}B'
            intervals[application] = intervals[packet_size]
            del intervals[packet_size]
        return intervals
    
    def data_series_packet_size(self) -> list:
        """Generates a data series with timestamp and packet size.

        Example: [(12345.78, 42), (12355.99, 42)]

        Returns:
            A list of tuples consisting of (unix_timestamp, size_bytes)

        """
        series = []
        for packet in self.packets:
            datapoint = (packet.timestamp, packet.size)
            series.append(datapoint)
        return series

    def group_packets_by_size(self) -> tuple:
        """Creates dictionaries keyed by similar packet size and direction.
        
        Returns:
            A tuple with 2 dictionaries representing flows A-B and B-A.
            In each dictionary the keys are the packet size and the value
                is a list of the packets of that size.

        """
        packets_a_b = {}
        packets_b_a = {}
        lengths = []
        for packet in self.packets:
            if packet.a_b:
                if packet.size not in packets_a_b:
                    packets_a_b[packet.size] = []
                packets_a_b[packet.size].append(packet)
            else:
                if packet.size not in packets_b_a:
                    packets_b_a[packet.size] = []
                packets_b_a[packet.size].append(packet)
            lengths.append(packet.size)
        return (packets_a_b, packets_b_a)

    def intervals(self) -> dict:
        """Analyzes the conversation and returns metrics in a dictionary.
        
        Returns:
            A dictionary including:
                * A (str): The host IP that initiated the conversation
                * B (str): The host IP opposite to A
                * AB_intervals (dict): A dictionary with grouped packet size
                average repeat interval A to B in seconds
                * AB_intervals (dict): A dictionary with grouped packet size
                average repeat interval B to A in seconds

        """
        # sort by direction and packet size
        packets_a_b, packets_b_a = self.group_packets_by_size()
        # TODO: dominant packet list based on quantity * size
        return {
            'A': self.hosts[0],
            'B': self.hosts[1],
            'AB_intervals': self._get_intervals_by_length(packets_a_b),
            'BA_intervals': self._get_intervals_by_length(packets_b_a)
        }


class PacketStatistics:
    """Encapsulates packet-level statistics from a capture over time.
    
    Attributes:
        conversations (list): A list of Conversation elements for analyses.

    """
    def __init__(self, log: logging.Logger = None) -> None:
        self._log = log or get_wrapping_logger()
        self._ip_src_curr = None   # TODO: obsolete?
        self._ip_dst_curr = None
        self._ip_src_last = None
        self._ip_dst_last = None
        self._ts_last = None
        self._packet_length_last = None
        self.conversations = []
        self._is_conversation = False
    
    def _packet_add(self, packet: SharkPacket) -> None:
        """Adds a packet to the statistics for analyses.
        
        Args:
            packet: A pyshark Packet object.

        """
        packet_type = packet.highest_layer
        packet_length = int(packet.length)
        ts = round(float(packet.sniff_timestamp), 3)
        if hasattr(packet, 'arp'):
            self._process_arp(packet)
        elif hasattr(packet, 'ip'):
            self._process_ip(packet)
        else:
            self._log.warning(f'Unhandled packet type {packet_type}')
            return
        self._ip_src_last = self._ip_src_curr
        self._ip_dst_last = self._ip_dst_curr
        self._ts_last = ts
        self._packet_length_last = packet_length
    
    def _process_arp(self, packet: SharkPacket):
        self._ip_src_curr = packet.arp.src_proto_ipv4
        self._ip_dst_curr = packet.arp.dst_proto_ipv4
        self._log.debug(f'ARP {self._ip_src_curr} --> {self._ip_dst_curr}')

    def _process_ip(self, packet: SharkPacket):
        in_conversation = False
        for conversation in self.conversations:
            if conversation.is_packet_in_flow(packet):
                conversation.packet_add(packet)
                in_conversation = True
        if not in_conversation:
            self._log.debug('Found new conversation')
            conversation = Conversation(packet, self._log)
            self.conversations.append(conversation)
        packet_type = packet.highest_layer
        packet_length = int(packet.length)
        ts = round(float(packet.sniff_timestamp), 3)
        self._ip_src_curr = packet.ip.src
        self._ip_dst_curr = packet.ip.dst
        transport = packet.transport_layer
        if transport is not None:
            srcport = packet[transport].srcport
            dstport = packet[transport].dstport
            stream_id = packet[transport].stream
        isotime = datetime.utcfromtimestamp(ts).isoformat()[0:23]
        self._log.debug(f'{isotime}|{packet_type}|'
            f'({transport}.{stream_id}:{dstport})'
            f'|{packet_length} bytes|{packet.ip.src}-->{packet.ip.dst}')

    def data_series_application_size(self) -> dict:
        """Returns a set of data series by conversation application.
        
        Example: {'MQTT': [(12345.67, 42)]}

        Returns:
            A dictionary with keys showing the application and values are
                tuples with (unix_timestamp, size_bytes)

        """
        multi_series = {}
        for conversation in self.conversations:
            app = conversation.application
            if app in multi_series:
                prev = int(app.split('-')[1]) if '-' in app else 1
                app = f'{app}-{prev + 1}'
            multi_series[app] = conversation.data_series_packet_size()
        return multi_series

    def analyze_conversations(self) -> list:
        """Analyzes the conversations.
        
        Returns:
            A list of analyses currently consisting of the intervals between
                similarly sized packets of a given application.

        """
        results = []
        for conversation in self.conversations:
            analysis = conversation.intervals()
            # self._log.info(analysis)
            results.append(analysis)
        return results


def _get_event_loop():
    err = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as e:
        err = e
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    asyncio.get_child_watcher().attach_loop(loop)
    return loop, err


def process_pcap(filename: str,
                 display_filter: str = None,
                 queue: Queue = None,
                 debug: bool = False,
                 ) -> PacketStatistics:
    """Processes a PCAP file to create metrics for conversations.

    To run in the background use a multiprocessing.Process and Queue:
    ```
    queue = multiprocessing.Queue()
    kwargs = {
        'filename': filename,
        'display_filter': display_filter,
        'queue': queue,
    }
    capture_process = multiprocessing.Process(target=process_pcap,
                                      name='packet_capture', kwargs=kwargs)
    process.start()
    process.join()
    capture_file = queue.get()
    ```
    
    Args:
        filename: The path/name of the PCAP file
        display_filter: An optional tshark display filter
        queue: An optional multiprocessing Queue (e.g. required for Flask)
        debug: Enables pyshark debug output
    
    Returns:
        A PacketStatistics object with data and analytics functions.

    """
    log = get_wrapping_logger()
    packet_stats = PacketStatistics(log=log)
    file = clean_path(filename)
    loop = None
    newloop = False
    if queue is not None:
        loop, err = _get_event_loop()
        if err is not None:
            newloop = True
            log.error(err)
    capture = pyshark.FileCapture(input_file=file,
        display_filter=display_filter, eventloop=loop)
    capture.set_debug(debug)
    packet_count = 0
    try:
        for packet in capture:
            packet_count += 1
            packet_stats._packet_add(packet)
    except Exception as e:
        #TODO: better error capture e.g. appears to have been cut short use editcap
        # https://tshark.dev/share/pcap_preparation/
        log.error(f'Packet {packet_count} processing ERROR:\n{e}')
    if queue is not None:
        queue.put(packet_stats)
        if newloop:
            loop.close()
    else:
        return packet_stats


def pcap_filename(duration: int) -> str:
    """Generates a pcap filename using datetime of the capture start.
    
    The datetime is UTC, and DDDDD is the duration in seconds.

    Returns:
        A string formatted as `capture_YYYYmmddTHHMMSS_DDDDD.pcap`.

    """
    dt = datetime.utcnow().isoformat().replace('-', '').replace(':', '')[0:15]
    filename = f'capture_{dt}_{duration}.pcap'
    return filename


def create_pcap(interface: str = 'eth1',
                duration: int = 60,
                filename: str = None,
                target_directory: str = '$HOME',
                queue: Queue = None,
                debug: bool = False,
                log: logging.Logger = None,
                ) -> str:
    """Creates a packet capture file of a specified interface.

    A subdirectory is created in the `target_directory`, if none is specified it
    stores to the user's home directory.
    The subdirectory name is `capture_YYYYmmdd`.
    The filename can be specified or `capture_YYYYmmddTHHMMSS_DDDDD.pcap`
    format will be used.
    To run in the background use a multiprocessing.Process and Queue:
    ```
    queue = multiprocessing.Queue()
    kwargs = {
        'interface': my_interface,
        'duration': my_duration,
        'filename': pcap_filename(),
        'target_directory': my_folder,
        'queue': queue,
    }
    capture_process = multiprocessing.Process(target=create_pcap,
                                      name='packet_capture', kwargs=kwargs)
    capture_process.start()
    capture_process.join()
    capture_file = queue.get()
    ```
    
    Args:
        interface: The interface to capture from e.g. `eth1`
        duration: The duration of the capture in seconds
        target_directory: The path to save the capture to
        finish_event: A threading Event that gets set when capture is complete

    Returns:
        The full file/path name if no event is passed in.

    """
    log = log or get_wrapping_logger()
    if filename is None:
        filename = pcap_filename(duration)
    target_directory = clean_path(target_directory)
    subdir = f'{target_directory}/{filename[0:len("capture_YYYYmmdd")]}'
    filepath = f'{subdir}/{filename}'
    if not os.path.isdir(subdir):
        os.makedirs(subdir)
    loop = None
    newloop = False
    if queue is not None:
        loop, err = _get_event_loop()
        if err is not None:
            newloop = True
            log.error(err)
    capture = pyshark.LiveCapture(interface=interface, output_file=filepath,
        eventloop=loop)
    capture.set_debug(debug)
    capture.sniff(timeout=duration)
    if queue is not None:
        queue.put(filepath)
        if newloop:
            loop.close()
    else:
        return filepath