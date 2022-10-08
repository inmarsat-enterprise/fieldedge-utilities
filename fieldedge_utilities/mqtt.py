"""MQTT client for local broker inter-service communications.

This MQTT client sets up automatic connection and reconnection intended mainly
for use with a local broker on an edge device e.g. Raspberry Pi.

Reads broker configuration from a local `.env` file or environment variables:

* `MQTT_HOST` the IP address or hostname or container of the broker
* `MQTT_USER` the authentication username for the broker
* `MQTT_PASS` the authentication password for the broker

Typically the `fieldedge-broker` will be a **Mosquitto** service running locally
in a **Docker** container listening on port 1883 for authenticated connections.

"""
import json
import logging
import os
from atexit import register as on_exit
from enum import IntEnum
from socket import timeout  # : for Python < 3.10 compatibility vs TimeoutError
from threading import enumerate as enumerate_threads
from time import sleep, time
from typing import Callable

from dotenv import load_dotenv
from paho.mqtt.client import Client as PahoClient
from paho.mqtt.client import MQTTMessage as PahoMessage

from .class_properties import json_compatible
from .logger import verbose_logging

MQTT_HOST = os.getenv('MQTT_HOST', 'fieldedge-broker')
MQTT_USER = os.getenv('MQTT_USER')
MQTT_PASS = os.getenv('MQTT_PASS')

_log = logging.getLogger(__name__)

load_dotenv()


class MqttResultCode(IntEnum):
    """Eclipse Paho MQTT Error Codes."""
    SUCCESS = 0
    ERR_INCORRECT_PROTOCOL = 1
    ERR_INVALID_CLIENT_ID = 2
    ERR_SERVER_UNAVAILABLE = 3
    ERR_BAD_USERNAME_OR_PASSWORD = 4
    ERR_UNAUTHORIZED = 5
    ERR_CONNECTION_LOST = 6
    ERR_TIMEOUT_LENGTH = 7
    ERR_TIMEOUT_PAYLOAD = 8
    ERR_TIMEOUT_CONNACK = 9
    ERR_TIMEOUT_SUBACK = 10
    ERR_TIMEOUT_UNSUBACK = 11
    ERR_TIMEOUT_PINGRESP = 12
    ERR_MALFORMED_LENGTH = 13
    ERR_COMMUNICATION_PORT = 14
    ERR_ADDRESS_PARSING = 15
    ERR_MALFORMED_PACKET = 16
    ERR_SUBSCRIPTION_FAILURE = 17
    ERR_PAYLOAD_DECODE_FAILURE = 18
    ERR_COMPILE_DECODER = 19
    ERR_UNSUPPORTED_PACKET_TYPE = 20


def _get_mqtt_result(rc: int) -> str:
    try:
        return MqttResultCode(rc).name
    except:
        return 'UNKNOWN'


class MqttError(Exception):
    """A MQTT-specific error."""


class MqttClient:
    """A customized MQTT client.

    Attributes:
        client_id (str): A unique client_id.
        subscriptions (dict): A dictionary of subscriptions with qos and
            message ID properties
        on_message (callable): The callback when subscribed messages are
            received as `topic`(str), `message`(dict|str).
        is_connected (bool): Status of the connection to the broker.
        auto_connect (bool): Automatically attempts to connect when created
            or reconnect after disconnection.
        connect_retry_interval (int): Seconds between broker reconnect attempts.

    """
    def __init__(self,
                 client_id: str = __name__,
                 on_message: callable = None,
                 subscribe_default: 'str|list[str]' = None,
                 auto_connect: bool = True,
                 connect_retry_interval: int = 5,
                 **kwargs,
                 ):
        """Initializes a managed MQTT client.
        
        Args:
            client_id (str): The client ID (default imports module `__name__`)
            on_message (callable): The callback when subscribed messages are
                received as `topic`(str), `message`(dict|str).
            subscribe_default (str|list[str]): The default subscription(s)
                established on re/connection.
            connect_retry_interval (int): Seconds between broker reconnect
                attempts if auto_connect is `True`.
            auto_connect (bool): Automatically attempts to connect when created
                or reconnect after disconnection.
            **kwargs: includes advanced feature overrides such as:
            
            * `client_uid` defaults to True, appends a timestamp to the
            client_id to avoid being rejected by the host.
            * `bind_address` to bind to a specific IP
            * `on_connect`, `on_disconnect`, `on_log` callbacks
            * `host`, `port` (default 1883) and `keepalive` (default 60)
            * `username` and `password`
            * `ca_certs`, `certfile`, `keyfile`
            * `qos` (default = 0)

        Raises:
            `MqttError` if the client_id is not valid.

        """
        self._host = kwargs.get('host', MQTT_HOST)
        self._username = kwargs.get('username', MQTT_USER)
        self._password = kwargs.get('password', MQTT_PASS)
        self._port = kwargs.get('port', 1883)
        self._keepalive = kwargs.get('keepalive', 60)
        self._bind_address = kwargs.get('bind_address', '')
        self._ca_certs = kwargs.get('ca_certs', None)
        self._certfile = kwargs.get('certfile', None)
        self._keyfile = kwargs.get('keyfile', None)
        if not isinstance(client_id, str) or client_id == '':
            _log.error('Invalid client_id')
            raise MqttError('Invalid client_id')
        if not callable(on_message):
            _log.warning('No on_message specified')
        on_exit(self._cleanup)
        self.on_message = on_message
        self.on_connect = kwargs.get('on_connect', None)
        self.on_disconnect = kwargs.get('on_disconnect', None)
        self._qos = kwargs.get('qos', 0)
        self._thread_name: str = kwargs.get('thread_name', None)
        self._client_base_id = client_id
        self._client_id = None
        self._client_uid = kwargs.get('client_uid', True)
        if self._host.endswith('azure-devices.net'):
            _log.debug(f'Assuming {client_id} is the Azure IoT Device ID')
            self._client_uid = False
        self.client_id = client_id
        self._clean_session = kwargs.get('clean_session', True)
        self._mqtt = PahoClient(clean_session=self._clean_session)
        self.is_connected = False
        self._subscriptions = {}
        self.connect_retry_interval = connect_retry_interval
        self.auto_connect = auto_connect
        self._failed_connect_attempts = 0
        if subscribe_default:
            if not isinstance(subscribe_default, list):
                subscribe_default = [subscribe_default]
            for sub in subscribe_default:
                self.subscribe(sub, self._qos)
        if self.auto_connect:
            self.connect()
    
    @property
    def client_id(self):
        return self._client_id
    
    @client_id.setter
    def client_id(self, id: str):
        if not self._client_uid:
            self._client_id = id
        else:
            if id != self._client_base_id:
                if verbose_logging('mqtt'):
                    _log.debug(f'Updating client_id {id} with new timestamp')
                id = self._client_base_id
            self._client_id = f'{id}_{int(time())}'

    @property
    def subscriptions(self) -> dict:
        """The dictionary of subscriptions.
        
        Use subscribe or unsubscribe to change the dict.

        'topic' : { 'qos': (int), 'mid': (int) }

        """
        return self._subscriptions

    @property
    def failed_connection_attempts(self) -> int:
        return self._failed_connect_attempts

    @property
    def on_log(self) -> Callable:
        return self._mqtt.on_log

    @on_log.setter
    def on_log(self, callback: Callable):
        if not isinstance(callback, Callable):
            raise ValueError('Callback must be a function')
        self._mqtt.on_log = callback

    @property
    def socket_timeout(self) -> int:
        read_timeout = int(self._mqtt._sockpairR.gettimeout())
        write_timeout = int(self._mqtt._sockpairW.gettimeout())
        if read_timeout != write_timeout:
            _log.warning(f'Read timeout ({read_timeout})'
                         f' != Write timeout ({write_timeout})')
        return write_timeout

    @socket_timeout.setter
    def socket_timeout(self, value: int):
        if not (0 < value <= 120):
            raise ValueError('Socket timeout must be 1..120 seconds')
        self._mqtt._sockpairR.settimeout(float(value))
        self._mqtt._sockpairW.settimeout(float(value))

    def _cleanup(self, *args):
        # TODO: logging raises an error since the log file was closed
        # if _vlog():
        #     for arg in args:
        #         _log.debug(f'mqtt cleanup called with arg = {arg}')
        #     _log.debug('Terminating MQTT connection')
        self._mqtt.user_data_set('terminate')
        self._mqtt.loop_stop()
        self._mqtt.disconnect()
    
    def connect(self):
        """Attempts to establish a connection to the broker and re-subscribe."""
        try:
            if _vlog():
                _log.debug(f'Attempting MQTT broker connection to {self._host}'
                           f' as {self.client_id}')
            self._mqtt.reinitialise(client_id=self.client_id)
            self._mqtt.user_data_set(None)
            self._mqtt.on_connect = self._mqtt_on_connect
            self._mqtt.on_disconnect = self._mqtt_on_disconnect
            self._mqtt.on_subscribe = self._mqtt_on_subscribe
            self._mqtt.on_message = self._mqtt_on_message
            if self._username and self._password:
                self._mqtt.username_pw_set(username=self._username,
                                           password=self._password)
            if self._port == 8883:
                self._mqtt.tls_set(ca_certs=self._ca_certs,
                                   certfile=self._certfile,
                                   keyfile=self._keyfile)
                # self._mqtt.tls_insecure_set(False)
            self._mqtt.connect(host=self._host,
                               port=self._port,
                               keepalive=self._keepalive,
                               bind_address=self._bind_address)
            threads_before = enumerate_threads()
            self._mqtt.loop_start()
            threads_after = enumerate_threads()
            basename = 'MqttThread'
            if self._thread_name:
                basename += f'-{self._thread_name}'
            name = basename
            number = 1
            for thread in threads_after:
                if thread in threads_before:
                    if thread.name.startswith(basename):
                        number += 1
                        name = f'{basename}-{number}'
                    continue
                if _vlog():
                    _log.debug(f'Naming new MQTT client thread: {name}')
                thread.name = name
                break
        except (ConnectionError, timeout, TimeoutError) as err:
            self._failed_connect_attempts += 1
            if self.connect_retry_interval > 0:
                _log.warning(f'Unable to connect to {self._host} ({err})'
                             f' - retrying in {self.connect_retry_interval} s')
                sleep(self.connect_retry_interval)
                self.connect()
            else:
                _log.warning(f'Failed to connect to {self._host}'
                             ' but retry disabled - call connect() to retry')

    def disconnect(self):
        """Attempts to disconnect from the broker."""
        self._mqtt.user_data_set('terminate')
        self._mqtt.loop_stop()
        self._mqtt.disconnect()

    def _mqtt_on_connect(self,
                         client: PahoClient,
                         userdata: any,
                         flags: dict,
                         rc: int):
        """Internal callback re-subscribes on (re)connection."""
        self._failed_connect_attempts = 0
        if rc == MqttResultCode.SUCCESS:
            if _vlog():
                _log.debug(f'Established MQTT connection to {self._host}')
            if not self.is_connected:
                for sub in self.subscriptions:
                    self._mqtt_subscribe(sub, self.subscriptions[sub]['qos'])
                self.is_connected = True
            if self.on_connect:
                self.on_connect(client, userdata, flags, rc)
        else:
            _log.error(f'MQTT broker connection result code: {rc}'
                       f' ({_get_mqtt_result(rc)})')
    
    def _mqtt_subscribe(self, topic: str, qos: int = 0):
        """Internal subscription handler assigns id indicating *subscribed*."""
        (result, mid) = self._mqtt.subscribe(topic=topic, qos=qos)
        if _vlog():
            _log.debug(f'{self.client_id} subscribing to {topic}'
                       f' (qos={qos}, mid={mid})')
        if result == MqttResultCode.SUCCESS:
            if mid == 0:
                _log.warning(f'Received mid={mid} expected > 0')
            self._subscriptions[topic]['mid'] = mid
        else:
            _log.error(f'MQTT Error {result} subscribing to {topic}')

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """Adds a subscription.
        
        Subscriptions property is updated with qos and message id.
        Message id `mid` is 0 when not actively subscribed.

        Args:
            topic (str): The MQTT topic to subscribe to
            qos (int): The MQTT qos 0..2

        """
        if _vlog():
            _log.debug(f'Adding subscription {topic} (qos={qos})')
        self._subscriptions[topic] = {'qos': qos, 'mid': 0}
        if self.is_connected:
            self._mqtt_subscribe(topic, qos)
        else:
            _log.warning(f'MQTT not connected...subscribing to {topic} later')

    def _mqtt_on_subscribe(self,
                           client: PahoClient,
                           userdata: any,
                           mid: int,
                           granted_qos: 'list[int]'):
        match = ''
        for sub in self.subscriptions:
            if mid == self.subscriptions[sub]['mid']:
                _log.info(f'Subscription to {sub} successful'
                          f' (mid={mid}, granted_qos={granted_qos})')
                match = sub
                break
        if not match:
            _log.error(f'Unable to match mid={mid} to pending subscription')

    def is_subscribed(self, topic: str):
        if (topic in self.subscriptions and
            self.subscriptions[topic]['mid'] > 0):
            return True
        return False

    def _mqtt_on_message(self,
                         client: PahoClient,
                         userdata: any,
                         message: PahoMessage):
        """Internal callback on message simplifies passback to topic/payload."""
        payload = message.payload.decode()
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as e:
            if _vlog():
                _log.debug(f'MQTT message payload non-JSON ({e})')
        if _vlog():
            _log.debug(f'MQTT received message "{payload}"'
                       f' on topic "{message.topic}" with QoS {message.qos}')
            if userdata:
                _log.debug(f'MQTT client userdata: {userdata}')
        self.on_message(message.topic, payload)

    def _mqtt_unsubscribe(self, topic: str):
        if _vlog():
            _log.debug(f'{self.client_id} unsubscribing to {topic}')
        (result, mid) = self._mqtt.unsubscribe(topic)
        if result != MqttResultCode.SUCCESS:
            _log.error(f'MQTT Error {result} unsubscribing to {topic}'
                       f' (mid {mid})')

    def unsubscribe(self, topic: str) -> None:
        """Removes a subscription.
        
        Args:
            topic (str): The MQTT topic to unsubscribe

        """
        if _vlog():
            _log.debug(f'Removing subscription {topic}')
        if topic in self._subscriptions:
            del self._subscriptions[topic]
        if self.is_connected:
            self._mqtt_unsubscribe(topic)

    def _mqtt_on_disconnect(self, client: PahoClient, userdata: any, rc: int):
        """Internal callback when disconnected, clears subscription status."""
        if self.on_disconnect:
            self.on_disconnect(client, userdata, rc)
        if userdata != 'terminate':
            _log.warning('MQTT broker disconnected'
                         f' - result code {rc} ({_get_mqtt_result(rc)})')
            self._mqtt.loop_stop()
            for sub in self.subscriptions:
                self._subscriptions[sub]['mid'] = 0
            # get new unique ID to avoid bouncing connection
            self.is_connected = False
            if self.auto_connect:
                if self._client_uid:
                    self.client_id = self.client_id
                self.connect()

    def publish(self,
                topic: str,
                message: 'str|dict|None',
                qos: int = 1,
                camel_keys: bool = False,
                ) -> bool:
        """Publishes a message to a MQTT topic.

        If the message is a dictionary, 
        
        Args:
            topic: The MQTT topic
            message: The message to publish
            qos: The MQTT Quality of Service (0, 1 or 2)
            camel_keys: Ensures all embedded dictionary keys are JSON style
                (camelCase)

        Returns:
            True if successful, else False.

        """
        if message and not isinstance(message, (str, dict)):
            raise ValueError(f'Invalid message {message}')
        if self._host.endswith('.azure-devices.net'):
            device_to_cloud = f'devices/{self.client_id}/messages/events/'
            if device_to_cloud not in topic:
                _log.warning('Applying Azure device-to-cloud topic prefix')
                topic = f'{device_to_cloud}{topic}'
        if isinstance(message, dict):
            message = json.dumps(json_compatible(message, camel_keys),
                                 skipkeys=True)
        if not isinstance(qos, int) or qos not in range(0, 3):
            _log.warning(f'Invalid MQTT QoS {qos} - using QoS 1')
            qos = 1
        (rc, mid) = self._mqtt.publish(topic=topic, payload=message, qos=qos)
        if _vlog():
            _log.debug(f'MQTT published (mid={mid}) {topic} {message}')
        if rc != MqttResultCode.SUCCESS:
            errmsg = f'Publishing error {rc} ({_get_mqtt_result(rc)})'
            _log.error(errmsg)
            return False
        return True


def _vlog() -> bool:
    return verbose_logging('mqtt')
