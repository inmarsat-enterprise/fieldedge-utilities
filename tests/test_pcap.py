import os
import shutil
import queue
import subprocess
from multiprocessing import Process, Queue
from time import time

from fieldedge_utilities import pcap

def is_corrupt(filename: str) -> bool:
    try:
        res = subprocess.run(['tshark', '-r', f'{filename}'], check=True,
            capture_output=True, text=True)
    except subprocess.CalledProcessError as err:
        res = err.stderr
    if 'appears to have been cut short' in res:
        return True
    return False

def fix_corrupt(filename: str) -> bool:
    try:
        res = subprocess.run(['editcap', f'{filename}', f'{filename}'],
            check=True, capture_output=True, text=True).returncode
    except subprocess.CalledProcessError as err:
        res = err.returncode
    if res == 0:
        return True
    return False

def test_create():
    """Creates and reads a pcap file on a local interface."""
    interface = 'en0'
    target_directory = '../pcaps'
    filename = pcap.create_pcap(interface=interface, duration=5,
        target_directory=target_directory, debug=True)
    assert(os.path.isfile(filename))

def test_create_multiprocessing():
    interface = 'en0'
    target_directory = '../pcaps'
    queue = Queue()
    kwargs = {
        'interface': interface,
        'duration': 5,
        'target_directory': target_directory,
        'queue': queue,
        'debug': True,
    }
    process = Process(target=pcap.create_pcap, kwargs=kwargs)
    process.start()
    process.join()
    filename = queue.get()
    assert(os.path.isfile(filename))
    if is_corrupt(filename):
        assert fix_corrupt(filename)

def test_create_and_read_pcap():
    """Creates and reads a pcap file on a local interface."""
    interface = 'en0'
    target_directory = '../pcaps'
    filename = pcap.create_pcap(interface=interface, duration=5,
        target_directory=target_directory, debug=True)
    assert(os.path.isfile(filename))
    if is_corrupt(filename):
        assert fix_corrupt(filename)
    packet_statistics = pcap.process_pcap(filename=filename)
    assert(isinstance(packet_statistics, pcap.PacketStatistics))
    shutil.rmtree(os.path.dirname(filename))

def test_packet_statistics():
    """Validates content of the PacketStatistics object."""
    filename = '../pcaps/samples/mqtts_sample.pcap'
    duration = 50
    # filename = '../pcaps/samples/capture_20211210T173939_1800.pcap'
    # duration = 1800
    packet_stats = pcap.process_pcap(filename=filename)
    assert isinstance(packet_stats, pcap.PacketStatistics)
    assert isinstance(packet_stats.duration, int)
    assert packet_stats.duration == duration
    assert packet_stats.packet_count > 0
    assert packet_stats.bytes_total > 0
    for conversation in packet_stats.conversations:
        assert isinstance(conversation, pcap.Conversation)
        for simple_packet in conversation.packets:
            assert isinstance(simple_packet, pcap.SimplePacket)
            assert isinstance(simple_packet.a_b, bool)
            assert isinstance(simple_packet.application, str)
            assert isinstance(simple_packet.highest_layer, str)
            assert isinstance(simple_packet.timestamp, float)
            assert isinstance(simple_packet.size, int)
            assert isinstance(simple_packet.src, str)
            assert isinstance(simple_packet.dst, str)
            assert isinstance(simple_packet.srcport, int)
            assert isinstance(simple_packet.dstport, int)
        grouped = conversation.group_packets_by_size()
        assert isinstance(grouped, tuple)
        assert len(grouped) == 2
        for direction in grouped:
            assert isinstance(direction, dict)
            for key in direction:
                assert isinstance(direction[key], list)
    dataset = packet_stats.data_series_application_size()
    assert isinstance(dataset, dict)
    for key in dataset:
        assert isinstance(dataset[key], list)
        for datapoint in dataset[key]:
            assert isinstance(datapoint, tuple)
            assert isinstance(datapoint[0], float)
            assert isinstance(datapoint[1], int)

def test_process_multiprocessing():
    """Processes a pcap separately using multiprocessing."""
    # filename = '../pcaps/samples/mqtts_sample.pcap'
    # filename = '../pcaps/samples/capture_20211205T142537_60.pcap'
    filename = '../pcaps/samples/capture_20211215T031635_3600.pcap'
    q = Queue()
    process = Process(target=pcap.process_pcap, args=(filename, None, q))
    starttime = time()
    process.start()
    while process.is_alive():
        try:
            while True:
                packet_stats = q.get(block=False)
        except queue.Empty:
            pass
    process.join()
    processing_time = time() - starttime
    assert isinstance(packet_stats, pcap.PacketStatistics)
    data_dict = packet_stats.data_series_application_size()
    assert isinstance(data_dict, dict)


def test_process():
    """Processes a pcap."""
    # filename = '../pcaps/samples/mqtts_sample.pcap'
    filename = '../pcaps/samples/capture_20211215T031635_3600.pcap'
    if is_corrupt(filename):
        assert fix_corrupt(filename)
    starttime = time()
    packet_stats = pcap.process_pcap(filename=filename)
    processing_time = time() - starttime
    assert isinstance(packet_stats, pcap.PacketStatistics)
