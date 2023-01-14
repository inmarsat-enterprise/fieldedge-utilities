import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable
from uuid import UUID, uuid4

from .class_properties import (get_class_properties, get_class_tag,
                               json_compatible, tag_class_properties,
                               tag_class_property, untag_class_property)
from .logger import verbose_logging
from .mqtt import MqttClient
from .timer import RepeatingTimer

_log = logging.getLogger(__name__)


class FieldedgeMicroservice(ABC):
    """Abstract base class for a FieldEdge microservice.
    
    Use `__slots__` to expose initialization properties.
    
    """
    
    __slots__ = ('tag', '_mqttc_local', '_default_publish_topic', '_hide',
                 '_isc_tags', '_isc_ignore', '_rollcall_properties',
                 '_isc_queue', '_isc_timer', '_property_cache')
    
    LOG_LEVELS = ['DEBUG', 'INFO']
    
    @abstractmethod
    def __init__(self,
                 tag: str = None,
                 mqtt_client_id: str = None,
                 auto_connect: bool = False,
                 isc_tags: bool = False,
                 isc_poll_interval: float = 1,
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
            prop_tags (bool): If set then isc_properties will include the class
                tag as a prefix. Disabled by default.
                
        """
        self.tag: str = tag or get_class_tag(self.__class__)
        self._isc_tags: bool = isc_tags
        if not mqtt_client_id:
            mqtt_client_id = f'fieldedge_{self.tag}'
        default_subscriptions = [ 'fieldedge/+/rollcall/#' ]
        default_subscriptions.append(f'fieldedge/{tag}/request/#')
        self._mqttc_local = MqttClient(client_id=mqtt_client_id,
                                       subscribe_default=default_subscriptions,
                                       on_message=self._on_isc_message,
                                       auto_connect=auto_connect)
        self._default_publish_topic = f'fieldedge/{tag}'
        self._hide: 'list[str]' = []
        self._isc_ignore: 'list[str]' = [
            'properties',
            'properties_by_type',
            'isc_properties',
            'isc_properties_by_type'
        ]
        self._rollcall_properties: 'list[str]' = []
        self._isc_queue = IscTaskQueue()
        self._isc_timer = RepeatingTimer(seconds=isc_poll_interval,
                                         target=self._isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer')
        self._isc_timer.start()
        self._property_cache: dict = {}
    
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
        """Public properties of the class."""
        return get_class_properties(self, ignore=self._hide)
    
    @property
    def properties_by_type(self) -> 'dict[str, list[str]]':
        """Public properties of the class tagged `read_only` or `read_write`."""
        return get_class_properties(self,
                                    ignore=self._hide,
                                    categorize=True)
    
    def cache_property(self, cache_tag: str, cache_lifetime: int = 5):
        """Sets a cache indicator for the tag name based on current time.
        
        The cache validity can be checked against `cache_lifetime` using the
        `cache_valid` method.
        
        Args:
            cache_tag (str): The name of the property or proxy.
            cache_lifetime (int): The valid time in seconds.
        
        """
        if cache_tag in self._property_cache:
            _log.warning(f'Overwriting cache for {cache_tag}')
        self._property_cache[cache_tag] = (int(time.time()), cache_lifetime)
    
    def cache_valid(self, cache_tag: str) -> bool:
        """Returns `True` if the cache tag exists and is still valid.
        
        If expired this method will remove the cache tag.
        
        Args:
            cache_tag (str): The name of the property or proxy.
        
        Returns:
            `True` if the time passed since cached is within the cache_lifetime
                specified using the `cache_property` method.
                
        """
        if cache_tag not in self._property_cache:
            return False
        cache_time, cache_lifetime = self._property_cache[cache_tag]
        if time.time() - cache_time < cache_lifetime:
            return True
        _log.debug(f'Cached {cache_tag} expired - removing')
        del self._property_cache[cache_tag]
        return False
        
    @property
    def isc_properties(self) -> 'list[str]':
        """ISC exposed properties."""
        ignore = self._hide + self._isc_ignore
        return tag_class_properties(self,
                                    auto_tag=self._isc_tags,
                                    ignore=ignore)
    
    @property
    def isc_properties_by_type(self) -> 'dict[str, list[str]]':
        """ISC exposed properties tagged `readOnly` or `readWrite`."""
        ignore = self._hide + self._isc_ignore
        return tag_class_properties(self,
                                    auto_tag=self._isc_tags,
                                    categorize=True,
                                    ignore=ignore)
    
    def get_prop_from_isc(self, isc_prop: str) -> Any:
        """Gets a property value based on its ISC name."""
        target_prop = untag_class_property(isc_prop)
        if target_prop not in self.properties:
            raise AttributeError(f'{target_prop} not in properties')
        for prop in self.properties:
            if prop == target_prop:
                return getattr(self, prop)
    
    def set_prop_from_isc(self, isc_prop: str, value) -> None:
        """Sets a property value based on its ISC name."""
        target_prop = untag_class_property(isc_prop)
        if target_prop not in self.properties:
            raise AttributeError(f'{target_prop} not in properties')
        if target_prop not in self.properties_by_type['read_write']:
            raise AttributeError(f'{target_prop} is not writable')
        for prop in self.properties:
            if prop == target_prop:
                setattr(prop, value)
                break
    
    def hide_property(self, prop_name: str):
        """Hides a property so it will not list in `properties`."""
        if prop_name not in self.properties:
            raise ValueError(f'Invalid prop_name {prop_name}')
        if prop_name not in self._hide:
            self._hide.append(prop_name)
    
    def unhide_property(self, prop_name: str):
        """Unhides a hidden property so it appears in `properties`."""
        if prop_name in self._hide:
            self._hide.remove(prop_name)
    
    def isc_ignore_property(self, prop_name: str):
        """Hides a property from ISC - does not appear in `isc_properties`."""
        if prop_name not in self.properties:    
            raise ValueError(f'Invalid prop_name {prop_name}')
        if prop_name not in self._isc_ignore:
            self._isc_ignore.append(prop_name)
    
    def isc_unignore_property(self, prop_name: str):
        """Unhides a property to ISC so it appears in `isc_properties`."""
        if prop_name in self._isc_ignore:
            self._isc_ignore.remove(prop_name)
        
    @property
    def rollcall_properties(self) -> 'list[str]':
        """Property key/values that will be sent in the rollcall response."""
        return self._rollcall_properties
    
    def add_rollcall_property(self, prop_name: str):
        """Add a property to the rollcall response."""
        if prop_name not in self.properties:
            raise ValueError(f'Invalid prop_name {prop_name}')
        if prop_name not in self._rollcall_properties:
            self._rollcall_properties.append(prop_name)
    
    def del_rollcall_property(self, prop_name: str):
        """Remove a property from the rollcall response."""
        if prop_name in self._rollcall_properties:
            self._rollcall_properties.remove(prop_name)
        
    @abstractmethod
    def _on_isc_message(self, topic: str, message: dict) -> None:
        """Routes or drops incoming ISC/MQTT requests and responses."""
        if self._vlog:
            _log.debug(f'Received ISC {topic}: {message}')
        if topic.endswith('/rollcall'):
            self.rollcall_receive(topic, message)
        else:
            _log.warning(f'Unhandled message!')
        
    def rollcall_receive(self, topic: str, message: dict):
        if f'/{self.tag}/' in topic:
            if self._vlog:
                _log.debug(f'Ignoring rollcall request from self')
        else:
            self.rollcall_respond(message)
        
    def rollcall(self):
        """Publishes a rollcall broadcast to other microservices with UUID."""
        subtopic = 'rollcall'
        rollcall = { 'uid': str(uuid4()) }
        self.notify(rollcall, subtopic=subtopic)
    
    def rollcall_respond(self, request: dict):
        """Responds to rollcall from another microservice with the request UUID.
        
        Includes key/value pairs from the `rollcall_properties` list.
        
        Args:
            request (dict): The request message from the other microservice.
        
        """
        subtopic = 'rollcall/response'
        if 'uid' not in request:
            _log.warning('Rollcall request missing unique ID')
        response = { 'uid': request.get('uid', None) }
        tag = self.tag if self._isc_tags else None
        for prop in self._rollcall_properties:
            if prop in self.properties:
                tagged_prop = tag_class_property(prop, tag)
                response[tagged_prop] = getattr(self, prop)
        self.notify(response, subtopic=subtopic)
    
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
    
    def isc_expiry_check_enable(self, enable: bool):
        if enable:
            self._isc_timer.start_timer()
        else:
            self._isc_timer.stop_timer()


class QueuedIscTask:
    """An interservice communication task waiting for an MQTT response.
    
    May be a long-running query typically triggering a callback, with optional
    callback metadata.
    
    The `cb_meta` dictionary supports a special keyword `timeout_callback` as
    a Callable that will be passed the metadata and `uid` if the task expires.
    This must be triggered from the `IscTaskQueue` method `remove_expired`.
    
    Attributes:
        uid (UUID): A unique task identifier
        task_type (str): A short name for the task purpose
        callback (Callable): An optional callback function
        cb_meta (any): Meta/data dictionary to be passed to the callback
        lifetime (int): Seconds before the task times out. `None` value
            means the task will not expire/timeout.
        queued_time (float): The unix timestamp when the task was queued

    """
    def __init__(self,
                 uid: 'str|UUID',
                 task_type: str = None,
                 lifetime: int = 10,
                 callback: Callable = None,
                 cb_meta: dict = None,
                 ) -> None:
        """Initialize the Task.
        
        Args:
            uid (UUID): A unique task identifier
            task_type (str): A short name for the task purpose
            callback (Callable): An optional callback function
            cb_meta (any): Meta/data dictionary to be passed to the callback
            lifetime (int): Seconds before the task times out. `None` value
                means the task will not expire/timeout.
            queued_time (float): The unix timestamp when the task was queued
        
        """
        self.uid = uid
        self.task_type = task_type
        self.callback = callback
        self.queued_time = round(time.time(), 3)
        self.lifetime = lifetime
        self.cb_meta = cb_meta


class IscTaskQueue(list):
    """A task queue (order-independent) for interservice communications."""
    
    def append(self, item: QueuedIscTask):
        """Add a task to the queue."""
        if not isinstance(item, QueuedIscTask):
            raise ValueError('item must be QueuedIscTask type')
        super().append(item)
    
    def insert(self, index: int, element: Any):
        """Invalid operation."""
        raise OSError('ISC task queue does not support insertion')
        
    def is_queued(self, task_id: 'str|UUID' = None, cb_meta: tuple = None) -> bool:
        """Returns `True` if the specified task or meta is queued."""
        if not task_id and not cb_meta:
            raise ValueError('Missing task ID or cb_meta search criteria')
        if isinstance(cb_meta, tuple) and len(cb_meta) != 2:
            raise ValueError('cb_meta must be a key/value pair')
        for task in self:
            assert isinstance(task, QueuedIscTask)
            if task_id and task.uid == task_id:
                return True
            if isinstance(cb_meta, tuple):
                if not isinstance(task.cb_meta, dict):
                    continue
                for k, v in task.cb_meta.items():
                    if k == cb_meta[0] and v == cb_meta[1]:
                        return True
        return False
            
    def task_get(self, task_id: 'str|UUID') -> 'QueuedIscTask|None':
        """Retrieves the specified task from the queue."""
        index = None
        for i, task in enumerate(self):
            assert isinstance(task, QueuedIscTask)
            if task.uid == task_id:
                index = i
                break
        if index is not None:
            return self.pop(index)
    
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
            assert isinstance(task, QueuedIscTask)
            if task.lifetime is None:
                continue
            if time.time() - task.queued_time > task.lifetime:
                expired.append(i)
        for i in expired:
            rem: QueuedIscTask = self.pop(i)
            _log.warning(f'Removing expired task {rem.uid}')
            if (isinstance(rem.cb_meta, dict) and
                'timeout_callback' in rem.cb_meta and
                callable(rem.cb_meta['timeout_callback'])):
                # Callback with metadata
                timeout_meta = { 'task_id': rem.uid }
                for k, v in rem.cb_meta.items():
                    if k in ['timeout_callback']:
                        continue
                    timeout_meta[k] = v
                rem.cb_meta['timeout'](timeout_meta)
