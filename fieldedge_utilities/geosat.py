"""Geostationary Satellite class for FieldEdge microservices."""

import math
from enum import Enum

__all__ = ['GeoSatellite', 'geo_azimuth', 'geo_elevation', 'geo_closest']

# Constants
R_EARTH = 6378.137  # Radius of Earth in kilometers
R_GEO = 35786       # Altitude of geostationary orbit in kilometers


class GeoSatellite(Enum):
    """A class defining Viasat/Inmarsat geostationary satellite location.
    
    A shorthand name for the geographic zone is given to a satellite longitude.
    """
    AMER = -98.0   # I4F3 at time of writing
    AORW = -54.0   # I3F5 at time of writing
    APAC = 143.5   # I4F2 at time of writing
    EMEA = 24.9   # I4A4 (Alphasat) at time of writing
    IOE = 83.8   # I6F1 at time of writing
    USCA = -101.3   # Ligado SkyTerra-1 at time of writing


def _validate(sat_lon: float, es_lat: float, es_lon: float, precision: int):
    if any(not isinstance(lon, (float, int)) or lon < -180 or lon > 180
           for lon in (sat_lon, es_lon)):
        raise ValueError('Invalid longitude must be in range +/- 180')
    if not isinstance(es_lat, (float, int)) or es_lat < -90 or es_lat > 90:
        raise ValueError('Invalid latitude must be in range +/- 90')
    if not isinstance(precision, int) or precision not in range(0, 4):
        raise ValueError('Invalid precision must be integer in range 0..3')

    
def geo_azimuth(sat_lon: float, es_lat: float, es_lon: float, precision: int = 0) -> 'int|float':
    """Get the azimuth of a geostationary satellite.
    
    Args:
        sat_lon (float): The longitude of the satellite in degrees (+ East)
        es_lat (float): The earth station latitude in degrees (+ North)
        es_lon (float): The earth station longitude in degrees (+ East)
        precision (int): The decimal rounding of the result
    
    Returns:
        The azimuth to the satellite relative to the earth station in degrees.
    """
    _validate(sat_lon, es_lat, es_lon, precision)
    d_lon = math.radians(es_lon - sat_lon)
    es_az_rad = math.atan(math.tan(d_lon)/math.sin(math.radians(es_lat)))
    es_az = 180 + math.degrees(es_az_rad)
    if es_lat < 0:
        es_az = es_az - 180
    if es_az < 0:
        es_az = es_az + 360
    result = round(es_az, precision)
    return result if precision else int(result)


def geo_elevation(sat_lon: float, es_lat: float, es_lon: float, precision: int = 0) -> 'int|float':
    """Get the elevation of a geostationary satellite.
    
    Args:
        sat_lon (float): The longitude of the satellite in degrees (+ East)
        es_lat (float): The earth station latitude in degrees (+ North)
        es_lon (float): The earth station longitude in degrees (+ East)
        precision (int): The decimal rounding of the result
    
    Returns:
        The elevation to the satellite relative to the earth station in degrees.
    """
    _validate(sat_lon, es_lat, es_lon, precision)
    d_lon = math.radians(es_lon - sat_lon)
    es_lat_rad = math.radians(es_lat)
    r1 = 1 + R_GEO / R_EARTH
    v1 = r1 * math.cos(es_lat_rad) * math.cos(d_lon) - 1
    v2 = r1 * math.sqrt(1 - math.cos(es_lat_rad)**2 * math.cos(d_lon)**2)
    es_el = math.degrees(math.atan(v1/v2))
    result = round(es_el, precision)
    return result if precision else int(result)


def geo_closest(es_lat: float, es_lon: float, exclude: 'list[str]' = []) -> 'GeoSatellite':
    """Get the GeoSatellite closest to the specified location.
    
    Args:
        es_lat (float): The earth station latitude in degrees.
        es_lon (float): The earth station longitude in degrees.
        exclude (list[str]): Optional satellite shorthand names to exclude
    
    Returns:
        `GeoSatellite` closest to the earth station.
    """
    sats = [e for e in GeoSatellite]
    sat_names = [e.name for e in GeoSatellite]
    if not isinstance(es_lat, (float, int)) or es_lat < -90 or es_lat > 90:
        raise ValueError('Invalid latitude must be in range +/- 90')
    if not isinstance(es_lon, (float, int)) or es_lon < -180 or es_lon > 180:
        raise ValueError('Invalid longitude must be in range +/- 180')
    if not isinstance(exclude, list) or not all(x in sat_names for x in exclude):
        raise ValueError(f'Invalid exclusion name must be in ({sat_names})')
    if isinstance(exclude, list) and all(isinstance(x, str) for x in exclude):
        rem = []
        for i, sat in enumerate(sats):
            if sat.name in exclude:
                rem.append(i)
        for i in rem:
            del sats[i]
    closest = min(sats, key=lambda x:abs(x.value - es_lon))
    if (GeoSatellite.AORW.name not in exclude and
        closest == GeoSatellite.AORW):
        if es_lat >= 15 or es_lat <= -45:
            if es_lon < -27:
                closest = GeoSatellite.AMER
            else:
                closest = GeoSatellite.EMEA
    if (GeoSatellite.USCA.name not in exclude and
        closest == GeoSatellite.AMER):
        if (es_lat > 25 and es_lat < 60) and es_lon > -123:
            closest = GeoSatellite.USCA
    return closest
