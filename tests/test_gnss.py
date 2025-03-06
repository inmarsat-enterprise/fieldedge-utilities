import logging
import os
import serial
import time

from fieldedge_utilities.gnss import GnssLocation, parse_nmea_to_location

logger = logging.getLogger(__name__)

TEST_GNSS_OUTPUT = './tests/gnss_output.txt'


def get_gnss_output():
    ser = serial.Serial(os.getenv('GNSS_SERIAL', '/dev/ttyUSB0'))
    start_time = time.time()
    with open(TEST_GNSS_OUTPUT, 'a') as file:
        while time.time() - start_time < 10:
            line = ser.readline().decode()
            if line:
                file.write(line)


def test_parsing():
    loc = GnssLocation()
    if not os.path.isfile(TEST_GNSS_OUTPUT):
        logger.info('Reading sample GNSS data')
        get_gnss_output()
    sentences_read = 0
    with open(TEST_GNSS_OUTPUT, 'r') as file:
        for _, line in enumerate(file, start=1):
            if not line:
                continue
            sentences_read += 1
            loc_before = loc.json_compatible()
            loc = parse_nmea_to_location(line, loc)
            loc_after = loc.json_compatible()
            if loc_after != loc_before:
                nmea_type = line[:6]
                logger.info('Location updated by %s: %s', nmea_type,loc_after)
    logger.info('Processed %d NMEA sentences', sentences_read)
    assert loc.latitude is not None
    assert loc.longitude is not None
    assert loc.timestamp is not None
