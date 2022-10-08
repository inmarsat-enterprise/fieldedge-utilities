"""FieldEdge class/property helpers
"""

import json
import logging
import os
import re
from time import time

from .logger import verbose_logging

PROPERTY_CACHE_DEFAULT = int(os.getenv('PROPERTY_CACHE_DEFAULT', 5))

_log = logging.getLogger(__name__)


def snake_to_camel(snake_str: str) -> str:
    """Converts a snake_case string to camelCase."""
    words = snake_str.split('_')
    return words[0] + ''.join(w.title() for w in words[1:])


def camel_to_snake(camel_str: str) -> str:
    """Converts a camelCase string to snake_case."""
    pattern = re.compile(r'(?<!^)(?=[A-Z])')
    return pattern.sub('_', camel_str).lower()


def cache_valid(ref_time: int,
                max_age: int = PROPERTY_CACHE_DEFAULT,
                tag: str = 'value',
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
        if _vlog():
            _log.debug(f'No cached timestamp for {tag}')
        return False
    cache_age = int(time()) - ref_time
    if cache_age > max_age:
        if _vlog():
            _log.debug(f'Cached {tag} only {cache_age} seconds old'
                       f' (cache = {max_age}s)')
        return False
    _log.debug(f'Using cached {tag} ({cache_age} seconds)')
    return True


def get_class_properties(cls_instance: object,
                         ignore: 'list[str]' = [],
                         ) -> dict:
    """Returns non-hidden, non-callable properties/values of a Class instance.
    
    Args:
        cls_instance: The Class instance whose properties/values will be derived
        ignore: A list of names to ignore
    
    Returns:
        A dictionary as { 'property_name': 'property_value' }
        
    Raises:
        ValueError if cls_instance does not have a dir method.
        
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
    return props


def tag_class_properties(cls,
                         tag: str = None,
                         json: bool = True,
                         ignore: 'list[str]' = ['exposed_properties'],
                         ) -> dict:
    """Retrieves `@property`s from a class and tags them with a routing prefix.
    
    The dictionary items describe `read_only` and `config` items which each
    consist of a list of strings for the property names.
    Each property name is optionally prefixed by a `tag` for the class
    e.g. `modem_manufacturer`.
    A reserved name `exposed_properties` is ignored by default, but a list of
    values to ignore is supported.
    
    TODO: check `vars` vs `dir` use for robustness.

    Args:
        cls: The class to fetch properties from (`fset`)
        tag: A prefex to apply for identification/routing
        json: Property names are expressed in camelCase
        ignore: An optional filter of property names to ignore
    
    Returns:
        `{ 'config': [<str>], 'read_only': [<str>]}`

    """
    rw = [attr for attr, value in vars(cls).items()
          if isinstance(value, property) and
          value.fset is not None and
          attr not in ignore]
    ro = [attr for attr, value in vars(cls).items()
          if isinstance(value, property) and
          value.fset is None and
          attr not in ignore]
    if tag is not None:
        for i, prop in enumerate(rw):
            rw[i] = f'{tag}_{prop}'
        for i, prop in enumerate(ro):
            ro[i] = f'{tag}_{prop}'
    tagged = { 'config': rw, 'read_only': ro }
    if not json:
        return tagged
    json_tagged = {}
    for key, value in tagged.items():
        json_list = []
        for item in value:
            json_list.append(snake_to_camel(item))
        json_tagged[snake_to_camel(key)] = json_list
    return json_tagged


def untag_class_property(tagged_property: str,
                   tag: str = None,
                   include_tag: bool = False,
                   ) -> 'str|tuple[str, str]':
    """Reverts a JSON-format tagged property to its PEP representation.
    
    Expects a JSON-format tagged value e.g. `modemUniqueId` would return
    `(unique_id, modem)`.

    Args:
        tagged_property: The tagged property value, allowing for camelCase.
        tag: Optional to specify the tag, allowing for camelCase tags.
        include_tag: If True, a tuple is returned with the tag as the second
            element.
    
    Returns:
        A string with the original property name, or a tuple with the original
            property value in snake_case, and the tag

    """
    if isinstance(tag, str) and tagged_property.startswith(tag):
        tagged_property = tagged_property.replace(tag, f'{tag}_')
    tagged_property = camel_to_snake(tagged_property)
    parts = tagged_property.split('_', 1)
    if len(parts) > 1:
        tag = parts[0]
        prop = parts[1]
    else:
        tag = None
        prop = parts[0]
    if not include_tag:
        return prop
    return (prop, tag)


def tag_merge(*dicts: dict) -> dict:
    """Merge multiple tagged property dictionaries.
    
    Args:
        *dicts: A set of dictionaries
    
    Returns:
        Merged dictionary with: `{'config':[], 'readOnly': []}`

    """
    merged = { 'config': [], 'readOnly': [] }
    for d in dicts:
        if not isinstance(d, dict) or 'config' not in d or 'readOnly' not in d:
            raise ValueError(f'Invalid tag dictionary {d}')
        merged['config'] = merged['config'] + d['config']
        merged['readOnly'] = merged['readOnly'] + d['readOnly']
    return merged


def json_compatible(obj: object, camel_keys: bool = True) -> dict:
    """Returns a dictionary compatible with `json.dumps` function.

    Nested objects are converted to dictionaries.
    
    Args:
        obj: The source object.
        camel_keys: Flag indicating whether to convert all nested dictionary
            keys to `camelCase`.
        
    Returns:
        A dictionary with nested arrays, dictionaries and other compatible with
            `json.dumps`.

    """
    res = obj
    if camel_keys and isinstance(obj, dict):
        res = {}
        for k, v in obj.items():
            camel_key = snake_to_camel(str(k))
            res[camel_key] = json_compatible(v, camel_keys)
    try:
        json.dumps(res)
    except TypeError:
        try:
            if isinstance(res, list):
                _temp = []
                for element in res:
                    _temp.append(json_compatible(element, camel_keys))
                res = _temp
            if hasattr(res, '__dict__'):
                res = vars(res)
            if isinstance(res, dict):
                res = json_compatible(res, camel_keys)
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
        if not hasattr(other, attr) or val != vars(other)[attr]:
            return False
    return True


def _vlog() -> bool:
    return verbose_logging('classes')
