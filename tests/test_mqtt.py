
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
    TEST_SERVERS = [
        'test.mosquitto.org',
        'broker.hivemq.com',
    ]
    log = logger.get_wrapping_logger(log_level=DEBUG)
    for test_server in TEST_SERVERS:
        try:
            os.environ['MQTT_HOST'] = test_server
            mqttc = mqtt.MqttClient(client_id='test_client',
                                    on_message=on_message,
                                    subscribe_default=TEST_TOPIC + '/#',
                                    logger=log,
                                    connect_retry_interval=0)
            break
        except mqtt.MqttError as err:
            assert 'timed out' in err.args[0]
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
