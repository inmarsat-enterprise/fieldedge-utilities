"""A proxy class for interfacing with other Microservices via MQTT.
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Callable, Any

from fieldedge_utilities.timer import RepeatingTimer
from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.mqtt import MqttClient

from .interservice import IscTaskQueue, IscTask, IscException
from .propertycache import PropertyCache

__all__ = ['MicroserviceProxy', 'SubscriptionProxy']

_log = logging.getLogger(__name__)


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
        self._tag: str = self.__class__.__name__.lower()
        self._publish: Callable[[str, dict], None] = None
        self._subscribe: Callable[['str|list[str]'], bool] = None
        self._unsubscribe: Callable[['str|list[str]'], bool] = None
        self._init_callback: Callable[[bool, str], None] = None
        self._init_timeout: int = 10
        self._cache_lifetime: int = None
        self._isc_poll_interval: int = 1
        callbacks = ['publish', 'subscribe', 'unsubscribe', 'init_callback']
        for key, val in kwargs.items():
            if key == 'tag':
                if not isinstance(val, str) or val == '':
                    raise ValueError('tag must be a valid microservice name')
                self._tag = val
            elif key in callbacks:
                if not callable(val):
                    raise ValueError(f'{key} must be callable')
                setattr(self, f'_{key}', val)
            elif key in ['init_timeout', 'cache_lifetime', 'isc_poll_interval']:
                if not isinstance(val, int) or val <= 0:
                    raise ValueError(f'{key} must be integer > 0')
                setattr(self, f'_{key}', val)
        self._isc_queue = IscTaskQueue(blocking=True)
        self._isc_timer = RepeatingTimer(seconds=self._isc_poll_interval,
                                         target=self._isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer',
                                         auto_start=True)
        self._proxy_properties: dict = None
        self._property_cache: PropertyCache = PropertyCache()
        self._initialized: bool = False
        self._initializing: bool = False

    @property
    def tag(self) -> str:
        """The name of the microservice used in MQTT topic."""
        return self._tag

    @property
    def is_initialized(self) -> bool:
        """Returns True if the proxy has been initialized with properties."""
        return self._initialized

    @property
    def _base_topic(self) -> str:
        if not self.tag:
            raise ValueError('tag is not defined')
        return f'fieldedge/{self.tag}'

    @property
    def properties(self) -> 'dict|None':
        """The microservice properties.
        
        If cached returns immediately, otherwise blocks waiting for an update
        via the MQTT thread.
        Raises `OSError` if the proxy has not been initialized.
        
        """
        if not self.is_initialized and not self._initializing:
            raise OSError('Proxy not initialized')
        cached = self._property_cache.get_cached('all')
        if cached:
            return self._proxy_properties
        pending = self._isc_queue.peek(task_meta=('properties', 'all'))
        if pending:
            _log.debug('Prior query pending')
        else:
            self._proxy_properties = None
            task_meta = { 'properties': 'all' }
            self.query_properties(['all'], task_meta)
        attempts = 0
        while self._isc_queue.peek(task_meta=('properties', 'all')):
            attempts += 1
            _log.debug(f'Waiting for property update ({attempts})')
            time.sleep(1)
        return self._proxy_properties

    def property_get(self, property_name: str) -> Any:
        """Gets the proxy property value."""
        cached = self._property_cache.get_cached(property_name)
        if cached:
            return cached
        return self.properties.get(property_name)

    def property_set(self, property_name: str, value: Any):
        """Sets the proxy property value."""
        task_meta = { 'set': property_name }
        self.query_properties({ property_name: value }, task_meta)

    def task_add(self, task: IscTask) -> None:
        """Adds a task to the task queue."""
        self._isc_queue.task_blocking.wait()
        try:
            self._isc_queue.append(task)
        except IscException as err:
            self._isc_queue.task_blocking.set()
            raise err

    def task_handle(self, response: dict) -> bool:
        """Returns True if the task_id is in the queue after any task
        callbacks are completed.
        """
        task_id = response.get('uid', None)
        if not task_id or not self._isc_queue.is_queued(task_id):
            _log.debug(f'No task ID {task_id} queued - ignoring')
            return False
        task = self._isc_queue.get(task_id)
        if not isinstance(task.task_meta, dict):
            if task.task_meta is not None:
                _log.warning(f'Overwriting {task.task_meta}')
            task.task_meta = {}
        task.task_meta['task_id'] = task_id
        task.task_meta['task_type'] = task.task_type
        if callable(task.callback):
            task.callback(response, task.task_meta)
        return True

    def task_complete(self, task_meta: dict = None):
        """Call to complete a task and remove from the blocking queue."""
        task_id = None
        if isinstance(task_meta, dict):
            task_id = task_meta.get('task_id', None)
            task_type = task_meta.get('task_type', 'task')
        _log.debug(f'Completing {task_type} ({task_id})')
        self._isc_queue.task_blocking.set()

    def initialize(self) -> None:
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
        self._initializing = True
        self.query_properties(['all'], task_meta)

    def _init_fail(self, task_meta: dict = None):
        """Calls back with a failure on initialization failure/timeout."""
        self._initialized = False
        self._initializing = False
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
        _log.debug(f'{method}ting properties {properties}')
        lifetime = task_meta.get('timeout', 10)
        prop_task = IscTask(task_type=f'property_{method}',
                            task_meta=task_meta,
                            callback=self.update_proxy_properties,
                            lifetime=lifetime)
        topic = f'{self._base_topic}/request/properties/{method}'
        message = {
            'uid': prop_task.uid,
            'properties': properties,
        }
        if isinstance(query_meta, dict):
            for key, val in query_meta.items():
                message[key] = val
        self._publish(topic, message)
        self.task_add(prop_task)

    def update_proxy_properties(self, message: dict, task_meta: dict = None):
        """Updates the proxy property dictionary with queried values.
        
        If querying all properties, pushes values into warm storage under
        self._proxy_properties. Otherwise hot storage in self._property_cache.
        """
        properties = message.get('properties', None)
        if not isinstance(properties, dict):
            _log.error(f'Unable to process properties: {properties}')
            return
        cache_lifetime = self._cache_lifetime
        cache_all = False
        new_init = False
        if isinstance(task_meta, dict):
            if 'initialize' in task_meta:
                self._initialized = True
                self._initializing = True
                new_init = True
                cache_all = True
                _log.info(f'{self.tag} proxy initialized')
            if 'cache_lifetime' in task_meta:
                cache_lifetime = task_meta.get('cache_liftime')
            if task_meta.get('properties', None) == 'all':
                cache_all = True
        if self._proxy_properties is None:
            self._proxy_properties = {}
        for prop, val in properties.items():
            if (prop not in self._proxy_properties or
                self._proxy_properties[prop] != val):
                _log.debug(f'Updating {prop} = {val}')
                self._proxy_properties[prop] = val
                self._property_cache.cache(val, prop, cache_lifetime)
        if cache_all:
            self._property_cache.cache(cache_all, 'all', cache_lifetime)
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
            raise ValueError('subscribe callback not defined')
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
        if verbose_logging(self.tag):
            _log.debug(f'Proxy received {topic}: {message}')
        if not topic.startswith(f'fieldedge/{self.tag}/'):
            return False
        if topic.endswith('info/properties/values'):
            return self.task_handle(message)
        return False


class SubscriptionProxy:
    """Passes MQTT topic/message from a parent to a child object.
    
    For example a MicoserviceProxy may want to listen for other microservice
    events than just the one it is a proxy for.
    
    """

    def __init__(self, mqtt_client: MqttClient) -> None:
        """Initializes the subscription proxy.
        
        Args:
            mqtt_client (MqttClient): The parent MQTT client.
            
        """
        if not isinstance(mqtt_client, MqttClient):
            raise ValueError('mqtt_client must be a valid MqttClient instance')
        self._mqttc: MqttClient = mqtt_client
        self._subscriptions: dict = {}

    def proxy_add(self,
                  module: str,
                  topic: str,
                  callback: Callable,
                  qos: int = 0) -> bool:
        """Adds a subscription proxy to the parent.
        
        Args:
            module: The module name used as a routing key.
            topic: The MQTT topic e.g. `fieldedge/my-microservice/events/#`
            callback: The callback function that will receive the MQTT publish
                `(topic: str, message: dict)`
            qos: The MQTT QoS 0 = max once, 1 = at least once, 2 = exactly once
            
        """
        for mod, topics in self._subscriptions.items():
            for top in topics:
                if top == topic and mod == module:
                    _log.warning(f'Topic {topic} already subscribed by {mod}')
                    return False
        if module not in self._subscriptions:
            self._subscriptions[module] = {}
        try:
            self._mqttc.subscribe(topic, qos)
            self._subscriptions[module][topic] = callback
            return True
        except Exception as err:
            _log.error(f'Failed to proxy subscribe: {err}')
            return False

    def proxy_del(self, module: str, topic: str) -> bool:
        """Removes a subscription proxy."""
        modules_subscribed = []
        for mod, topics in self._subscriptions.items():
            for top in topics:
                if top == topic:
                    modules_subscribed.append(mod)
        if (module in self._subscriptions and
            topic in self._subscriptions[module]):
            # found it - ok to remove
            try:
                del self._subscriptions[module][topic]
                if not self._subscriptions[module]:
                    del self._subscriptions[module]
                if len(modules_subscribed) == 1:
                    self._mqttc.unsubscribe(topic)
                return True
            except Exception as err:
                _log.error(f'Failed to proxy unsubscribe: {err}')
                return False
        return True

    def proxy_pub(self, topic: str, message: dict) -> None:
        """Publishes via a parent MQTT publish function."""
        for topics in self._subscriptions.values():
            if topic in topics:
                if callable(topics[topic]):
                    topics[topic](topic, message)
