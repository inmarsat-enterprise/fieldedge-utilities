"""Delegated Property class with optional caching.
"""
import inspect
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Generic, Optional, TypeVar

from fieldedge_utilities.path import get_caller_name

__all__ = [
    'DelegatedProperty',
    'clear_delegated_cache',
    'temporary_delegated_cache',
    'hold_delegated_cache',
]

T = TypeVar("T")
_MISSING = object()
LOG_LEVELS = (
    0,  # disabled
    logging.CRITICAL,
    logging.ERROR,
    logging.WARNING,
    logging.INFO,
    logging.DEBUG,
)

_log = logging.getLogger(__name__)


class DelegatedProperty(Generic[T]):
    """
    Descriptor that acts like a hybrid of `@property` and an attribute delegate,
    with optional caching.

    A `DelegatedProperty` may be defined in two ways:
      * As an explicit instance attribute reference:
          foo: DelegatedProperty[str] = DelegatedProperty("foo")
      * As a decorator above a method that computes the value:
          @DelegatedProperty(cache_ttl=10)
          def foo(self) -> str:
              return "computed"

    The resolution order when accessing the property is:

        1. **Cached value**  
           If a cached value is stored and still valid within its TTL
           (`cache_ttl=None` means forever, `cache_ttl=0` disables caching),
           that value is returned immediately.

        2. **Instance attribute override**  
           If the instance’s `__dict__` contains an explicit value for the
           property name, that is returned.

        3. **Decorator-provided function**  
           If this `DelegatedProperty` was declared with `@DelegatedProperty`,
           the decorated function is invoked to compute the value.

        4. **Base class definition**  
           If a base class defines an attribute of the same name (but not
           another `DelegatedProperty`), it is used:
             - If it is a `property`, its getter is invoked.
             - If it is a method, the bound method is called (treating the
               method like a computed property).
             - Otherwise, the raw class attribute is returned.

        5. **Fallback getter method**  
           If no value was found, an instance method named `get_<name>()`
           is looked up and called. For example, `foo` will fallback to
           `self.get_foo()`.

    Assignment (`obj.foo = value`) and deletion (`del obj.foo`) write through
    to the instance’s `__dict__`, and also update or clear the cache slots.

    Args:
        name: Optional explicit property name. If omitted when used as a
              decorator, the decorated function name is used.
        cache_ttl: Time-to-live in seconds for cached values.
                   * `0` disables caching (always recompute).
                   * `None` caches forever.
                   * `>0` caches until the TTL expires.
    """
    
    def __init__(self,
                 name: Optional[str] = None,
                 cache_ttl: float | None = 0,
                 log_getter: int = 0,
                 writable: bool = False,
                 ):
        """
        name: attribute name to expose (or 'get_<name>' method)
        cache_ttl: Time to live in seconds; 0 = no cache (default);
            None = cache forever
        getter_info: Optional string to log as INFO when calling non-cached.
        """
        self.name = name
        self.cache_ttl = cache_ttl
        if not isinstance(log_getter, int) or log_getter not in LOG_LEVELS:
            raise ValueError('Invalid log_getter level')
        self._log_getter = log_getter
        self._writable = writable
        self._func: Optional[Callable[[Any], T]] = None
        # Expose property-like attributes
        self.fget: Optional[Callable[[Any], T]] = None
        self.fset: Optional[Callable[[Any, T], None]] = None
        self.fdel: Optional[Callable[[Any], None]] = None
        if name:
            self._cache_name = f'__cache_{name}'
            self._time_name = f'__cache_time_{name}'

    def __call__(self, func: Callable[..., T]) -> 'DelegatedProperty[T]':
        """Allow decorator syntax above a method."""
        if self.name is None:
            self.name = func.__name__
            self._cache_name = f'__cache_{self.name}'
            self._time_name = f'__cache_time_{self.name}'
        self._func = func
        self.fget = func
        return self
    
    def __get__(self, instance: Any, owner: Optional[type] = None) -> T:
        if instance is None:
            return self  # type: ignore for class access

        now = time.monotonic()
        inst_dict: dict[str, Any] = object.__getattribute__(instance, '__dict__')
        notified = False

        # 0) Check temporary cache override if present
        if self.name is None:
            raise AttributeError('No name for property')
        override_key = f'__cache_ttl_override_{self.name}'
        ttl = inst_dict.get(override_key, self.cache_ttl)
        
        # 1) cache check
        cached = inst_dict.get(self._cache_name, _MISSING)
        if cached is not _MISSING:
            if ttl is None:
                return cached  # forever
            if ttl > 0:
                t_cached = inst_dict.get(self._time_name, 0.0)
                if (now - t_cached) < ttl:
                    return cached
                if self._log_getter and not notified:
                    caller = get_caller_name(depth=2, mth=True)
                    _log.log(self._log_getter,
                             'Refreshing expired %s cache (for: %s, ttl: %s)',
                             self.name, caller, ttl)
                    notified = True
            if ttl == 0:
                # clean stale cache entries then fall through
                inst_dict.pop(self._cache_name, None)
                inst_dict.pop(self._time_name, None)

        # 2) instance attribute (bypass descriptor)
        if self.name is None:
            raise AttributeError('No name for property')
        inst_val = inst_dict.get(self.name, _MISSING)
        if inst_val is not _MISSING:
            value = inst_val
        elif self._func and callable(self._func):
            value = self._func(instance)
        else:
            # 3) base class implementation (skip this descriptor)
            value = _MISSING
            for base in type(instance).__mro__[1:]:  # skip current class
                if self.name in base.__dict__:
                    attr = base.__dict__[self.name]

                    # If the base defines the same DelegatedProperty, skip to avoid recursion
                    if isinstance(attr, DelegatedProperty):
                        continue

                    # property or function: bind/resolve properly
                    if isinstance(attr, property):
                        value = attr.__get__(instance, type(instance))
                    elif inspect.isfunction(attr) or inspect.ismethoddescriptor(attr):
                        # bind and call if you expect a method-as-property pattern,
                        # but normally you'd treat this as a method, not a property.
                        bound = attr.__get__(instance, type(instance))
                        value = bound()
                    else:
                        # class-level constant
                        value = attr
                    break

            # 4) fallback: get_<name>() on the instance (bypass dynamic lookup)
            if value is _MISSING:
                getter_name = f"get_{self.name}"
                try:
                    if self._log_getter and not notified:
                        caller = get_caller_name(depth=2, mth=True)
                        _log.info('Getting new %s... (for: %s, ttl: %s)',
                                  self.name, caller, ttl)
                        notified = True
                    getter = object.__getattribute__(instance, getter_name)
                except AttributeError:
                    raise AttributeError('No property, instance attr, or getter'
                                         f'for {self.name}')
                value = getter()

        # 5) write cache if configured
        if ttl is None or ttl > 0:
            now = time.monotonic()  # update time based on query response
            inst_dict[self._cache_name] = value
            inst_dict[self._time_name] = now

        return value  # type: ignore[return-value]

    def __set__(self, instance: Any, value: T) -> None:
        # Make this a data-descriptor only if you truly want assignment through it.
        if self.name is None:
            raise AttributeError('No name for property')
        if not self._writable:
            raise AttributeError(f'{self.name} is read-only')
        if self._func is not None:
            raise AttributeError('Cannot assign to computed DelegatedProperty'
                                 f' {self.name}')
        inst_dict: dict[str, Any] = object.__getattribute__(instance, '__dict__')
        if self.cache_ttl is None or self.cache_ttl > 0:
            inst_dict[self._cache_name] = value
            inst_dict[self._time_name] = time.monotonic()
        if self.fset is None:
            self.fset = self.__set__
            inst_dict[self.name] = value  # write-through to instance (bypasses recursion)
        elif callable(self.fset):
            self.fset(instance, value)

    def setter(self, func: Callable[[Any, T], None]) -> 'DelegatedProperty[T]':
        """Attach a custom setter like @prop.setter."""
        self.fset = func
        self._writable = True
        return self
    
    def __delete__(self, instance: Any) -> None:
        if self.name is None:
            raise AttributeError('No name for property')
        inst_dict: dict[str, Any] = object.__getattribute__(instance, "__dict__")
        inst_dict.pop(self._cache_name, None)
        inst_dict.pop(self._time_name, None)
        inst_dict.pop(self.name, None)
        if self.fdel is None:
            self.fdel = self.__delete__
        elif callable(self.fdel):
            self.fdel(instance)
    
    def deleter(self, func: Callable[[Any], None]) -> 'DelegatedProperty[T]':
        """Attach a custom deleter like @prop.deleter."""
        self.fdel = func
        return self


def clear_delegated_cache(instance: Any, name: Optional[str] = None) -> None:
    """Clear all cached values for DelegatedProperty descriptors on the instance.
    
    Args:
        instance: The object whose cache(s) should be cleared.
        name: If provided, only clear the cache for this property name
    """
    if name is not None and (not isinstance(name, str) or len(name) == 0):
        raise ValueError('Name must be a non-empty string or None')
    inst_dict: dict[str, Any] = object.__getattribute__(instance, '__dict__')
    for cls in type(instance).__mro__:
        for attr_name, attr in cls.__dict__.items():
            if not isinstance(attr, DelegatedProperty):
                continue
            if name is not None and attr_name != name:
                continue
            if isinstance(attr, DelegatedProperty):
                inst_dict.pop(attr._cache_name, None)
                inst_dict.pop(attr._time_name, None)
            if name is not None:
                return


@contextmanager
def temporary_delegated_cache(instance: Any, name: str, ttl: float|None):
    """Temporarily modify the DelegatedProperty cache for one read.
    
    Args:
        instance: The object with the delegated property.
        name: The name of the delegated property.
        ttl: The temporary time-to-live in seconds.
    """
    if not isinstance(name, str) or len(name) == 0:
        raise ValueError('Invalid name')
    if ttl is not None and (not isinstance(ttl, (float, int)) or ttl < 0):
        raise ValueError('Invalid ttl')
    key = f'__cache_ttl_override_{name}'
    inst_dict: dict[str, Any] = object.__getattribute__(instance, '__dict__')
    old = inst_dict.get(key, _MISSING)
    inst_dict[key] = ttl
    try:
        yield
    finally:
        if old is _MISSING:
            inst_dict.pop(key, None)
        else:
            inst_dict[key] = old


def hold_delegated_cache(instance: Any, *props: DelegatedProperty):
    """Temporarily extend the cache lifetime for one or more DelegatedProperty.
    
    This resets their cache timestamps to 'now' at entry (and again at exit),
    ensuring that successive reads during the block won’t expire mid-loop.
    """
    def _extend():
        now = time.monotonic()
        inst_dict = object.__getattribute__(instance, '__dict__')
        for prop in props:
            if prop.cache_ttl and prop.cache_ttl > 0:
                inst_dict[prop._time_name] = now    
    _extend()   # at entry
    try:
        yield
    finally:
        _extend()   # at exit
