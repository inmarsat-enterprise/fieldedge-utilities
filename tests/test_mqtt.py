"""Unit tests for mqtt sub-package."""
import os
import logging
import time

import pytest
from fieldedge_utilities.mqtt import MqttClient, MqttError

TEST_TOPIC = 'fieldedge/test'
TEST_PAYLOAD = 'payload'
message_received = ''
_log = logging.getLogger(__name__)


@pytest.fixture
def client():
    TEST_SERVER = 'test.mosquitto.org'
    return MqttClient(client_id='test_client', host=TEST_SERVER)

    
def on_message(topic, payload):
    """Called during test of (subscribed) message received."""
    global message_received
    message_received = f'{topic}: {payload}'


def test_basic_pubsub(capsys):
    global message_received
    TEST_SERVERS = [
        'test.mosquitto.org',
        'broker.hivemq.com',
    ]
    connect_timeout = 6.0
    for test_server in TEST_SERVERS:
        try:
            mqttc = MqttClient(client_id='test_client',
                               host=test_server,
                               on_message=on_message,
                               subscribe_default=TEST_TOPIC + '/#',
                               connect_retry_interval=0,
                               connect_timeout=connect_timeout)
            break
        except MqttError as err:
            assert 'timed out' in err.args[0]
    assert mqttc._mqtt._connect_timeout == connect_timeout
    captured = capsys.readouterr()
    assert isinstance(mqttc, MqttClient)
    while not mqttc.is_connected:
        time.sleep(0.5)
    captured = capsys.readouterr()
    mqttc.publish(TEST_TOPIC, TEST_PAYLOAD)
    captured = capsys.readouterr()
    while not message_received:
        time.sleep(0.5)
    captured = capsys.readouterr()
    assert message_received == f'{TEST_TOPIC}: {TEST_PAYLOAD}'


connected = False

def on_connect(*args):
    global connected
    connected = True
    _log.info('Connected: %s', connected)
    

def on_disconnect(*args):
    global connected
    connected = False
    _log.info('Connected: %s', connected)
    

# *** Below tests are manual, may require tools or generation of parameters

def mtest_local_manual():
    """Requires running a local broker that is started and stopped manually."""
    global connected
    mqttc = MqttClient('test_client',
                       host='localhost',
                       auto_connect=True,
                       connect_retry_interval=5,
                       on_connect=on_connect,
                       on_disconnect=on_disconnect,)
    while not mqttc.is_connected:
        pass
    assert connected
    while mqttc.is_connected:
        pass
    assert not connected
    while not mqttc.is_connected:
        pass
    assert connected


def mtest_azure_sas(capsys):
    global message_received
    AZURE_IOT_HUB = os.getenv('AZURE_IOT_HUB')
    AZURE_ROOT_CA = os.getenv('AZURE_ROOT_CA')
    AZURE_DEVICE_ID = os.getenv('AZURE_DEVICE_ID')
    AZURE_SAS_TOKEN = os.getenv('AZURE_SAS_TOKEN')
    azure_username = (f'{AZURE_IOT_HUB}/{AZURE_DEVICE_ID}'
                      '/?api-version=2021-04-12')
    azure_base_topic = f'devices/{AZURE_DEVICE_ID}/messages/events'
    subscribe_default = f'{azure_base_topic}/#'
    mqttc = MqttClient(
        client_id=AZURE_DEVICE_ID,
        client_uid=False,
        on_message=on_message,
        subscribe_default=subscribe_default,
        connect_retry_interval=0,
        auto_connect=False,
        username=azure_username,
        password=AZURE_SAS_TOKEN,
        host=AZURE_IOT_HUB,
        port=8883,
        keepalive=120,
        ca_certs=AZURE_ROOT_CA,
    )
    mqttc.connect()
    attempts = 0
    while not mqttc.is_subscribed(subscribe_default) and attempts <= 5:
        attempts += 1
        time.sleep(0.5)
    assert mqttc.is_connected
    subtopic = f'{azure_base_topic}/telemetryReport'
    test_payload = '{"testProperty":"testValue"}'
    # Azure can't subscribe to generic topics
    pubres = mqttc.publish(subtopic, test_payload)
    assert pubres


def mtest_aws(capsys):
    # TODO: broken, disconnect RC=7 probably illegal subscription/publish topic
    AWS_ENDPOINT = os.getenv('AWS_ENDPOINT')
    AWS_ROOT_CA = os.getenv('AWS_ROOT_CA')
    AWS_DEVICE_CERT = os.getenv('AWS_DEVICE_CERT')
    AWS_DEVICE_KEY = os.getenv('AWS_DEVICE_KEY')
    mqttc = MqttClient(
        client_id='test_client',
        on_connect=on_message,
        subscribe_default=f'{TEST_TOPIC}/#',
        connect_retry_interval=0,
        auto_connect=False,
        host=AWS_ENDPOINT,
        port=8883,
        keepalive=120,
        ca_certs=AWS_ROOT_CA,
        certfile=AWS_DEVICE_CERT,
        keyfile=AWS_DEVICE_KEY,
    )
    mqttc.connect()
    # captured = capsys.readouterr()
    # assert mqttc.is_connected
    mqttc.publish(TEST_TOPIC, TEST_PAYLOAD)
    captured = capsys.readouterr()
    attempts = 0
    while not message_received and attempts <= 10:
        attempts += 1
        time.sleep(0.5)
    captured = capsys.readouterr()
    assert message_received == f'{TEST_TOPIC}: {TEST_PAYLOAD}'
