"""Tools for file path and caller traces."""

import inspect
import os
from pathlib import Path


def clean_filename(filename: str) -> str:
    """Adjusts relative and shorthand filenames for OS independence.
    
    Args:
        filename: The full path/to/file
    
    Returns:
        A clean file/path name for the current OS and directory structure.
    """
    if filename.startswith('$HOME/'):
        filename = filename.replace('$HOME', str(Path.home()))
    elif filename.startswith('~/'):
        filename = filename.replace('~', str(Path.home()))
    elif filename.startswith('../'):
        mod_path = Path(__file__).parent
        src_path = (mod_path / filename).resolve()
        dir_path = os.path.dirname(os.path.realpath(__file__))
        filename = os.path.join(dir_path, src_path)
    return filename


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


