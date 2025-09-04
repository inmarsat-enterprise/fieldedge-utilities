"""A Feature class for use as a child of a `Microservice`.
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, TypeAlias

from fieldedge_utilities.properties import (
    camel_case,
    get_class_properties,
    property_is_read_only,
    ConfigurableProperty,
)

from .interservice import IscTaskQueue

__all__ = ['Feature']


OptCallback: TypeAlias = Optional[Callable[..., None]]


class Feature(ABC):
    """Template for a microservice feature as a child of the microservice.
    
    References the parent microservice's IscTaskQueue and methods to callback
    for task notification/complete/fail as private attributes.
    
    """

    __slots__ = ['_task_queue', '_task_notify', '_task_complete', '_task_fail',
                 '_props']

    def __init__(self, **kwargs) -> None:
        """Initializes the feature.
        
        Additional keyword arguments passed in each become a property/value.
        
        Args:
            **task_queue (`IscTaskQueue`): The parent microservice ISC task queue.
            **task_notify (`Callable[[str, dict]]`): The parent `notify`
                method for MQTT publish.
            **task_complete (`Callable[[str, dict]]`): A parent task
                completion function to receive task `uid` and `task_meta`.
            **task_fail (`Callable`): An optional parent function to call if the
                task fails.
        """
        try:
            super().__init__(**kwargs)
        except TypeError:
            try:
                super().__init__()
            except TypeError:
                # Some exotic bases may require positional args only
                pass
        self._task_queue: Optional[IscTaskQueue] = kwargs.pop('task_queue', None)
        self._task_notify: OptCallback = kwargs.pop('task_notify', None)
        self._task_complete: OptCallback = kwargs.pop('task_complete', None)
        self._task_fail: OptCallback = kwargs.pop('task_fail', None)
        self._props: dict[str, Any] = dict(kwargs)

    def __getattr__(self, name):
        # only called if normal lookup fails
        props = self.__dict__.get('_props', None)
        if props and name in props:
            return props[name]
        raise AttributeError(f'{name} not found')

    def __setattr__(self, name, value):
        # Directly set known slots
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        # For dynamic properties, ensure _props exists first
        elif '_props' in self.__dict__:
            self._props[name] = value
        # For early/inheritance initialization before _props is set
        else:
            object.__setattr__(self, name, value)
    
    @property
    def tag(self) -> str:
        try:
            return super().__getattribute__('_tag')
        except AttributeError:
            return self.__class__.__name__.lower()

    @abstractmethod
    def properties_list(self, **kwargs) -> 'list[str]':
        """Returns a lists of exposed property names.
        
        Args:
            **config (bool): Returns only configuration properties if True.
            **info (bool): Returns only information properties if True.
        """
        all_props = get_class_properties(self.__class__, ignore=['tag'])
        all_props += [p for p in self._props if not p.startswith('_')]
        if kwargs.get('config') is True:
            return [p for p in all_props if not property_is_read_only(self, p)]
        if kwargs.get('info') is True:
            return [p for p in all_props if property_is_read_only(self, p)]
        return all_props
    
    def isc_configurable(self) -> 'dict[str, ConfigurableProperty]':
        """Get the map of configurable properties."""
        return {}

    @abstractmethod
    def status(self, **kwargs) -> dict:
        """Returns a dictionary of key status summary information.
        
        Args:
            **categorized (bool): Returns categorized 
        """
        if kwargs.get('categorized') is True:
            return {
                'config': {camel_case(k): getattr(self, k)
                           for k in self.properties_list(config=True)},
                'info': {camel_case(k): getattr(self, k)
                         for k in self.properties_list(info=True)},
            }
        return {camel_case(k): getattr(self, k) for k in self.properties_list()}

    @abstractmethod
    def on_isc_message(self, topic: str, message: dict) -> bool:
        """Called by a parent Microservice to pass relevant MQTT messages.
        
        Args:
            topic (str): The message topic.
            message (dict): The message content.
        
        Returns:
            `True` if the message was processed or `False` otherwise.
            
        """
        return False
