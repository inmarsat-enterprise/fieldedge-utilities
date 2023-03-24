"""Helper Classes for a FieldEdge microservice and inter-service communications.

"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from .class_properties import (READ_ONLY, READ_WRITE, get_class_properties,
                               get_class_tag, json_compatible, property_is_async,
                               property_is_read_only, tag_class_property,
                               untag_class_property)
from .logger import verbose_logging
from .mqtt import MqttClient
from .timer import RepeatingTimer

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
    
    @abstractmethod
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
        self._subscriptions.append(f'fieldedge/+/{self.tag}/#')
        self._mqttc_local = MqttClient(client_id=mqtt_client_id,
                                       subscribe_default=self._subscriptions,
                                       on_message=self._on_isc_message,
                                       auto_connect=auto_connect)
        self._default_publish_topic = f'fieldedge/{tag}'
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
        ]
        self._rollcall_properties: 'list[str]' = []
        self._isc_poll_interval: int = int(isc_poll_interval)
        self._isc_queue = IscTaskQueue()
        self._isc_timer = RepeatingTimer(seconds=isc_poll_interval,
                                         target=self._isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer')
        self._cached_properties: dict = {}
    
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
        
    def _categorized(self, prop_list: 'list[str]') -> 'dict[str, list[str]]':
        """Categorizes properties as `config` or `info`."""
        categorized = {}
        for prop in prop_list:
            if property_is_read_only(self, prop):
                if READ_ONLY not in categorized:
                    categorized[READ_ONLY] = []
                categorized[READ_ONLY].append(prop)
            else:
                if READ_WRITE not in categorized:
                    categorized[READ_WRITE] = []
                categorized[READ_WRITE].append(prop)
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
    
    def property_cache(self, property_name: str, cache_lifetime: int = 5):
        """Sets a cache indicator for the tag name based on current time.
        
        Typically used to avoid repeat checking of properties or proxy
        properties that may be slow to refresh.
        The cache validity can be checked against `cache_lifetime` using the
        `property_is_cached` method.
        
        Setting `cache_lifetime` to `None` persists the cached value forever
        unless a subsequent property_cache overwrites the lifetime.
        
        Args:
            property_name (str): The name of the property or proxy.
            cache_lifetime (int): The validity time in seconds.
        
        """
        if property_name in self._cached_properties:
            old_lifetime = self._cached_properties[property_name][1]
            _log.warning(f'Overwriting cache for {property_name}'
                         f' from {old_lifetime} to {cache_lifetime}')
        self._cached_properties[property_name] = (time.time(),
                                                  cache_lifetime)
    
    def property_is_cached(self, property_name: str) -> bool:
        """Returns `True` if the property cache_lifetime is not expired.
        
        If expired, the property's cache tag will be removed from the cache.
        
        Args:
            property_name (str): The name of the property or proxy.
        
        Returns:
            `True` if the time passed since cached is within the cache_lifetime
                specified using the `property_cache` method.
                
        """
        if property_name not in self._cached_properties:
            return False
        cache_time, cache_lifetime = self._cached_properties[property_name]
        if cache_lifetime is None:
            return True
        elapsed = int(time.time() - cache_time)
        if elapsed < cache_lifetime:
            return True
        _log.debug(f'Cached {property_name} expired ({elapsed}s) - removing')
        del self._cached_properties[property_name]
        return False
        
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
        """ISC exposed properties tagged `readOnly` or `readWrite`."""
        categorized = {}
        for isc_prop in self.isc_properties:
            entry = self._categorized([untag_class_property(isc_prop,
                                                            self._isc_tags)])
            if READ_WRITE in entry:
                if READ_WRITE not in categorized:
                    categorized[READ_WRITE] = []
                categorized[READ_WRITE].append(isc_prop)
            else:
                if READ_ONLY not in categorized:
                    categorized[READ_ONLY] = []
                categorized[READ_ONLY].append(isc_prop)
        return categorized
    
    def isc_get_property(self, isc_property: str) -> Any:
        """Gets a property value based on its ISC name."""
        prop = untag_class_property(isc_property, self._isc_tags)
        if prop not in self.properties:
            raise AttributeError(f'{prop} not in properties')
        return getattr(self, prop)
    
    def isc_set_property(self, isc_property: str, value: Any) -> None:
        """Sets a property value based on its ISC name."""
        prop = untag_class_property(isc_property, self._isc_tags)
        if prop not in self.properties:
            raise AttributeError(f'{prop} not in properties')
        if prop not in self.properties_by_type[READ_WRITE]:
            raise AttributeError(f'{prop} is not writable')
        setattr(self, prop, value)
    
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
    
    def rollcall_property_add(self, prop_name: str):
        """Add a property to the rollcall response."""
        if prop_name not in self.properties:
            raise ValueError(f'Invalid prop_name {prop_name}')
        if prop_name not in self._rollcall_properties:
            self._rollcall_properties.append(prop_name)
    
    def rollcall_property_remove(self, prop_name: str):
        """Remove a property from the rollcall response."""
        if prop_name in self._rollcall_properties:
            self._rollcall_properties.remove(prop_name)
        
    def rollcall(self):
        """Publishes a rollcall broadcast to other microservices with UUID."""
        subtopic = 'rollcall'
        rollcall = { 'uid': str(uuid4()) }
        self.notify(rollcall, subtopic=subtopic)
    
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
        if f'/{self.tag}/' in topic:
            if self._vlog:
                _log.debug(f'Ignoring rollcall request from self')
        else:
            subtopic = 'rollcall/response'
            if 'uid' not in message:
                _log.warning('Rollcall request missing unique ID')
            response = { 'uid': message.get('uid', None) }
            tag = self.tag if self._isc_tags else None
            for prop in self._rollcall_properties:
                if prop in self.properties:
                    tagged_prop = tag_class_property(prop, tag)
                    response[tagged_prop] = getattr(self, prop)
            self.notify(response, subtopic=subtopic)
        
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
        if topic.endswith('/rollcall'):
            self._rollcall_respond(topic, message)
        elif (topic.endswith('/rollcall/response') and
              f'/{self.tag}/' in topic):
            if self._vlog:
                _log.debug(f'Ignoring own rollcall response')
        elif (topic.endswith(f'/{self.tag}/request/properties/list') or
              topic.endswith(f'/{self.tag}/request/properties/get')):
            self.properties_notify(message)
        elif topic.endswith(f'/{self.tag}/request/properties/set'):
            self.properties_change(message)
        else:
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
        _log.warning('TODO: testing')
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
            req_props: list = request['properties']
            response['properties'] = {}
            res_props = response['properties']
            if categorized:
                props_source = self.isc_properties_by_type
                if (READ_WRITE in props_source and
                    any(prop in req_props for prop in props_source[READ_WRITE])):
                    res_props[READ_WRITE] = {}
                if (READ_ONLY in props_source and
                    any(prop in req_props for prop in props_source[READ_ONLY])):
                    res_props[READ_ONLY] = {}
            else:
                props_source = self.isc_properties
            if len(req_props) == 0:
                req_props = self.isc_properties
            if categorized:
                for p in req_props:
                    if (READ_WRITE in props_source and
                        p in props_source[READ_WRITE]):
                        res_props[READ_WRITE][p] = props_source[READ_WRITE][p]
                    else:
                        res_props[READ_ONLY][p] = props_source[READ_ONLY][p]
            else:
                for p in req_props:
                    res_props[p] = props_source[p]
        _log.debug(f'Responding to request {request_id} for properties'
                   f': {request["properties"] or "ALL"}')
        self.notify(response, subtopic=subtopic)
    
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
        _log.warning('TODO: testing')
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
        self.notify(response, subtopic='info/properties/values')
        
    def notify(self,
               message: dict,
               topic: str = None,
               subtopic: str = None,
               qos: int = 1) -> None:
        """Publishes an inter-service (ISC) message to the local MQTT broker.
        
        Args:
            message: The message to publish as a JSON object.
            topic: Optional override of the class `_default_publish_topic`
                used if `topic` is not passed in.
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
        json_message = json_compatible(message)
        if 'ts' not in json_message:
            json_message['ts'] = int(time.time() * 1000)
        if not self._mqttc_local or not self._mqttc_local.is_connected:
            _log.error('MQTT client not connected - failed to publish'
                            f'{topic}: {message}')
            return
        _log.info(f'Publishing ISC {topic}: {json_message}')
        self._mqttc_local.publish(topic, message, qos)
    
    def task_add(self, task: IscTask) -> None:
        """Adds a task to the task queue."""
        if self._isc_queue.is_queued(task_id=task.uid):
            _log.warning(f'Task {task.uid} already queued')
        else:
            self._isc_queue.append(task)
        
    def task_get(self, task_id: str) -> 'IscTask|None':
        """Retrieves a task from the queue.
        
        Args:
            task_id: The unique ID of the task.
        
        Returns:
            The `QueuedIscTask` if it was found in the queue, else `None`.
            
        """
        return self._isc_queue.get(task_id)
        
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


@dataclass
class CachedProperty:
    name: str
    value: Any
    cache_lifetime: int = 5
    cache_time: float = time.time()


class MicroserviceProxy:
    """"""
    def __init__(self,
                 tag: str,
                 isc_poll_interval: int = 1) -> None:
        if not isinstance(tag, str):
            raise ValueError('Tag must be a valid microservice name')
        self._tag: str = tag
        self._isc_queue = IscTaskQueue()
        self._isc_timer = RepeatingTimer(seconds=isc_poll_interval,
                                         target=self._isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer')
        self._cached_properties: dict = {}
    
    def task_add(self, task: IscTask) -> None:
        """Adds a task to the task queue."""
        if self._isc_queue.is_queued(task_id=task.uid):
            _log.warning(f'Task {task.uid} already queued')
        else:
            self._isc_queue.append(task)
        
    def task_get(self, task_id: str) -> 'IscTask|None':
        """Retrieves a task from the queue.
        
        Args:
            task_id: The unique ID of the task.
        
        Returns:
            The `QueuedIscTask` if it was found in the queue, else `None`.
            
        """
        return self._isc_queue.get(task_id)
        
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
    
    def initialize(self) -> None:
        """Requests properties of the microservice to create the proxy."""
    
    def property_cache(self, property_name: str):
        """"""
