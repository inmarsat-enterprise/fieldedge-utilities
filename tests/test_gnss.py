import logging
import os
import serial
import time

import pytest

from fieldedge_utilities.gnss import GnssLocation, parse_nmea_to_location

logger = logging.getLogger(__name__)

TEST_GNSS_OUTPUT = './tests/gnss_output.txt'
TEST_GGA = '$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47'
TEST_RMC = '$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A'
TEST_VTG = '$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48'
TEST_GSA = '$GPGSA,A,3,04,05,09,12,24,32,,,,,,,1.8,1.0,1.5*33'
TEST_GSV = '$GPGSV,2,1,08,01,40,083,41,02,50,060,45,03,48,180,43,04,30,310,42*7C'
TEST_GLL = '$GPGLL,4916.45,N,12311.12,W,225444,A*31'
TEST_ZDA = '$GPZDA,201530.00,04,07,2022,00,00*60'


def get_gnss_output():
    ser = serial.Serial(os.getenv('GNSS_SERIAL', '/dev/ttyUSB0'))
    start_time = time.time()
    with open(TEST_GNSS_OUTPUT, 'a') as file:
        while time.time() - start_time < 10:
            line = ser.readline().decode()
            if line:
                file.write(line)


def test_parse_nmea_to_location():
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


@pytest.mark.skip(reason='Placeholder')
def test_parse_nmea():
    """Ensure the elements of an individual NMEA string are in the dictionary."""
    assert False
