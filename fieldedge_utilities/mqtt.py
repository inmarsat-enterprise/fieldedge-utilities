"""MQTT client for local Mosquitto broker inter-service communications.
"""
import os
from atexit import register as on_exit
from json import JSONDecodeError
from json import dumps as json_dumpstr
from json import loads as json_loadstr
from logging import DEBUG, Logger
from threading import enumerate as enumerate_threads
from time import sleep, time
from typing import Callable, Union

from dotenv import load_dotenv
from paho.mqtt.client import MQTT_ERR_SUCCESS, Client

from fieldedge_utilities.logger import get_wrapping_logger

load_dotenv()

CONNECTION_RESULT_CODES = {
    0: 'MQTT_ERR_SUCCESS',
    1: 'MQTT_ERR_INCORRECT_PROTOCOL',
    2: 'MQTT_ERR_INVALID_CLIENT_ID',
    3: 'MQTT_ERR_SERVER_UNAVAILABLE',
    4: 'MQTT_ERR_BAD_USERNAME_PASSWORD',
    5: 'MQTT_ERR_UNAUTHORIZED',
    6: 'MQTT_ERR_CONNECTION_LOST',
    7: 'MQTT_ERR_TIMEOUT_WAITING_FOR_LENGTH',
    8: 'MQTT_ERR_TIMEOUT_WAITING_FOR_PAYLOAD',
    9: 'MQTT_ERR_TIMEOUT_WAITING_FOR_CONNACK',
    10: 'MQTT_ERR_TIMEOUT_WAITING_FOR_SUBACK',
    11: 'MQTT_ERR_TIMEOUT_WAITING_FOR_UNSUBACK',
    12: 'MQTT_ERR_TIMEOUT_WAITING_FOR_PINGRESP',
}


def get_mqtt_result(rc: int) -> str:
    if rc in CONNECTION_RESULT_CODES:
        return CONNECTION_RESULT_CODES[rc]
    return 'UNKNOWN'


class MqttError(Exception):
    pass


class MqttClient:
    """A customized MQTT client.

    Attributes:
        client_id (str): A unique client_id.
        on_message (Callable): A function called when a subscribed message
            is received from the broker .
        on_connect (Callable): A function called when the client connects
            to the broker.
        on_disconnect (Callable): A function called when the client disconnects.
        is_connected (bool): Status of the connection to the broker.

    """
    def __init__(self,
                 client_id: str,
                 on_message: Callable[..., "tuple[str, object]"],
                 subscribe_default: Union[str, "list[str]"] = None,
                 on_connect: Callable = None,
                 on_disconnect: Callable = None,
                 logger: Logger = None,
                 connect_retry_interval: int = 5):
        """Initializes a managed MQTT client.
        
        Args:
            client_id: The unique client ID
            on_message: The callback when subscribed messages are received
            subscribe_default: The default subscription(s) on re/connection
            logger: (optional) Logger
            connect_retry_interval: Seconds between broker reconnect attempts
        """
        self._host = os.getenv('MQTT_HOST') or 'fieldedge_broker'
        self._user = os.getenv('MQTT_USERNAME') or None
        self._pass = os.getenv('MQTT_PASS') or None
        self._log = logger or get_wrapping_logger(name='mqtt_client')
        if not isinstance(client_id, str) or client_id == '':
            self._log.error('Invalid client_id')
            raise MqttError('Invalid client_id')
        if not callable(on_message):
            self._log.warning('No on_message specified')
        on_exit(self._cleanup)
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.client_id = client_id
        self._mqtt = Client()
        self.is_connected = False
        self._subscriptions = {}
        self.connect_retry_interval = connect_retry_interval
        if subscribe_default:
            if not isinstance(subscribe_default, list):
                subscribe_default = [subscribe_default]
            for sub in subscribe_default:
                self.subscription_add(sub)
        self._connect()
    
    @property
    def client_id(self):
        return self._client_id
    
    @client_id.setter
    def client_id(self, id: str):
        try:
            if isinstance(int(id.split('_')[1]), int):
                # previously made unique, could be a bouncing MQTT connection
                id = id.split('_')[0]
        except (ValueError, IndexError):
            pass   #: new id will be made unique
        self._client_id = '{}_{}'.format(id, str(int(time())))

    @property
    def subscriptions(self) -> dict:
        """The dictionary of subscriptions.
        
        Use subscription_add or subscription_del to change the dict.

        'topic' : { 'qos': (int), 'mid': (int) }

        """
        return self._subscriptions

    def _cleanup(self, *args):
        for arg in args:
            self._log.debug('mqtt cleanup called with arg = {}'.format(arg))
        self._log.debug('Terminating MQTT connection')
        self._mqtt.user_data_set('terminate')
        self._mqtt.loop_stop()
        self._mqtt.disconnect()
    
    def _connect(self):
        try:
            self._log.debug('Attempting MQTT broker connection to {} as {}'
                .format(self._host, self._client_id))
            self._mqtt.reinitialise(client_id=self.client_id)
            self._mqtt.user_data_set(None)
            self._mqtt.on_connect = self._mqtt_on_connect
            self._mqtt.on_disconnect = self._mqtt_on_disconnect
            self._mqtt.on_subscribe = self._mqtt_on_subscribe
            self._mqtt.on_message = self._mqtt_on_message
            if self._user and self._pass:
                self._mqtt.username_pw_set(username=self._user,
                                           password=self._pass)
            self._mqtt.connect(self._host)
            threads_before = enumerate_threads()
            self._mqtt.loop_start()
            threads_after = enumerate_threads()
            for thread in threads_after:
                if thread in threads_before:
                    continue
                thread.name = 'MqttThread'
                break
        except ConnectionError as e:
            self._log.warning(f'Unable to connect to {self._host} ({e})...'
                f'retrying in {self.connect_retry_interval} seconds')
            sleep(self.connect_retry_interval)
            # raise MqttError('MQTT {}'.format(e))

    def _mqtt_on_connect(self, client, userdata, flags, rc):
        self._log.debug('MQTT broker connection result code: {} ({})'
            .format(rc, get_mqtt_result(rc)))
        if rc == 0:
            self._log.info('MQTT connection to {}'.format(self._host))
            if not self.is_connected:
                for sub in self.subscriptions:
                    self._mqtt_subscribe(sub, self.subscriptions[sub]['qos'])
                self.is_connected = True
            if self.on_connect:
                self.on_connect(client, userdata, flags, rc)
        else:
            self._log.error('MQTT connection result code {}'.format(rc))
    
    def _mqtt_subscribe(self, topic: str, qos: int = 0):
        self._log.debug('{} subscribing to {}'.format(self._client_id, topic))
        (result, mid) = self._mqtt.subscribe(topic=topic, qos=2)
        if result == MQTT_ERR_SUCCESS:
            self._subscriptions[topic]['mid'] = mid
        else:
            self._log.error('MQTT Error {} subscribing to {}'.format(
                result, topic))

    def _mqtt_unsubscribe(self, topic: str):
        self._log.debug('{} unsubscribing to {}'.format(self._client_id, topic))
        (result, mid) = self._mqtt.unsubscribe(topic)
        if result != MQTT_ERR_SUCCESS:
            self._log.error('MQTT Error {} unsubscribing to {}'.format(
                result, topic))

    def subscription_add(self, topic: str, qos: int = 0) -> None:
        """Adds a subscription.
        
        Subscriptions property is updated with qos and message id.

        Args:
            topic (str): The MQTT topic to subscribe to
            qos (int): The MQTT qos 0..2

        """
        self._log.debug('Adding subscription {} qos={}'.format(topic, qos))
        self._subscriptions[topic] = {'qos': qos, 'mid': 0}
        if self.is_connected:
            self._mqtt_subscribe(topic, qos)
        else:
            self._log.warning('MQTT not connected will subscribe later')

    def subscription_del(self, topic: str) -> None:
        """Removes a subscription.
        
        Args:
            topic (str): The MQTT topic to unsubscribe

        """
        self._log.debug('Removing subscription {}'.format(topic))
        if topic in self._subscriptions:
            del self._subscriptions[topic]
        if self.is_connected:
            self._mqtt_unsubscribe(topic)

    def _mqtt_on_disconnect(self, client, userdata, rc):
        if self.on_disconnect:
            self.on_disconnect(client, userdata, rc)
        if userdata != 'terminate':
            self._log.warning('MQTT broker disconnected: result code {} ({})'
                .format(rc, get_mqtt_result(rc)))
            self._mqtt.loop_stop()
            # get new unique ID to avoid bouncing connection
            self.client_id = self.client_id
            self.is_connected = False
            #TODO: delay before retrying
            self._connect()

    def _mqtt_on_subscribe(self, client, userdata, mid, granted_qos):
        self._log.debug('MQTT subscription message id: {}'.format(mid))
        for sub in self.subscriptions:
            if mid != self.subscriptions[sub]['mid']:
                self._log.error('Subscription failed message id={} expected {}'
                    .format(mid, self.subscriptions[sub]['mid']))
            else:
                self._log.info('Subscription to {} successful'.format(sub))

    def _mqtt_on_message(self, client, userdata, message):
        payload = message.payload.decode()
        try:
            payload = json_loadstr(payload)
        except JSONDecodeError as e:
            self._log.debug('MQTT message payload non-JSON ({})'.format(e))
        self._log.debug('MQTT received {} message: {}'.format(
            message.topic, payload))
        self.on_message(message.topic, payload)

    def publish(self, topic: str, message: str, qos: int = 2):
        """Publishes a message to a MQTT topic.
        
        Args:
            topic (str): The MQTT topic
            message (str): The message to publish
            qos (int): The MQTT qos 0..2

        Raises:
            MqttError: if publishing fails

        """
        if not isinstance(message, str):
            message = json_dumpstr(message)
        self._log.info('MQTT publishing: {}: {}'.format(topic, message))
        (rc, mid) = self._mqtt.publish(topic=topic, payload=message, qos=qos)
        del mid
        if rc != MQTT_ERR_SUCCESS:
            self._log.error('Publishing error {}'.format(rc))
            raise MqttError('Publishing error {}'.format(rc))
