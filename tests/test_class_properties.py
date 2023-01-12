import json
from enum import IntEnum
from time import sleep, time

import pytest

from fieldedge_utilities.class_properties import *


class TestNestedObj:
    def __init__(self) -> None:
        self.one_int = 1
        self.two_list = ['element']


class TestEnum(IntEnum):
    FIRST = 1
    SECOND = 2


class TestObj:
    """A class for testing property manipulation for MQTT/JSON-based ISC."""
    def __init__(self) -> None:
        self._one: int = 1   #: private
        self.two: object = TestNestedObj()
        self.three = None
        self.four: TestEnum = TestEnum.FIRST
        self._five: str = 'string'   #: read-only by proxy
        self._six: int = 6   #: read/write by proxy
    
    @property
    def five(self) -> str:
        return self._five
    
    @property
    def six(self) -> int:
        return self._six
    
    @six.setter
    def six(self, value: int):
        if not isinstance(value, int) or value not in range(1, 5):
            raise ValueError('Invalid value')
        self._six = value
    
    @property
    def seven(self) -> dict:
        return vars(self.four)
    
    @property
    def one_plus_six(self) -> int:
        return self._one + self._six


class TestObjToo:
    """Another test class for merging another microservice properties as a child.
    
    For example a satellite monitor service could be proxied as a child through
    an IoT demo service.
    """
    def __init__(self) -> None:
        self._one: str = '010203'
        self.two: int = 2
    
    @property
    def one(self) -> str:
        return self._one
    
    @one.setter
    def one(self, value: str):
        try:
            bytes.fromhex(value)
            self._one = value
        except:
            raise ValueError('value must be a hex string')
        
    @property
    def one_bytes(self) -> bytearray:
        return bytearray(bytes.fromhex(self._one))


def test_snake_to_camel():
    snake = 'test_string'
    camel = 'testString'
    capital = 'TEST_STRING'
    assert snake_to_camel(snake) == camel
    assert snake_to_camel(camel) == camel
    assert snake_to_camel(capital) == camel
    assert snake_to_camel(capital, True) == capital
    with pytest.raises(ValueError):
        x = snake_to_camel('')


def test_camel_to_snake():
    camel = 'testString'
    snake = 'test_string'
    capital = 'TEST_STRING'
    assert camel_to_snake(camel) == snake
    assert camel_to_snake(snake) == snake
    assert camel_to_snake(capital) == snake
    assert camel_to_snake(capital, True) == capital
    with pytest.raises(ValueError):
        x = snake_to_camel(1)


def test_cache_valid():
    cache = {}
    CACHE_MAX_TIME = 1
    CACHE_TAG = 'prop_value'
    cache[CACHE_TAG] = time()
    sleep(1)
    assert cache_valid(cache[CACHE_TAG], CACHE_MAX_TIME)
    sleep(CACHE_MAX_TIME + 1)
    assert not cache_valid(cache[CACHE_TAG], CACHE_MAX_TIME)
    with pytest.raises(ValueError):
        x = cache_valid('time')


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


@pytest.fixture
def test_obj():
    return TestObj()


@pytest.fixture
def test_obj_too():
    return TestObjToo()


def test_get_class_properties_basic(test_obj: TestObj):
    props = get_class_properties(test_obj)
    expected = ['two', 'three', 'four', 'five', 'six', 'seven', 'one_plus_six']
    assert isinstance(props, dict)
    assert all(prop in props for prop in expected)
    assert not any(prop not in expected for prop in props)
    for prop, val in props.items():
        assert hasattr(test_obj, prop)
        assert getattr(test_obj, prop) == val


def test_get_class_properties_categorized(test_obj: TestObj):
    props_c = get_class_properties(test_obj, categorize=True)
    expected_categories = ['read_only', 'read_write']
    expected_ro = ['five', 'seven', 'one_plus_six']
    expected_rw = ['two', 'three', 'four', 'six']
    assert isinstance(props_c, dict)
    assert all(cat in props_c for cat in expected_categories)
    assert not any(cat not in expected_categories for cat in props_c)
    for k, v in props_c.items():
        assert isinstance(v, dict)
    assert all(prop in props_c['read_only'] for prop in expected_ro)
    assert not any(prop not in expected_ro for prop in props_c['read_only'])
    assert all(prop in props_c['read_write'] for prop in expected_rw)
    assert not any(prop not in expected_rw for prop in props_c['read_write'])
    for cat, props in props_c.items():
        for prop in props:
            assert hasattr(test_obj, prop)
            assert getattr(test_obj, prop) == props[prop]


def test_get_class_properties_ignore(test_obj: TestObj):
    ignore = ['seven', 'one_plus_six']
    props = get_class_properties(test_obj, ignore)
    expected = ['two', 'three', 'four', 'five', 'six']
    assert isinstance(props, dict)
    assert all(prop in props for prop in expected)
    assert not any(prop not in expected for prop in props)


def test_tag_properties_basic(test_obj: TestObj):
    notag_tag = get_tag_class(test_obj)
    ignore = ['six', 'seven']
    tagged_props = tag_class_properties(test_obj, ignore=ignore)
    expected_untagged = ['two', 'three', 'four', 'five', 'one_plus_six']
    expected_tagged = [f'{notag_tag}{x.title().replace("_", "")}'
                       for x in expected_untagged]
    assert all(tp in expected_tagged for tp in tagged_props)


def test_untag_property(test_obj: TestObj):
    tagged_properties = tag_class_properties(test_obj)
    tag = get_tag_class(test_obj)
    for prop in tagged_properties:
        untagged = untag_class_property(prop, tag)
        assert hasattr(test_obj, untagged)


def test_tag_merge(test_obj: TestObj, test_obj_too: TestObjToo):
    tagged_1 = tag_class_properties(test_obj)
    tagged_2 = tag_class_properties(test_obj_too)
    merged = tag_merge(tagged_1, tagged_2)
    assert merged == tagged_1 + tagged_2
    tagged_vals_1 = tag_class_properties(test_obj, include_values=True)
    tagged_vals_2 = tag_class_properties(test_obj_too, include_values=True)
    merged_vals = tag_merge(tagged_vals_1, tagged_vals_2)
    for k, v in merged_vals.items():
        if k in tagged_vals_1:
            assert v == tagged_vals_1[k]
        elif k in tagged_vals_2:
            assert v == tagged_vals_2[k]
        else:
            assert False
    tagged_cat_vals_1 = tag_class_properties(test_obj, categorize=True, include_values=True)
    tagged_cat_vals_2 = tag_class_properties(test_obj_too, categorize=True, include_values=True)
    merged_cat_vals = tag_merge(tagged_cat_vals_1, tagged_cat_vals_2)
    for k, v in merged_cat_vals.items():
        assert k in ['read_only', 'read_write']
        assert isinstance(v, dict)
        for nk, nv in v.items():
            if nk in tagged_cat_vals_1[k]:
                assert nv == tagged_cat_vals_1[k][nk]
            elif nk in tagged_cat_vals_2[k]:
                assert nv == tagged_cat_vals_2[k][nk]


def test_json_compatible(test_obj):
    json_test_obj = json_compatible(test_obj)
    assert isinstance(json.dumps(json_test_obj), str)
    cat_tagged_vals = tag_class_properties(test_obj, categorize=True, include_values=True)
    json_categorized = json_compatible(cat_tagged_vals)
    assert isinstance(json.dumps(json_categorized), str)


def test_equivalent_attributes_simple():
    obj_1 = TestObjToo()
    obj_2 = TestObjToo()
    assert equivalent_attributes(obj_1, obj_2)


def test_equivalent_attributes_nested_object():
    # FAILING
    obj_1 = TestObj()
    obj_2 = TestObj()
    assert equivalent_attributes(obj_1, obj_2)
    
#: More specific test cases for FieldEdge project concepts --------
class SatModemBaseAttribute:
    """Generic base attribute for a satellite modem."""
    def __eq__(self, __o: object) -> bool:
        return equivalent_attributes(self, __o)


class Location(SatModemBaseAttribute):
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


def test_location():
    location = Location()
    jsonable = json_compatible(location)
    assert isinstance(json.dumps(jsonable), str)
    