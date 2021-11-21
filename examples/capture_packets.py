import argparse
import sys

from fieldedge_utilities.pcap import create_pcap, process_pcap


def get_kwargs(argv: tuple) -> dict:
    """Parses the command line arguments.

    Args:
        argv: An array containing the command line arguments.
    
    Returns:
        A dictionary containing the command line arguments and their values.
    """
    parser = argparse.ArgumentParser(description='Processes network packets.')
    parser.add_argument('-i', '--interface', dest='interface', type=str,
                        required=False, default=None,
                        help=('The interface to be monitored.'))
    parser.add_argument('-t', '--duration', dest='duration', type=int,
                        required=False, default=60,
                        help=('The duration in seconds to monitor.'))
    parser.add_argument('-d', '--directory', dest='directory', type=str,
                        required=False, default='$HOME/',
                        help=('The directory to save the pcap to.'))
    parser.add_argument('-f', '--filename', dest='filename', type=str,
                        required=False, default=None,
                        help=('The path/to/filename to be processed.'))
    return vars(parser.parse_args(args=argv[1:]))


if __name__ == '__main__':
    kwargs = get_kwargs(sys.argv)
    filename = kwargs.pop('filename', None)
    interface = kwargs.pop('interface', None)
    directory = kwargs.pop('directory', None)
    duration = kwargs.pop('duration', None)
    if interface is None:
        raise ValueError('Missing filename or interface name')
    print(f'Starting packet capture on {interface}'
        f' for {duration} seconds, please wait...')
    new_pcap = create_pcap(interface=interface, duration=duration,
        target_directory=directory)
    print(f'Packet capture complete - gathering statistics...')
    packet_statistics = process_pcap(new_pcap)
    analyses = packet_statistics.analyze_conversations()
    for analysis in analyses:
        print(f'{analysis}')
