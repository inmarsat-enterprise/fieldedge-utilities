"""FieldEdge class/property helpers
"""

import json
import logging
import os
import re
import inspect
import itertools
from time import time
# from abc import ABC

from .logger import verbose_logging
# from .path import get_caller_name

PROPERTY_CACHE_DEFAULT = int(os.getenv('PROPERTY_CACHE_DEFAULT', 5))
READ_ONLY = 'info'
READ_WRITE = 'config'

_log = logging.getLogger(__name__)


def snake_to_camel(snake_str: str, skip_caps: bool = False) -> str:
    """Converts a snake_case string to camelCase.
    
    Args:
        snake_str: The string to convert.
        skip_caps: If `True` will return CAPITAL_CASE unchanged
    
    Returns:
        The input string in camelCase structure.
        
    """
    if not isinstance(snake_str, str) or not snake_str:
        raise ValueError('Invalid string input')
    if snake_str.isupper() and skip_caps:
        return snake_str
    words = snake_str.split('_')
    if len(words) == 1 and words[0] == snake_str:
        return snake_str
    return words[0].lower() + ''.join(w.title() for w in words[1:])


def camel_to_snake(camel_str: str, skip_caps: bool = False) -> str:
    """Converts a camelCase string to snake_case.
    
    Args:
        camel_str: The string to convert.
        skip_caps: A flag if `True` will return CAPITAL_CASE unchanged.
        
    Returns:
        The input string in snake_case format.
        
    Raises:
        `ValueError` if camel_str is not a valid string.
        
    """
    if not isinstance(camel_str, str) or not camel_str:
        raise ValueError('Invalid string input')
    if camel_str.isupper() and skip_caps:
        return camel_str
    snake_str = re.compile(r'(?<!^)(?=[A-Z])').sub('_', camel_str).lower()
    if '__' in snake_str:
        words = snake_str.split('__')
        snake_str = '_'.join(f'{word.replace("_", "")}' for word in words)
    return snake_str


def cache_valid(ref_time: 'int|float',
                max_age: int = PROPERTY_CACHE_DEFAULT,
                tag: str = None,
                ) -> bool:
    """Determines if cached property value is younger than the threshold.
    
    `PROPERTY_CACHE_DEFAULT` = 5 seconds. Can be overridden as an environment
    variable.
    Many FieldEdge Class properties are derived from *slow* operations but may
    be queried in rapid succession and can be inter-dependent. Caching reduces
    query time for such values.
    
    Args:
        ref: The reference time (seconds) of the previously cached value
            (typically a private property held in a dictionary)
        max_age: The maximum age of the cached value in seconds.
        tag: The name of the property (used for debug purposes).
    
    Returns:
        False is the cache is stale and a new value should be queried from the
            raw resource.

    """
    if ref_time is None:
        return False
    if not isinstance(ref_time, int):
        try:
            ref_time = int(ref_time)
        except:
            raise ValueError('Invalid reference time')
    cache_age = int(time()) - ref_time
    if cache_age > max_age:
        if _vlog():
            tag = tag or '?'
            _log.debug(f'Cached {tag} only {cache_age} seconds old'
                       f' (cache = {max_age}s)')
        return False
    if tag:
        _log.debug(f'Using cached {tag} ({cache_age} seconds)')
    return True


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
    if not hasattr_static(instance, property_name):
        raise ValueError(f'Object has no property {property_name}')
    prop = inspect.getattr_static(instance, property_name)
    try:
        return prop.fset is None
    except AttributeError:
        return False
        
    
def property_is_async(instance: object, property_name: str) -> bool:
    if not hasattr_static(instance, property_name):
        raise ValueError(f'Object has no property {property_name}')
    if inspect.isawaitable(getattr(instance, property_name)):
        return True
    return False

    
def get_class_tag(cls: type) -> str:
    if isinstance(cls, type):
        return cls.__name__.lower()
    return cls.__class__.__name__.lower()


def get_class_properties(cls: type,
                         ignore: 'list[str]' = [],
                         ) -> 'list[str]|dict[str, list]':
    """Returns non-hidden, non-callable properties/values of a Class instance.
    
    Also ignores CAPITAL_CASE attributes which are assumed to be constants.
    
    Args:
        cls: The Class whose properties will be derived
        ignore: A list of names to ignore (optional)
    
    Returns:
        A list of exposed property names.
        
    Raises:
        ValueError if `cls` does not have a `dir()` method or is not a `type`.
        
    """
    if not dir(cls):
        raise ValueError('Invalid cls_instance - must have dir() method')
    if isinstance(cls, type) and '__slots__' not in dir(cls):
        _log.warning(f'No __slots__: attributes in __init__ will be missed')
    attrs = [attr for attr in dir(cls)
             if not attr.startswith(('_',)) and
             attr not in ignore and
             not callable(inspect.getattr_static(cls, attr)) and
             not attr.isupper()]
    return attrs


def get_instance_properties_values(instance: object) -> dict:
    """Returns the instance properties and values."""
    props_list = get_class_properties(instance)
    props_values = {}
    for prop in props_list:
        props_values[prop] = getattr(instance, prop)
    return props_values


def tag_class_properties(cls: type,
                         tag: str = None,
                         auto_tag: bool = True,
                         json: bool = True,
                         categorize: bool = False,
                         ignore: 'list[str]' = [],
                         ) -> 'list|dict':
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
    if isinstance(cls, type) and _vlog():
        _log.debug('Processing for class type')
    # elif issubclass(cls, ABC):
    #     _log.debug('Processing for microservice')
    if auto_tag and not tag:
        tag = get_class_tag(cls)
    class_props = get_class_properties(cls,
                                       ignore)
    if not categorize:
        return [tag_class_property(prop, tag, json) for prop in class_props]
    result = {}
    for prop in class_props:
        if property_is_read_only(cls, prop):
            if READ_ONLY not in result:
                result[READ_ONLY] = []
            result[READ_ONLY].append(tag_class_property(prop, tag, json))
        else:
            if READ_WRITE not in result:
                result[READ_WRITE] = []
            result[READ_WRITE].append(tag_class_property(prop, tag, json))
    return result


def tag_class_property(prop: str,
                       tag_or_cls: 'str|type' = None,
                       json: bool = True) -> str:
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
    if json:
        return snake_to_camel(f'{tagged}')
    return f'{tag}_{prop}'


def untag_class_property(property_name: str,
                         is_tagged: bool = True,
                         include_tag: bool = False,
                         ) -> 'str|tuple[str, str]':
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
    if '_' not in camel_to_snake(property_name):
        raise ValueError(f'Invalid camelCase {property_name}')
    if is_tagged:
        tag, prop = camel_to_snake(property_name).split('_', 1)
    else:
        tag, prop = None, camel_to_snake(property_name)
    if not include_tag:
        return prop
    return (prop, tag)


def tag_merge(*args) -> 'list|dict':
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
            for k, v in arg.items():
                merged[k] = v      
    return merged


def _nested_tag_merge(add: dict, merged: dict) -> dict:
    for k, v in add.items():
        if k not in merged:
            merged[k] = v
        else:
            if isinstance(merged[k], list):
                merged[k] = merged[k] + v
            else:
                assert isinstance(merged[k], dict)
                assert isinstance(v, dict)
                for nk, nv in v.items():
                    merged[k][nk] = nv
    return merged


def json_compatible(obj: object,
                    camel_keys: bool = True,
                    skip_caps: bool = True) -> dict:
    """Returns a dictionary compatible with `json.dumps` function.

    Nested objects are converted to dictionaries.
    
    Args:
        obj: The source object.
        camel_keys: Flag indicating whether to convert all nested dictionary
            keys to `camelCase`.
        skip_caps: Preserves `CAPITAL_CASE` keys if True
        
    Returns:
        A dictionary with nested arrays, dictionaries and other compatible with
            `json.dumps`.

    """
    res = obj
    if camel_keys:
        if isinstance(obj, dict):
            res = {}
            for k, v in obj.items():
                if ((isinstance(k, str) and k.isupper() and skip_caps) or
                    not isinstance(k, str)):
                    # no change
                    camel_key = k
                else:
                    camel_key = snake_to_camel(str(k))
                if camel_key != k and _vlog():
                    _log.debug(f'Changed {k} to {camel_key}')
                res[camel_key] = json_compatible(v, camel_keys, skip_caps)
        elif isinstance(obj, list):
            res = []
            for item in obj:
                res.append(json_compatible(item, camel_keys, skip_caps))
    try:
        json.dumps(res)
    except TypeError:
        try:
            if isinstance(res, list):
                _temp = []
                for element in res:
                    _temp.append(json_compatible(element,
                                                 camel_keys,
                                                 skip_caps))
                res = _temp
            if hasattr(res, '__dict__'):
                res = json_compatible(get_instance_properties_values(res))
            if isinstance(res, dict):
                res = json_compatible(res, camel_keys, skip_caps)
        except Exception as err:
            _log.error(err)
    finally:
        return res


def equivalent_attributes(ref: object,
                          other: object,
                          exclude: 'list[str]' = [],
                          dbg: str = '',
                          ) -> bool:
    """Confirms attribute equivalence between objects of the same type.
    
    Args:
        ref: The reference object being compared to.
        other: The object comparing against the reference.
        exclude: Optional list of attribute names to exclude from comparison.
    
    Returns:
        True if all (non-excluded) attribute name/values match.

    """
    if type(ref) != type(other):
        return False
    if not hasattr(ref, '__dict__') or not hasattr(other, '__dict__'):
        return ref == other
    if dbg:
        dbg += '.'
    for attr in dir(ref):
        if attr.startswith('__') or attr in exclude:
            continue
        if not hasattr(other, attr):
            _log.debug(f'Other missing {dbg}{attr}')
            return False
        ref_val = getattr(ref, attr)
        if callable(ref_val):
            continue
        other_val = getattr(other, attr)
        if any(hasattr(ref_val, a) for a in ['__dict__', '__slots__']):
            if not equivalent_attributes(ref_val, other_val, dbg=attr):
                return False
        elif ref_val != other_val:
            _log.debug(f'{dbg}{attr} mismatch')
            return False
    return True


def _vlog() -> bool:
    return verbose_logging('classes')
