"""Methods for reading and writing user configuration file settings.

"""
import json
import logging
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode
from json import JSONDecodeError

_log = logging.getLogger(__name__)


APPDIR = os.getenv('APPDIR', '/home/fieldedge/fieldedge')
USERDIR = os.getenv('USERDIR', f'{APPDIR}/user')
USER_CONFIG_FILE = os.getenv('USER_CONFIG_FILE', f'{USERDIR}/user.conf')


def _is_valid_prefix(prefix) -> bool:
    return prefix is None or isinstance(prefix, str) and len(prefix) > 0


def read_user_config(filename: str = USER_CONFIG_FILE,
                     prefix: str = None) -> dict:
    """Reads user configuration from a `.env` style file.
    
    Format of the file is `key=value` with one entry per line.
    Attempts to convert boolean and numeric values.
    
    Args:
        filename (str): The full path/filename. Defaults to
            `{APPDIR}/user/config.env`, where `APPDIR` is an environment
            variable with default `/home/fieldedge/fieldedge`.
        prefix (str): Optional prefix for keys.
    
    Returns:
        A dictionary of configuration settings.
        
    """
    if not _is_valid_prefix(prefix):
        raise ValueError('Invalid prefix')
    file_config: 'dict[str, str]' = {}
    if not isinstance(filename, str):
        filename = USER_CONFIG_FILE
    if os.path.isfile(filename):
        with open(filename) as file:
            for line in file.readlines():
                if line.startswith('#') or not line.strip():
                    continue
                key, value = line.split('=', 1)
                file_config[key] = value.strip()
                if 'PASSWORD' in key.upper():
                    file_config[key] = unobscure(value)
    user_config: 'dict[str, str]' = {}
    for k, v in file_config.items():
        if isinstance(prefix, str):
            if not k.startswith(prefix):
                continue
            k = k.replace(f'{prefix}_', '', 1)
        if k in user_config:
            _log.warning('Overwriting duplicate key %s', k)
        if isinstance(v, str):
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            if ((v.startswith('{') and v.endswith('}')) or
                (v.startswith('[') and v.endswith(']'))):
                try:
                    v = json.loads(v)
                except JSONDecodeError:
                    pass
            elif v.lower() in ['true', 'false']:
                v = v.lower() == 'true'
            elif '.' in v:
                try:
                    v = float(v)
                except ValueError:
                    pass
            else:
                try:
                    v = int(v)
                except ValueError:
                    pass
        user_config[k] = v
    return user_config


def write_user_config(config: dict,
                      filename: str = USER_CONFIG_FILE,
                      prefix: str = None) -> None:
    """Writes the user config values to the `.env` style file path specified.
    
    Format of the file is `key=value` with one entry per line.
    
    Args:
        config (dict): The configuration settings dictionary.
        filename (str): The full file path/name to store into. Defaults to
            `{APPDIR}/user/config.env`, where `APPDIR` is an environment
            variable with default `/home/fieldedge/fieldedge`.
        prefix (str): Optional prefix for keys.
        
    """
    if not _is_valid_prefix(prefix):
        raise ValueError('Invalid prefix')
    if not isinstance(filename, str) or not os.path.dirname(filename):
        filename = USER_CONFIG_FILE
    old_config = {}
    lines_to_write: 'list[str]' = []
    if os.path.isfile(filename):
        old_config = read_user_config(filename, prefix)
        with open(filename) as file:
            lines_to_write = [line.strip() for line in file.readlines()]
    line_indices_to_remove = []
    for k, v in config.items():
        if k in old_config and v == old_config[k]:
            continue   # no change - skip
        if prefix:
            k = f'{prefix}_{k}'
        if 'PASSWORD' in k and v is not None:
            line_to_write = f'{k}={obscure(v)}'
        else:
            line_to_write = f'{k}={v}'
        seen = False
        for i, line in enumerate(lines_to_write):
            if line.startswith(f'{k}='):
                if seen or v is None:
                    line_indices_to_remove.append(i)
                else:   
                    lines_to_write[i] = line_to_write
                    seen = True
        if not seen and v is not None:
            lines_to_write.append(line_to_write)
    for i in sorted(line_indices_to_remove, reverse=True):
        del lines_to_write[i]
    with open(filename, 'w') as file:
        file.writelines('\n'.join(lines_to_write))


def obscure(value: str) -> str:
    """Obscures a value for simple security."""
    return urlsafe_b64encode(value.encode()).decode()


def unobscure(obscured: str) -> str:
    """Unobscures a value previously obscured."""
    return urlsafe_b64decode(obscured.encode()).decode()
     