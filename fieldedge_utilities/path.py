"""Tools for file path and caller traces."""

import inspect
import os
from pathlib import Path


def clean_filename(filename: str) -> str:
    """Adjusts relative and shorthand filenames for OS independence.
    """
    return clean_path(filename)


def clean_path(pathname: str) -> str:
    """Adjusts relative and shorthand filenames for OS independence.
    
    Args:
        pathname: The full path/to/file
    
    Returns:
        A clean file/path name for the current OS and directory structure.
    """
    if pathname.startswith('$HOME/'):
        pathname = pathname.replace('$HOME', str(Path.home()))
    elif pathname.startswith('~/'):
        pathname = pathname.replace('~', str(Path.home()))
    elif pathname.startswith('../'):
        mod_path = Path(__file__).parent
        src_path = (mod_path / pathname).resolve()
        dir_path = os.path.dirname(os.path.realpath(__file__))
        pathname = os.path.join(dir_path, src_path)
    return pathname


def get_caller_name(depth: int = 2,
                    mod: bool = True,
                    cls: bool =False,
                    mth: bool = False) -> str:
    """Returns the name of the calling function.

    Args:
        depth: Starting depth of stack inspection.
        mod: Include module name.
        cls: Include class name.
        mth: Include method name.
    
    Returns:
        Name (string) including module[.class][.method]

    """
    stack = inspect.stack()
    start = 0 + depth
    if len(stack) < start + 1:
        return ''
    parent_frame = stack[start][0]
    name = []
    module = inspect.getmodule(parent_frame)
    if module and mod:
        name.append(module.__name__)
    if cls and 'self' in parent_frame.f_locals:
        name.append(parent_frame.f_locals['self'].__class__.__name__)
    if mth:
        codename = parent_frame.f_code.co_name
        if codename != '<module>':
            name.append(codename)
    del parent_frame, stack
    return '.'.join(name)


