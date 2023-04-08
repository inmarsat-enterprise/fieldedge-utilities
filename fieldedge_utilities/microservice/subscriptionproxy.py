"""A proxy class for interfacing with other Microservices via MQTT.
"""
import logging
from typing import Callable

from fieldedge_utilities.mqtt import MqttClient

__all__ = ['SubscriptionProxy']

_log = logging.getLogger(__name__)


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
