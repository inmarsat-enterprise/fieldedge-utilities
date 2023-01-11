import os
from base64 import urlsafe_b64decode, urlsafe_b64encode


APPDIR = os.getenv('APPDIR', '/home/fieldedge/fieldedge')
USERDIR = os.getenv('USERDIR', f'{APPDIR}/user')
USER_CONFIG_FILE = os.getenv('USER_CONFIG_FILE', f'{USERDIR}/config.env')


def read_user_config(filename: str = USER_CONFIG_FILE) -> dict:
    """Reads user configuration from a `.env` style file.
    
    Format of the file is `CONST_CASE=value` with one entry per line.
    
    Args:
        filename: The full path/filename
    
    Returns:
        A dictionary of configuration settings.
        
    """
    user_config = {}
    if not isinstance(filename, str):
        filename = USER_CONFIG_FILE
    if os.path.isfile(filename):
        with open(filename) as f:
            for line in f.readlines():
                if line.startswith('#') or not line.strip():
                    continue
                key, value = line.split('=', 1)
                user_config[key] = value.strip()
                if 'PASSWORD' in key:
                    user_config[key] = unobscure(value)
    return user_config


def write_user_config(config: dict, filename: str = USER_CONFIG_FILE) -> None:
    """Writes the user config values to the file path specified.
    
    Keys are converted to `CONST_CASE`.
    
    Args:
        config: The configuration settings dictionary.
        filename: The full file path/name to store into. Defaults to
            `{APPDIR}/user/config.env`, where `APPDIR` is an environment
            variable with default `/home/fieldedge/fieldedge`.
        
    """
    lines_to_write: 'list[str]' = []
    keys_written: 'list[str]' = []
    if not isinstance(filename, str) or not os.path.dirname(filename):
        filename = USER_CONFIG_FILE
    if os.path.isfile(filename):
        with open(filename) as f:
            for line in f.readlines():
                if line.startswith('#') or not line.strip():
                    continue
                file_key, file_value = line.strip().split('=', 1)
                if file_key in config:
                    keys_written.append(file_key)
                    if 'PASSWORD' in file_key:
                        file_value = unobscure(file_value)
                    if file_value != config[file_key]:
                        new_value = config[file_key]
                        if 'PASSWORD' in file_key:
                            new_value = obscure(new_value)
                        lines_to_write.append(f'{file_key}={new_value}')
                        continue
                lines_to_write.append(line.strip())
    for k, v in config.items():
        if k in keys_written:
            continue
        if 'PASSWORD' in k:
            lines_to_write.append(f'{k}={obscure(v)}') 
        else:
            lines_to_write.append(f'{k}={v}')
    with open(filename, 'w') as f:
        f.writelines('\n'.join(lines_to_write))


def obscure(value: str) -> str:
    """Obscures a value for simple security."""
    return urlsafe_b64encode(value.encode()).decode()


def unobscure(obscured: str) -> str:
    """Unobscures a value previously obscured."""
    return urlsafe_b64decode(obscured.encode()).decode()
     