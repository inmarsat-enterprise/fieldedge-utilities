import asyncio
import logging
import pytest
import time

import fieldedge_utilities   # required for mocking
from fieldedge_utilities.microservice import Microservice, IscTask, IscTaskQueue
from fieldedge_utilities.class_properties import get_class_tag, get_class_properties


logger = logging.getLogger()


class TestService(Microservice):
    """Basic subclass of abstract class for testing."""
    
    # __slots__ = ['slot_config', '_info_prop', '_config_prop']   # must expose all init properties
    
    TAG = 'test'   # a class constant
    
    def __init__(self) -> None:
        super().__init__(tag=self.TAG)
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
    
    @property
    async def async_info_prop(self) -> str:
        await asyncio.sleep(1)
        return self._info_prop
    
    def on_isc_message(self, topic: str, message: dict) -> None:
        logger.info(f'Received ISC message {topic}: {message}')


@pytest.fixture
def test_service() -> TestService:
    return TestService()


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
    assert not any(prop not in expected_props for prop in test_service.properties)
    assert all(prop in test_service.properties_by_type['config'] for prop in expected_config_props)
    assert not any(prop not in expected_config_props for prop in test_service.properties_by_type['config'])
    assert all(prop in test_service.properties_by_type['info'] for prop in expected_info_props)
    assert not any(prop not in expected_info_props for prop in test_service.properties_by_type['info'])
    expected_isc_config_props = ['logLevel', 'configProp']
    expected_isc_info_props = ['infoProp']
    expected_isc_props = expected_isc_config_props + expected_isc_info_props
    assert all(prop in test_service.isc_properties for prop in expected_isc_props)
    assert not any(prop not in expected_isc_props for prop in test_service.isc_properties)
    isc_props = test_service.isc_properties_by_type
    assert all(prop in test_service.isc_properties_by_type['config'] for prop in expected_isc_config_props)
    assert not any(prop not in expected_isc_config_props for prop in test_service.isc_properties_by_type['config'])
    assert all(prop in test_service.isc_properties_by_type['info'] for prop in expected_isc_info_props)
    assert not any(prop not in expected_isc_info_props for prop in test_service.isc_properties_by_type['info'])
    assert test_service.log_level == logging.getLevelName(logger.getEffectiveLevel())


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


@pytest.mark.asyncio
async def test_ms_isc_get_property_async(test_service: TestService):
    test_prop = 'async_info_prop'
    test_isc_prop = 'asyncInfoProp'
    assert test_service.isc_get_property(test_isc_prop) == await getattr(test_service, test_prop)


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
    mocker.patch('fieldedge_utilities.isc.FieldedgeMicroservice.notify',
                 side_effect=mock_isc)
    test_service.rollcall()


def test_ms_on_isc_message_other_rollcall(test_service: TestService, mocker):
    def mock_isc(message, **kwargs):
        topic = f'fieldedge/{TestService.TAG}/{kwargs.get("subtopic", None)}'
        logger.info(f'Mocking ISC {topic}: {message}')
        assert 'subtopic' in kwargs and kwargs['subtopic'] == 'rollcall/response'
        assert 'uid' in message and message['uid'] == 'requestor-uuid'
        assert 'infoProp' in message and message['infoProp'] == 'test'
    mocker.patch('fieldedge_utilities.isc.FieldedgeMicroservice.notify',
                 side_effect=mock_isc)
    test_service.rollcall_property_add('info_prop')
    topic = 'fieldedge/otherservice/rollcall'
    message = { 'uid': 'requestor-uuid' }
    logger.info(f'Mocking ISC {topic}: {message}')
    test_service._on_isc_message(topic, message)


@pytest.fixture
def isc_task() -> IscTask:
    return IscTask(uid='a-unique-id',
                   task_type='test',
                   task_meta={
                       'test': 'test',
                       'timeout_callback': isc_task_timeout,
                   },
                   callback=isc_task_chained)


def isc_task_timeout(*args, **kwargs):
    for arg in args:
        logger.info(f'Task timeout received {arg}')
    for k, v in kwargs.items():
        logger.info(f'Task timeout received {k}={v}')


def isc_task_chained(*args, **kwargs):
    for arg in args:
        logger.info(f'Task chain received {arg}')
    for k, v in kwargs.items():
        logger.info(f'Task chain received {k}={v}')


def test_isc_task_creation():
    queued_task = IscTask(task_type='test')
    assert isinstance(queued_task.uid, str)
    assert queued_task.task_type == 'test'
    assert queued_task.lifetime == 10


def test_isc_task_queue_basic(isc_task: IscTask):
    task_queue = IscTaskQueue()
    task_queue.append(isc_task)
    with pytest.raises(ValueError):
        task_queue.append(isc_task)
    assert task_queue.is_queued(isc_task.uid)
    assert task_queue.is_queued(task_type=isc_task.task_type)
    assert task_queue.is_queued(task_meta=('test', 'test'))
    got = task_queue.get(isc_task.uid)
    assert got == isc_task
    assert not task_queue.is_queued(isc_task.uid)
    assert callable(got.task_meta.pop('timeout_callback'))
    got.callback(got.task_meta)


def test_isc_task_queue_expiry(isc_task: IscTask):
    isc_task.lifetime = 1
    task_queue = IscTaskQueue()
    task_queue.append(isc_task)
    while task_queue.is_queued(isc_task.uid):
        time.sleep(1)
        task_queue.remove_expired()
    assert not task_queue.is_queued(isc_task.uid)


def test_ms_cached_property(test_service: TestService, mocker):
    ref_time = time.time()
    cache_lifetime = 1
    test_service.property_cache('sub_prop', cache_lifetime)
    while test_service.property_is_cached('sub_prop'):
        pass
    elapsed = time.time() - ref_time
    logger.info(f'Time elapsed: {elapsed}')
    assert elapsed >= cache_lifetime
    assert not test_service.property_is_cached('sub_prop')
