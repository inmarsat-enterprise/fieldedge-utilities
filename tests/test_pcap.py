import os

from fieldedge_utilities import pcap

def test_create_and_read_pcap():
    filename = pcap.create_pcap(interface='en0', duration=5,
        directory='../pcaps')
    assert(os.path.isfile(filename))
    packet_statistics = pcap.process_pcap(filename=filename)
    assert(isinstance(packet_statistics, pcap.PacketStatistics))
    os.remove(filename)

def test_packet_statistics():
    filename = '../pcaps/mqtts_sample.pcap'
    packet_stats = pcap.process_pcap(filename=filename)
    assert isinstance(packet_stats, pcap.PacketStatistics)
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
