"""NMEA helper utilities for location data from commercial GNSS devices."""

import logging
# import re   # future support for regex optimization
from dataclasses import dataclass, asdict
from enum import Enum, IntEnum
from typing import Any, Optional

from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.properties import camel_case
from fieldedge_utilities.timestamp import iso_to_ts, ts_to_iso

__all__ = ['GnssFixType', 'GnssFixQuality', 'GnssLocation',
           'validate_nmea', 'parse_nmea_to_location']

_log = logging.getLogger(__name__)


class GnssFixType(IntEnum):
    """Enumerated fix type from NMEA-0183 standard."""
    FIX_NONE = 1
    FIX_2D = 2
    FIX_3D = 3


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
    speed: Optional[float] = None
    heading: Optional[float] = None
    hdop: Optional[float] = None
    pdop: Optional[float] = None
    vdop: Optional[float] = None
    satellites: Optional[int] = None
    timestamp: Optional[int] = None
    fix_type: Optional[GnssFixType] = None
    fix_quality: Optional[GnssFixQuality] = None

    @property
    def iso_time(self) -> 'str|None':
        if self.timestamp is None:
            return None
        return ts_to_iso(self.timestamp)
    
    def json_compatible(self, **kwargs) -> dict[str, Any]:
        lat_lon_precision = kwargs.get('lat_lon_precision', 5)
        other_precision = kwargs.get('other_precision', 1)
        result = { k: v for k, v in asdict(self).items() if v is not None }
        if self.timestamp is not None:
            result['iso_time'] = self.iso_time
        for k, v in result.items():
            if k in ['latitude', 'longitude']:
                result[k] = round(v, lat_lon_precision)
            elif isinstance(v, float):
                result[k] = round(v, other_precision)
            elif isinstance(v, Enum):
                result[k] = v.name
        return { camel_case(k): v for k, v in result.items() if v is not None }


def validate_nmea(nmea_sentence: str) -> bool:
    """Validates a given NMEA-0183 sentence with CRC.
    
    Args:
        nmea_sentence (str): NMEA-0183 sentence ending in checksum.
    
    """
    if '*' not in nmea_sentence:
        return False
    data, cs_hex = nmea_sentence.rsplit('*', 1)
    candidate = int(cs_hex, 16)
    crc = 0   # initial
    for char in data[1:]:   # ignore initial $
        crc ^= ord(char)
    return candidate == crc


def parse_nmea_to_location(nmea_sentence: str,
                           location: Optional[GnssLocation] = None,
                           **kwargs) -> GnssLocation|dict[str, Any]|None:
    """Parses a NMEA-0183 sentence to a location or update.
    
    Passing a Location object in will update the location with NMEA data.
    Otherwise a dictionary is returned.
    """
    if not validate_nmea(nmea_sentence):
        raise ValueError('Invalid NMEA-0183 sentence')
    vlog = _vlog()
    if location is None:
        location = GnssLocation()
        old_location = None
    else:
        from copy import deepcopy
        old_location = deepcopy(location)
        if vlog:
            _log.debug('Updating location: %s', old_location)
    void_fix = False
    data = nmea_sentence.rsplit('*', 1)[0]
    fields = data.split(',')
    nmea_type = fields[0][-3:]
    
    def _parse_rmc(fields):
        nonlocal void_fix
        cache = {}
        try:
            # Time
            hh, mm, ss = fields[1][0:2], fields[1][2:4], fields[1][4:6]
            cache.update({'fix_hour': hh, 'fix_min': mm, 'fix_sec': ss})
            # Status
            if fields[2] == 'V':
                void_fix = True
                return
            # Latitude
            if fields[3]:
                lat = float(fields[3][0:2]) + float(fields[3][2:]) / 60.0
                if fields[4] == 'S':
                    lat *= -1
                location.latitude = round(lat, 6)
            # Longitude
            if fields[5]:
                lon = float(fields[5][0:3]) + float(fields[5][3:]) / 60.0
                if fields[6] == 'W':
                    lon *= -1
                location.longitude = round(lon, 6)
            # Speed in km/h
            if fields[7]:
                location.speed = round(float(fields[7]) * 1.852, 2)
            # Heading
            if fields[8]:
                location.heading = float(fields[8])
            # Date → timestamp
            if fields[9]:
                day, month, yy = int(fields[9][0:2]), int(fields[9][2:4]), int(fields[9][4:])
                yy += 1900 if yy >= 73 else 2000
                iso_time = f"{yy}-{month:02}-{day:02}T{hh}:{mm}:{ss}Z"
                location.timestamp = int(iso_to_ts(iso_time))
        except Exception as e:
            _log.warning("Failed parsing RMC fields: %s", e)

    def _parse_gga(fields):
        try:
            # Latitude
            if fields[2]:
                lat = float(fields[2][0:2]) + float(fields[2][2:]) / 60.0
                if fields[3] == 'S':
                    lat *= -1
                location.latitude = round(lat, 6)
            # Longitude
            if fields[4]:
                lon = float(fields[4][0:3]) + float(fields[4][3:]) / 60.0
                if fields[5] == 'W':
                    lon *= -1
                location.longitude = round(lon, 6)
            # Fix quality
            location.fix_quality = GnssFixQuality(int(fields[6] or 0))
            # Satellites
            if fields[7]:
                location.satellites = int(fields[7])
            # HDOP
            if fields[8]:
                location.hdop = round(float(fields[8]), 1)
            # Altitude
            if fields[9]:
                location.altitude = float(fields[9])
        except Exception as e:
            _log.warning("Failed parsing GGA fields: %s", e)

    def _parse_gsa(fields):
        try:
            # Fix type
            if fields[2]:
                location.fix_type = GnssFixType(int(fields[2] or 0))
            # PDOP, HDOP, VDOP
            if len(fields) > 15 and fields[15]:
                location.pdop = round(float(fields[15]), 1)
            if len(fields) > 17 and fields[17]:
                location.vdop = round(float(fields[17]), 1)
        except Exception as e:
            _log.warning("Failed parsing GSA fields: %s", e)
                
    if vlog:
        _log.debug('Parsing NMEA: %s', nmea_sentence)
    
    if nmea_type == 'RMC':
        _parse_rmc(fields)
    elif nmea_type == 'GGA':
        _parse_gga(fields)
    elif nmea_type == 'GSA':
        _parse_gsa(fields)
    else:
        if vlog:
            _log.warning('Unsupported NMEA sentence type: %s', nmea_type)
    # void = False
    # data = nmea_sentence.split('*')[0]
    # nmea_type = ''
    # cache = {}
    # for i, field_data in enumerate(data.split(',')):
    #     if i == 0:
    #         nmea_type = field_data[-3:]
    #         if nmea_type not in ['RMC', 'GGA', 'GSA']:
    #             if vlog:
    #                 _log.warning('No processing defined for %s sentence',
    #                              nmea_type)
    #             break
    #         if vlog:
    #             _log.debug('Processing NMEA type: %s', nmea_type)
    #     elif i == 1:
    #         if nmea_type == 'RMC' and field_data:
    #             cache['fix_hour'] = field_data[0:2]
    #             cache['fix_min'] = field_data[2:4]
    #             cache['fix_sec'] = field_data[4:6]
    #             if vlog:
    #                 _log.debug('Fix time %s:%s:%s', cache['fix_hour'],
    #                            cache['fix_min'], cache['fix_sec'])
    #     elif i == 2:
    #         if nmea_type == 'RMC':
    #             if (field_data == 'V'):
    #                 _log.warning('Fix Void - stop processing')
    #                 void = True
    #                 break
    #         elif nmea_type == 'GSA':
    #             location.fix_type = GnssFixType(int(field_data or 0))
    #             if vlog:
    #                 _log.debug('Fix type: %s', location.fix_type.name)
    #     elif i == 3:
    #         if nmea_type == 'RMC' and field_data:
    #             location.latitude = round(float(field_data[0:2]) +
    #                                       float(field_data[2:]) / 60.0, 6)
    #     elif i == 4:
    #         if nmea_type == 'RMC':
    #             if field_data == 'S' and location.latitude is not None:
    #                 location.latitude *= -1
    #             if vlog:
    #                 _log.debug('Latitude: %.5f', location.latitude)
    #     elif i == 5:
    #         if nmea_type == 'RMC' and field_data:
    #             location.longitude = round(float(field_data[0:3]) +
    #                                        float(field_data[3:]) / 60.0, 6)
    #     elif i == 6:
    #         if nmea_type == 'RMC':
    #             if field_data == 'W' and location.longitude is not None:
    #                 location.longitude *= -1
    #             if vlog:
    #                 _log.debug('Longitude: %.5f', location.longitude)
    #         elif nmea_type == 'GGA':
    #             location.fix_quality = GnssFixQuality(int(field_data or 0))
    #             if vlog:
    #                 _log.debug('Fix quality: %s', location.fix_quality.name)
    #     elif i == 7:
    #         if nmea_type == 'RMC' and field_data:
    #             location.speed = round(float(field_data) * 1.852, 2)
    #             if vlog:
    #                 _log.debug('Speed: %.1f', location.speed)
    #         elif nmea_type == 'GGA' and field_data:
    #             location.satellites = int(field_data)
    #             if vlog:
    #                 _log.debug('GNSS satellites used: %d', location.satellites)
    #     elif i == 8:
    #         if nmea_type == 'RMC' and field_data:
    #             location.heading = float(field_data)
    #             if vlog:
    #                 _log.debug('Heading: %.1f', location.heading)
    #         elif nmea_type == 'GGA' and field_data:
    #             location.hdop = round(float(field_data), 1)
    #             if vlog:
    #                 _log.debug('HDOP: %.1f', location.hdop)
    #     elif i == 9:
    #         if nmea_type == 'RMC' and field_data:
    #             fix_day = field_data[0:2]
    #             fix_month = field_data[2:4]
    #             fix_yy = int(field_data[4:])
    #             fix_yy += 1900 if fix_yy >= 73 else 2000
    #             if vlog:
    #                 _log.debug('Fix date %d-%s-%s', fix_yy, fix_month, fix_day)
    #             iso_time = (f'{fix_yy}-{fix_month}-{fix_day}T'
    #                         f'{cache["fix_hour"]}:{cache["fix_min"]}'
    #                         f':{cache["fix_sec"]}Z')
    #             unix_timestamp = int(iso_to_ts(iso_time))
    #             if vlog:
    #                 _log.debug('Fix time ISO 8601: %s | Unix: %d',
    #                            iso_time, unix_timestamp)
    #             location.timestamp = unix_timestamp
    #         elif nmea_type == 'GGA' and field_data:
    #             location.altitude = float(field_data)
    #             if vlog:
    #                 _log.debug('Altitude: %.1f', location.altitude)
    #     elif i == 10:
    #         # RMC magnetic variation - ignore
    #         if nmea_type == 'GGA' and field_data != 'M':
    #             _log.warning('Unexpected altitude units: %s', field_data)
    #     # elif i == 11:   # RMC magnetic variation direction, GGA height of geoid - ignore
    #     # elif i == 12:   # GGA units height of geoid - ignore
    #     # elif i == 13:   # GGA seconds since last DGPS update - ignore
    #     # elif i == 14:   # GGA DGPS station ID - ignore
    #     elif i == 15:   # GSA PDOP - ignore (unused)
    #         if nmea_type == 'GSA' and field_data:
    #             location.pdop = round(float(field_data), 1)
    #             if vlog:
    #                 _log.debug('PDOP: %d', location.pdop)
    #     # elif i == 16:   # GSA HDOP - ignore (use GGA)
    #     elif i == 17:
    #         if nmea_type == 'GSA' and field_data:
    #             location.vdop = round(float(field_data), 1)
    #             if vlog:
    #                 _log.debug('VDOP: %d', location.vdop)
    if void_fix:
         return old_location if old_location else None
    if old_location is not None:
        return location
    return location.json_compatible(**kwargs)
    # if isinstance(old_location, GnssLocation):
    #     return location
    # return location.json_compatible(**kwargs)


def _vlog() -> bool:
    return verbose_logging('gnss')
