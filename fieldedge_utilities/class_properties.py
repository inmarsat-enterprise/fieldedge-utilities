"""FieldEdge class/property helpers
"""

import json
import logging
import os
import re
import itertools
from time import time

from .logger import verbose_logging
from .path import get_caller_name

PROPERTY_CACHE_DEFAULT = int(os.getenv('PROPERTY_CACHE_DEFAULT', 5))

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


def get_class_properties(cls_instance: object,
                         ignore: 'list[str]' = [],
                         categorize: bool = False,
                         ) -> 'dict|dict[str, dict]':
    """Returns non-hidden, non-callable properties/values of a Class instance.
    
    Args:
        cls_instance: The Class instance whose properties/values will be derived
        ignore: A list of names to ignore (optional)
        categorize: If `True` the properties will be grouped as `read_only` or
            `read_write`.
    
    Returns:
        A dictionary as `{ 'property': <value> }`. If `categorize`
            flag is set the return dictionary structure is:
            `{ 'read_write': { 'property': <value> },
            'read_only': { 'property': <value> } }`
        
    Raises:
        ValueError if cls_instance does not have a `dir` method.
        
    """
    if not dir(cls_instance):
        raise ValueError('Invalid cls_instance - must have dir() method')
    props = {}
    props_list = [a for a in dir(cls_instance)
                  if not a.startswith(('_', 'properties')) and
                  a not in ignore and
                  not callable(getattr(cls_instance, a))]
    for prop in props_list:
        props[prop] = getattr(cls_instance, prop)
    if not categorize:
        return props
    ro_props = [attr for attr, val in vars(cls_instance.__class__).items()
                if isinstance(val, property) and val.fset is None and
                attr not in ignore]
    read_only = {}
    read_write = {}
    for prop in props:
        if prop in ro_props:
            read_only[prop] = props[prop]
        else:
            read_write[prop] = props[prop]
    categorized = {}
    if read_only:
        categorized['read_only'] = read_only
    if read_write:
        categorized['read_write'] = read_write
    return categorized


def tag_class_properties(instance: object,
                         tag: str = None,
                         json: bool = True,
                         categorize: bool = False,
                         include_values: bool = False,
                         ignore: 'list[str]' = [],
                         ) -> 'list|dict':
    """Retrieves the class public properties tagged with a routing prefix.
    
    If a `tag` is not provided, the lowercase name of the instance's class will
    be used.
    
    Using the defaults will return a simple list of tagged property names
    with the form `['tagProp1Name', 'tagProp2Name']`
    
    If `categorize` is `True` a dictionary is returned of the form
    `{ 'read_only': ['tagProp1Name'], 'read_write': ['tagProp2Name']}` where
    `read_only` or `read_write` are not present if no properties meet the
    respective criteria. If `include_values` is also `True` each list will be
    replaced by a nested dictionary
    `{ 'tagProp1Name': <prop1_value>, 'tagProp2Name': <prop2_value> }`
    
    If `categorize` is `False` and `include_values` is `True` then a simple
    dictionary of tagged names and values will be returned with the form
    `{ 'tagProp1Name': <prop1_value>, 'tagProp2Name': <prop2_value> }`
    
    If `json` is `False` the above applies but property names will use
    their original case e.g. `tag_prop1_name`
    
    Args:
        instance: A class instance to tag.
        tag: The name of the routing prefix. If `None`, the calling function's
            module `__name__` will be used.
        json: A flag indicating whether to use camelCase keys.
        categorize: A flag indicating whether to group as `read_only` and
            `read_write`.
        include_values: A flag indicating whether to return values or just
            a list of property names.
        ignore: A list of property names to ignore.
    
    Retuns:
        A dictionary or list of strings (see docstring).
        
    """
    if not isinstance(tag, str) or not tag:
        tag = get_tag_class(instance)
    class_props = get_class_properties(instance, ignore, categorize)
    if not categorize:
        if not include_values:
            return [tag_property(tag, prop, json) for prop in class_props]
        result = {}
        for prop, val in class_props.items():
            result[tag_property(tag, prop, json)] = val
        return result
    result = {}
    for category, props in class_props.items():
        assert isinstance(props, dict)
        if not include_values:
            result[category] = [tag_property(tag, prop, json) for prop in props]
        else:
            result[category] = {}
            for prop, val in props.items():
                result[category][tag_property(tag, prop, json)] = val
    return result


def tag_property(tag: str, prop: str, json: bool = True):
    if json:
        return snake_to_camel(f'{tag}_{prop}')
    return f'{tag}_{prop}'


def get_tag_class(instance: object) -> str:
    return instance.__class__.__name__.lower()


def untag_class_property(tagged_property: str,
                         include_tag: bool = False,
                         ) -> 'str|tuple[str, str]':
    """Reverts a JSON-format tagged property to its PEP representation.
    
    Expects a JSON-format tagged value e.g. `modemUniqueId` would return
    `(unique_id, modem)` where it assumes the first word is the tag.

    Args:
        tagged_property: The tagged property value, allowing for camelCase.
        include_tag: If True, a tuple is returned with the tag as the second
            element.
    
    Returns:
        A string with the original property name, or a tuple with the original
            property value in snake_case, and the tag

    """
    if '_' not in camel_to_snake(tagged_property):
        raise ValueError(f'Invalid camelCase {tagged_property}')
    tag, prop = camel_to_snake(tagged_property).split('_', 1)
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
    categories = ['read_only', 'read_write']
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
                if camel_key != k:
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
                simplified = get_class_properties(res)
                res = json_compatible(simplified)
            if isinstance(res, dict):
                res = json_compatible(res, camel_keys, skip_caps)
        except Exception as err:
            _log.error(err)
    finally:
        return res


def equivalent_attributes(reference: object,
                          other: object,
                          exclude: 'list[str]' = None,
                          ) -> bool:
    """Confirms attribute equivalence between objects of the same type.
    
    Args:
        reference: The reference object being compared to.
        other: The object comparing against the reference.
        exclude: Optional list of attribute names to exclude from comparison.
    
    Returns:
        True if all (non-excluded) attribute name/values match.

    """
    if type(reference) != type(other):
        return False
    if not hasattr(reference, '__dict__') or not hasattr(other, '__dict__'):
        return reference == other
    for attr, val in vars(reference).items():
        if exclude is not None and attr in exclude:
            continue
        if not hasattr(other, attr):
            _log.warning(f'Other missing {attr}')
            return False
        if val != vars(other)[attr]:
            _log.warning(f'{val} != {vars(other)[attr]}')
            return False
    return True


def _vlog() -> bool:
    return verbose_logging('classes')
