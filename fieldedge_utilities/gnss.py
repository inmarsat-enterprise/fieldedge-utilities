"""NMEA helper utilities for location data from commercial GNSS devices."""

import logging
from copy import deepcopy
from dataclasses import dataclass, asdict
from enum import IntEnum
from typing import Optional

from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.timestamp import iso_to_ts

__all__ = ['GnssFixType', 'GnssFixQuality', 'GnssLocation',
           'validate_nmea', 'parse_nmea_to_location']

_log = logging.getLogger(__name__)


class GnssFixType(IntEnum):
    """Enumerated fix type from NMEA-0183 standard."""
    NONE = 1
    D2 = 2
    D3 = 3


class GnssFixQuality(IntEnum):
    """Enumerated fix type from NMEA-0183 standard."""
    INVALID = 0
    GPS_SPS = 1
    DGPS = 2
    PPS = 3
    RTK = 4
    FLOAT_RTK = 5
    EST_DEAD_RECKONING = 6
    MANUAL = 7
    SIMULATION = 8


@dataclass
class GnssLocation:
    """A location class."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    speed_kn: Optional[float] = None
    heading: Optional[float] = None
    hdop: Optional[float] = None
    pdop: Optional[float] = None
    vdop: Optional[float] = None
    satellites: int = 0
    timestamp: int = 0
    fix_type: GnssFixType = GnssFixType.NONE
    fix_quality: GnssFixQuality = GnssFixQuality.INVALID
    

def validate_nmea(nmea_sentence: str) -> bool:
    """Validates a given NMEA-0183 sentence with CRC.
    
    Args:
        nmea_sentence (str): NMEA-0183 sentence ending in checksum.
    
    """
    if '*' not in nmea_sentence:
        return False
    data, cs_hex = nmea_sentence.split('*')
    candidate = int(cs_hex, 16)
    crc = 0   # initial
    for i in range(1, len(data)):   # ignore initial $
        crc ^= ord(data[i])
    return candidate == crc


def parse_nmea_to_location(nmea_sentence: str,
                           location: GnssLocation = None) -> 'dict|GnssLocation|None':
    """Parses a NMEA-0183 sentence to a location or update.
    
    Passing a Location object in will update the location with NMEA data.
    Otherwise a dictionary is returned.
    """
    if _vlog():
        _log.debug('Parsing NMEA: %s', nmea_sentence)
    if not validate_nmea(nmea_sentence):
        raise ValueError('Invalid NMEA-0183 sentence')
    if not isinstance(location, GnssLocation):
        location = GnssLocation()
        old_location = None
    else:
        old_location = deepcopy(location)
    void = False
    data = nmea_sentence.split('*')[0]
    nmea_type = ''
    cache = {}
    for i, field_data in enumerate(data.split(',')):
        if i == 0:
            nmea_type = field_data[-3:]
            if nmea_type == 'GSV':
                _log.warning('No processing required for GSV sentence')
                return
            if _vlog():
                _log.debug('Processing NMEA type: %s', nmea_type)
        elif i == 1:
            if nmea_type == 'RMC':
                cache['fix_hour'] = field_data[0:2]
                cache['fix_min'] = field_data[2:4]
                cache['fix_sec'] = field_data[4:6]
                if _vlog():
                    _log.debug('Fix time %s:%s:%s', cache['fix_hour'],
                               cache['fix_min'], cache['fix_sec'])
        elif i == 2:
            if nmea_type == 'RMC':
                if (field_data == 'V'):
                    _log.warning('Fix Void')
                    void = True
                    break
            elif nmea_type == 'GSA':
                location.fix_type = GnssFixType(int(field_data))
                if _vlog():
                    _log.debug('Fix type: %D', location.fix_type.name)
        elif i == 3:
            if nmea_type == 'RMC':
                location.latitude = (float(field_data[0:2]) +
                                     float(field_data[2]) / 60.0)
        elif i == 4:
            if nmea_type == 'RMC':
                if field_data == 'S':
                    location.latitude *= -1
                if _vlog():
                    _log.debug('Latitude: %.5f', location.latitude)
        elif i == 5:
            if nmea_type == 'RMC':
                location.longitude = (float(field_data[0:3]) +
                                      float(field_data[3]) / 60.0)
        elif i == 6:
            if nmea_type == 'RMC':
                if field_data == 'W':
                    location.longitude *= -1
                if _vlog():
                    _log.debug('Longitude: %.5f', location.longitude)
            elif nmea_type == 'GGA':
                location.fix_quality = GnssFixQuality(int(field_data))
                if _vlog():
                    _log.debug('Fix quality: %s', location.fix_quality.name)
        elif i == 7:
            if nmea_type == 'RMC':
                location.speed_kn = float(field_data)
                if _vlog():
                    _log.debug('Speed: %.1f', location.speed_kn)
            elif nmea_type == 'GGA':
                location.satellites = int(field_data)
                if _vlog():
                    _log.debug('GNSS satellites used: %d', location.satellites)
        elif i == 8:
            if nmea_type == 'RMC':
                location.heading = float(field_data)
                if _vlog():
                    _log.debug('Heading: %.1f', location.heading)
            elif nmea_type == 'GGA':
                location.hdop = round(float(field_data), 1)
                if _vlog():
                    _log.debug('HDOP: %.1f', location.hdop)
        elif i == 9:
            if nmea_type == 'RMC':
                fix_day = field_data[0:2]
                fix_month = field_data[2:4]
                fix_yy = int(field_data[4:])
                fix_yy += 1900 if fix_yy >= 73 else 2000
                if _vlog():
                    _log.debug('Fix date %d-%s-%s', fix_yy, fix_month, fix_day)
                iso_time = (f'{fix_yy}-{fix_month}-{fix_day}T'
                            f'{cache["fix_hour"]}:{cache["fix_min"]}'
                            f':{cache["fix_sec"]}Z')
                unix_timestamp = iso_to_ts(iso_time)
                if _vlog():
                    _log.debug('Fix time ISO 8601: %s | Unix: %d',
                               iso_time, unix_timestamp)
                location.timestamp = unix_timestamp
            elif nmea_type == 'GGA':
                location.altitude = float(field_data)
                if _vlog():
                    _log.debug('Altitude: %.1f', location.altitude)
        elif i == 10:
            # RMC magnetic variation - ignore
            if nmea_type == 'GGA' and field_data != 'M':
                _log.warning('Unexpected altitude units: %s', field_data)
        # elif i == 11:   # RMC magnetic variation direction, GGA height of geoid - ignore
        # elif i == 12:   # GGA units height of geoid - ignore
        # elif i == 13:   # GGA seconds since last DGPS update - ignore
        # elif i == 14:   # GGA DGPS station ID - ignore
        elif i == 15:   # GSA PDOP - ignore (unused)
            if nmea_type == 'GSA':
                location.pdop = round(float(field_data), 1)
                if _vlog():
                    _log.debug('PDOP: %d', location.pdop)
        # elif i == 16:   # GSA HDOP - ignore (use GGA)
        elif i == 17:
            if nmea_type == 'GSA':
                location.vdop = round(float(field_data), 1)
                if _vlog():
                    _log.debug('VDOP: %d', location.vdop)
    if void:
         if old_location:
             return old_location
         return None
    if isinstance(old_location, GnssLocation):
        return location
    return { k: v for k, v in asdict(location) if v is not None }


def _vlog() -> bool:
    """Check if vebose logging is enabled for this microservice."""
    return verbose_logging('nmea')
