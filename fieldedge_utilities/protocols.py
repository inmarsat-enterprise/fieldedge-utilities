"""Enumerated types for protocol analysis.

"""
from enum import Enum


class KnownTcpPorts(Enum):
    """Mappings for application layer TCP ports."""
    SMTP = 25
    HTTP = 80
    HTTP_TLS = 443
    HTTP_ALT = 8080
    DNS = 53
    FTP = 20
    FTP_CTRL = 21
    TELNET = 23
    IMAP = 143
    RDP = 3389
    SSH = 22
    MODBUS = 502
    MODBUS_TLS = 802
    DNP = 20000
    DNP_TLS = 19999
    IEC60870 = 2404
    OPCUA = 4840
    OPCUA_TLS = 4843   # OPC-UA secure
    SRCP = 4303   # Simple Railroad Command Protocol
    MQTT = 1883
    MQTT_TLS = 8883
    MQTT_SOCKET = 9001
    COAP = 5683
    COAP_TLS = 5684   # Constrained Application Protocol Secure
    DOCKERAPI = 2375
    DOCKERAPI_TLS = 2376
    KAFKA = 9092   # Apache Kafka message queue
    OPENVPN = 1194
    IPSEC = 1293
    RSYNC = 873
    FLIR = 22136   # Camera Resource Protocol
    WEATHERLINK = 22222   # Davis Instruments WeatherLink IP
    SQL = 118

class KnownUdpPorts(Enum):
    """Mappings for application layer UDP ports."""
    SNMP = 161
    DNS = 53
    DHCP_CLIENT = 67
    DHCP_SERVER = 68
    NTP = 123
