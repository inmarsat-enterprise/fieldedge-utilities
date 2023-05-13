"""Classes for interservice communications (ISC).
"""
import logging
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from fieldedge_utilities.logger import verbose_logging

__all__ = ['IscException', 'IscTaskQueueFull', 'IscTask', 'IscTaskQueue']

_log = logging.getLogger(__name__)


class IscException(Exception):
    """"""


class IscTaskQueueFull(IscException):
    """"""


class IscTaskNotReleased(IscException):
    """"""


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
                 uid: str = None,
                 task_type: str = None,
                 task_meta: Any = None,
                 callback: Callable = None,
                 lifetime: 'float|None' = 10,
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
        self.task_type: str = task_type
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
        self.callback: Callable = callback
    
    @property
    def ts(self) -> float:
        return self._ts
    
    @property
    def lifetime(self) -> 'float|None':
        if self._lifetime is None:
            return None
        return round(self._lifetime, 3)
    
    @lifetime.setter
    def lifetime(self, value: 'float|int|None'):
        if value is None:
            _log.warning('Task lifetime set to None (no expiry)')
            self._lifetime = None
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

    @property
    def task_blocking(self) -> 'threading.Event|None':
        """A threading.Event if the queue was initialized as blocking, or None.
        """
        if self._blocking:
            return self._task_blocking

    @property
    def _vlog(self) -> bool:
        return verbose_logging('isctaskqueue')

    def unblock_tasks(self, unblock: bool = True):
        """Unblocks tasks if set."""
        if self._blocking and unblock is True:
            if not self.task_blocking.is_set():
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
        if not isinstance(task, IscTask):
            raise ValueError('item must be IscTask type')
        if self.is_queued(task.uid):
            raise ValueError(f'Task {task.uid} already queued')
        if self._blocking:
            if len(self) == 1:
                raise IscTaskQueueFull
            if not self.task_blocking.is_set():
                raise IscTaskNotReleased
            self.task_blocking.clear()
        if self._vlog:
            _log.debug('Queued task: %s', task.__dict__)
        super().append(task)

    def peek(self,
             task_id: str = None,
             task_type: str = None,
             task_meta: 'tuple[str, Any]' = None) -> 'IscTask|None':
        """Returns the task based on search criteria or None."""
        if not task_id and not task_type and not task_meta:
            raise ValueError('Missing search criteria')
        if isinstance(task_meta, tuple) and len(task_meta) != 2:
            raise ValueError('cb_meta must be a key/value pair')
        for task in self:
            assert isinstance(task, IscTask)
            if ((task_id and task.uid == task_id) or
                (task_type and task.task_type == task_type)):
                return task
            if isinstance(task_meta, tuple):
                if not isinstance(task.task_meta, dict):
                    continue
                for k, v in task.task_meta.items():
                    if k == task_meta[0] and v == task_meta[1]:
                        return task
        return None

    def is_queued(self,
                  task_id: str = None,
                  task_type: str = None,
                  task_meta: 'tuple[str, Any]' = None) -> bool:
        """Returns `True` if the specified task is queued.
        
        Args:
            task_id: Optional (preferred) unique search criteria.
            task_type: Optional search criteria. May not be unique.
            cb_meta: Optional key/value search criteria.
        
        Returns:
            True if the specified task is in the queue.
        
        """
        return isinstance(self.peek(task_id, task_type, task_meta), IscTask)

    def get(self,
            task_id: str = None,
            task_meta: 'tuple[str, Any]' = None,
            unblock: bool = False) -> 'IscTask|None':
        """Retrieves the specified task from the queue.
        
        Uses task `uid` or `task_meta` tuple.
        
        Args:
            task_id (str): The task `uid`.
            task_meta (tuple): A `task_meta` tuple with (key, value).
        
        Returns:
            The specified `IscTask`, removing it from the queue.
        
        Raises:
            `ValueError` if neither task_id nor task_meta are specified.
        
        """
        if isinstance(task_id, str):
            for i, task in enumerate(self):
                assert isinstance(task, IscTask)
                if task.uid == task_id:
                    self.unblock_tasks(unblock)
                    return self.pop(i)
            _log.warning('task_id %s not in queue', task_id)
        elif isinstance(task_meta, tuple):
            k, v = task_meta
            for i, task in enumerate(self):
                assert isinstance(task, IscTask)
                candidate = task.task_meta
                if (isinstance(candidate, dict) and
                    k in candidate and candidate[k] == v):
                    # found match
                    self.unblock_tasks(unblock)
                    return self.pop(i)
            _log.warning('task_id %s not in queue', task_id)
        else:
            raise ValueError('task_id or meta_tag must be specified')

    def remove_expired(self):
        """Removes expired tasks from the queue.
        
        Should be called regularly by the parent, for example every second.
        
        Any tasks with callback and cb_meta that include the keyword `timeout`
        will be called with the cb_meta kwargs.
        
        """
        if len(self) == 0:
            return
        expired: 'dict[int, str]' = {}
        for i, task in enumerate(self):
            assert isinstance(task, IscTask)
            if task.lifetime is None:
                continue
            if time.time() - task.ts > task.lifetime:
                expired[i] = task.uid
        for i, uid in expired.items():
            rem: IscTask = self.pop(i)
            _log.warning(f'Removed expired task {rem.uid}')
            if self._blocking and not self.task_blocking.is_set():
                if self._unblock_on_expiry:
                    _log.info('Unblocking expired task %s', uid)
                    self.task_blocking.set()
                else:
                    _log.warning('Expired task %s still blocking', uid)
            cb_key = 'timeout_callback'
            if (isinstance(rem.task_meta, dict) and
                cb_key in rem.task_meta and
                callable(rem.task_meta[cb_key])):
                # Callback with metadata
                timeout_meta = { 'uid': rem.uid }
                for k, v in rem.task_meta.items():
                    if k in [cb_key]:
                        continue
                    timeout_meta[k] = v
                rem.task_meta[cb_key](timeout_meta)

    def clear(self):
        """Removes all items from the queue."""
        super().clear()
        self.unblock_tasks(True)

    def insert(self, index, item):
        """Invalid operation."""
        raise OSError('ISC task queue does not support insertion')

    def extend(self, other):
        """Invalid operation."""
        raise OSError('ISC task queue does not support insertion')
