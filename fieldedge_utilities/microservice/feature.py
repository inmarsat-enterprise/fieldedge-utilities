"""A Feature class for use as a child of a `Microservice`.
"""
from abc import ABC, abstractmethod
from typing import Callable
from .interservice import IscTaskQueue

__all__ = ['Feature']

class Feature(ABC):
    """Template for a microservice feature as a child of the microservice.
    
    Private objects and methods include _task_queue, _task_notify,
    _task_complete, _task_fail_callback.
    
    """
    def __init__(self,
                 task_queue: IscTaskQueue = None,
                 task_notify: Callable[[str, dict], None] = None,
                 task_complete: Callable[[str, dict], None] = None,
                 **kwargs) -> None:
        """Initializes the feature.
        
        Args:
            task_queue (`IscTaskQueue`): The parent microservice ISC task queue.
            task_notify (`Callable[[str, dict]]`): The parent `notify`
                method for MQTT publish.
            task_complete (`Callable[[str, dict]]`): A parent task
                completion function to receive task `uid` and `task_meta`.

        Keyword Args:
            task_fail (`Callable`): An optional parent
                function to call if the task fails.
             
        """
        self._task_queue: IscTaskQueue = task_queue
        self._task_notify: Callable[[str, dict], None] = task_notify
        self._task_complete: Callable[[str, dict], None] = task_complete
        for key, val in kwargs.items():
            setattr(self, key, val)

    @abstractmethod
    def properties_list(self) -> 'list[str]':
        """Returns a lists of exposed property names."""
        return []

    @abstractmethod
    def status(self) -> dict:
        """Returns a dictionary of key status summary information."""
        return {}

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
