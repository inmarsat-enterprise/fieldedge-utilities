"""Tools for file path and caller traces."""
import os
import sys
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
    
    Raises:
        `FileNotFoundError` if the clean path cannot be determined.
    
    """
    if '/' not in pathname:
        return pathname
    if pathname.startswith('$HOME/'):
        pathname = pathname.replace('$HOME', str(Path.home()))
    elif pathname.startswith('~/'):
        pathname = pathname.replace('~', str(Path.home()))
    if os.path.isdir(os.path.dirname(pathname)):
        return os.path.realpath(pathname)
    else:
        raise FileNotFoundError(f'Path {pathname} not found')


def get_caller_name(depth: int = 2,
                    mod: bool = True,
                    cls: bool =False,
                    mth: bool = False) -> str:
    """Returns the name of the calling module/class/function.

    Args:
        depth: Starting depth of stack inspection. Default 2 refers to the
            prior entry in the stack relative to this function.
        mod: Include module name.
        cls: Include class name.
        mth: Include method name.
    
    Returns:
        Name (string) including module[.class][.method]

    """
    try:
        frame = sys._getframe(depth)
    except (ValueError, AttributeError):
        return ''
    name_parts = []
    if mod:
        module_name = frame.f_globals.get('__name__')
        if module_name:
            name_parts.append(module_name)
    if cls:
        self_obj = frame.f_locals.get('self')
        if self_obj is not None:
            name_parts.append(type(self_obj).__name__)
    if mth:
        code_name = frame.f_code.co_name
        if code_name != '<module>':
            name_parts.append(code_name)
    return '.'.join(name_parts)
