"""Methods for interfacing to the system host.

When inside a Docker container with environment setting `DOCKER=1`:

    * `hostpipe` A legacy FieldEdge pipe writing to a log file for parsing,
    is used if the environment variable `HOSTPIPE_LOG` exists.
    * `hostrequest` An HTTP based microserver acting as a pipe, is used if the
    environment variable `HOSTREQUEST_PORT` exists.

For interacting with a remote host allowing SSH this will be used if all
environment variables `SSH_HOST`, `SSH_USER` and `SSH_PASS` are configured.

If none of the above environment variables are configured the command will
execute natively on the host shell.

"""
try:
    import paramiko
except ImportError:
    pass

import logging
import os
import http.client
import subprocess
from dataclasses import dataclass

from fieldedge_utilities import hostpipe
from fieldedge_utilities.logger import verbose_logging

_log = logging.getLogger(__name__)


@dataclass
class SshInfo:
    host: str
    user: str
    passwd: str


def _get_ssh_info() -> 'SshInfo|None':
    if os.getenv('SSH_HOST'):
        return SshInfo(os.getenv('SSH_HOST'),
                       os.getenv('SSH_USER'),
                       os.getenv('SSH_PASS'))
    return None


def host_command(command: str, **kwargs) -> str:
    """Sends a Linux command to the host and returns the response.
    
    Args:
        command (str): The shell command to send.
    
    Keyword Args:
        timeout (float): Optional timeout value if no response.
    
    """
    result = ''
    method = None
    if (str(os.getenv('DOCKER')).lower() in ['1', 'true'] or
        'test_mode' in kwargs):
        if os.getenv('HOSTPIPE_LOG') or 'pipelog' in kwargs:
            method = 'HOSTPIPE'
            valid_kwargs = ['timeout', 'noresponse', 'pipelog', 'test_mode']
            hostpipe_kwargs = {}
            for key, val in kwargs.items():
                if key in valid_kwargs:
                    hostpipe_kwargs[key] = val
                if key == 'test_mode':
                    hostpipe_kwargs[key] = val is not None
            result = hostpipe.host_command(command, **hostpipe_kwargs)
        elif os.getenv('HOSTREQUEST_PORT'):
            method = 'HOSTREQUEST'
            host = os.getenv('HOSTREQUEST_HOST', 'localhost')
            port = os.getenv('HOSTREQUEST_PORT')
            try:
                conn = http.client.HTTPConnection(host, port)
                headers = { 'Content-Type': 'text/plain' }
                conn.request('POST', '/', command, headers)
                result = conn.getresponse().read().decode()
            except ConnectionError:
                _log.error('Failed to reach HTTP server')
    elif (kwargs.get('ssh_client') is not None or _get_ssh_info() is not None):
        method = 'SSH'
        try:
            result = ssh_command(command, kwargs.get('ssh_client', None))
        except (ModuleNotFoundError, ConnectionError, NameError):
            _log.error('Failed to access SSH')
    else:
        method = 'DIRECT'
        chained = [' | ', ' || ', ' && ']
        if any(c in command for c in chained):
            args = command
            shell = True
        else:
            args = command.split(' ')
            shell = False
        try:
            res = subprocess.run(args, capture_output=True,
                                 shell=shell, check=True)
            result = res.stdout.decode() if res.stdout else res.stderr.decode()
        except subprocess.CalledProcessError as exc:
            _log.error('%s [Errno %d]: %s',exc.cmd, exc.returncode, exc.output)
    result = result.strip()
    if verbose_logging('host'):
        _log.debug('%s: %s -> %s', method, command, result)
    return result


def ssh_command(command: str, ssh_client = None) -> str:
    """Sends a host command via SSH.
    
    Args:
        command (str): The shell command to send.
        ssh_client (paramiko.SSHClient): Optional SSH client session.
    
    Returns:
        A string with the response, typically multiline separated by `\n`.
    
    Raises:
        `TypeError` if client or environment settings are invalid.
        
    """
    if (not isinstance(ssh_client, paramiko.SSHClient) and not _get_ssh_info()):
        raise TypeError('Invalid SSH client or configuration')
    if not isinstance(ssh_client, paramiko.SSHClient):
        close_client = True
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh = _get_ssh_info()
        ssh_client.connect(ssh.host, username=ssh.user, password=ssh.passwd,
                           look_for_keys=False)
    else:
        close_client = False
    _stdin, stdout, stderr = ssh_client.exec_command(command)
    res: 'list[str]' = stdout.readlines()
    if not res:
        res = stderr.readlines()
    _stdin.close()
    stdout.close()
    stderr.close()
    if close_client:
        ssh_client.close()
    return '\n'.join([l.strip() for l in res])


def get_ssh_session(**kwargs):   # -> paramiko.SSHClient:
    """Returns a connected SSH client.
    
    Keyword Args:
        hostname (str): The hostname of the SSH target.
        username (str): SSH login username.
        password (str): SSH login password.
    
    Returns:
        A `paramiko.SSHClient` if paramiko is installed.
    
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=kwargs.get('hostname', os.getenv('SSH_HOST')),
                   username=kwargs.get('username', os.getenv('SSH_USER')),
                   password=kwargs.get('password', os.getenv('SSH_PASS')),
                   look_for_keys=False)
    return client
