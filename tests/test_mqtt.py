
from logging import DEBUG
import os
from time import sleep

from fieldedge_utilities import logger, mqtt

TEST_TOPIC = 'fieldedge/test'
TEST_PAYLOAD = 'payload'
message_received = ''


def on_message(topic, payload):
    global message_received
    message_received = f'{topic}: {payload}'


def test_basic_pubsub(capsys):
    global message_received
    os.environ['MQTT_HOST'] = 'test.mosquitto.org'
    log = logger.get_wrapping_logger(log_level=DEBUG)
    mqttc = mqtt.MqttClient(client_id='test_client',
                            on_message=on_message,
                            subscribe_default=TEST_TOPIC + '/#',
                            logger=log)
    captured = capsys.readouterr()
    assert isinstance(mqttc, mqtt.MqttClient)
    while not mqttc.is_connected:
        sleep(0.5)
    captured = capsys.readouterr()
    mqttc.publish(TEST_TOPIC, TEST_PAYLOAD)
    captured = capsys.readouterr()
    while not message_received:
        sleep(0.5)
    captured = capsys.readouterr()
    assert message_received == f'{TEST_TOPIC}: {TEST_PAYLOAD}'


def test_no_connection(capsys):
    os.environ['MQTT_HOST'] = '127.0.0.1'
    connect_retry_interval = 1
    mqttc = mqtt.MqttClient(client_id='test_client',
                            on_message=on_message,
                            subscribe_default=TEST_TOPIC + '/#',
                            connect_retry_interval=connect_retry_interval)
    sleep(connect_retry_interval)
    captured = capsys.readouterr()
    assert f'retrying in {connect_retry_interval}' in captured.err
