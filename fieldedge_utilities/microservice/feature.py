"""A Feature class for use as a child of a `Microservice`.
"""
from abc import ABC, abstractmethod
from typing import Any, Callable

from fieldedge_utilities.properties import (
    camel_case,
    get_class_properties,
    property_is_read_only,
    ConfigurableProperty,
)

from .interservice import IscTaskQueue

__all__ = ['Feature']


class Feature(ABC):
    """Template for a microservice feature as a child of the microservice.
    
    References the parent microservice's IscTaskQueue and methods to callback
    for task notification/complete/fail as private attributes.
    
    """

    __slots__ = ['_task_queue', '_task_notify', '_task_complete', '_task_fail']

    def __init__(self,
                 task_queue: IscTaskQueue = None,
                 task_notify: Callable[[str, dict], None] = None,
                 task_complete: Callable[[str, dict], None] = None,
                 task_fail: Callable[[Any], None] = None,
                 **kwargs) -> None:
        """Initializes the feature.
        
        Additional keyword arguments passed in each become a property/value.
        
        Args:
            task_queue (`IscTaskQueue`): The parent microservice ISC task queue.
            task_notify (`Callable[[str, dict]]`): The parent `notify`
                method for MQTT publish.
            task_complete (`Callable[[str, dict]]`): A parent task
                completion function to receive task `uid` and `task_meta`.
            task_fail (`Callable`): An optional parent function to call if the
                task fails.
        """
        self._task_queue: IscTaskQueue = task_queue
        self._task_notify: Callable[[str, dict], None] = task_notify
        self._task_complete: Callable[[str, dict], None] = task_complete
        self._task_fail: Callable[[Any], None] = task_fail
        for key, val in kwargs.items():
            self.__slots__.append(key)
            setattr(self, key, val)

    @property
    def tag(self) -> str:
        try:
            return getattr(self, '_tag')
        except AttributeError:
            return self.__class__.__name__.lower()

    @abstractmethod
    def properties_list(self, **kwargs) -> 'list[str]':
        """Returns a lists of exposed property names.
        
        Args:
            **config (bool): Returns only configuration properties if True.
            **info (bool): Returns only information properties if True.
        """
        all_props = get_class_properties(self, ignore=['tag'])
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
            info = { camel_case(k): getattr(self, k)
                    for k in self.properties_list(info=True) }
            config = { camel_case(k): getattr(self, k)
                      for k in self.properties_list(config=True) }
            return { 'config': config, 'info': info }
        return {camel_case(key): getattr(self, key)
                for key in self.properties_list()}

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
