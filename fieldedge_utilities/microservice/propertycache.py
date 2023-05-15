"""Classes for managing cached properties.

Cached properties are slow to initially read such as serial IO or transactions
via MQTT.
The cached value is valid for a lifetime and used to return the last read value
within a short window before a slow read is required.
Cached properties are useful for rapid-repeat queries when building message
structures for interservice communications.

"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from fieldedge_utilities.logger import verbose_logging

__all__ = ['CachedProperty', 'PropertyCache']

_log = logging.getLogger(__name__)


@dataclass
class CachedProperty:
    """A property value with a capture timestamp and lifetime.
    
    Setting `lifetime` to `None` makes the cached value always valid.
    
    """
    value: Any
    name: 'str|None' = None
    lifetime: 'float|None' = 1.0
    cache_time: float = field(default_factory=time.time)

    @property
    def age(self) -> float:
        """The age of the cached value in seconds."""
        return round(time.time() - self.cache_time, 3)

    @property
    def is_valid(self) -> bool:
        """Returns True if the age is within the lifetime."""
        if self.lifetime is None:
            return True
        return self.age <= self.lifetime


class PropertyCache:
    """A proxy dictionary for managing `CachedProperty` objects.
    
    `LOG_VERBOSE` optional environment variable may include `cache`.
    
    """
    def __init__(self) -> None:
        self._cache: 'dict[str, CachedProperty]' = {}

    def cache(self, value: Any, tag: str, lifetime: 'float|None' = 1.0) -> None:
        """Timestamps and adds a property value to the cache.
        
        If the property is already cached, it will be overwritten.
         
        Args:
            value: The property value to be cached.
            tag: The name of the property (must be unique in the cache).
            lifetime: The lifetime/validity of the value. `None` means always
                valid.
            
        """
        if value is None:
            _log.warning('Request to cache None for %s', tag)
        if tag in self._cache:
            _log.debug('Overwriting cached %s', tag)
        to_cache = CachedProperty(value, name=tag, lifetime=lifetime)
        self._cache[tag] = to_cache

    def clear(self) -> None:
        """Removes all entries from the cache."""
        _log.debug('Clearing property cache')
        self._cache = {}

    def remove(self, tag: str) -> None:
        """Removes a property value from the cache.
        
        Args:
            tag: The property name to be removed from the cache.
        
        Raises:
            `KeyError` if the tag is not in the cache.
            
        """
        cached = self._cache.pop(tag, None)
        if _vlog():
            if cached:
                _log.debug('Removed %s aged %d seconds', tag, cached.age)
            else:
                _log.debug('%s was not cached', tag)

    def get_cached(self, tag: str) -> Any:
        """Retrieves the cached property value if valid.
        
        If the property is aged/invalid, it is removed from the cache.
        
        Args:
            tag: The property name to be retrieved from the cache.
        
        Returns:
            The cached property value, or `None` if the tag is not found.
            
        """
        if tag not in self._cache:
            if _vlog():
                _log.debug('%s not cached', tag)
            return None
        cached = self._cache[tag]
        if cached.is_valid:
            if _vlog():
                _log.debug('Returning %s value %s (age %.3f seconds)',
                           tag, cached.value, cached.age)
            return cached.value
        self.remove(tag)

def _vlog() -> bool:
    return verbose_logging('propertycache')
