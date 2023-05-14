"""Unit tests for microservices sub-package.
"""
# import asyncio
import logging
import time
import unittest

import pytest

import fieldedge_utilities  # required for mocking
from fieldedge_utilities.microservice import *
from fieldedge_utilities.mqtt import MqttClient
from fieldedge_utilities.properties import get_class_properties, get_class_tag

logger = logging.getLogger()


class TestService(Microservice):
    """Basic subclass of abstract class for testing."""

    # __slots__ = ['slot_config', '_info_prop', '_config_prop']   # must expose all init properties

    TAG = 'test'   # a class constant

    def __init__(self, tag: str = None) -> None:
        super().__init__(tag=tag or self.TAG)
        self._info_prop: str = 'test'
        self._config_prop: int = 2
        # self.slot_config: str = 'slot_test'

    @property
    def info_prop(self) -> str:
        return self._info_prop

    @property
    def config_prop(self) -> int:
        return self._config_prop

    @config_prop.setter
    def config_prop(self, value: int):
        if not isinstance(value, int):
            raise ValueError('config_prop must be integer')
        self._config_prop = value

    # @property
    # async def async_info_prop(self) -> str:
    #     await asyncio.sleep(1)
    #     return self._info_prop

    def rollcall(self):
        return super().rollcall()

    def rollcall_respond(self, topic: str, message: dict):
        return super().rollcall_respond(topic, message)

    def on_isc_message(self, topic: str, message: dict) -> None:
        logger.info(f'Microservice received ISC message {topic}: {message}')

    def task_progress(self, **kwargs):
        logger.info(f'Task info: {kwargs}')

    def task_completed(self, **kwargs):
        logger.info(f'Task complete: {kwargs}')


class TestFeature(Feature):
    @property
    def test_prop(self) -> bool:
        return True

    def status(self) -> dict:
        return { 'test_prop': self.test_prop }

    def properties_list(self) -> 'list[str]':
        return ['test_prop']

    def on_isc_message(self, topic: str, message: dict) -> bool:
        logger.info(f'Feature received ISC {topic}: {message}')
        feature_relevant = message.get('feature', None)
        if feature_relevant:
            logger.info('Feature handled')
            return True
        return False


class TestProxy(MicroserviceProxy):
    def on_isc_message(self, topic: str, message: dict) -> bool:
        logger.info(f'Proxy received ISC {topic}: {message}')
        handled = super().on_isc_message(topic, message)
        if handled:
            return True
        proxy_relevant = message.get('proxy', None)
        if proxy_relevant:
            logger.info('Proxy handled')
            return True
        return False


@pytest.fixture
def test_service() -> TestService:
    return TestService()


@pytest.fixture
def test_complex() -> TestService:
    complex_ms = TestService(tag='complex')
    complex_ms.features['feature'] = TestFeature(
        task_queue=complex_ms._isc_queue,
        task_notify=complex_ms.task_progress,
        task_complete=complex_ms.task_completed,
        _custom_protected='test',
    )
    complex_ms.ms_proxies['proxy'] = TestProxy(
        tag='test',
        publish=complex_ms.notify,
        subscribe=complex_ms.isc_topic_subscribe,
        init_callback=complex_ms_init_callback,
        # cache_lifetime=2,
    )
    return complex_ms


def test_get_subclass_name(test_service: TestService):
    assert get_class_tag(TestService) == 'testservice'
    assert get_class_tag(test_service) == 'testservice'
    props_cls = get_class_properties(TestService)
    props_inst = get_class_properties(test_service)
    assert props_cls == props_inst


def test_microservice_subclass_creation(test_service: TestService):
    assert test_service.tag == TestService.TAG
    expected_config_props = ['log_level', 'config_prop']
    expected_info_props = ['tag', 'properties', 'properties_by_type',
                           'isc_properties', 'isc_properties_by_type',
                           'rollcall_properties', 'info_prop',]
    expected_props = expected_config_props + expected_info_props
    assert all(prop in test_service.properties for prop in expected_props)
    assert not any(prop not in expected_props
                   for prop in test_service.properties)
    assert all(prop in test_service.properties_by_type['config']
               for prop in expected_config_props)
    assert not any(prop not in expected_config_props
                   for prop in test_service.properties_by_type['config'])
    assert all(prop in test_service.properties_by_type['info']
               for prop in expected_info_props)
    assert not any(prop not in expected_info_props
                   for prop in test_service.properties_by_type['info'])
    expected_isc_config_props = ['logLevel', 'configProp']
    expected_isc_info_props = ['infoProp']
    expected_isc_props = expected_isc_config_props + expected_isc_info_props
    assert all(prop in test_service.isc_properties
               for prop in expected_isc_props)
    assert not any(prop not in expected_isc_props
                   for prop in test_service.isc_properties)
    isc_props = test_service.isc_properties_by_type
    assert all(prop in test_service.isc_properties_by_type['config']
               for prop in expected_isc_config_props)
    assert not any(prop not in expected_isc_config_props
                   for prop in test_service.isc_properties_by_type['config'])
    assert all(prop in test_service.isc_properties_by_type['info']
               for prop in expected_isc_info_props)
    assert not any(prop not in expected_isc_info_props
                   for prop in test_service.isc_properties_by_type['info'])
    assert test_service.log_level == (
        logging.getLevelName(logger.getEffectiveLevel()))


def test_ms_property_hide(test_service: TestService):
    test_prop = 'config_prop'
    expected_props = ['tag', 'log_level', 'properties', 'properties_by_type',
                      'isc_properties', 'isc_properties_by_type', test_prop]
    assert all(prop in test_service.properties for prop in expected_props)
    test_service.property_hide(test_prop)
    expected_props.remove(test_prop)
    assert not any(prop not in test_service.properties for prop in expected_props)
    test_service.property_unhide(test_prop)
    expected_props.append(test_prop)
    assert all(prop in test_service.properties for prop in expected_props)


def test_ms_isc_property_hide(test_service: TestService):
    test_isc_prop = 'infoProp'
    test_prop = 'info_prop'
    expected_isc_props = ['logLevel', 'configProp', test_isc_prop]
    assert all(prop in test_service.isc_properties for prop in expected_isc_props)
    test_service.isc_property_hide(test_isc_prop)
    expected_isc_props.remove(test_isc_prop)
    assert not any(prop not in test_service.isc_properties for prop in expected_isc_props)
    assert test_prop in test_service.properties
    test_service.isc_property_unhide(test_isc_prop)
    expected_isc_props.append(test_isc_prop)
    assert all(prop in test_service.isc_properties for prop in expected_isc_props)


def test_ms_isc_get_property(test_service: TestService):
    test_prop = 'info_prop'
    test_isc_prop = 'infoProp'
    assert test_service.isc_get_property(test_isc_prop) == getattr(test_service, test_prop)


# @pytest.mark.asyncio
# async def test_ms_isc_get_property_async(test_service: TestService):
#     test_prop = 'async_info_prop'
#     test_isc_prop = 'asyncInfoProp'
#     async_val = await getattr(test_service, test_prop)
#     assert test_service.isc_get_property(test_isc_prop) == async_val


def test_ms_isc_set_property(test_service: TestService):
    test_prop = 'config_prop'
    test_isc_prop = 'configProp'
    test_val = 10
    test_service.isc_set_property(test_isc_prop, test_val)
    assert test_service.isc_get_property(test_isc_prop) == test_val
    assert getattr(test_service, test_prop) == test_val


def test_ms_on_isc_message_self_rollcall(test_service: TestService, mocker):
    def mock_isc(message, **kwargs):
        topic = f'fieldedge/{TestService.TAG}'
        if 'subtopic' in kwargs:
            topic += f'/{kwargs["subtopic"]}'
        logger.info(f'Mocking ISC {topic}: {message}')
        if 'subtopic' in kwargs:
            if kwargs['subtopic'] == 'rollcall':
                test_service._on_isc_message(topic, message)
                assert True
            else:
                logger.warning('Unexpected chained response')
                assert False
    mocker.patch('fieldedge_utilities.microservice.Microservice.notify',
                 side_effect=mock_isc)
    test_service.rollcall()


def test_ms_on_isc_message_other_rollcall(test_service: TestService, mocker):
    def mock_isc(message, **kwargs):
        topic = f'fieldedge/{TestService.TAG}/{kwargs.get("subtopic", None)}'
        logger.info(f'Mocking ISC {topic}: {message}')
        assert 'subtopic' in kwargs and kwargs['subtopic'] == 'rollcall/response'
        assert 'uid' in message and message['uid'] == 'requestor-uuid'
        assert 'infoProp' in message and message['infoProp'] == 'test'
    mocker.patch('fieldedge_utilities.microservice.Microservice.notify',
                 side_effect=mock_isc)
    test_service.rollcall_property_add('info_prop')
    topic = 'fieldedge/otherservice/rollcall'
    message = { 'uid': 'requestor-uuid' }
    logger.info(f'Mocking ISC {topic}: {message}')
    test_service._on_isc_message(topic, message)


def test_ms_cached_property(test_service: TestService, mocker):
    TEST_PROP = 'sub_prop'
    ref_time = time.time()
    cache_lifetime = 1
    test_service._property_cache.cache('something', TEST_PROP, cache_lifetime)
    while test_service._property_cache.get_cached(TEST_PROP):
        time.sleep(0.5)
    elapsed = time.time() - ref_time
    logger.info(f'Time elapsed: {elapsed}')
    assert elapsed >= cache_lifetime
    assert not test_service._property_cache.get_cached(TEST_PROP)


class StubMqtt(MqttClient):
    def __init__(self, auto_connect=False) -> None:
        pass
    
    def subscribe(self, topic, qos):
        return True
    
    def unsubscribe(self, topic):
        return True


proxy_call_one_count = 0
proxy_call_two_count = 0


def proxy_call_one(topic: str, message: dict):
    global proxy_call_one_count
    proxy_call_one_count += 1


def proxy_call_two(topic: str, message: dict):
    global proxy_call_two_count
    proxy_call_two_count += 1


def test_sub_proxy():
    global proxy_call_one_count
    global proxy_call_two_count
    topic = 'fieldedge/test/event/test'
    message = {}
    other_topic = 'fieldedge/other/info/stuff'
    other_message = {}
    mqttc = StubMqtt()
    proxy = SubscriptionProxy(mqttc)
    proxy.proxy_add('test_module', topic, callback=proxy_call_one)
    proxy.proxy_add('other_module', topic, callback=proxy_call_two)

    def main_on_message(topic, message):
        proxy.proxy_pub(topic, message)

    main_on_message(topic, message)
    assert proxy_call_one_count == 1
    assert proxy_call_two_count == 1
    main_on_message(other_topic, other_message)
    assert proxy_call_one_count == 1
    assert proxy_call_two_count == 1
    proxy.proxy_del('test_module', topic)
    main_on_message(topic, message)
    assert proxy_call_one_count == 1
    assert proxy_call_two_count == 2


init_success = None


def complex_ms_init_callback(success: bool, tag: str):
    global init_success
    init_success = success
    logger.info(f'Initialization of {tag} success = {success}')


def test_complex_ms(test_complex: TestService, test_service: TestService):
    """Requires live connection to a MQTT broker."""
    global init_success
    assert isinstance(test_complex.features, dict) and test_complex.features
    assert 'feature' in test_complex.features
    feature = test_complex.features.get('feature')
    logger.info('Feature tag: %s', feature.tag)
    assert hasattr(feature, '_custom_protected')
    complex_props = test_complex.properties
    assert 'feature_test_prop' in complex_props
    complex_isc_props = test_complex.isc_properties
    assert 'featureTestProp' in complex_isc_props
    test_service._mqttc_local.connect()
    attempts = 0
    while not test_service._mqttc_local.is_connected and attempts < 3:
        attempts += 1
        time.sleep(0.5)
    assert test_service._mqttc_local.is_connected, 'Failed to connect to MQTT'
    test_complex._mqttc_local.connect()
    while not test_complex._mqttc_local.is_connected:
        time.sleep(0.5)
    test_complex.rollcall()
    time.sleep(0.5)
    proxy = test_complex.ms_proxies['proxy']
    proxy.initialize()
    attempts = 0
    while not proxy.is_initialized and attempts < 3:
        attempts += 1
        time.sleep(0.5)
    assert proxy.is_initialized
    assert init_success == True
    proxy_props = proxy.properties
    assert 'configProp' in proxy_props and proxy_props['configProp'] == 2
    assert 'infoProp' in proxy_props and proxy_props['infoProp'] == 'test'
    assert 'logLevel' in proxy_props and proxy_props['logLevel'] == 'DEBUG'
    assert proxy.property_get('configProp') == 2
    proxy.property_set('configProp', 3)
    attempts = 0
    while not proxy.property_get('configProp') == 3 and attempts < 3:
        attempts += 1
        time.sleep(0.5)
    assert proxy.property_get('configProp') == 3


def mtest_proxy_init_fail(test_complex: TestService):
    """Requires live connection to a MQTT broker."""
    global init_success
    timeout = 2
    proxy = test_complex.ms_proxies['proxy']
    proxy._init_timeout = timeout
    test_complex._mqttc_local.connect()
    while not test_complex._mqttc_local.is_connected:
        time.sleep(0.5)
    with pytest.raises(OSError) as e_info:
        assert isinstance(proxy.properties, dict)
    proxy.initialize()
    time.sleep(timeout + 1)
    assert init_success == False
