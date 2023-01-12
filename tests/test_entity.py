"""CONCEPTUAL ONLY - NOT WORKING"""
import logging
import pytest

from fieldedge_utilities.entity import *

_log = logging.getLogger()


class EntitySubclass(FieldEdgeEntity):
    def __init__(self, tag_name: str) -> None:
        super().__init__(tag_name)
        self._hidden_prop = 'hidden'
        self._hidden_too = 'hidden'
        self.visible_prop = 'visible'
    
    @property
    def proxy_prop(self):
        return self._hidden_prop
    
    @proxy_prop.setter
    def proxy_prop(self, val: str):
        self._hidden_prop = val
    
    @property
    def proxy_too(self):
        return self._hidden_too
    
    def f_call(self, **kwargs):
        print(f'{kwargs}')


@pytest.fixture
def test_entity():
    return EntitySubclass(tag_name='test')


def test_entity_subclassing(test_entity):
    entity: EntitySubclass = test_entity
    _log.info(f'Properties: {entity.properties}')
    assert isinstance(entity, FieldEdgeEntity)
    assert isinstance(entity, EntitySubclass)


def test_property_cache(test_entity):
    entity: EntitySubclass = test_entity
    assert entity.property_cache == {}
    entity.cache_update('visible_prop')
    assert entity.cache_valid('visible_prop')
    