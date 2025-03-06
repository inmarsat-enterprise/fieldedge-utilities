"""NMEA helper utilities for location data from commercial GNSS devices."""

import logging
# import re
from copy import deepcopy
from dataclasses import dataclass, asdict
from enum import Enum, IntEnum
from typing import Optional

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
    
    def json_compatible(self, **kwargs) -> str:
        lat_lon_precision = kwargs.get('lat_lon_precision', 5)
        other_precision = kwargs.get('other_precision', 1)
        result = { k: v for k, v in asdict(self).items() if v is not None }
        if self.timestamp is not None:
            result['iso_time'] = self.iso_time
        for k, v in result.items():
            if k in ['latitude', 'longitude']:
                result[k] = round(v, lat_lon_precision)
            elif isinstance(k, float):
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
    data, cs_hex = nmea_sentence.split('*')
    candidate = int(cs_hex, 16)
    crc = 0   # initial
    for i in range(1, len(data)):   # ignore initial $
        crc ^= ord(data[i])
    return candidate == crc


def parse_nmea_to_location(nmea_sentence: str,
                           location: GnssLocation = None,
                           **kwargs) -> 'dict|GnssLocation|None':
    """Parses a NMEA-0183 sentence to a location or update.
    
    Passing a Location object in will update the location with NMEA data.
    Otherwise a dictionary is returned.
    """
    if _vlog():
        _log.debug('Parsing NMEA: %s', nmea_sentence)
        _log.debug('Previous location: %s', location)
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
        if not field_data:
            continue   # skip empty fields
        if i == 0:
            nmea_type = field_data[-3:]
            if nmea_type not in ['RMC', 'GGA', 'GSA']:
                _log.warning('No processing defined for %s sentence', nmea_type)
                break
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
                location.speed = float(field_data) * 1.852
                if _vlog():
                    _log.debug('Speed: %.1f', location.speed)
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
         if isinstance(old_location, GnssLocation):
             return old_location
         return None
    if isinstance(old_location, GnssLocation):
        return location
    return location.json_compatible(**kwargs)


def _vlog() -> bool:
    """Check if vebose logging is enabled for this microservice."""
    return verbose_logging('nmea')


# def parse_nmea_sentence(nmea):
#     """
#     Parse an NMEA sentence and extract location, heading, speed, and UTC time.

#     Parameters:
#     - nmea: A string containing an NMEA sentence.

#     Returns:
#     - A dictionary with keys 'latitude', 'longitude', 'heading', 'speed', 'fix_quality', and 'utc_time'.
#     """
#     # Define regex patterns for NMEA sentences of interest
#     gga_pattern = re.compile(r"\$G[NP]GGA,(\d{6}\.\d+),(\d{2})(\d{2}\.\d+),([NS]),(\d{3})(\d{2}\.\d+),([EW]),(\d),")
#     rmc_pattern = re.compile(r"\$G[NP]RMC,(\d{6}\.\d+),[AV],(\d{2})(\d{2}\.\d+),([NS]),(\d{3})(\d{2}\.\d+),([EW]),(\d+\.\d+),(\d+\.\d+),")
#     gsa_pattern = re.compile(r"\$G[NP]GSA,[AM],(\d),.*")

#     # Initialize result dictionary
#     result = {
#         "latitude": None,
#         "longitude": None,
#         "heading": None,
#         "speed": None,
#         "fix_quality": None,
#         "utc_time": None,
#     }

#     # Parse GGA data (latitude, longitude, fix quality, UTC time)
#     gga_match = gga_pattern.search(nmea)
#     if gga_match:
#         utc_time = gga_match.group(1)
#         lat_deg = int(gga_match.group(2))
#         lat_min = float(gga_match.group(3))
#         lat_dir = gga_match.group(4)
#         lon_deg = int(gga_match.group(5))
#         lon_min = float(gga_match.group(6))
#         lon_dir = gga_match.group(7)
#         fix_quality = int(gga_match.group(8))

#         # Convert latitude and longitude to decimal degrees
#         latitude = lat_deg + lat_min / 60.0
#         if lat_dir == 'S':
#             latitude = -latitude

#         longitude = lon_deg + lon_min / 60.0
#         if lon_dir == 'W':
#             longitude = -longitude

#         result["latitude"] = latitude
#         result["longitude"] = longitude
#         result["fix_quality"] = fix_quality
#         result["utc_time"] = utc_time

#     # Parse RMC data (latitude, longitude, speed, heading, UTC time)
#     rmc_match = rmc_pattern.search(nmea)
#     if rmc_match:
#         utc_time = rmc_match.group(1)
#         lat_deg = int(rmc_match.group(2))
#         lat_min = float(rmc_match.group(3))
#         lat_dir = rmc_match.group(4)
#         lon_deg = int(rmc_match.group(5))
#         lon_min = float(rmc_match.group(6))
#         lon_dir = rmc_match.group(7)
#         speed_knots = float(rmc_match.group(8))
#         heading = float(rmc_match.group(9))

#         # Convert latitude and longitude to decimal degrees
#         latitude = lat_deg + lat_min / 60.0
#         if lat_dir == 'S':
#             latitude = -latitude

#         longitude = lon_deg + lon_min / 60.0
#         if lon_dir == 'W':
#             longitude = -longitude

#         # Convert speed from knots to km/h
#         speed_kmh = speed_knots * 1.852

#         result["latitude"] = latitude
#         result["longitude"] = longitude
#         result["speed"] = speed_kmh
#         result["heading"] = heading
#         result["utc_time"] = utc_time

#     # Parse GSA data (fix type)
#     gsa_match = gsa_pattern.search(nmea)
#     if gsa_match:
#         fix_quality = int(gsa_match.group(1))
#         result["fix_quality"] = fix_quality

#     return result
