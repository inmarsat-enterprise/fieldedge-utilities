"""Microservice and related meta/classes.
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional
from uuid import uuid4

from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.microservice.interservice import (IscException,
                                                           IscTask,
                                                           IscTaskQueue)
from fieldedge_utilities.microservice.properties import *
from fieldedge_utilities.microservice.propertycache import PropertyCache
from fieldedge_utilities.mqtt import MqttClient
from fieldedge_utilities.timer import RepeatingTimer

__all__ = ['Microservice', 'Feature', 'MicroserviceProxy', 'SubscriptionProxy']

_log = logging.getLogger(__name__)


class Feature(ABC):
    """Template for a microservice feature as a child of the microservice.
    
    Private objects and methods include _task_queue, _task_notify_callback,
    _task_complete_callback, _task_fail_callback.
    
    """
    def __init__(self,
                 task_queue: IscTaskQueue,
                 task_notify_callback: Callable,
                 task_complete_callback: Callable[[str, dict], None],
                 task_fail_callback: Callable = None,
                 ) -> None:
        """Initializes the feature.
        
        Args:
            task_queue: The parent microservice task queue.
            task_notify_callback: The parent `notify` function.
            task_complete_callback: A parent task completion function.
            task_fail_callback: An optional parent function to call if the task
                fails.
             
        """
        self._task_queue = task_queue
        self._task_notify_callback = task_notify_callback
        self._task_complete_callback = task_complete_callback
        self._task_fail_callback = task_fail_callback
    
    @abstractmethod
    def properties_list(self) -> 'list[str]':
        """Returns a lists of exposed property names."""
    
    @abstractmethod
    def status(self) -> dict:
        """Returns a dictionary of key status summary information."""
    
    @abstractmethod
    def on_isc_message(self, topic: str, message: dict) -> bool:
        """Called by a parent Microservice to pass relevant MQTT messages.
        
        Args:
            topic (str): The message topic.
            message (dict): The message content.
        
        Returns:
            `True` if the message was processed or `False` otherwise.
            
        """


class MicroserviceProxy(ABC):
    """A proxy model for another FieldEdge microservice accessed via MQTT.
    
    Queries a microservice based on its tag to populate proxy_properties.
    Has a blocking (1-deep) `IscTaskQueue` for each remote query to complete
    before the next task can be queued.
    
    """
    def __init__(self,
                 tag: str,
                 publish_callback: Callable,
                 subscribe_callback: Callable,
                 init_callback: Callable = None,
                 init_timeout: int = 10,
                 cache_lifetime: int = 5,
                 isc_poll_interval: int = 1) -> None:
        """Initialize the proxy.
        
        Args:
            tag (str): The name of the microservice used in the MQTT topic.
            publish_callback (Callable): The parent's MQTT publish function
                which expects `topic` (str) and `message` (dict)
            publish_callback (Callable): The parent's MQTT subscribe function
                which expects a `topic` (str)
            init_callback (Callable): Optional callback after initialized will
                receive boolean success and the tag of the initialized proxy.
            init_timeout (int): Time in seconds allowed for initialization.
            cache_lifetime (int): The proxy property cache time.
            isc_poll_interval (int): The time between checks for task expiry.
        
        """
        if not isinstance(tag, str):
            raise ValueError('Tag must be a valid microservice name')
        if not callable(publish_callback):
            raise ValueError('publish_callback must be callable')
        if not callable(subscribe_callback):
            raise ValueError('subscribe_callback must be callable')
        if init_callback is not None and not callable(init_callback):
            raise ValueError('init_callback must be callable or None')
        if init_timeout is not None:
            if not isinstance(init_timeout, (int, float)) or init_timeout <= 1:
                raise ValueError('init_timeout must be None or number >= 1')
        self._tag: str = tag
        self._isc_queue = IscTaskQueue(blocking=True)
        self._isc_timer = RepeatingTimer(seconds=isc_poll_interval,
                                         target=self._isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer',
                                         auto_start=True)
        self._publish: Callable = publish_callback
        self._subscribe: Callable = subscribe_callback
        self._init_callback: 'Callable|None' = init_callback
        self._init_timeout: 'int|float|None' = init_timeout
        self._proxy_properties: dict = None
        self._cached_properties: PropertyCache = PropertyCache()
        self._cache_lifetime = int(cache_lifetime)
        self._initialized: bool = False
        self._initializing: bool = False
        self._base_topic: str = f'fieldedge/{self.tag}'
    
    @property
    def tag(self) -> str:
        return self._tag
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized
    
    @property
    def properties(self) -> 'dict|None':
        """The microservice properties.
        
        If cached returns immediately, otherwise blocks waiting for an update
        via the MQTT thread.
        Raises `OSError` if the proxy has not been initialized.
        
        """
        if not self.is_initialized and not self._initializing:
            raise OSError('Proxy not initialized')
        cached = self._cached_properties.get_cached('all')
        if cached:
            return self._proxy_properties
        pending = self._isc_queue.peek(task_meta=('properties', 'all'))
        if pending:
            _log.debug(f'Prior query pending')
        else:
            self._proxy_properties = None
            task_meta = { 'properties': 'all' }
            self.query_properties(['all'], task_meta)
        while self._isc_queue.peek(task_meta=('properties', 'all')):
            _log.debug('Waiting for property update')
            time.sleep(1)
        return self._proxy_properties
    
    def property_get(self, property_name: str) -> Any:
        """Gets the proxy property value."""
        cached = self._cached_properties.get_cached(property_name)
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
        
    def initialize(self) -> None:
        """Requests properties of the microservice to create the proxy."""
        topics = [f'{self._base_topic}/event/#', f'{self._base_topic}/info/#']
        for topic in topics:
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
    
    def _init_fail(self, task_meta: dict = {}):
        """Calls back with a failure on initialization failure/timeout."""
        self._initialized = False
        self._initializing = False
        if callable(self._init_callback):
            self._init_callback(success=False,
                                tag=task_meta.get('initialize', None))
    
    def _handle_task(self, response: dict) -> bool:
        """Returns True if the task_id is in the queue after any task
        callbacks are completed.
        """
        task_id = response.get('uid', None)
        if not task_id or not self._isc_queue.is_queued(task_id):
            _log.debug(f'No task ID {task_id} queued - ignoring')
            return False
        task = self._isc_queue.get(task_id)
        if not task.task_meta:
            task.task_meta = { 'task_id': task_id }
        if callable(task.callback):
            task.callback(response, task.task_meta)
        return True
        
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
            for k, v in query_meta.items():
                message[k] = v
        self._publish(topic, message)
        self.task_add(prop_task)
    
    def update_proxy_properties(self, message: dict, task_meta: dict = {}):
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
                self._cached_properties.cache(self._proxy_properties[prop],
                                              prop,
                                              cache_lifetime)
        if cache_all:
            self._cached_properties.cache(cache_all, 'all', cache_lifetime)
        self.task_complete(task_meta)
        if new_init and callable(self._init_callback):
            self._init_callback(success=True,
                                tag=task_meta.get('initialize', None))
        
    def task_complete(self, task_meta: dict = None):
        task_id = None
        if isinstance(task_meta, dict):
            task_id = task_meta.get('task_id', None)
        _log.debug(f'Completing task ({task_id})')
        self._isc_queue.task_blocking.set()
    
    def publish(self, topic: str, message: dict, qos: int = 0):
        """Publishes to MQTT via the parent."""
        self._publish(topic, message, qos=qos)
    
    def subscribe(self, topic: str):
        """Subscribes to a MQTT topic via the parent."""
        self._subscribe(topic)
    
    def _on_isc_message(self, topic: str, message: dict) -> bool:
        """Called by a parent Microservice.
        
        Handles property value responses for proxy properties.
        Passes unhandled topic/message to the public `on_isc_message` method.
        
        """
        if verbose_logging(self.tag):
            _log.debug(f'Proxy received {topic}: {message}')
        if not topic.startswith(f'fieldedge/{self.tag}/'):
            return False
        if topic.endswith('info/properties/values'):
            return self._handle_task(message)
        return self.on_isc_message(topic, message)
    
    @abstractmethod
    def on_isc_message(self, topic: str, message: dict) -> bool:
        """Processes MQTT messages for the proxy.
        
        Called by an internal _on_isc_message which was called by the parent.
        
        Args:
            topic (str): The message topic.
            message (dict): The message content.
        
        Returns:
            `True` if the message was processed or `False` otherwise.
            
        """


class Microservice(ABC):
    """Abstract base class for a FieldEdge microservice.
    
    Use `__slots__` to expose initialization properties.
    
    """
    
    __slots__ = (
        '_tag', '_mqttc_local', '_default_publish_topic', '_subscriptions',
        '_isc_queue', '_isc_timer', '_isc_tags', '_isc_ignore',
        '_properties', '_hidden_properties', '_cached_properties',
        '_isc_properties', '_hidden_isc_properties', '_rollcall_properties',
    )
    
    LOG_LEVELS = ['DEBUG', 'INFO']
    
    # @abstractmethod
    def __init__(self,
                 tag: str = None,
                 mqtt_client_id: str = None,
                 auto_connect: bool = False,
                 isc_tags: bool = False,
                 isc_poll_interval: int = 1,
                 ) -> None:
        """Initialize the class instance.
        
        Args:
            tag (str): The short name of the microservice used in MQTT topics
                and interservice communication properties. If not provided, the
                lowercase name of the class will be used.
            mqtt_client_id (str): The name of the client ID when connecting to
                the local broker. If not provided, will be `fieldedge_<tag>`.
            auto_connect (bool): If set will automatically connect to the broker
                during initialization.
            isc_tags (bool): If set then isc_properties will include the class
                tag as a prefix. Disabled by default.
            isc_poll_interval (int): The interval at which to poll
                
        """
        self._tag: str = tag or get_class_tag(self.__class__)
        self._isc_tags: bool = isc_tags
        if not mqtt_client_id:
            mqtt_client_id = f'fieldedge_{self.tag}'
        self._subscriptions = [ 'fieldedge/+/rollcall/#' ]
        self._subscriptions.append(f'fieldedge/{self.tag}/#')
        self._mqttc_local = MqttClient(client_id=mqtt_client_id,
                                       subscribe_default=self._subscriptions,
                                       on_message=self._on_isc_message,
                                       auto_connect=auto_connect)
        self._default_publish_topic = f'fieldedge/{self._tag}'
        self._properties: 'list[str]' = None
        self._hidden_properties: 'list[str]' = []
        self._isc_properties: 'list[str]' = None
        self._hidden_isc_properties: 'list[str]' = [
            'tag',
            'properties',
            'properties_by_type',
            'isc_properties',
            'isc_properties_by_type',
            'rollcall_properties',
            'isc_queue',
            'features',
            'ms_proxies',
            'sub_proxies',
        ]
        self._rollcall_properties: 'list[str]' = []
        self._isc_poll_interval: int = isc_poll_interval
        self._isc_queue = IscTaskQueue()
        self._isc_timer = RepeatingTimer(seconds=self._isc_poll_interval,
                                         target=self._isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer')
        self._cached_properties: PropertyCache = PropertyCache()
        self._features: 'dict[str, Feature]' = {}
        self._ms_proxies: 'dict[str, MicroserviceProxy]' = {}
        self._sub_proxies = SubscriptionProxy(self._mqttc_local)
    
    @property
    def tag(self) -> str:
        return self._tag
    
    @property
    def log_level(self) -> 'str|None':
        """The logging level of the root logger."""
        return str(logging.getLevelName(logging.getLogger().level))
    
    @log_level.setter
    def log_level(self, value: str):
        "The logging level of the root logger."
        if not isinstance(value, str) or value.upper() not in self.LOG_LEVELS:
            raise ValueError(f'Level must be in {self.LOG_LEVELS}')
        logging.getLogger().setLevel(value.upper())
        
    @property
    def _vlog(self) -> bool:
        """True if environment variable LOG_VERBOSE includes the class tag."""
        return verbose_logging(self.tag)
    
    @property
    def properties(self) -> 'list[str]':
        """A list of public properties of the class."""
        if not self._properties:
            self._get_properties()
        return self._properties
    
    def _get_properties(self) -> None:
        """Refreshes the class properties."""
        ignore = self._hidden_properties
        self._properties = get_class_properties(self.__class__, ignore)
        for tag, feature in self._features.items():
            feature_props = feature.properties_list()
            for prop in feature_props:
                self._properties.append(f'{tag}_{prop}')
        
    @staticmethod
    def _categorize_prop(obj: object,
                         prop: str,
                         categorized: dict,
                         alias: str = None):
        """"""
        if property_is_read_only(obj, prop):
            if READ_ONLY not in categorized:
                categorized[READ_ONLY] = []
            categorized[READ_ONLY].append(alias or prop)
        else:
            if READ_WRITE not in categorized:
                categorized[READ_WRITE] = []
            categorized[READ_WRITE].append(alias or prop)
        
    def _categorized(self, prop_list: 'list[str]') -> 'dict[str, list[str]]':
        """Categorizes properties as `config` or `info`."""
        categorized = {}
        for prop in prop_list:
            if hasattr_static(self, prop):
                self._categorize_prop(self, prop, categorized)
            else:
                for tag, feature in self._features.items():
                    if not prop.startswith(f'{tag}_'):
                        continue
                    untagged = prop.replace(f'{tag}_', '')
                    if hasattr_static(feature, untagged):
                        self._categorize_prop(feature, prop, categorized)
        return categorized
        
    @property
    def properties_by_type(self) -> 'dict[str, list[str]]':
        """Public properties lists of the class tagged `info` or `config`."""
        return self._categorized(self.properties)
    
    def property_hide(self, prop_name: str):
        """Hides a property so it will not list in `properties`."""
        if prop_name not in self.properties:
            raise ValueError(f'Invalid prop_name {prop_name}')
        if prop_name not in self._hidden_properties:
            self._hidden_properties.append(prop_name)
            self._get_properties()
    
    def property_unhide(self, prop_name: str):
        """Unhides a hidden property so it appears in `properties`."""
        if prop_name in self._hidden_properties:
            self._hidden_properties.remove(prop_name)
            self._get_properties()
    
    @property
    def isc_properties(self) -> 'list[str]':
        """ISC exposed properties."""
        if self._isc_properties is None:
            self._get_isc_properties()
        return self._isc_properties
    
    def _get_isc_properties(self) -> None:
        """Refreshes the cached ISC properties list."""
        ignore = self._hidden_properties
        ignore.extend(p for p in self._hidden_isc_properties
                      if p not in self._hidden_properties)
        tag = self.tag if self._isc_tags else None
        self._isc_properties = [tag_class_property(prop, tag)
                                for prop in self.properties
                                if prop not in ignore]
    
    @property
    def isc_properties_by_type(self) -> 'dict[str, list[str]]':
        """ISC exposed properties tagged `info` or `config`."""
        # subfunction
        def feature_prop(prop) -> 'tuple[object, str]':
            fprop, ftag = untag_class_property(prop, True, True)
            feature = self._features.get(ftag, None)
            if feature and hasattr(feature, ftag):
                return (feature, fprop)
            raise ValueError(f'Unknown tag {prop}')
        # main function
        categorized = {}
        for isc_prop in self.isc_properties:
            if self._isc_tags:
                prop, tag = untag_class_property(isc_prop, self._isc_tags, True)
                if tag == self.tag:
                    if hasattr(self, prop):
                        obj = self
                    else:
                        obj, prop = feature_prop(prop)
                else:
                    raise ValueError(f'Unknown tag {tag}')
            else:
                if hasattr(self, isc_prop):
                    obj = self
                else:
                    obj, prop = feature_prop(isc_prop)
            self._categorize_prop(obj, prop, categorized, isc_prop)
        return categorized
    
    def isc_get_property(self, isc_property: str) -> Any:
        """Gets a property value based on its ISC name."""
        prop = untag_class_property(isc_property, self._isc_tags)
        if prop not in self.properties:
            raise AttributeError(f'{prop} not in properties')
        if hasattr_static(self, prop):
            return getattr(self, prop)
        else:
            for tag, feature in self._features.items():
                if not prop.startswith(f'{tag}_'):
                    continue
                fprop = prop.replace(f'{tag}_', '')
                if hasattr_static(feature, fprop):
                    return getattr(feature, fprop)
        _log.warning(f'ISC property {isc_property} not found')
    
    def isc_set_property(self, isc_property: str, value: Any) -> None:
        """Sets a property value based on its ISC name."""
        prop = untag_class_property(isc_property, self._isc_tags)
        if prop not in self.properties:
            raise AttributeError(f'{prop} not in properties')
        if prop not in self.properties_by_type[READ_WRITE]:
            raise AttributeError(f'{prop} is not writable')
        if hasattr_static(self, prop):
            setattr(self, prop, value)
            return
        else:
            for tag, feature in self._features.items():
                if not prop.startswith(f'{tag}_'):
                    continue
                fprop = prop.replace(f'{tag}_', '')
                if hasattr_static(feature, fprop):
                    setattr(feature, fprop, value)
                    return
        _log.warning(f'ISC property {isc_property} not found')
    
    def isc_property_hide(self, isc_property: str) -> None:
        """Hides a property from ISC - does not appear in `isc_properties`."""
        if isc_property not in self.isc_properties:    
            raise ValueError(f'Invalid prop_name {isc_property}')
        if isc_property not in self._hidden_isc_properties:
            self._hidden_isc_properties.append(isc_property)
            self._get_isc_properties()
    
    def isc_property_unhide(self, isc_property: str) -> None:
        """Unhides a property to ISC so it appears in `isc_properties`."""
        if isc_property in self._hidden_isc_properties:
            self._hidden_isc_properties.remove(isc_property)
            self._get_isc_properties()
        
    @property
    def rollcall_properties(self) -> 'list[str]':
        """Property key/values that will be sent in the rollcall response."""
        return self._rollcall_properties
    
    def rollcall_property_add(self, isc_prop_name: str):
        """Add a property to the rollcall response."""
        if isc_prop_name not in self.properties:
            raise ValueError(f'Invalid prop_name {isc_prop_name}')
        if isc_prop_name not in self._rollcall_properties:
            self._rollcall_properties.append(isc_prop_name)
    
    def rollcall_property_remove(self, isc_prop_name: str):
        """Remove a property from the rollcall response."""
        if isc_prop_name in self._rollcall_properties:
            self._rollcall_properties.remove(isc_prop_name)
        
    def rollcall(self):
        """Publishes a rollcall broadcast to other microservices with UUID."""
        subtopic = 'rollcall'
        rollcall = { 'uid': str(uuid4()) }
        self.notify(message=rollcall, subtopic=subtopic)
    
    def _rollcall_respond(self, topic: str, message: dict):
        """Processes an incoming rollcall request.
        
        If the requestor is this service based on the topic, it is ignored.
        If the requestor is another microservice, the response will include
        key/value pairs from the `rollcall_properties` list.
        
        Args:
            topic: The topic from which the requestor will be determined from
                the second level of the topic e.g. `fieldedge/<requestor>/...`
            request (dict): The request message.
            
        """
        if not topic.endswith('/rollcall'):
            _log.warning(f'rollcall_respond called without rollcall topic')
            return
        subtopic = 'rollcall/response'
        if 'uid' not in message:
            _log.warning('Rollcall request missing unique ID')
        response = { 'uid': message.get('uid', None) }
        for isc_prop in self._rollcall_properties:
            if isc_prop in self.isc_properties:
                response[isc_prop] = self.isc_get_property(isc_prop)
        self.notify(message=response, subtopic=subtopic)
        
    def isc_topic_subscribe(self, topic: str) -> bool:
        """Subscribes to the specified ISC topic."""
        if not topic.startswith('fieldedge/'):
            raise ValueError('First level topic must be fieldedge')
        if topic not in self._subscriptions:
            try:
                self._mqttc_local.subscribe(topic)
                self._subscriptions.append(topic)
                return True
            except:
                return False
        else:
            _log.warning(f'Already subscribed to {topic}')
            return True
    
    def isc_topic_unsubscribe(self, topic: str) -> bool:
        """Unsubscribes from the specified ISC topic."""
        mandatory = ['fieldedge/+/rollcall/#', f'fieldedge/+/{self.tag}/#']
        if topic in mandatory:
            _log.warning(f'Subscription to {topic} is mandatory')
            return False
        if topic not in self._subscriptions:
            _log.warning(f'Already not subscribed to {topic}')
            return True
        try:
            self._mqttc_local.unsubscribe(topic)
            self._subscriptions.remove(topic)
            return True
        except:
            return False
        
    def _on_isc_message(self, topic: str, message: dict) -> None:
        """Handles rollcall requests or passes to the `on_isc_message` method.
        
        This private method ensures rollcall requests are handled in a standard
        way.
        
        Args:
            topic: The MQTT topic
            message: The MQTT/JSON message
        
        """
        if self._vlog:
            _log.debug(f'Received ISC {topic}: {message}')
        if (topic.startswith(f'fieldedge/{self.tag}/') and
            '/request/' not in topic):
            # ignore own publishing
            if self._vlog:
                _log.debug(f'Ignoring own response/event')
            return
        elif topic.endswith('/rollcall'):
            self._rollcall_respond(topic, message)
        elif (topic.endswith(f'/{self.tag}/request/properties/list') or
              topic.endswith(f'/{self.tag}/request/properties/get')):
            self.properties_notify(message)
        elif topic.endswith(f'/{self.tag}/request/properties/set'):
            self.properties_change(message)
            report = message.get('reportChange', False)
            if report:   # pass message to downstream handler
                self.on_isc_message(topic, message)
        else:
            if self._features:
                for tag, feature in self._features.items():
                    if (hasattr(feature, 'on_isc_message') and
                        callable(feature.on_isc_message)):
                        handled = feature.on_isc_message(topic, message)
                        # check public handlers
                        if handled:
                            return
            if self._ms_proxies:
                for tag, proxy in self._ms_proxies.items():
                    if (hasattr(proxy, '_on_isc_message') and
                        callable(proxy._on_isc_message)):
                        # check private then public handlers
                        handled = proxy._on_isc_message(topic, message)
                        if handled:
                            return
            self.on_isc_message(topic, message)
        
    @abstractmethod
    def on_isc_message(self, topic: str, message: dict) -> None:
        """Handles incoming ISC/MQTT requests.
        
        Messages are received from any topics subscribed to using the
        `isc_subscribe` method. The default subscription `fieldedge/+/rollcall`
        is handled in a standard way by the private version of this method.
        The default subscription is `fieldedge/<self.tag>/request/#` which other
        services use to query this one. After receiving a rollcall, this service
        may subscribe to `fieldedge/<other>/info/#` topic to receive responses
        to its queries, tagged with a `uid` in the message body.
        
        Args:
            topic: The MQTT topic received.
            message: The MQTT/JSON message received.
            
        """
        
    def properties_notify(self, request: dict) -> None:
        """Publishes the requested ISC property values to the local broker.
        
        If no `properties` key is in the request, it implies a simple list of
        ISC property names will be generated.
        
        If `properties` is a list it will be used as a filter to create and
        publish a list of properties/values. An empty list will result in all
        ISC property/values being published.
        
        If the request has the key `categorized` = `True` then the response
        will be a nested dictionary with `config` and `info` dictionaries.
        
        Args:
            request: A dictionary with optional `properties` list and
                optional `categorized` flag.
        
        """
        if self._vlog:
            _log.debug(f'Request to notify properties: {request}')
        if not isinstance(request, dict):
            raise ValueError('Request must be a dictionary')
        if ('properties' in request and
            not isinstance(request['properties'], list)):
            raise ValueError('Request properties must be a list')
        response = {}
        request_id = request.get('uid', None)
        if request_id:
            response['uid'] = request_id
        else:
            _log.warning('Request missing uid for response correlation')
        categorized = request.get('categorized', False)
        if 'properties' not in request:
            subtopic = 'info/properties/list'
            if categorized:
                response['properties'] = self.isc_properties_by_type
            else:
                response['properties'] = self.isc_properties
        else:
            subtopic = 'info/properties/values'
            req_props: list = request.get('properties', [])
            if not req_props or 'all' in req_props:
                req_props = self.isc_properties
            response['properties'] = {}
            res_props = response['properties']
            props_source = self.isc_properties
            if categorized:
                props_source = self.isc_properties_by_type
                for p in req_props:
                    if (READ_WRITE in props_source and
                        p in props_source[READ_WRITE]):
                        # config property
                        if READ_WRITE not in res_props:
                            res_props[READ_WRITE] = {}
                        res_props[READ_WRITE][p] = self.isc_get_property(p)
                    else:
                        if READ_ONLY not in res_props:
                            res_props[READ_ONLY] = {}
                        res_props[READ_ONLY][p] = self.isc_get_property(p)
            else:
                for p in req_props:
                    res_props[p] = self.isc_get_property(p)
        _log.debug(f'Responding to request {request_id} for properties'
                   f': {request["properties"] or "ALL"}')
        self.notify(message=response, subtopic=subtopic)
    
    def properties_change(self, request: dict) -> 'None|dict':
        """Processes the requested property changes.
        
        The `request` dictionary must include the `properties` key with a
        dictionary of ISC property names and respective value to set.
        
        If the request contains a `uid` then the changed values will be notified
        as `info/property/values` to confirm the changes to the
        ISC requestor. If no `uid` is present then a dictionary confirming
        successful changes will be returned to the calling function.
        
        Args:
            request: A dictionary containing a `properties` dictionary of
                select ISC property names and values to set.
        
        """
        if self._vlog:
            _log.debug(f'Request to change properties: {request}')
        if (not isinstance(request, dict) or
            'properties' not in request or
            not isinstance(request['properties'], dict)):
            raise ValueError('Request must contain a properties dictionary')
        response = { 'properties': {} }
        request_id = request.get('uid', None)
        if request_id:
            response['uid'] = request_id
        else:
            _log.warning('Request missing uid for response correlation')
        for k, v in request['properties'].items():
            if k not in self.isc_properties_by_type[READ_WRITE]:
                _log.warning(f'{k} is not a config property')
                continue
            try:
                self.isc_set_property(k, v)
                response['properties'][k] = v
            except Exception as err:
                _log.warning(f'Failed to set {k}={v} ({err})')
        if not request_id:
            return response
        _log.debug(f'Responding to property change request {request_id}')
        self.notify(message=response, subtopic='info/properties/values')
        
    def notify(self,
               topic: str = None,
               message: dict = {},
               subtopic: str = None,
               qos: int = 1) -> None:
        """Publishes an inter-service (ISC) message to the local MQTT broker.
        
        Args:
            topic: Optional override of the class `_default_publish_topic`
                used if `topic` is not passed in.
            message: The message to publish as a JSON object.
            subtopic: A subtopic appended to the `_default_publish_topic`.
            
        """
        if not isinstance(message, dict):
            raise ValueError('Invalid message must be a dictionary')
        topic = topic or self._default_publish_topic
        if not isinstance(topic, str) or not topic:
            raise ValueError('Invalid topic must be string')
        if subtopic is not None:
            if not isinstance(subtopic, str) or not subtopic:
                raise ValueError('Invalid subtopic must be string')
            if not subtopic.startswith('/'):
                topic += '/'
            topic += subtopic
        json_message = json_compatible(message, camel_keys=True)
        if 'ts' not in json_message:
            json_message['ts'] = int(time.time() * 1000)
        if not self._mqttc_local or not self._mqttc_local.is_connected:
            _log.error('MQTT client not connected - failed to publish'
                            f'{topic}: {message}')
            return
        _log.info(f'Publishing ISC {topic}: {json_message}')
        self._mqttc_local.publish(topic, json_message, qos)
    
    def task_add(self, task: IscTask) -> None:
        """Adds a task to the task queue."""
        if self._isc_queue.is_queued(task_id=task.uid):
            _log.warning(f'Task {task.uid} already queued')
        else:
            self._isc_queue.append(task)
        if not self._isc_timer.is_alive() or not self._isc_timer.is_running:
            _log.warning('Task queue expiry not being checked')
        
    def task_get(self,
                 task_id: str = None,
                 meta_tag: str = None) -> 'IscTask|None':
        """Retrieves a task from the queue.
        
        Args:
            task_id: The unique ID of the task.
        
        Returns:
            The `QueuedIscTask` if it was found in the queue, else `None`.
            
        """
        return self._isc_queue.get(task_id, meta_tag)
        
    def task_expiry_enable(self, enable: bool = True):
        """Starts or stops periodic checking for expired ISC tasks.
        
        Args:
            enable: If `True` (default) starts the checks, else stops checking.
            
        """
        if enable:
            if not self._isc_timer.is_alive():
                self._isc_timer.start()
            self._isc_timer.start_timer()
        else:
            self._isc_timer.stop_timer()


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
        for m, topics in self._subscriptions.items():
            for t in topics:
                if t == topic:
                    if m == module:
                        _log.warning(f'Topic {topic} already subscribed by {m}')
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
        for m, topics in self._subscriptions.items():
            for t in topics:
                if t == topic:
                    modules_subscribed.append(m)
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
        for module, topics in self._subscriptions.items():
            if (topic in topics):
                if callable(self._subscriptions[module][topic]):
                    self._subscriptions[module][topic](topic, message)
