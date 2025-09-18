import logging
import time

from fieldedge_utilities.properties.delegated import (
    DelegatedProperty,
    clear_delegated_cache,
    temporary_delegated_cache,
)

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)


class Base:
    def __init__(self) -> None:
        self._never_changes = 42
        self._changes_slowly = 0
        self._changes_fast = 0
        self._reads = {
            'never_changes': 0,
            'changes_slowly': 0,
            'changes_fast': 0,
        }
        self._value = 0
    
    def get_reads(self) -> dict[str, int]:
        return self._reads
    
    def get_never_changes(self) -> int:
        self._reads['never_changes'] += 1
        logger.info('Checked never_changes source: %d', self._never_changes)
        return self._never_changes
    
    def get_changes_slowly(self) -> int:
        self._reads['changes_slowly'] += 1
        self._changes_slowly += 1
        logger.info('Checked changes_slowly source: %d', self._changes_slowly)
        return self._changes_slowly
    
    def get_changes_fast(self) -> int:
        self._reads['changes_fast'] += 1
        self._changes_fast += 5
        logger.info('Checked changes_fast source: %d', self._changes_fast)
        return self._changes_fast
    
    def get_value(self) -> int:
        return self._value
    
    def set_value(self, value: int):
        if not isinstance(value, int):
            raise ValueError('Must be integer')
        self._value = value


class Demo(Base):
    def __init__(self) -> None:
        super().__init__()
        self.counter = 0

    @DelegatedProperty(cache_ttl=1)
    def foo(self):
        self.counter += 1
        return self.counter

    reads: DelegatedProperty[dict[str, int]] = DelegatedProperty(
        'reads',
        cache_ttl=0,
    )
    
    never_changes: DelegatedProperty[int] = DelegatedProperty(
        'never_changes',
        cache_ttl=None,
    )
    
    changes_slowly: DelegatedProperty[int] = DelegatedProperty(
        'changes_slowly',
        cache_ttl=5,
    )
    
    changes_fast: DelegatedProperty[int] = DelegatedProperty(
        'changes_fast',
        cache_ttl=1,
    )
    
    @DelegatedProperty(cache_ttl=1)
    def value(self) -> int: # type: ignore
        return self.get_value()
    
    @value.setter
    def value(self, v: int):
        self.set_value(v)


def test_normal_caching_behavior():
    obj = Demo()
    first = obj.foo
    second = obj.foo
    assert first == second  # same cached value
    assert obj.counter == 1  # only computed once


def test_cache_expires_normally():
    obj = Demo()
    val1 = obj.foo
    time.sleep(1.1)
    val2 = obj.foo
    assert val2 != val1  # recomputed after TTL
    assert obj.counter >= 2


def test_clear_all_cache():
    obj = Demo()
    v0 = obj.never_changes
    v1 = obj.changes_slowly
    v2 = obj.changes_fast
    assert v0 == 42
    assert v1 == 1
    assert v2 == 5
    assert obj.reads.get('never_changes') == 1
    assert obj.reads.get('changes_slowly') == 1
    assert obj.reads.get('changes_fast') == 1
    
    assert obj.never_changes == v0
    assert obj.changes_slowly == v1
    assert obj.changes_fast == v2
    time.sleep(1)
    assert obj.never_changes == v0
    assert obj.changes_fast > v2
    assert obj.changes_slowly == v1
    assert obj.reads.get('never_changes') == 1
    assert obj.reads.get('changes_slowly') == 1
    assert obj.reads.get('changes_fast') == 2
    
    clear_delegated_cache(obj)
    
    v3 = obj.never_changes
    v4 = obj.changes_slowly
    v5 = obj.changes_fast
    assert v3 == v0
    assert v4 > v1
    assert v5 > v2
    assert obj.reads.get('never_changes') == 2
    assert obj.reads.get('changes_slowly') == 2
    assert obj.reads.get('changes_fast') == 3


def test_clear_specific_property():
    obj = Demo()
    v1 = obj.never_changes
    v2 = obj.changes_fast
    assert obj.reads.get('never_changes') == 1
    assert obj.reads.get('changes_fast') == 1
    assert obj.never_changes == v1
    assert obj.changes_fast == v2
    clear_delegated_cache(obj, 'never_changes')
    assert obj.never_changes == v1
    assert obj.changes_fast == v2
    assert obj.reads.get('never_changes') == 2
    assert obj.reads.get('changes_fast') == 1


def test_temporary_delegated_cache_override_shorter_ttl():
    obj = Demo()
    val1 = obj.foo
    # Use temporary cache override with ttl=0 (always recompute)
    with temporary_delegated_cache(obj, 'foo', 0):
        val2 = obj.foo
        val3 = obj.foo
    assert val2 != val1  # recomputed
    assert val3 != val2  # recomputed again inside override


def test_temporary_delegated_cache_override_longer_ttl(caplog):
    caplog.at_level(logging.DEBUG)
    obj = Demo()
    val1 = obj.foo
    time.sleep(1.1)  # normally would expire
    with temporary_delegated_cache(obj, 'foo', 10):
        val2 = obj.foo
    assert val2 == val1  # override should have kept it valid
