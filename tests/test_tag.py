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
        return self._prop_read_two
    

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
    assert tag.camel_to_snake(camel) == snake
    assert tag.camel_to_snake(snake) == snake


def test_snake_to_camel():
    snake = 'this_is_snake_case'
    camel = 'thisIsSnakeCase'
    assert tag.snake_to_camel(snake) == camel
    assert tag.snake_to_camel(camel) == camel


def test_tag_class_properties():
    test_tag = 'test'
    tagged_props = tag.tag_class_properties(TestTag, test_tag)
    assert 'config' in tagged_props
    assert isinstance(tagged_props['config'], list)
    assert len(tagged_props['config']) == 1
    for item in tagged_props['config']:
        assert isinstance(item, str)
        assert item.startswith(test_tag)
        assert hasattr(TestTag, tag.camel_to_snake(item.replace(test_tag, '')))
    assert 'readOnly' in tagged_props
    assert isinstance(tagged_props['readOnly'], list)
    assert len(tagged_props['readOnly']) == 1
    for item in tagged_props['readOnly']:
        assert isinstance(item, str)
        assert item.startswith(test_tag)
        assert hasattr(TestTag, tag.camel_to_snake(item.replace(test_tag, '')))


def test_untag():
    test_tag = 'test'
    tagged_props = tag.tag_class_properties(TestTag, test_tag)
    for key, value in tagged_props.items():
        for item in value:
            orig_prop, extracted_tag = tag.untag_property(item, True)
            assert hasattr(TestTag, orig_prop)
            assert extracted_tag == test_tag
            orig_prop_alone = tag.untag_property(item)
            assert hasattr(TestTag, orig_prop_alone)


def test_tag_merge():
    test_tag1 = 'test_one'
    test_tag2 = 'test_too'
    tagged1 = tag.tag_class_properties(TestTag, test_tag1)
    tagged2 = tag.tag_class_properties(TestTagToo, test_tag2)
    merged = tag.tag_merge(tagged1, tagged2)
    assert 'config' in merged
    assert len(merged['config']) == 2
    assert 'readOnly' in merged
    assert len(merged['readOnly']) == 2
