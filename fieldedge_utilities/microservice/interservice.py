"""Classes for interservice communications (ISC).
"""
import logging
import threading
import time
from typing import Any, Callable, Optional, Protocol, Union
from uuid import uuid4

from fieldedge_utilities.logger import verbose_logging

__all__ = ['IscException', 'IscTaskQueueFull', 'IscTask', 'IscTaskQueue']

_log = logging.getLogger(__name__)


class PublishCallback(Protocol):
    """Protocol for calling back to a microservice to publish ISC."""
    def __call__(self, topic: str, message: dict[str, Any], **kwargs) -> None:
        ...


class SubscribeCallback(Protocol):
    """Protocol for calling back to a microservice to subscribe to ISC topic."""
    def __call__(self, topic: str, **kwargs) -> bool:
        ...


class UnsubscribeCallback(Protocol):
    """Protocol for calling back to a microservice to unsubscribe to ISC topic."""
    def __call__(self, topic: str) -> bool:
        ...


class IscException(Exception):
    """Base class for ISC exceptions."""


class IscTaskQueueFull(IscException):
    """ISC task queue is full."""


class IscTaskNotReleased(IscException):
    """ISC task was not released."""


class IscTask:
    """An interservice communication task waiting for an MQTT response.
    
    May be a long-running query with optional metadata, and optional callback
    to a chained function.
    
    The `task_meta` attribute supports a dictionary keyword `timeout_callback`
    as a `Callable` that will be passed the metadata and `uid` if the task
    expires triggered by the method `IscTaskQueue.remove_expired`.
    
    Attributes:
        uid (UUID): A unique task identifier, if none is provided a `UUID4` will
            be generated.
        ts: (float): The unix timestamp when the task was queued
        lifetime (int): Seconds before the task times out. `None` value
            means the task will not expire/timeout.
        task_type (str): A short name for the task purpose
        task_meta (Any): Metadata to be used on completion or passed to the
            `callback`
        callback (Callable): An optional callback function

    """
    def __init__(self,
                 uid: Optional[str] = None,
                 task_type: Optional[str] = None,
                 task_meta: Optional[Any] = None,
                 callback: Optional[Callable] = None,
                 lifetime: Union[float, None] = 10,
                 ) -> None:
        """Initialize the Task.
        
        Args:
            uid (UUID): A unique task identifier
            task_type (str): A short name for the task purpose
            task_meta (Any): Metadata to be passed to the callback. Supports
                dict key 'timeout_callback' with Callable value.
            callback (Callable): An optional callback function to chain
            lifetime (int): Seconds before the task times out. `None` value
                means the task will not expire/timeout.
        
        """
        self._ts: float = round(time.time(), 3)
        self.uid: str = uid or str(uuid4())
        self.task_type: Optional[str] = task_type
        self._lifetime: 'float|None' = None
        self.lifetime = lifetime
        self.task_meta = task_meta
        if (isinstance(task_meta, dict) and
            'timeout_callback' in task_meta and
            not callable(task_meta['timeout_callback'])):
            # Generate warning
            _log.warning('Task timeout_callback is not callable')
        if callback is not None and not callable(callback):
            raise ValueError('Next task callback must be callable if not None')
        self.callback: Optional[Callable] = callback
    
    @property
    def ts(self) -> float:
        return self._ts
    
    @property
    def lifetime(self) -> 'float|None':
        if self._lifetime is None:
            return None
        return round(self._lifetime, 3)
    
    @lifetime.setter
    def lifetime(self, value: Union[float, int, None]):
        if value is None:
            _log.warning('Task lifetime set to None (no expiry)')
            self._lifetime = None
            return
        elif not isinstance(value, (float, int)):
            raise ValueError('Value must be float or int')
        self._lifetime = float(value)


class IscTaskQueue(list):
    """Order-independent searchable task queue for interservice communications.
    
    By default the depth is None (infinite) and supports multiple tasks.
    Tasks may be retrieved by `uid` or by a `task_meta` key.
    
    Supports optional blocking initialization with a queue depth of 1.
    Care must be taken to `set()` the `task_blocking` Event after using `get`.
    
    Attributes:
        task_blocking (threading.Event): Accessible if initialized as blocking.
        unblock_on_expiry (bool): If blocking and task expires, automatically
            unblock.
    
    Raises:
        `IscTaskQueueFull` if blocking and a task is in the queue.
        `OSError` for unsupported list operations: `insert`, `extend`.
    
    """
    def __init__(self, blocking: bool = False, unblock_on_expiry: bool = True):
        super().__init__()
        self._blocking = blocking
        self._unblock_on_expiry = unblock_on_expiry
        self._task_blocking = threading.Event()
        self._task_blocking.set()
        self._lock = threading.Lock()

    @property
    def task_blocking(self) -> Union[threading.Event, None]:
        """A threading.Event if the queue was initialized as blocking."""
        return self._task_blocking if self._blocking else None

    @property
    def is_full(self) -> bool:
        return self._blocking and len(self) > 0
    
    def unblock_tasks(self, unblock: bool = True):
        """Unblocks tasks if set."""
        if self._blocking and unblock is True:
            if self.task_blocking and not self.task_blocking.is_set():
                _log.debug('Unblocking tasks - task_blocking.set()')
                self.task_blocking.set()

    def append(self, task: IscTask) -> None:
        """Add a task to the queue.
        
        Args:
            task (IscTask): The task to add to the queue.
        
        Raises:
            `ValueError` if the task is invalid type or a conflicting uid is
                already in the queue.
            `IscTaskQueueFull` if the queue is blocking and has a task already.
            `IscTaskNotReleased` if the queue is blocking, empty but the Event
                was not set (released).
        
        """
        if not isinstance(task, IscTask) or not hasattr(task, 'uid'):
            raise ValueError('item must be IscTask with uid')
        with self._lock:
            if any(t.uid == task.uid for t in self):
                raise ValueError(f'Task {task.uid} already queued')
            if self._blocking:
                if len(self) == 1:
                    raise IscTaskQueueFull
                if self.task_blocking:
                    if not self.task_blocking.is_set():
                        raise IscTaskNotReleased
                    self.task_blocking.clear()
            if _vlog():
                _log.debug('Queued task: %s', task.__dict__)
            super().append(task)

    def peek(self,
             task_id: Optional[str] = None,
             task_type: Optional[str] = None,
             task_meta: Optional[dict[str, Any]] = None,
             ) -> Union[IscTask, None]:
        """Returns a queued task if it matches the search criteria.
        
        The task remains in the queue.
        
        Args:
            task_id: optional first criteria is unique id
            task_type: optional second criteria returns first match
            task_meta: optional metadata filter criteria
            
        """
        if not task_id and not task_type and not task_meta:
            raise ValueError('Missing search criteria')
        if isinstance(task_meta, tuple):
            task_meta = dict([task_meta])     # convert legacy tuple to dict
        with self._lock:
            for task in self:
                assert isinstance(task, IscTask)
                if ((task_id and task.uid == task_id) or
                    (task_type and task.task_type == task_type)):
                    return task
                elif isinstance(task_meta, dict):
                    candidate = task.task_meta
                    if isinstance(candidate, dict):
                        if all(k in candidate and task_meta[k] == v
                            for k, v in task_meta.items()):
                            return task
        return None

    def is_queued(self,
                  task_id: Optional[str] = None,
                  task_type: Optional[str] = None,
                  task_meta: Optional[dict[str, Any]] = None) -> bool:
        """Returns `True` if the specified task is queued.
        
        Args:
            task_id: Optional (preferred) unique search criteria.
            task_type: Optional search criteria. May not be unique.
            task_meta: Optional key/value search criteria.
        
        Returns:
            True if the specified task is in the queue.
        
        """
        return isinstance(self.peek(task_id, task_type, task_meta), IscTask)

    def get(self,
            task_id: Optional[str] = None,
            task_meta: Optional[dict[str, Any]] = None,
            unblock: bool = False) -> Union[IscTask, None]:
        """Retrieves the specified task from the queue.
        
        Uses task `uid` or `task_meta` tuple.
        
        Args:
            task_id (str): The task `uid`.
            task_meta (dict): A `task_meta` dict to match key/value pair(s).
        
        Returns:
            The specified `IscTask`, removing it from the queue.
        
        Raises:
            `ValueError` if neither task_id nor task_meta are specified.
        
        """
        if not task_id and not task_meta:
            raise ValueError('task_id or task_meta must be specified')
        if isinstance(task_meta, tuple):
            task_meta = dict(task_meta)     # convert legacy tuple to dict
        with self._lock:
            for i, task in enumerate(self):
                assert isinstance(task, IscTask)
                match = False
                if task_id and task.uid == task_id:
                    match = True
                elif (isinstance(task_meta, dict) and
                      isinstance(task.task_meta, dict)):
                    if all(task.task_meta.get(k) == v
                           for k, v in task_meta.items()):
                        match = True
                if match:
                    if unblock:
                        self.unblock_tasks(True)
                    return self.pop(i)
        _log.warning('No matching task found in ISC queue')
        return None

    def remove_expired(self):
        """Removes expired tasks from the queue.
        
        Should be called regularly by the parent, for example every second.
        
        Any tasks with callback and cb_meta that include the keyword `timeout`
        will be called with the cb_meta kwargs.
        
        """
        if len(self) == 0:
            return
        now = time.time()
        with self._lock:
            expired_indices = []
            for i, task in enumerate(self):
                assert isinstance(task, IscTask)
                if task.lifetime is not None and now - task.ts > task.lifetime:
                    expired_indices.append(i)
            for i in sorted(expired_indices, reverse=True):
                task: IscTask = self.pop(i)
                _log.warning('Removed expired task %s', task.uid)
                if (self._blocking and
                    self.task_blocking and not self.task_blocking.is_set()):
                    if self._unblock_on_expiry:
                        _log.info('Unblocking expired task %s', task.uid)
                        self.task_blocking.set()
                    else:
                        _log.warning('Expired task %s still blocking', task.uid)
                if isinstance(task.task_meta, dict):
                    cb_key = 'timeout_callback'
                    timeout_callback = task.task_meta.get(cb_key)
                    if callable(timeout_callback):
                        timeout_meta = {k: v for k, v in task.task_meta.items()
                                        if k != cb_key}
                        timeout_meta['uid'] = task.uid
                        timeout_callback(timeout_meta)

    def clear(self):
        """Removes all items from the queue."""
        with self._lock:
            super().clear()
            self.unblock_tasks(True)

    def insert(self, index, item):
        """Invalid operation."""
        raise OSError('ISC task queue does not support insertion')

    def extend(self, other):
        """Invalid operation."""
        raise OSError('ISC task queue does not support extension')


def _vlog() -> bool:
    return verbose_logging('isctaskqueue')
