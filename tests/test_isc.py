import logging
import pytest

import fieldedge_utilities   # required for mocking
from fieldedge_utilities.isc import FieldedgeMicroservice


logger = logging.getLogger()


class TestService(FieldedgeMicroservice):
    """Basic subclass of abstract class for testing."""
    
    __slots__ = ['sub_prop']   # expose init properties
    
    TAG = 'test'   # a class constant
    
    def __init__(self) -> None:
        super().__init__(tag=self.TAG)
        self.sub_prop: str = 'test'
    
    def _on_isc_message(self, topic: str, message: dict) -> None:
        return super()._on_isc_message(topic, message)
    
    def rollcall(self, **kwargs):
        return super().rollcall(**kwargs)
    
    def rollcall_respond(self, request: dict, **kwargs):
        return super().rollcall_respond(request, **kwargs)


@pytest.fixture
def test_service() -> TestService:
    return TestService()


def test_microservice_subclass_creation(test_service: TestService):
    assert test_service.tag == TestService.TAG
    expected_props = ['tag', 'log_level', 'properties', 'properties_by_type',
                      'isc_properties', 'isc_properties_by_type', 'sub_prop']
    assert all(prop in test_service.properties for prop in expected_props)
    assert not any(prop not in test_service.properties for prop in expected_props)
    expected_isc_props = ['tag', 'logLevel', 'subProp']
    assert all(isc in test_service.isc_properties for isc in expected_isc_props)
    assert not any(isc not in test_service.isc_properties for
                   isc in expected_isc_props)


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
        assert 'subProp' in message and message['subProp'] == 'test'
    mocker.patch('fieldedge_utilities.isc.FieldedgeMicroservice.notify',
                 side_effect=mock_isc)
    test_service._rollcall_properties.append('sub_prop')
    topic = 'fieldedge/otherservice/rollcall'
    message = { 'uid': 'requestor-uuid' }
    logger.info(f'Mocking ISC {topic}: {message}')
    test_service._on_isc_message(topic, message)


def test_ms_isc_task_expired(test_service: TestService, mocker):
    assert False


def test_ms_cached_property_expired(test_service: TestService, mocker):
    assert False
