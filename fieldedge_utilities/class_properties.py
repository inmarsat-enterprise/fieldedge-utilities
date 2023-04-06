"""FieldEdge class/property helpers

*DEPRECATED*.
Moved into microservice.properties module

"""
from time import time

from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.microservice.properties import *
from fieldedge_utilities.microservice.properties import _log

PROPERTY_CACHE_DEFAULT = 5


def cache_valid(ref_time: 'int|float',
                max_age: int = PROPERTY_CACHE_DEFAULT,
                tag: str = None,
                ) -> bool:
    """Determines if cached property value is younger than the threshold.
    
    **NOTE** Will be deprecated. Use microservice.propertycache objects instead.
    
    `PROPERTY_CACHE_DEFAULT` = 5 seconds. Can be overridden as an environment
    variable.
    Many FieldEdge Class properties are derived from *slow* operations but may
    be queried in rapid succession and can be inter-dependent. Caching reduces
    query time for such values.
    
    Args:
        ref: The reference time (seconds) of the previously cached value
            (typically a private property held in a dictionary)
        max_age: The maximum age of the cached value in seconds.
        tag: The name of the property (used for debug purposes).
    
    Returns:
        False is the cache is stale and a new value should be queried from the
            raw resource.
    """
    if not isinstance(ref_time, int):
        try:
            ref_time = int(ref_time)
        except:
            raise ValueError('Invalid reference time')
    cache_age = int(time()) - ref_time
    if cache_age > max_age:
        if verbose_logging('cache'):
            tag = tag or '?'
            _log.debug(f'Cached {tag} only {cache_age} seconds old'
                       f' (cache = {max_age}s)')
        return False
    if tag:
        _log.debug(f'Using cached {tag} ({cache_age} seconds)')
    return True
