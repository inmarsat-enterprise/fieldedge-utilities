import os
import serial
import time

from fieldedge_utilities.gnss import GnssLocation, parse_nmea_to_location


def test_parsing():
    loc = GnssLocation()
    time.sleep(0.1)
    ser = serial.Serial(os.getenv('GNSS_SERIAL', '/dev/ttyUSB0'))
    sentences_read = 0
    start_time = time.time()
    while time.time() - start_time < 15:
        if ser.in_waiting:
            line = ser.readline().decode().strip()
            sentences_read += 1
            loc = parse_nmea_to_location(line, loc)
    assert loc.latitude is not None
    assert loc.longitude is not None
    assert loc.timestamp is not None
