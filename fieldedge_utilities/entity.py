import logging
import os
from time import time

from .class_properties import json_compatible
from .mqtt import MqttClient

PROPERTY_CACHE_DEFAULT = int(os.getenv('PROPERTY_CACHE_DEFAULT', 5))

_log = logging.getLogger(__name__)


class FieldEdgeEntity(object):
    
    LOG_VERBOSE = os.getenv('LOG_VERBOSE')
    PROPERTY_CACHE_DEFAULT = int(os.getenv('PROPERTY_CACHE_DEFAULT', 5))
    
    def __init__(self, tag_name: str) -> None:
        raise NotImplementedError
        if not tag_name:
            raise ValueError('Missing tag_name')
        self.tag_name: str = tag_name
        self._log = logging.getLogger(__name__)
        self._exposed_properties: dict = {}
        self._property_cache: dict = {}
        self._mqttc_local: 'MqttClient|None' = None
    
    @property
    def properties(self) -> dict:
        """"""
        if not dir(self):
            raise ValueError(f'Invalid Type - must have dir method')
        ignore_startswith = ('_', 'properties', 'property_cache',
                             'cache_update', 'cache_valid',
                             'merge_exposed_properties')
        props = {}
        props_list = [a for a in dir(self)
                      if not a.startswith(ignore_startswith) and
                      not callable(getattr(self, a))]
        for prop in props_list:
            props[prop] = getattr(self, prop)
        return props
        
    @property
    def property_cache(self) -> dict:
        return self._property_cache
    
    def cache_update(self, property_name: str) -> None:
        if property_name not in self.properties:
            raise ValueError(f'{property_name} not found')
        self._property_cache[property_name] = int(time())
        
    def cache_valid(self, property_name: str, max_age: int = None) -> bool:
        if property_name not in self.properties:
            raise ValueError(f'{property_name} not found')
        if max_age is None:
            max_age = self.PROPERTY_CACHE_DEFAULT
        if property_name in self.property_cache:
            cache_age = int(time()) - self.property_cache[property_name]
            if cache_age > max_age:
                if self._verbose_log:
                    self._log.debug(f'Cached {property_name} only {cache_age}s'
                                    f' old (cache = {max_age}s)')
                return False
            return True
    
    @property
    def exposed_properties(self) -> dict:
        return self._exposed_properties
    
    def expose_properties(self,
                          tag: str = None,
                          ignore: 'list[str]' = [],
                          json: bool = False,
                          ) -> dict:
        """Gets a dictionary of properties exposed for MQTT-ISC interaction.
        
        Properties are grouped by entity `tag_name` then by `config` or
        `read_only`.
        
        Args:
            tag: the tag prefix to use
                e.g. modem location becomes `modemLocation`
            ignore: any properties to explicitly ignore
            json: if set, will camelCase all dictionary keys
        
        Returns:
            A dictionary of tagged and grouped properties
        
        """
        rw = []
        ro = []
        for prop, val in self.properties:
            if prop in ignore or not isinstance(val, property):
                if self._verbose_log:
                    _log.debug(f'Ignoring {prop}')
                continue
            if val.fset is not None:
                rw.append(prop)
            else:
                ro.append(prop)
        if tag is None:
            tag = self.tag_name
        for i, prop in enumerate(rw):
            rw[i] = f'{tag}_{prop}'
        for i, prop in enumerate(ro):
            ro[i] = f'{tag}_{prop}'
        tagged = { 'config': rw, 'read_only': ro }
        if json:
            return json_compatible(tagged, True)
        return tagged
    
    def extend_exposed_properties(self, tagged_properties: dict) -> dict:
        """Merges another FieldEdge set of tagged properties with this entity.
        
        Args:
            tagged_properties: A dictionary of exposed_properties from the other
                entity
        """
        for prop_type in self._exposed_properties:
            in_exposed = set(self._exposed_properties[prop_type])
            if prop_type in tagged_properties:
                to_inherit = set(tagged_properties[prop_type])
            else:
                to_inherit = set()
            self._exposed_properties[prop_type] = list(in_exposed|to_inherit)

    @property
    def _verbose_log(self) -> bool:
        if self.LOG_VERBOSE and self.tag_name in self.LOG_VERBOSE:
            return True
        return False
        
    def notify(self, message: dict, subtopic: str = None):
        """Send a notification to other microservices via MQTT."""
        topic = f'fieldedge/{self.tag_name}'
        if subtopic:
            topic += f'/{subtopic}'
        if 'ts' not in message:
            message['ts'] = int(time() * 1000)   # Telegraf timestamp
        if not self._mqttc_local or not self._mqttc_local.is_connected:
            self._log.warning('MQTT local client not connected'
                              f' - cannot publish {topic}: {message}')
            return
        if self._verbose_log:
            self._log.debug(f'Notifying {topic}: {message}')
        self._mqttc_local.publish(topic, message)
