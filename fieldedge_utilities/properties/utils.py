"""Helper functions for dealing with FieldEdge classes and interservice comms.
"""
import inspect
import itertools
import json
import logging
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Optional, Union

from fieldedge_utilities.logger import verbose_logging

__all__ = [
    'camel_case', 'snake_case', 'pascal_case',
    'get_class_tag', 'get_class_properties',
    'get_instance_properties_values',
    'equivalent_attributes', 'json_compatible', 'hasattr_static',
    'property_is_read_only', 'property_is_async',
    'tag_class_properties', 'tag_class_property', 'untag_class_property',
    'tag_merge',
    'READ_ONLY', 'READ_WRITE',
]

READ_ONLY = 'info'
READ_WRITE = 'config'

_log = logging.getLogger(__name__)


def snake_case(original: str,
               skip_caps: bool = False,
               skip_pascal: bool = False) -> str:
    """Converts a string to snake_case.
    
    Args:
        original: The string to convert.
        skip_caps: A flag if `True` will return CAPITAL_CASE unchanged.
        skip_pascal: A flag if `True` will return PascalCase unchanged.
        
    Returns:
        The original string converted to snake_case format.
        
    Raises:
        `ValueError` if original is not a valid string.
        
    """
    if not isinstance(original, str) or not original:
        raise ValueError('Invalid string input')
    if original.isupper() and skip_caps:
        return original
    snake = re.compile(r'(?<!^)(?=[A-Z])').sub('_', original).lower()
    if '__' in snake:
        words = snake.split('__')
        snake = '_'.join(f'{word.replace("_", "")}' for word in words)
    words = snake.split('_')
    if original[0].isupper() and skip_pascal:
        if all(word.title() in original for word in words):
            return original
    return snake


def camel_case(original: str,
               skip_caps: bool = False,
               skip_pascal: bool = False) -> str:
    """Converts a string to camelCase.
    
    Args:
        original: The string to convert.
        skip_caps: If `True` will return CAPITAL_CASE unchanged
        skip_pascal: If `True` will return PascalCase unchanged
    
    Returns:
        The input string in camelCase structure.
        
    """
    if not isinstance(original, str) or not original:
        raise ValueError('Invalid string input')
    if original.isupper() and skip_caps:
        return original
    words = snake_case(original, skip_pascal=skip_pascal).split('_')
    if len(words) == 1:
        regex = '.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)'
        matches = re.finditer(regex, original)
        words = [m.group(0) for m in matches]
    if skip_pascal and all(word.title() == word for word in words):
        return original
    return words[0].lower() + ''.join(w.title() for w in words[1:])


def pascal_case(original: str, skip_caps: bool = False) -> str:
    """Returns the string converted to PascalCase.
    
    Args:
        original: The original string.
        skip_caps: A flag that returns the original if CAPITAL_CASE.

    """
    camel = camel_case(original, skip_caps)
    return camel[0].upper() + camel[1:]


def get_class_tag(cls: type) -> str:
    """Returns a lowercase name to use as the tag for a class."""
    if isinstance(cls, type):
        return cls.__name__.lower()
    return cls.__class__.__name__.lower()


def get_class_properties(cls: type, ignore: Optional[list[str]] = None) -> list[str]:
    """Returns non-hidden, non-callable properties/values of a Class instance.
    
    Ignores CAPITAL_CASE attributes which are assumed to be constants.
    If the class has no __slots__ attributes may be missed but an attempt is
    made to instantiate the class to mitigate this before logging a warning.
    
    Args:
        cls: The Class whose properties will be derived
        ignore: A list of attribute names to ignore (optional)
    
    Returns:
        A list of exposed property names.
        
    Raises:
        ValueError if `cls` does not have a `__dir__` attribute.
        
    """
    from .delegated import DelegatedProperty
    
    if not hasattr(cls, '__dir__'):
        raise ValueError(f'{cls.__name__} invalid - must have dir() method')
    inst = cls if isinstance(cls, type) else None
    if isinstance(cls, type) and '__slots__' not in dir(cls):
        try:
            inst = cls()
        except Exception:
            _log.warning('%s has no __slots__: __init__ attributes will be lost',
                         cls.__name__)
    if not isinstance(ignore, list):
        ignore = []
    props: list[str] = []
    for attr_name in dir(inst or cls):
        if attr_name.startswith('_') or attr_name in ignore or attr_name.isupper():
            continue
        # Use static lookup to avoid triggering descriptors
        try:
            attr = inspect.getattr_static(inst or cls, attr_name)
        except AttributeError:
            continue
        # Expose normal and delegated properties
        if isinstance(attr, (property, DelegatedProperty)):
            props.append(attr_name)
            continue
        # Skip methods and callables
        if isinstance(attr, (classmethod, staticmethod)):
            if callable(attr.__func__):
                continue
        if callable(attr):
            continue
        # Fallback: constant or class-level value
        props.append(attr_name)
    return props


def get_instance_properties_values(instance: object) -> dict[str, Any]:
    """Returns the instance properties and values."""
    props_list = get_class_properties(instance.__class__)
    return { k: getattr(instance, k) for k in props_list }


def equivalent_attributes(ref: object,
                          other: object,
                          exclude: Optional[list[str]] = None,
                          dbg: str = '',
                          ) -> bool:
    """Recursively check that two objects have equivalent non-callable attributes.
    
    Args:
        ref: The reference object being compared to.
        other: The object comparing against the reference.
        exclude: Optional list of attribute names to exclude from comparison.
    
    Returns:
        True if all (non-excluded) attribute name/values match.

    """
    if not isinstance(other, type(ref)):
        return False
    if exclude is None:
        exclude = []
    if dbg:
        dbg += '.'
    if hasattr(ref, '__slots__'):
        attrs = list(getattr(ref, '__slots__', []))
    else:
        attrs = list(getattr(ref, '__dict__', {}).keys())
    # Add in properties defined on the class
    for name, val in inspect.getmembers(type(ref)):
        if isinstance(val, property):
            attrs.append(name)
    for attr in sorted(set(attrs)):
        if attr.startswith('__') or attr in exclude:
            continue
        if not hasattr(other, attr):
            _log.debug('Other missing %s%s', dbg, attr)
            return False
        ref_val = getattr(ref, attr)
        other_val = getattr(other, attr)
        # Skip methods and functions
        if inspect.ismethod(ref_val) or inspect.isfunction(ref_val):
            continue
        # Recurse if they’re objects with attributes
        if (hasattr(ref_val, '__dict__') or hasattr(ref_val, '__slots__')) \
           and not isinstance(ref_val, (str, bytes, int, float, bool, tuple, frozenset)):
            if not equivalent_attributes(ref_val, other_val, exclude=exclude, dbg=dbg+attr):
                return False
        elif ref_val != other_val:
            _log.debug('%s%s mismatch: %r != %r', dbg, attr, ref_val, other_val)
            return False
    return True


def json_compatible(obj: object,
                    camel_keys: bool = True,
                    skip_caps: bool = True) -> Any:
    """Returns a dictionary compatible with `json.dumps` function.

    Nested objects are converted to dictionaries.
    Supports `json_compatible` override method on object.
    
    `LOG_VERBOSE` optional key: `tags`
    
    Args:
        obj: The source object.
        camel_keys: Flag indicating whether to convert all nested dictionary
            keys to `camelCase`.
        skip_caps: Preserves `CAPITAL_CASE` keys if True
        
    Returns:
        A dictionary with nested arrays, dictionaries and other compatible with
            `json.dumps`.

    """
    # First check for override method
    method = getattr(obj, 'json_compatible', None)
    if callable(method):
        return method()
    # Handle simple base cases next
    if isinstance(obj, Enum):
        return obj.name
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        res: dict[Any, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str):
                if k.isupper() and skip_caps:
                    new_key = k
                else:
                    new_key = camel_case(k) if camel_keys else k
            else:
                new_key = k
            res[new_key] = json_compatible(v, camel_keys, skip_caps)
        return res
    if isinstance(obj, (list, tuple)):
        return [json_compatible(i, camel_keys, skip_caps) for i in obj]
    if is_dataclass(obj):
        as_dict = { f.name: getattr(obj, f.name) for f in fields(obj) }
        for name, attr in type(obj).__dict__.items():
            if isinstance(attr, property) and not name.startswith('_'):
                as_dict[name] = getattr(obj, name)
        return json_compatible(as_dict, camel_keys, skip_caps)  # type: ignore
    if callable(obj):
        name = getattr(obj, '__name__', repr(obj))
        return f'<function:{name}>'
    if hasattr(obj, '__dict__'):
        return json_compatible(get_instance_properties_values(obj),
                               camel_keys, skip_caps)
    if hasattr(obj, '__slots__'):
        slots = getattr(obj, '__slots__')
        if isinstance(slots, str):
            slots = (slots,)
        return {
            s: json_compatible(getattr(obj, s, None), camel_keys, skip_caps)
            for s in slots
        }
    try:
        json.dumps(obj)
        return obj
    except Exception as exc:
        _log.error(exc)
        return '<non-serializable>'


def hasattr_static(obj: object, attr: str) -> bool:
    """Determines if an object has an attribute without calling the attribute.
    
    Args:
        obj: The object to inspect.
        attr: The name of the attribute to query.
    
    Returns:
        `True` if the object has the attribute.
        
    """
    try:
        inspect.getattr_static(obj, attr)
        return True
    except AttributeError:
        return False


def property_is_read_only(instance: object, property_name: str) -> bool:
    """Returns True if the instance attribute has no fset method."""
    if not hasattr_static(instance, property_name):
        raise ValueError(f'Object has no property {property_name}')
    prop = inspect.getattr_static(instance, property_name)
    try:
        return prop.fset is None
    except AttributeError:
        return False


def property_is_async(instance: object, property_name: str) -> bool:
    """Returns True if an object is awaitable."""
    if not hasattr_static(instance, property_name):
        raise ValueError(f'Object has no property {property_name}')
    return inspect.isawaitable(getattr(instance, property_name))


def tag_class_properties(cls: type,
                         tag: Optional[str] = None,
                         auto_tag: bool = True,
                         use_json: bool = True,
                         categorize: bool = False,
                         ignore: Optional[list[str]] = None,
                         ) -> Union[list, dict]:
    """Retrieves the class public properties tagged with a routing prefix.
    
    If a `tag` is not provided and `auto_tag` is `True` then the lowercase name
    of the instance's class will be used e.g. MyClass.property becomes
    myclassProperty.
    
    Using the defaults will return a simple list of tagged property names
    with the form `['tagProp1Name', 'tagProp2Name']`
    
    If `tag` is `None` and `auto_tag` is `False` then no tag will be applied
    and the native property names will be returned as JSON if `json` is `True`.
    
    If `categorize` is `True` a dictionary is returned of the form
    `{ 'info': ['tagProp1Name'], 'config': ['tagProp2Name']}` where
    the category is not present if no properties meet the respective criteria.
    
    If `json` is `False` the above applies but property names will use
    their original case e.g. `tag_prop1_name`
    
    `LOG_VERBOSE` optional key: `tags`.
    
    Args:
        cls: A class to tag.
        tag: The name of the routing prefix. If `None`, the calling function's
            module `__name__` will be used.
        auto_tag: If `True` will use the class name in lowercase.
        json: A flag indicating whether to use camelCase keys.
        categorize: A flag indicating whether to group as `info` and `config`.
        ignore: A list of property names to ignore.
    
    Retuns:
        A dictionary or list of strings (see docstring).
        
    """
    # TODO: class checking seems not to work for certain subclasses
    if isinstance(cls, type) and verbose_logging('tags'):
        _log.debug('Processing for class type')
    # elif issubclass(cls, ABC):
    #     _log.debug('Processing for microservice')
    if auto_tag and not tag:
        tag = get_class_tag(cls)
    class_props = get_class_properties(cls, ignore)
    if not categorize:
        return [tag_class_property(prop, tag, use_json) for prop in class_props]
    result = {}
    for prop in class_props:
        if property_is_read_only(cls, prop):
            if READ_ONLY not in result:
                result[READ_ONLY] = []
            result[READ_ONLY].append(tag_class_property(prop, tag, use_json))
        else:
            if READ_WRITE not in result:
                result[READ_WRITE] = []
            result[READ_WRITE].append(tag_class_property(prop, tag, use_json))
    return result


def tag_class_property(prop: str,
                       tag_or_cls: Optional[Union[str, type]] = None,
                       use_json: bool = True) -> str:
    """Converts a property for ISC adding an optional tag."""
    if tag_or_cls is None:
        tagged = prop
    else:
        if isinstance(tag_or_cls, type):
            tag = get_class_tag(tag_or_cls)
        elif isinstance(tag_or_cls, str):
            tag = tag_or_cls
        else:
            raise ValueError('tag_or_cls must be a string or class type')
        tagged = f'{tag.lower()}_{prop}'
    return camel_case(tagged) if use_json else tagged


def untag_class_property(property_name: str,
                         is_tagged: bool = True,
                         include_tag: bool = False,
                         ) -> Union[str, tuple[str, str|None]]:
    """Reverts a JSON-format tagged property to its PEP representation.
    
    Expects a JSON-format tagged value e.g. `modemUniqueId` would return
    `(unique_id, modem)` where it assumes the first word is the tag.

    Args:
        property_name: The property name, assumes using camelCase.
        include_tag: If True, a tuple is returned with the tag as the second
            element.
    
    Returns:
        A string with the original property name, or a tuple with the original
            property value in snake_case, and the tag

    """
    prop = snake_case(property_name)
    tag = None
    if is_tagged:
        if '_' not in prop:
            raise ValueError(f'Invalid tagged {property_name}')
        tag, prop = prop.split('_', 1)
    if include_tag:
        return (prop, tag)
    return prop


def tag_merge(*args) -> Union[list, dict]:
    """Merge multiple tagged property lists/dictionaries.
    
    Args:
        *args: A set of dictionaries or lists, must all be the same structure.
    
    Returns:
        Merged structure of whatever was passed in.

    """
    container_type = args[0].__class__.__name__
    if container_type not in ('list', 'dict'):
        raise ValueError('tag merge must be of list or dict type')
    if not all(arg.__class__.__name__ == container_type for arg in args):
        raise ValueError('args must all be of same type')
    if container_type == 'list':
        return list(itertools.chain(*args))
    merged = {}
    categories = [READ_ONLY, READ_WRITE]
    dict_0: dict = args[0]
    if any(k in categories for k in dict_0):
        for arg in args:
            assert isinstance(arg, dict)
            if not any(k in categories for k in arg):
                raise ValueError('Not all dictionaries are categorized')
            merged = _nested_tag_merge(arg, merged)
    else:
        for arg in args:
            assert isinstance(arg, dict)
            for key, val in arg.items():
                merged[key] = val
    return merged


def _nested_tag_merge(add: dict, merged: dict) -> dict:
    for key, val in add.items():
        if key not in merged:
            merged[key] = val
        else:
            if isinstance(merged[key], list):
                merged[key] = merged[key] + val
            else:
                assert isinstance(merged[key], dict)
                assert isinstance(val, dict)
                for nested_key, nested_val in val.items():
                    merged[key][nested_key] = nested_val
    return merged
