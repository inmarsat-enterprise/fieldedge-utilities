"""Classes for interservice communications (ISC).
"""
import logging
import time
from typing import Any, Callable
from uuid import uuid4

_log = logging.getLogger(__name__)


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
                 lifetime: float = 10,
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
        self._lifetime: float = float(lifetime)
        self.task_meta = task_meta
        if (isinstance(task_meta, dict) and
            'timeout_callback' in task_meta and
            not callable(task_meta['timeout_callback'])):
            # Generate warning
            _log.warning(f'Task timeout_callback is not callable')
        if callback is not None and not callable(callback):
            raise ValueError('Next task callback must be callable if not None')
        self.callback: Callable = callback
    
    @property
    def ts(self) -> float:
        return self._ts
    
    @property
    def lifetime(self) -> float:
        return round(self._lifetime, 3)
    
    @lifetime.setter
    def lifetime(self, value: 'float|int'):
        if not isinstance(value, (float, int)):
            raise ValueError('Value must be float or int')
        self._lifetime = float(value)


class IscTaskQueue(list):
    """A task queue (order-independent) for interservice communications."""
    
    def append(self, task: IscTask):
        """Add a task to the queue."""
        if not isinstance(task, IscTask):
            raise ValueError('item must be QueuedIscTask type')
        if self.is_queued(task.uid):
            raise ValueError(f'Task {task.uid} already queued')
        super().append(task)
    
    def insert(self, index: int, element: Any):
        """Invalid operation."""
        raise OSError('ISC task queue does not support insertion')
        
    def is_queued(self,
                  task_id: str = None,
                  task_type: str = None,
                  task_meta: tuple = None) -> bool:
        """Returns `True` if the specified task is queued.
        
        Args:
            task_id: Optional (preferred) unique search criteria.
            task_type: Optional search criteria. May not be unique.
            cb_meta: Optional key/value search criteria.
            
        """
        if not task_id and not task_type and not task_meta:
            raise ValueError('Missing search criteria')
        if isinstance(task_meta, tuple) and len(task_meta) != 2:
            raise ValueError('cb_meta must be a key/value pair')
        for task in self:
            assert isinstance(task, IscTask)
            if ((task_id and task.uid == task_id) or
                (task_type and task.task_type == task_type)):
                return True
            if isinstance(task_meta, tuple):
                if not isinstance(task.task_meta, dict):
                    continue
                for k, v in task.task_meta.items():
                    if k == task_meta[0] and v == task_meta[1]:
                        return True
        return False
            
    def get(self, task_id: str) -> 'IscTask|None':
        """Retrieves the specified task from the queue."""
        for i, task in enumerate(self):
            assert isinstance(task, IscTask)
            if task.uid == task_id:
                return self.pop(i)
    
    def remove_expired(self):
        """Removes expired tasks from the queue.
        
        Should be called regularly by the parent, for example every second.
        
        Any tasks with callback and cb_meta that include the keyword `timeout`
        will be called with the cb_meta kwargs.
        
        """
        expired = []
        if len(self) == 0:
            return
        for i, task in enumerate(self):
            assert isinstance(task, IscTask)
            if task.lifetime is None:
                continue
            if time.time() - task.ts > task.lifetime:
                expired.append(i)
        for i in expired:
            rem: IscTask = self.pop(i)
            _log.warning(f'Removing expired task {rem.uid}')
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
