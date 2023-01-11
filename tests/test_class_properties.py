import json
import pytest
from enum import IntEnum

from fieldedge_utilities.class_properties import *


class BganBaseAttribute:
    """Generic base attribute for BGAN modems."""
    def __eq__(self, __o: object) -> bool:
        return equivalent_attributes(self, __o)


class Location(BganBaseAttribute):
    """The modem's location derived from internal GNSS.
    
    Attributes:
        timestamp (int): The unix timestamp of the fix.
        latitude (float): Latitude in decimal degrees, signed (+ North).
        longitude (float): Longiutde in decimal degrees, signed (+ East).
        altitude (float): Height above sea level in meters.
        speed (float): Speed in knots
        heading (float): Course over ground, degrees from true North.
        gnss_satellites (int): Number of satellites used for the fix.
        pdop (int): Probability Dilution of Precision
        hdop (int): Horizontal Dilution of Precision
        vdop (int): Vertical Dilution of Precision
        fix_type (str): The fix type e.g. 2D, 3D
        fix_allowed (str): The fix allowed status
        fix_time (str): ISO UTC time of the fix

    """
    def __init__(self, **kwargs) -> None:
        self.timestamp: int = kwargs.get('timestamp', None)
        self.latitude: float = kwargs.get('latitude', None)
        self.longitude: float = kwargs.get('longitude', None)
        self.altitude: float = kwargs.get('altitude', None)
        self.speed: float = kwargs.get('speed', None)
        self.heading: float = kwargs.get('heading', None)
        self.gnss_satellites: int = kwargs.get('gnss_satellites', None)
        self.pdop: int = kwargs.get('pdop', None)
        self.hdop: int = kwargs.get('hdop', None)
        self.vdop: int = kwargs.get('vdop', None)
        self.fix_type: str = kwargs.get('fix_type', None)
        self.fix_allowed: str = kwargs.get('fix_allowed', None)
        self.fix_time: str = kwargs.get('')


class TestTag:
    def __init__(self) -> None:
        self._prop_config_one = 1
        self._prop_read_two = 'two'
        self._prop_three = 'three'
    
    @property
    def prop_config_one(self) -> int:
        return self._prop_one
    
    @prop_config_one.setter
    def prop_config_one(self, value: int):
        self._prop_one = value
    
    @property
    def prop_read_two(self) -> str:
        return self._prop_read_two
    
    @property
    def exposed_properties(self):
        return self._prop_three
    

class TestTagToo:
    def __init__(self) -> None:
        self._prop_config_too_one = 1
        self._prop_read_too_two = 'two'
    
    @property
    def prop_config_too_one(self) -> int:
        return self._prop_config_too_one
    
    @prop_config_too_one.setter
    def prop_config_too_one(self, value: int):
        self._prop_config_too_one = value
    
    @property
    def prop_read_too_two(self) -> str:
        return self._prop_read_too_two


def test_camel_to_snake():
    camel = 'thisIsCamelCase'
    snake = 'this_is_camel_case'
    assert camel_to_snake(camel) == snake
    assert camel_to_snake(snake) == snake


def test_snake_to_camel():
    snake = 'this_is_snake_case'
    camel = 'thisIsSnakeCase'
    assert snake_to_camel(snake) == camel
    assert snake_to_camel(camel) == camel


def test_tag_class_properties():
    test_tag = 'test'
    tagged_props = tag_class_properties(TestTag, test_tag)
    assert 'config' in tagged_props
    assert isinstance(tagged_props['config'], list)
    assert len(tagged_props['config']) == 1
    for item in tagged_props['config']:
        assert isinstance(item, str)
        assert item.startswith(test_tag)
        assert hasattr(TestTag, camel_to_snake(item.replace(test_tag, '')))
    assert 'readOnly' in tagged_props
    assert isinstance(tagged_props['readOnly'], list)
    assert len(tagged_props['readOnly']) == 1
    for item in tagged_props['readOnly']:
        assert isinstance(item, str)
        assert item.startswith(test_tag)
        assert hasattr(TestTag, camel_to_snake(item.replace(test_tag, '')))


def test_untag():
    test_tag = 'test'
    tagged_props = tag_class_properties(TestTag, test_tag)
    for key, value in tagged_props.items():
        for item in value:
            orig_prop, extracted_tag = untag_class_property(item,
                                                            include_tag=True)
            assert hasattr(TestTag, orig_prop)
            assert extracted_tag == test_tag
            orig_prop_alone = untag_class_property(item)
            assert hasattr(TestTag, orig_prop_alone)


def test_tag_merge():
    test_tag1 = 'test_one'
    test_tag2 = 'test_too'
    tagged1 = tag_class_properties(TestTag, test_tag1)
    tagged2 = tag_class_properties(TestTagToo, test_tag2)
    merged = tag_merge(tagged1, tagged2)
    assert 'config' in merged
    assert len(merged['config']) == 2
    assert 'readOnly' in merged
    assert len(merged['readOnly']) == 2


class TestNestedObj:
    def __init__(self) -> None:
        self.one_int = 1
        self.two_list = ['element']


class TestEnum(IntEnum):
    FIRST = 1
    SECOND = 2


class TestObj:
    def __init__(self) -> None:
        self.one_int = 1
        self.two_object = TestNestedObj()
        self.three_none = None
        self.four_enum = TestEnum.FIRST


@pytest.fixture
def test_obj():
    return TestObj()


def test_json_compatible(test_obj):
    jsonable = json_compatible(test_obj)
    assert isinstance(json.dumps(jsonable), str)
    wrapped = { 'key': test_obj }
    jsonable = json_compatible(wrapped)
    assert isinstance(json.dumps(jsonable), str)
    with_list = { 'key': [test_obj] }
    jsonable = json_compatible(with_list)
    assert isinstance(json.dumps(jsonable), str)
    with_complex = { 'key': [{ 'nkey': [test_obj] }] }
    jsonable = json_compatible(with_complex)
    assert isinstance(json.dumps(jsonable), str)
    specific = {
        'properties': {
            'modemPointingMode': False,
            'modemWatchdog': None,
            'modemAutomaticContextActivation': None,
            'modemSmsRemoteEnabled': True,
            'monitorMetricsInterval': 60,
            'modemManufacturer': 'HUGHES',
            'modemConnectedLocal': True,
            'modemEnabledLocal': True,
            'modemSatellite': test_obj,
            'modemElevation': 33,
            'modemAzimuth': 210,
            'modemBeamType': TestEnum.FIRST,
            'modemBeamId': 4,
            'modemSnr': 58.0,
            'modemSignalQuality': TestEnum.SECOND,
            'modemImsi': '901112112900265',
            'modemImei': '353938-03-002771-2',
            'modemRegistered': True,
            'modemRegistrationType': 'home',
            'modemRegistrationChangeNotifications': False,
            'modemPdpContexts': {
                1: {
                    'id': 1,
                    'service': 'IP',
                    'apn': 'stratos.bgan.inmarsat.com',
                    'ip_addr': '216.86.246.2'
                    }
            },
            'modemConnectedNetwork': True,
            'modemLocation': {
                'latitude': 42.0,
                'longitude': -42.0,
                'fix_type': '3D',
                'fix_allowed': 'allowed',
                'fix_time': '2022-05-31T01:07:50Z',
                'timestamp': 1653959270
            },
            'modemModel': '9502',
            'modemRevision': 'Software: 5.9.5.3, 09/25/2017',
            'monitorInitialized': True
        },
        'uid': None,
        'ts': 1653964306656
    }
    jsonable = json_compatible(specific)
    assert isinstance(json.dumps(jsonable), str)


def test_json_camel():
    TEST_1 = {
        'in': { 'key_a': 'value' },
        'out': { 'keyA': 'value' }
    }
    TEST_2 = {
        'in': { 'CAP_KEY': 'value' },
        'out': { 'CAP_KEY': 'value' }
    }
    TEST_3 = {
        'in': { 'key_a': [{ 'key_b': 'value_b' }, { 'key_c': 'value_c' }] },
        'out': { 'keyA': [{ 'keyB': 'value_b'}, { 'keyC': 'value_c' }] }
    }
    TEST_4 = {
        'in': { 1: 'value_1' },
        'out': { 1: 'value_1' }
    }
    TEST_5 = {
        'in': 'string',
        'out': 'string'
    }
    TEST_6 = {
        'in': 1,
        'out': 1
    }
    tests = [TEST_1, TEST_2, TEST_3, TEST_4, TEST_5, TEST_6]
    for test in tests:
        assert test['out'] == json_compatible(test['in'])
        assert isinstance(json.dumps(json_compatible(test)), str)


class PdpContext:
    """Enapsulates PDP Context metadata.
    
    Attributes:
        number (int): The context number within the BGAN terminal.
        service (str): The context type e.g. background IP.
        apn (str): The Access Point Name used for the context.
        ip_address (str): The IPv4 address of the terminal for the context.

    """
    def __init__(self, **kwargs) -> None:
        self.id: int = kwargs.get('id', None)
        self.service: str = kwargs.get('service', None)
        self.apn: str = kwargs.get('apn', None)
        self.ip_address: str = kwargs.get('ip_address', None)


class PdpContextEquivalent:
    def __init__(self, **kwargs) -> None:
        self.id: int = kwargs.get('id', None)
        self.service: str = kwargs.get('service', None)
        self.apn: str = kwargs.get('apn', None)
        self.ip_address: str = kwargs.get('ip_address', None)
    
    def __eq__(self, __o: object) -> bool:
        return equivalent_attributes(self, __o)


def test_pdp():
    pdp = PdpContext(id=1, service='IP', apn='www.inmarsat.com', ip_address='1.2.3.4')
    thing = {'imsi': '123', 'previous': {1: pdp}}
    jsonable = json_compatible(thing)
    assert isinstance(json.dumps(jsonable), str)


def test_obj_eq():
    pdp_1 = PdpContext(id=1, service='IP', apn='www.apn.com', ip_address='1.2.3.4')
    pdp_2 = PdpContext(id=1, service='IP', apn='www.apn.com', ip_address='1.2.3.4')
    assert pdp_1 != pdp_2
    assert equivalent_attributes(pdp_1, pdp_2)
    pdp_3 = PdpContextEquivalent(id=1, service='IP', apn='www.apn.com', ip_address='1.2.3.4')
    pdp_4 = PdpContextEquivalent(id=1, service='IP', apn='www.apn.com', ip_address='1.2.3.4')
    assert pdp_3 == pdp_4


def test_bgan_location():
    location = Location()
    jsonable = json_compatible(location)
    assert isinstance(json.dumps(jsonable), str)
    