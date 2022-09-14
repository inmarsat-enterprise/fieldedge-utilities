from fieldedge_utilities.entity import *


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


def test_entity():
    entity = EntitySubclass(tag_name='test')
    assert isinstance(entity, FieldEdgeEntity)
    assert isinstance(entity, EntitySubclass)
