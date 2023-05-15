"""A proxy class for interfacing with other Microservices via MQTT.
"""
import logging
import os
from abc import ABC, abstractmethod
from enum import IntEnum
from threading import Event
from typing import Any, Callable

from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.timer import RepeatingTimer

from .interservice import IscException, IscTask, IscTaskQueue
from .propertycache import PropertyCache

__all__ = ['MicroserviceProxy', 'InitializationState']

_log = logging.getLogger(__name__)

PROXY_PROPERTY_TIMEOUT = int(os.getenv('PROXY_PROPERTY_TIMEOUT', '35'))


class InitializationState(IntEnum):
    """Initialization state of the MicroserviceProxy."""
    NONE = 0
    PENDING = 1
    COMPLETE = 2


class MicroserviceProxy(ABC):
    """A proxy model for another FieldEdge microservice accessed via MQTT.
    
    Queries a microservice based on its tag to populate proxy_properties.
    Has a blocking (1-deep) `IscTaskQueue` for each remote query to complete
    before the next task can be queued.
    
    """
    def __init__(self, **kwargs):
        """Initialize the proxy.
        
        Keyword Args:
            tag (str): The name of the microservice used in the MQTT topic.
                If not provided will use the lowercase class name.
            publish (Callable[[str, dict]]): Parent MQTT publish function
            subscribe (Callable[[str]]): Parent MQTT subscribe function
            unsubscribe (Callable[[str]]): Parent MQTT unsubscribe function
            init_callback (Callable[[bool, str]]): Optional callback when
                initialize() completes.
            init_timeout (int): Time in seconds allowed for initialization.
            cache_lifetime (int): The proxy property cache time.
            isc_poll_interval (int): The time between checks for task expiry.
        
        """
        self._tag: str = (kwargs.get('tag', None) or
                          self.__class__.__name__.lower())
        if not self._tag:
            raise ValueError('Invalid tag provided')
        callbacks = ['publish', 'subscribe', 'unsubscribe', 'init_callback']
        int_config = ['init_timeout', 'cache_lifetime', 'isc_poll_interval']
        for key, val in kwargs.items():
            if key in callbacks:
                if not callable(val):
                    raise ValueError(f'{key} must be callable')
            elif key in int_config:
                if not isinstance(val, int) or val <= 0:
                    raise ValueError(f'{key} must be integer > 0')
        self._publish: Callable[[str, dict], None] = kwargs.get('publish', None)
        self._subscribe: Callable[['str|list[str]'], bool] = (
            kwargs.get('subscribe', None))
        self._unsubscribe: Callable[['str|list[str]'], bool] = (
            kwargs.get('unsubscribe', None))
        self._init_callback: Callable[[bool, str], None] = (
            kwargs.get('init_callback', None))
        self._init_timeout: int = kwargs.get('init_timeout', 10)
        self._cache_lifetime: 'int|None' = kwargs.get('cache_lifetime', None)
        self._isc_poll_interval: int = kwargs.get('isc_poll_interval', 1)
        self.isc_queue = IscTaskQueue(blocking=True)
        self._isc_timer = RepeatingTimer(seconds=self._isc_poll_interval,
                                         target=self.isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer',
                                         auto_start=True)
        self._proxy_properties: dict = None
        self._property_cache: PropertyCache = PropertyCache()
        self._proxy_event: Event = Event()
        self._init: InitializationState = InitializationState.NONE

    @property
    def tag(self) -> str:
        """The name of the microservice used in MQTT topic."""
        return self._tag

    @property
    def is_initialized(self) -> bool:
        """Returns True if the proxy has been initialized with properties."""
        return self._init == InitializationState.COMPLETE

    @property
    def initialization_state(self) -> InitializationState:
        """The current initialization state."""
        return self._init

    @property
    def _base_topic(self) -> str:
        if not self.tag:
            raise ValueError('tag is not defined')
        return f'fieldedge/{self.tag}'

    @property
    def properties(self) -> 'dict|None':
        """The microservice properties.
        
        If cached returns immediately, otherwise blocks waiting for an update
        via the MQTT thread. Some properties e.g. GNSS information may take
        longer than 30 seconds to resolve.
        
        Raises:
            `OSError` if the proxy has not been initialized, or if the request
            times out after `PROXY_PROPERTY_TIMEOUT` seconds (default 35).
        
        """
        if self._init < InitializationState.PENDING:
            raise OSError('Proxy not initialized')
        cached = self._property_cache.get_cached('all')
        if cached:
            return self._proxy_properties
        pending = self.isc_queue.peek(task_meta=('properties', 'all'))
        if pending:
            _log.debug('Prior query pending')
        else:
            self._proxy_properties = None
            task_meta = { 'properties': 'all' }
            if self._proxy_event.is_set():
                self._proxy_event.clear()
            self.query_properties(['all'], task_meta)
        self._proxy_event.wait(PROXY_PROPERTY_TIMEOUT)
        if not self._proxy_properties:
            raise OSError('proxy_properties unsuccessful')
        return self._proxy_properties

    def property_get(self, property_name: str) -> Any:
        """Gets the proxy property value."""
        cached = self._property_cache.get_cached(property_name)
        if cached:
            return cached
        return self.properties.get(property_name)

    def property_set(self, property_name: str, value: Any, **kwargs):
        """Sets the proxy property value."""
        task_meta = { 'set': property_name }
        self.query_properties({ property_name: value }, task_meta, kwargs)

    def task_add(self, task: IscTask) -> None:
        """Adds a task to the task queue."""
        self.isc_queue.task_blocking.wait()
        try:
            self.isc_queue.append(task)
        except IscException as err:
            self.isc_queue.task_blocking.set()
            raise err

    def task_handle(self, response: dict, unblock: bool = False) -> bool:
        """Returns True if the task was handled, after triggering any callback.
        
        Args:
            response (dict): The response message from the microservice.
            unblock (bool): If True unblock if the queue is blocking.
        
        """
        task_id = response.get('uid', None)
        if not task_id or not self.isc_queue.is_queued(task_id):
            _log.debug('No task ID %s queued - not handling', task_id)
            return False
        task = self.isc_queue.get(task_id, unblock=unblock)
        if not isinstance(task.task_meta, dict):
            if task.task_meta is not None:
                _log.warning('Overwriting task_meta: %s', task.task_meta)
            task.task_meta = {}
        task.task_meta['task_id'] = task_id
        task.task_meta['task_type'] = task.task_type
        if callable(task.callback):
            task.callback(response, task.task_meta)
        elif self.isc_queue.task_blocking:
            _log.warning('Task queue still blocking with no callback')
        return True

    def task_complete(self, task_meta: dict = None):
        """Call to complete a task and remove from the blocking queue."""
        task_id = None
        if isinstance(task_meta, dict):
            task_id = task_meta.get('task_id', None)
            task_type = task_meta.get('task_type', 'task')
        _log.debug('Completing %s (%s)', task_type, task_id)
        self.isc_queue.task_blocking.set()

    def initialize(self, **kwargs) -> None:
        """Requests properties of the microservice to create the proxy."""
        topics = [f'{self._base_topic}/event/#', f'{self._base_topic}/info/#']
        for topic in topics:
            if callable(self._subscribe):
                subscribed = self._subscribe(topic)
                if not subscribed:
                    raise ValueError(f'Unable to subscribe to {topic}')
        task_meta = {
            'initialize': self.tag,
            'timeout': self._init_timeout,
            'timeout_callback': self._init_fail,
        }
        self._init = InitializationState.PENDING
        self.query_properties(['all'], task_meta, kwargs)

    def deinitialize(self) -> None:
        """De-initialize the proxy and clear the property cache and task queue.
        """
        self._init = InitializationState.NONE
        self._property_cache.clear()
        self.isc_queue.clear()

    def _init_fail(self, task_meta: dict = None):
        """Calls back with a failure on initialization failure/timeout."""
        self._init = InitializationState.NONE
        if callable(self._init_callback):
            tag = None
            if isinstance(task_meta, dict):
                tag = task_meta.get('initialize', None)
            self._init_callback(success=False, tag=tag)

    def query_properties(self,
                         properties: 'dict|list',
                         task_meta: dict = None,
                         query_meta: dict = None):
        """Gets or sets the microservice properties via MQTT.
        
        Args:
            properties: A list for `get` or a dictionary for `set`.
            task_meta: Optional dictionary elements for cascaded functions.
            query_meta: Optional metadata to add to the MQTT message query.
            
        """
        if not callable(self._publish):
            raise ValueError('publish callback not defined')
        if properties is not None and not isinstance(properties, (list, dict)):
            raise ValueError('Invalid properties structure')
        if isinstance(properties, dict):
            if not properties:
                raise ValueError('Properties dictionary must include key/values')
            method = 'set'
        else:
            method = 'get'
        _log.debug('%sting %s properties %s', method, self.tag, properties)
        if isinstance(task_meta, dict):
            lifetime = task_meta.get('timeout', 10)
        else:
            lifetime = 10
        prop_task = IscTask(task_type=f'property_{method}',
                            task_meta=task_meta,
                            callback=self.update_proxy_properties,
                            lifetime=lifetime)
        self.task_add(prop_task)
        topic = f'{self._base_topic}/request/properties/{method}'
        message = {
            'uid': prop_task.uid,
            'properties': properties,
        }
        if isinstance(query_meta, dict):
            for key, val in query_meta.items():
                message[key] = val
        self._publish(topic, message)

    def update_proxy_properties(self, message: dict, task_meta: dict = None):
        """Updates the proxy property dictionary with queried values.
        
        If querying all properties, pushes values into warm storage under
        self._proxy_properties. Otherwise hot storage in self._property_cache.
        """
        properties = message.get('properties', None)
        if not isinstance(properties, dict):
            _log.error('Unable to process properties: %s', properties)
            return
        cache_lifetime = self._cache_lifetime
        cache_all = False
        new_init = False
        if isinstance(task_meta, dict):
            if 'initialize' in task_meta:
                self._init = InitializationState.COMPLETE
                new_init = True
                cache_all = True
                _log.info('%s proxy initialized', self.tag)
            if 'cache_lifetime' in task_meta:
                cache_lifetime = task_meta.get('cache_liftime')
            if task_meta.get('properties', None) == 'all':
                cache_all = True
        if self._proxy_properties is None:
            self._proxy_properties = {}
        for prop, val in properties.items():
            if (prop not in self._proxy_properties or
                self._proxy_properties[prop] != val):
                _log.debug('Updating %s = %s', prop, val)
                self._proxy_properties[prop] = val
                self._property_cache.cache(val, prop, cache_lifetime)
        if cache_all:
            self._property_cache.cache(cache_all, 'all', cache_lifetime)
            if not self._proxy_event.is_set():
                self._proxy_event.set()
        self.task_complete(task_meta)
        if new_init and callable(self._init_callback):
            self._init_callback(success=True,
                                tag=task_meta.get('initialize', None))

    def publish(self, topic: str, message: dict, qos: int = 0):
        """Publishes to MQTT via the parent."""
        if not callable(self._publish):
            raise ValueError('publish callback not defined')
        self._publish(topic, message, qos=qos)

    def subscribe(self, topic: str):
        """Subscribes to a MQTT topic via the parent."""
        if not callable(self._subscribe):
            raise ValueError('subscribe callback not defined')
        self._subscribe(topic)

    def unsubscribe(self, topic: str):
        """Subscribes to a MQTT topic via the parent."""
        if not callable(self._unsubscribe):
            raise ValueError('unsubscribe callback not defined')
        self._unsubscribe(topic)

    @abstractmethod
    def on_isc_message(self, topic: str, message: dict) -> bool:
        """Processes MQTT messages for the proxy.
        
        Required method. Called by the parent's MQTT message handler.
        Should call self.task_handle if info/properties/values is received.
        Should return False by default, True if the message was handled.
        
        Args:
            topic (str): The message topic.
            message (dict): The message content.
        
        Returns:
            `True` if the message was processed or `False` otherwise.
            
        """
        if _vlog(self.tag):
            _log.debug('Proxy received %s: %s', topic, message)
        if not topic.startswith(f'fieldedge/{self.tag}/'):
            return False
        if topic.endswith('info/properties/values'):
            return self.task_handle(message)
        return False


def _vlog(tag: str) -> bool:
    return verbose_logging(f'{tag}-msproxy')
