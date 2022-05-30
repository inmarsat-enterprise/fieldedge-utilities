from fieldedge_utilities import tag


class TestTag:
    def __init__(self) -> None:
        self._prop_config_one = 1
        self._prop_read_two = 'two'
        self.prop_three = 'three'
    
    @property
    def prop_one(self) -> int:
        return self._prop_one
    
    @prop_one.setter
    def prop_one(self, value: int):
        self._prop_one = value
    
    @property
    def prop_two(self) -> str:
        return self._prop_two
    

def test_camel_to_snake():
    camel = 'thisIsCamelCase'
    snake = 'this_is_camel_case'
    assert tag.camel_to_snake(camel) == snake


def test_snake_to_camel():
    snake = 'this_is_snake_case'
    camel = 'thisIsSnakeCase'
    assert tag.snake_to_camel(snake) == camel


def test_tag_class_properties():
    tagged_props = tag.tag_class_properties(TestTag, 'test')
    assert 'config' in tagged_props
    assert isinstance(tagged_props['config'], list)
    assert len(tagged_props['config']) == 1
    for item in tagged_props['config']:
        assert isinstance(item, str)
        assert item.startswith('test_')
    assert 'read_only' in tagged_props
    assert isinstance(tagged_props['read_only'], list)
    assert len(tagged_props['read_only']) == 1
    for item in tagged_props['read_only']:
        assert isinstance(item, str)
        assert item.startswith('test_')


def test_tag_jsonify():
    tagged_props = tag.tag_class_properties(TestTag, 'test')
    jsonified = {}
    for k, v in tagged_props.items():
        jsonified_list = []
        for item in v:
            jsonified_list.append(tag.snake_to_camel(item))
        jsonified[tag.snake_to_camel(k)] = jsonified_list
    for k, v in jsonified.items():
        assert tag.camel_to_snake(k) in tagged_props
        for item in v:
            assert tag.camel_to_snake(item) in tagged_props[tag.camel_to_snake(k)]
