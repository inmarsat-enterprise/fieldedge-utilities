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
import threading
from atexit import register as on_exit
from enum import IntEnum
from socket import gaierror, timeout  # : Python<3.10 vs TimeoutError
from time import sleep, time
from typing import Any, Callable

from dotenv import load_dotenv
from paho.mqtt.client import Client as PahoClient
from paho.mqtt.client import MQTTMessage as PahoMessage

from fieldedge_utilities.logger import verbose_logging
from fieldedge_utilities.properties import json_compatible

MQTT_HOST = os.getenv('MQTT_HOST', 'fieldedge-broker')
MQTT_USER = os.getenv('MQTT_USER')
MQTT_PASS = os.getenv('MQTT_PASS')

__all__ = ['MqttResultCode', 'MqttError', 'MqttClient']

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


def _get_mqtt_result(result_code: int) -> str:
    try:
        return MqttResultCode(result_code).name
    except ValueError:
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
                 **kwargs) -> None:
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
        
        Keyword Args: 
            client_uid (str): defaults to True, appends a timestamp to the
                client_id to avoid being rejected by the host.
            bind_address (str): to bind to a specific IP (broken in Paho Python)
            on_connect (Callable): optional callback when connecting to broker
            on_disconnect (Callable): optional callback when disconnecting from
                broker
            on_log (Callable): optional callback for client logging
            host (str): override hostname
            port (int): defaults to 1883
            keepalive (int): defaults to 60 seconds
            username (str): override username
            password (str): override password
            ca_certs (str): path to the CA certificate
            certfile (str): path to the PEM certificate for the client
            keyfile (str): path to the PEM certificate for the client key
            qos (int): MQTT QoS defaults to 0 (send at most once)
            thread_name (str): Optional tag to identify thread in logging.

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
        self.on_connect: 'Callable|None' = kwargs.get('on_connect', None)
        self.on_disconnect: 'Callable|None' = kwargs.get('on_disconnect', None)
        self._qos = kwargs.get('qos', 0)
        self._thread_name: str = kwargs.get('thread_name', None)
        self._client_base_id = client_id
        self._client_id = None
        self._client_uid = kwargs.get('client_uid', True)
        if self._host.endswith('azure-devices.net'):
            _log.debug('Assuming %s is the Azure IoT Device ID', client_id)
            self._client_uid = False
        self.client_id = client_id
        self._clean_session = kwargs.get('clean_session', True)
        self._mqtt = PahoClient(clean_session=self._clean_session,
                                reconnect_on_failure=False)
        self._connect_timeout = 5
        self.connect_timeout = int(kwargs.get('connect_timeout', 5))
        self._subscriptions = {}
        self._connect_retry_interval: int = 0
        self.connect_retry_interval = connect_retry_interval
        self.auto_connect: bool = auto_connect
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
    def client_id(self, uid: str):
        if not self._client_uid:
            self._client_id = uid
        else:
            if uid != self._client_base_id:
                if verbose_logging('mqtt'):
                    _log.debug('Updating client_id %s with new timestamp', uid)
                uid = self._client_base_id
            self._client_id = f'{uid}_{int(time())}'

    @property
    def is_connected(self) -> bool:
        return self._mqtt.is_connected()

    @property
    def subscriptions(self) -> 'dict[str, dict]':
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
    def connect_timeout(self) -> int:
        return int(self._mqtt._connect_timeout)

    @connect_timeout.setter
    def connect_timeout(self, value: 'int|float'):
        if (not isinstance(value, (int, float)) or
            not 0 < value <= 120):
            # invalid value
            raise ValueError('Connect timeout must be 1..120 seconds')
        self._connect_timeout = value
        self._mqtt._connect_timeout = float(value)

    @property
    def connect_retry_interval(self) -> int:
        return self._connect_retry_interval

    @connect_retry_interval.setter
    def connect_retry_interval(self, value: int):
        if not isinstance(value, int) or value < 0:
            raise ValueError('Retry interval must be integer 0 or higher')
        self._connect_retry_interval = value

    def _cleanup(self, *args):
        # TODO: logging raises an error since the log file was closed
        if _vlog():
            try:
                for arg in args:
                    _log.debug('mqtt cleanup called with arg = %s', arg)
                _log.debug('Terminating MQTT connection')
            except:
                pass
        self._mqtt.user_data_set('terminate')
        self._mqtt.loop_stop()
        self._mqtt.disconnect()

    def _unique_thread_name(self, before_names: 'list[str]') -> str:
        basename = 'MqttThread'
        if self._thread_name:
            basename += f'-{self._thread_name}'
        new_name = basename
        number = 1
        for name in before_names:
            if name.startswith(basename):
                number += 1
                new_name = f'{basename}-{number}'
        return new_name

    def connect(self):
        """Attempts to establish a connection to the broker and re-subscribe."""
        try:
            if _vlog():
                _log.debug('Attempting MQTT broker connection to %s as %s',
                           self._host, self.client_id)
            self._mqtt.reinitialise(client_id=self.client_id)
            self.connect_timeout = self._connect_timeout   #: just in case
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
            threads_before = threading.enumerate()
            self._mqtt.loop_start()
            threads_after = threading.enumerate()
            new_thread = list(set(threads_after) - set(threads_before))[0]
            before_names = [t.name for t in threads_before]
            new_thread.name = self._unique_thread_name(before_names)
            _log.debug('New MQTT client thread: %s', new_thread.name)
            return
        except (ConnectionError, TimeoutError, gaierror, timeout) as exc:
            self._mqtt.loop_stop()
            self._failed_connect_attempts += 1
            _log.error('Failed attempt %d to connect to %s (%s)',
                       self._failed_connect_attempts, self._host, exc)
            if not self.auto_connect or self.connect_retry_interval <= 0:
                raise ConnectionError(str(exc)) from exc
            _log.debug('Retrying in %d seconds', self.connect_retry_interval)
            sleep(self.connect_retry_interval)
            self.connect()

    def disconnect(self):
        """Attempts to disconnect from the broker."""
        self._mqtt.user_data_set('terminate')
        self._mqtt.loop_stop()
        self._mqtt.disconnect()

    def _mqtt_on_connect(self,
                         client: PahoClient,
                         userdata: Any,
                         flags: dict,
                         result_code: int):
        """Internal callback re-subscribes on (re)connection."""
        self._failed_connect_attempts = 0
        if result_code == MqttResultCode.SUCCESS:
            if _vlog():
                _log.debug('Established MQTT connection to %s', self._host)
            for sub, meta in self.subscriptions.items():
                self._mqtt_subscribe(sub, qos=meta.get('qos', None))
            if callable(self.on_connect):
                self.on_connect(client, userdata, flags, result_code)
        else:
            _log.error('MQTT broker connection result code: %d (%s)',
                       result_code, _get_mqtt_result(result_code))

    def _mqtt_subscribe(self, topic: str, qos: int = 0):
        """Internal subscription handler assigns id indicating *subscribed*."""
        (result, mid) = self._mqtt.subscribe(topic=topic, qos=qos)
        if _vlog():
            _log.debug('%s subscribing to %s (qos=%d, mid=%d)',
                       self.client_id, topic, qos, mid)
        if result == MqttResultCode.SUCCESS:
            if mid == 0:
                _log.warning('Received mid=%d expected > 0', mid)
            self._subscriptions[topic]['mid'] = mid
        else:
            _log.error('MQTT Error %s subscribing to %s', result, topic)

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """Adds a subscription.
        
        Subscriptions property is updated with qos and message id.
        Message id `mid` is 0 when not actively subscribed.

        Args:
            topic (str): The MQTT topic to subscribe to
            qos (int): The MQTT qos 0..2

        """
        if _vlog():
            _log.debug('Adding subscription %s (qos=%d)', topic, qos)
        self._subscriptions[topic] = {'qos': qos, 'mid': 0}
        if self.is_connected:
            self._mqtt_subscribe(topic, qos)
        else:
            _log.debug('MQTT not connected...subscribing to %s later', topic)

    def _mqtt_on_subscribe(self,
                           client: PahoClient,
                           userdata: Any,
                           mid: int,
                           granted_qos: 'tuple[int]'):
        match = ''
        for topic, detail in self.subscriptions.items():
            if mid == detail.get('mid', None):
                _log.info('Subscribed to %s (mid=%d, granted_qos=%s)',
                          topic, mid, granted_qos)
                match = topic
                break
        if not match:
            _log.error('Unable to match mid=%d to pending subscription', mid)

    def is_subscribed(self, topic: str) -> bool:
        """Returns True if the specified topic is an active subscription."""
        if (topic in self.subscriptions and
            self.subscriptions[topic]['mid'] > 0):
            return True
        return False

    def _mqtt_on_message(self,
                         client: PahoClient,
                         userdata: Any,
                         message: PahoMessage):
        """Internal callback on message simplifies passback to topic/payload."""
        payload = message.payload.decode()
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            if _vlog():
                _log.debug('MQTT message payload non-JSON (%s)', exc)
        if _vlog():
            _log.debug('MQTT received message "%s" on topic "%s" with QoS %d',
                       payload, message.topic, message.qos)
            if userdata:
                _log.debug('MQTT client userdata: %s', userdata)
        self.on_message(message.topic, payload)

    def _mqtt_unsubscribe(self, topic: str):
        if _vlog():
            _log.debug('%s unsubscribing to %s', self.client_id, topic)
        (result, mid) = self._mqtt.unsubscribe(topic)
        if result != MqttResultCode.SUCCESS:
            _log.error('MQTT Error %s unsubscribing from %s (mid=%d)',
                       result, topic, mid)

    def unsubscribe(self, topic: str) -> None:
        """Removes a subscription.
        
        Args:
            topic (str): The MQTT topic to unsubscribe

        """
        if _vlog():
            _log.debug('Removing subscription %s', topic)
        if topic in self._subscriptions:
            del self._subscriptions[topic]
        if self.is_connected:
            self._mqtt_unsubscribe(topic)

    def _mqtt_on_disconnect(self,
                            client: PahoClient,
                            userdata: Any,
                            result_code: int):
        """Internal callback when disconnected, clears subscription status."""
        if callable(self.on_disconnect):
            self.on_disconnect(client, userdata, result_code)
        if userdata != 'terminate':
            _log.warning('MQTT broker disconnected - result code %d (%s)',
                         result_code, _get_mqtt_result(result_code))
            # reconnect handling is managed automatically by Paho library

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
            _log.warning('Invalid MQTT QoS %s - using QoS 1', qos)
            qos = 1
        (result_code, mid) = self._mqtt.publish(topic=topic,
                                                payload=message,
                                                qos=qos)
        if _vlog():
            _log.debug('MQTT published (mid=%d) %s: %s', mid, topic, message)
        if result_code != MqttResultCode.SUCCESS:
            _log.error('Publishing error %d (%s)',
                       result_code, _get_mqtt_result(result_code))
            return False
        return True


def _vlog() -> bool:
    return verbose_logging('mqtt')
