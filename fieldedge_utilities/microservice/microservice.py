"""Microservice and related meta/classes.
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.mqtt import MqttClient
from fieldedge_utilities.timer import RepeatingTimer

from .feature import Feature
from .interservice import IscTask, IscTaskQueue
from .properties import (READ_ONLY, READ_WRITE, get_class_properties,
                         get_class_tag, hasattr_static, json_compatible,
                         property_is_read_only, snake_to_camel,
                         tag_class_property, untag_class_property)
from .propertycache import PropertyCache
from .msproxy import MicroserviceProxy

__all__ = ['Microservice']

_log = logging.getLogger(__name__)


class DictTrigger(dict):
    """A modified dictionary that monitors edits and executes a callback."""
    def __init__(self, *args, **kwargs) -> None:
        self._modify_callback = kwargs.pop('modify_callback', None)
        self.update(*args, **kwargs)

    def update(self, *args, **kwargs):
        for k, v in dict(*args, **kwargs).items():
            self[k] = v

    def __setitem__(self, __key: Any, __value: Any) -> None:
        if __value is None:
            del self[__key]
        else:
            dict.__setitem__(self, __key, __value)
        if callable(self._modify_callback):
            self._modify_callback()

    def __delitem__(self, __key: Any) -> None:
        dict.__delitem__(self, __key)
        if callable(self._modify_callback):
            self._modify_callback()


class Microservice(ABC):
    """Abstract base class for a FieldEdge microservice.
    
    Use `__slots__` to expose initialization properties.
    
    """

    __slots__ = (
        '_tag', '_mqttc_local', '_default_publish_topic', '_subscriptions',
        '_isc_queue', '_isc_timer', '_isc_tags', '_isc_ignore',
        '_hidden_properties', '_property_cache',
        '_isc_properties', '_hidden_isc_properties', '_rollcall_properties',
        'features', 'ms_proxies',
    )

    LOG_LEVELS = ['DEBUG', 'INFO']

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
        self._hidden_properties: 'list[str]' = [
            'features',
            'ms_proxies',
        ]
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
        self._isc_queue = IscTaskQueue()
        self._isc_timer = RepeatingTimer(seconds=isc_poll_interval,
                                         target=self._isc_queue.remove_expired,
                                         name='IscTaskExpiryTimer')
        self.features: 'dict[str, Feature]' = DictTrigger(
            modify_callback=self._refresh_properties)
        self.ms_proxies: 'dict[str, MicroserviceProxy]' = {}
        self._property_cache = PropertyCache()

    @property
    def tag(self) -> str:
        """The microservice tag used in MQTT topic."""
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
        cached = self._property_cache.get_cached('properties')
        if cached:
            return cached
        return self._refresh_properties()

    def _refresh_properties(self) -> 'list[str]':
        """Refreshes the class properties."""
        self._property_cache.remove('properties')
        self._property_cache.remove('isc_properties')
        ignore = self._hidden_properties
        properties = get_class_properties(self.__class__, ignore)
        for tag, feature in self.features.items():
            feature_props = feature.properties_list()
            for prop in feature_props:
                properties.append(f'{tag}_{prop}')
        self._property_cache.cache(properties, 'properties', None)
        return properties

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
                for tag, feature in self.features.items():
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
            self._refresh_properties()

    def property_unhide(self, prop_name: str):
        """Unhides a hidden property so it appears in `properties`."""
        if prop_name in self._hidden_properties:
            self._hidden_properties.remove(prop_name)
            self._refresh_properties()

    @property
    def isc_properties(self) -> 'list[str]':
        """ISC exposed properties."""
        cached = self._property_cache.get_cached('isc_properties')
        if cached:
            return cached
        return self._refresh_isc_properties()

    def _refresh_isc_properties(self) -> 'list[str]':
        """Refreshes the cached ISC properties list."""
        ignore = self._hidden_properties
        ignore.extend(p for p in self._hidden_isc_properties
                      if p not in self._hidden_properties)
        tag = self.tag if self._isc_tags else None
        isc_properties = [tag_class_property(prop, tag)
                          for prop in self.properties if prop not in ignore]
        self._property_cache.cache(isc_properties, 'isc_properties', None)
        return isc_properties

    @property
    def isc_properties_by_type(self) -> 'dict[str, list[str]]':
        """ISC exposed properties tagged `info` or `config`."""
        # subfunction
        def feature_prop(prop) -> 'tuple[object, str]':
            fprop, ftag = untag_class_property(prop, True, True)
            feature = self.features.get(ftag, None)
            if feature and fprop in feature.properties_list():
                return (feature, fprop)
            raise ValueError(f'Unknown tag {prop}')
        # main function
        categorized = {}
        for isc_prop in self.isc_properties:
            prop, tag = untag_class_property(isc_prop, self._isc_tags, True)
            if self._isc_tags:
                if tag == self.tag:
                    if hasattr_static(self, prop):
                        obj = self
                    else:
                        obj, prop = feature_prop(prop)
                else:
                    raise ValueError(f'Unknown tag {tag}')
            else:
                if hasattr_static(self, prop):
                    obj = self
                else:
                    obj, prop = feature_prop(isc_prop)
            self._categorize_prop(obj, prop, categorized, isc_prop)
        return categorized

    def isc_get_property(self, isc_property: str) -> Any:
        """Gets a property value based on its ISC name."""
        prop = untag_class_property(isc_property, self._isc_tags)
        if hasattr_static(self, prop):
            return getattr(self, prop)
        else:
            for tag, feature in self.features.items():
                if not prop.startswith(f'{tag}_'):
                    continue
                fprop = prop.replace(f'{tag}_', '')
                if hasattr_static(feature, fprop):
                    return getattr(feature, fprop)
        raise AttributeError(f'ISC property {isc_property} not found')

    def isc_set_property(self, isc_property: str, value: Any) -> None:
        """Sets a property value based on its ISC name."""
        prop = untag_class_property(isc_property, self._isc_tags)
        if hasattr_static(self, prop):
            if property_is_read_only(self, prop):
                raise AttributeError(f'{prop} is read-only')
            setattr(self, prop, value)
            return
        else:
            for tag, feature in self.features.items():
                if not prop.startswith(f'{tag}_'):
                    continue
                fprop = prop.replace(f'{tag}_', '')
                if hasattr_static(feature, fprop):
                    if property_is_read_only(feature, fprop):
                        raise AttributeError(f'{prop} is read-only')
                    setattr(feature, fprop, value)
                    return
        raise AttributeError(f'ISC property {isc_property} not found')

    def isc_property_hide(self, isc_property: str) -> None:
        """Hides a property from ISC - does not appear in `isc_properties`."""
        if isc_property not in self.isc_properties:
            raise ValueError(f'Invalid prop_name {isc_property}')
        if isc_property not in self._hidden_isc_properties:
            self._hidden_isc_properties.append(isc_property)
            self._refresh_isc_properties()

    def isc_property_unhide(self, isc_property: str) -> None:
        """Unhides a property to ISC so it appears in `isc_properties`."""
        if isc_property in self._hidden_isc_properties:
            self._hidden_isc_properties.remove(isc_property)
            self._refresh_isc_properties()

    @property
    def rollcall_properties(self) -> 'list[str]':
        """Property key/values that will be sent in the rollcall response."""
        return self._rollcall_properties

    def rollcall_property_add(self, prop_name: str):
        """Add a property to the rollcall response."""
        if (prop_name not in self.properties and
            prop_name not in self.isc_properties):
            # invalid
            raise ValueError(f'Invalid prop_name {prop_name}')
        isc_prop_name = snake_to_camel(prop_name)
        if isc_prop_name not in self.isc_properties:
            raise ValueError(f'{isc_prop_name} not in isc_properties')
        if prop_name not in self._rollcall_properties:
            self._rollcall_properties.append(isc_prop_name)

    def rollcall_property_remove(self, prop_name: str):
        """Remove a property from the rollcall response."""
        isc_prop_name = snake_to_camel(prop_name)
        if isc_prop_name in self._rollcall_properties:
            self._rollcall_properties.remove(isc_prop_name)

    def rollcall(self):
        """Publishes a rollcall broadcast to other microservices with UUID."""
        subtopic = 'rollcall'
        rollcall = { 'uid': str(uuid4()) }
        self.notify(message=rollcall, subtopic=subtopic)

    def rollcall_respond(self, topic: str, message: dict):
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
            _log.warning('rollcall_respond called without rollcall topic')
            return
        subtopic = 'rollcall/response'
        if 'uid' not in message:
            _log.warning('Rollcall request missing unique ID')
        requestor = topic.split('/')[1]
        response = { 'uid': message.get('uid', None), 'requestor': requestor }
        for isc_prop in self._rollcall_properties:
            if isc_prop in self.isc_properties:
                response[isc_prop] = self.isc_get_property(isc_prop)
        self.notify(message=response, subtopic=subtopic)

    def isc_topic_subscribe(self, topic: str) -> bool:
        """Subscribes to the specified ISC topic."""
        if not isinstance(topic, str) or not topic.startswith('fieldedge/'):
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

    def _kwarg_propagate(self,
                         topic: str,
                         message: dict,
                         filter: 'list[str]') -> None:
        if not isinstance(filter, list):
            filter = [filter]
        filter += ['uid', 'ts']
        kwargs = {key: val for key, val in message.items()
                  if key not in filter}
        if kwargs:
            self.on_isc_message(topic, message)

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
                _log.debug('Ignoring own response/event')
            return
        elif topic.endswith('/rollcall'):
            self.rollcall_respond(topic, message)
        elif (topic.endswith(f'/{self.tag}/request/properties/list') or
              topic.endswith(f'/{self.tag}/request/properties/get')):
            self.properties_notify(message)
            self._kwarg_propagate(topic, message, ['properties'])
        elif topic.endswith(f'/{self.tag}/request/properties/set'):
            self.properties_change(message)
            self._kwarg_propagate(topic, message, ['properties'])
        else:
            if (self.features and
                self._is_child_isc(self.features, topic, message)):
                return
            if (self.ms_proxies and
                self._is_child_isc(self.ms_proxies, topic, message)):
                return
            self.on_isc_message(topic, message)

    @staticmethod
    def _is_child_isc(children: 'dict[str, Feature|MicroserviceProxy]',
                      topic: str,
                      message: dict) -> bool:
        """Returns True if one of the children handled the message."""
        for child in children.values():
            if (hasattr_static(child, 'on_isc_message') and
                callable(child.on_isc_message)):
                handled = child.on_isc_message(topic, message)
                if handled:
                    return True
        return False

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
            try:
                subtopic = 'info/properties/values'
                req_props: list = request.get('properties', [])
                if not req_props or 'all' in req_props:
                    req_props = self.isc_properties
                response['properties'] = {}
                res_props = response['properties']
                props_source = self.isc_properties
                if categorized:
                    props_source = self.isc_properties_by_type
                    for prop in req_props:
                        if (READ_WRITE in props_source and
                            prop in props_source[READ_WRITE]):
                            # config property
                            if READ_WRITE not in res_props:
                                res_props[READ_WRITE] = {}
                            res_props[READ_WRITE][prop] = (
                                self.isc_get_property(prop))
                        else:
                            if READ_ONLY not in res_props:
                                res_props[READ_ONLY] = {}
                            res_props[READ_ONLY][prop] = (
                                self.isc_get_property(prop))
                else:
                    for prop in req_props:
                        res_props[prop] = self.isc_get_property(prop)
            except AttributeError as exc:
                response = { 'uid': request_id, 'error': {exc} }
        _log.debug(f'Responding to request {request_id} for properties'
                   f': {request.get("properties", "ALL")}')
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
        for key, val in request['properties'].items():
            if key not in self.isc_properties_by_type[READ_WRITE]:
                _log.warning(f'{key} is not a config property')
                continue
            try:
                self.isc_set_property(key, val)
                response['properties'][key] = val
            except Exception as exc:
                _log.warning(f'Failed to set {key}={val} ({exc})')
        if not request_id:
            return response
        _log.debug(f'Responding to property change request {request_id}')
        self.notify(message=response, subtopic='info/properties/values')

    def notify(self,
               topic: str = None,
               message: dict = None,
               subtopic: str = None,
               qos: int = 1) -> None:
        """Publishes an inter-service (ISC) message to the local MQTT broker.
        
        Args:
            topic: Optional override of the class `_default_publish_topic`
                used if `topic` is not passed in.
            message: The message to publish as a JSON object.
            subtopic: A subtopic appended to the `_default_publish_topic`.
            
        """
        if message is None:
            message = {}
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
        if 'uid' not in json_message:
            json_message['uid'] = str(uuid4())
        if not self._mqttc_local or not self._mqttc_local.is_connected:
            _log.error('MQTT client not connected - failed to publish'
                       f' {topic}: {message}')
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
