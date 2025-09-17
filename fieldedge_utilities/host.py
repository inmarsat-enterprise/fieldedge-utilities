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

import http.client
import json
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

try:
    import paramiko
    _HAS_PARAMIKO = True
except ImportError:
    paramiko = None
    _HAS_PARAMIKO = False

from fieldedge_utilities import hostpipe
from fieldedge_utilities.logger import verbose_logging

_log = logging.getLogger(__name__)


@dataclass
class SshInfo:
    host: str
    user: str
    passwd: str


def _require_paramiko():
    if not _HAS_PARAMIKO:
        raise ModuleNotFoundError('Paramiko is required for SSH operations')


def _get_ssh_info() -> SshInfo|None:
    try:
        host = os.getenv('SSH_HOST')
        user = os.getenv('SSH_USER')
        passwd = os.getenv('SSH_PASS')
        if not all(isinstance(x, str) and len(x) > 0
                   for x in [host, user, passwd]):
            return None
        return SshInfo(host, user, passwd)  # type: ignore
    except Exception:
        return None


def host_command(command: str, **kwargs) -> str:
    """Sends a Linux command to the host and returns the response.
    
    Args:
        command (str): The shell command to send.
    
    Keyword Args:
        timeout (float): Optional timeout value if no response.
    
    """
    
    def result_err(context: Any = None) -> str:
        result = f'sh: {command.split()[0]}: command failed'
        if context is not None:
            result += f' ({context})'
        return result
    
    result = ''
    method = None
    timeout = kwargs.get('timeout', 10)
    
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
        
        elif os.getenv('HOSTREQUEST_PORT') or 'hostrequest' in kwargs:
            method = 'HOSTREQUEST'
            host = os.getenv('HOSTREQUEST_HOST', 'localhost')
            port = int(os.getenv('HOSTREQUEST_PORT', '0')) or None
            conn = None
            try:
                conn = http.client.HTTPConnection(host, port, timeout)
                headers = { 'Content-Type': 'text/plain' }
                conn.request('POST', '/', command, headers)
                resp = conn.getresponse()
                body = resp.read().decode()
                if resp.status != 200:
                    result = body or result_err(f'status {resp.status}'
                                                f' {resp.reason}')
                    _log.error('HostRequest %s -> %s', command, result)
                else:
                    try:
                        parsed = json.loads(body)
                    except (json.JSONDecodeError, TypeError):
                        parsed = None
                    if (isinstance(parsed, dict) and 
                        any(s in parsed for s in {'stdout','stderr'})):
                        stdout = parsed.get('stdout', '')
                        stderr = parsed.get('stderr', '')
                        returncode = parsed.get('returncode', 0)
                        result = '\n'.join(filter(None, [stdout, stderr]))
                        if returncode and verbose_logging('host'):
                            _log.debug('HOSTREQUEST returncode=%s for cmd=%s',
                                    returncode, command)
                    else:
                        result = body
            except Exception as exc:
                _log.error('HOSTREQUEST command failed: %s', exc)
                result = result_err('HOSTREQUEST unreachable')
            finally:
                if conn:
                    conn.close()
    
    elif (kwargs.get('ssh_client') is not None or _get_ssh_info() is not None):
        method = 'SSH'
        try:
            result = ssh_command(command, kwargs.get('ssh_client', None))
        except Exception as exc:
            _log.error('SSH command failed: %s', exc)
            result = result_err('SSH failure')
    
    else:
        method = 'DIRECT'
        chained = ['|', '||', '&&', '>', '>>', '2>', '$(', '*', '?']
        shell = any(c in command for c in chained)
        try:
            args = command if shell else shlex.split(command)
            res = subprocess.run(
                args,
                capture_output=True,
                shell=shell,
                check=True,
                timeout=timeout,
                encoding='utf-8',   # ensure consistent decode
                errors='replace',   # avoid UnicodeDecodeError
            )
            result = '\n'.join(filter(None, [res.stdout, res.stderr]))
            if not result.strip() and res.returncode != 0:
                result = result_err(f'exit code {res.returncode}')
        except Exception as exc:
            _log.error('DIRECT command failed: %s', exc)
            result = result_err()
            if isinstance(exc, subprocess.TimeoutExpired):
                result += f' (timed out after {timeout} seconds)'
            elif hasattr(exc, 'returncode'):
                result += f' (exit code {getattr(exc, "returncode")})'
            
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
    _require_paramiko()
    assert paramiko is not None
    if (not isinstance(ssh_client, paramiko.SSHClient) and not _get_ssh_info()):
        raise TypeError('Invalid SSH client or configuration')
    if not isinstance(ssh_client, paramiko.SSHClient):
        close_client = True
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh = _get_ssh_info()
        if not ssh:
            raise ConnectionError('Unable to establish SSH connection')
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
    return '\n'.join([line.strip() for line in res])


def get_ssh_session(**kwargs):   # -> paramiko.SSHClient:
    """Returns a connected SSH client.
    
    Keyword Args:
        hostname (str): The hostname of the SSH target.
        username (str): SSH login username.
        password (str): SSH login password.
    
    Returns:
        A `paramiko.SSHClient` if paramiko is installed.
    
    """
    _require_paramiko()
    assert paramiko is not None
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=kwargs.get('hostname', os.getenv('SSH_HOST')),
                   username=kwargs.get('username', os.getenv('SSH_USER')),
                   password=kwargs.get('password', os.getenv('SSH_PASS')),
                   look_for_keys=False)
    return client


class HostAdapter:
    """Unified interface for executing commands on the host.

    Decides automatically between:
    * DIRECT (local subprocess)
    * SSH (remote host)
    * HOSTREQUEST (HTTP microserver for Docker)
    * HOSTPIPE (legacy file pipe)

    Optional kwargs are forwarded to the underlying implementation.
    """

    def __init__(self, **defaults):
        self._simulate_map: Optional[dict[str, str]] = None
        simulate_commands = defaults.pop('simulate_commands', None)
        if isinstance(simulate_commands, dict):
            self._simulate_map = simulate_commands
        self.defaults = defaults
        self.ssh_client = None
    
    @property
    def is_simulating(self) -> bool:
        return self._simulate_map is not None
    
    @property
    def is_ssh(self) -> bool:
        if self.is_simulating:
            return False
        if self.defaults.get('ssh_client') is not None:
            return True
        return False
    
    @property
    def is_hostrequest(self) -> bool:
        if self.is_simulating:
            return False
        return self.defaults.get('hostrequest') is not None
    
    @property
    def is_direct(self) -> bool:
        if self.is_simulating:
            return False
        return not (self.is_ssh or self.is_hostrequest)
     
    def enable_simulation(self, response_map: dict[str, str]):
        if (not isinstance(response_map, dict) or
            not all(isinstance(k, str) and isinstance(v, str)
                    for k, v in response_map.items())):
            raise ValueError('Invalid response map')
        self._simulate_map = response_map
    
    def disable_simulation(self):
        self._simulate_map = None

    def run(self, command: str, **kwargs) -> str:
        if self._simulate_map is not None:
            if command in self._simulate_map:
                return self._simulate_map[command]
            else:
                for candidate in self._simulate_map:
                    match = re.search(r'<[^<>]+>', candidate)
                    if match:
                        if command[:match.start()] == candidate[:match.start()]:
                            return self._simulate_map[candidate]
            return f'sh: {command.split()[0]}: command not found (SIMULATOR)'
        opts = {**self.defaults, **kwargs}
        return host_command(command, **opts)

    def get_ssh_session(self, **kwargs):
        _require_paramiko()
        assert paramiko is not None
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=kwargs.get('hostname', os.getenv('SSH_HOST')),
                       username=kwargs.get('username', os.getenv('SSH_USER')),
                       password=kwargs.get('password', os.getenv('SSH_PASS')),
                       look_for_keys=False)
        self.ssh_client = client
        return client

    def close_ssh(self):
        if self.ssh_client:
            self.ssh_client.close()
            self.ssh_client = None
