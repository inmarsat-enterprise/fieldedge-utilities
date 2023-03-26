import json
from enum import IntEnum
from time import sleep, time

import pytest

from fieldedge_utilities.class_properties import *


class TestNestedObj:
    def __init__(self) -> None:
        self.one = 1
        self.two = ['element']


class TestEnum(IntEnum):
    FIRST = 1
    SECOND = 2


class TestObj:
    """A class for testing property manipulation for MQTT/JSON-based ISC."""
    __slots__ = ('__dict__', '_one', 'two', 'three', 'four', '_five', '_six')
    
    CLASS_CONSTANT = 'a_constant'
    
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
    
    def some_callable(self) -> str:
        return 'called'


class TestObjToo:
    """Another test class for merging another microservice properties as a child.
    
    For example a satellite monitor service could be proxied as a child through
    an IoT demo service.
    """
    def __init__(self, one: str) -> None:
        self._one: str = None
        self.one = one
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


# TODO: Deprecate this method and test
def test_cache_valid():
    cache = {}
    CACHE_MAX_TIME = 1
    CACHE_TAG = 'prop_value'
    cache[CACHE_TAG] = time()
    sleep(CACHE_MAX_TIME - 0.25)
    assert cache_valid(cache[CACHE_TAG], CACHE_MAX_TIME)
    sleep(CACHE_MAX_TIME)
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
    return TestObjToo('010203')


def test_get_class_tag(test_obj: TestObj, test_obj_too: TestObjToo):
    assert get_class_tag(TestObj) == 'testobj'
    assert get_class_tag(test_obj) == 'testobj'
    props_cls = get_class_properties(TestObj)
    props_inst = get_class_properties(test_obj)
    assert props_cls == props_inst
    props_cls_2 = get_class_properties(TestObjToo)
    props_inst_2 = get_class_properties(test_obj_too)
    assert props_cls_2 != props_inst_2


def test_get_class_properties_basic():
    props = get_class_properties(TestObj)
    expected = ['two', 'three', 'four', 'five', 'six', 'seven', 'one_plus_six']
    assert isinstance(props, list)
    assert all(prop in props for prop in expected)
    assert not any(prop not in expected for prop in props)


def test_get_instance_properties_values(test_obj: TestObj):
    props_vals = get_instance_properties_values(test_obj)
    for prop, val in props_vals.items():
        assert val == getattr(test_obj, prop)


def test_get_class_properties_ignore():
    ignore = ['seven', 'one_plus_six']
    props = get_class_properties(TestObj, ignore)
    expected = ['two', 'three', 'four', 'five', 'six']
    assert all(prop in props for prop in expected)
    assert not any(prop not in expected for prop in props)


def test_tag_properties_basic():
    notag_tag = get_class_tag(TestObj)
    ignore = ['six', 'seven']
    tagged_props = tag_class_properties(TestObj, ignore=ignore)
    expected_untagged = ['two', 'three', 'four', 'five', 'one_plus_six']
    expected_tagged = [f'{notag_tag}{x.title().replace("_", "")}'
                       for x in expected_untagged]
    assert all(tp in expected_tagged for tp in tagged_props)


def test_tag_properties_categorized():
    tagged_cat_props = tag_class_properties(TestObj, categorize=True)
    assert all(k in tagged_cat_props for k in ['info', 'config'])
    exp_ro_untagged = ['five', 'seven', 'one_plus_six']
    exp_rw_untagged = ['two', 'three', 'four', 'six']
    for prop in exp_ro_untagged:
        expected = tag_class_property(prop, get_class_tag(TestObj))
        assert expected in tagged_cat_props['info']
    for prop in exp_rw_untagged:
        expected = tag_class_property(prop, get_class_tag(TestObj))
        assert expected in tagged_cat_props['config']


def test_tag_properties_kwargs():
    notag_tag = get_class_tag(TestObjToo)
    tagged_props = tag_class_properties(TestObjToo)
    expected_untagged = ['one', 'two', 'one_bytes']
    expected_tagged = [f'{notag_tag}{x.title().replace("_", "")}'
                       for x in expected_untagged]
    assert all(tp in expected_tagged for tp in tagged_props)


def test_untag_property():
    tagged_properties = tag_class_properties(TestObj)
    tag = get_class_tag(TestObj)
    for prop in tagged_properties:
        untagged, derived_tag = untag_class_property(prop,
                                                     is_tagged=True,
                                                     include_tag=True)
        assert hasattr(TestObj, untagged)
        assert derived_tag == tag


def test_tag_merge(test_obj: TestObj, test_obj_too: TestObjToo):
    tagged_1 = tag_class_properties(TestObj)
    tagged_2 = tag_class_properties(TestObjToo)
    merged = tag_merge(tagged_1, tagged_2)
    assert merged == tagged_1 + tagged_2
    tagged_cat_1 = tag_class_properties(TestObj, categorize=True)
    tagged_cat_2 = tag_class_properties(TestObjToo, categorize=True)
    merged_cat = tag_merge(tagged_cat_1, tagged_cat_2)
    for cat, props in merged_cat.items():
        if cat in tagged_cat_1:
            assert all(p in props for p in tagged_cat_1[cat])
        if cat in tagged_cat_2:
            assert all(p in props for p in tagged_cat_2[cat])


def test_json_compatible(test_obj):
    json_test_obj = json_compatible(test_obj)
    assert isinstance(json.dumps(json_test_obj), str)
    cat_tagged_vals = tag_class_properties(test_obj, categorize=True)
    json_categorized = json_compatible(cat_tagged_vals)
    assert isinstance(json.dumps(json_categorized), str)


def test_equivalent_attributes_simple():
    obj_1 = TestObjToo('01')
    obj_2 = TestObjToo('01')
    assert equivalent_attributes(obj_1, obj_2)


def test_equivalent_attributes_nested_object():
    obj_1 = TestObj()
    obj_2 = TestObj()
    assert equivalent_attributes(obj_1, obj_2)
    obj_1.two.one = 2
    assert not equivalent_attributes(obj_1, obj_2)
    
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
    