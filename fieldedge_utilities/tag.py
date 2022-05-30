"""Helper functions for converting tags between PEP and JSON styles."""
import re


def snake_to_camel(snake_str: str) -> str:
    """Converts a snake_case string to camelCase."""
    words = snake_str.split('_')
    return words[0] + ''.join(w.title() for w in words[1:])


def camel_to_snake(camel_str: str) -> str:
    """Converts a camelCase string to snake_case."""
    pattern = re.compile(r'(?<!^)(?=[A-Z])')
    return pattern.sub('_', camel_str).lower()


def tag_class_properties(cls, tag: str = None) -> dict:
    """Retrieves `@property`s from a class and tags them with a routing prefix.
    
    The dictionary items describe `read_only` and `config` items which each
    consist of a list of strings for the property names.
    Each property name is optionally prefixed by a `tag` for the class
    e.g. `modem_manufacturer`.
    
    TODO: check `vars` vs `dir` use for robustness.

    Args:
        cls: The class to fetch properties from (`fset`)
        tag: A prefex to apply for identification/routing
    
    Returns:
        `{ 'config': [<str>], 'read_only': [<str>]}`

    """
    rw = [attr for attr, value in vars(cls).items()
          if isinstance(value, property) and value.fset is not None]
    ro = [attr for attr, value in vars(cls).items()
          if isinstance(value, property) and value.fset is None]
    if tag is not None:
        for i, prop in enumerate(rw):
            rw[i] = f'{tag}_{prop}'
        for i, prop in enumerate(ro):
            ro[i] = f'{tag}_{prop}'
    return { 'config': rw, 'read_only': ro }
