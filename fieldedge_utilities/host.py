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

from . import hostpipe
from .logger import verbose_logging

_log = logging.getLogger(__name__)

DOCKER = os.getenv('DOCKER', None) == '1'
HOSTPIPE_LOG = os.getenv('HOSTPIPE_LOG')
HOSTREQUEST_HOST = os.getenv('HOSTREQUEST_HOST', 'localhost')
HOSTREQUEST_PORT = os.getenv('HOSTREQUEST_PORT')
SSH_HOST = os.getenv('SSH_HOST')
SSH_USER = os.getenv('SSH_USER')
SSH_PASS = os.getenv('SSH_PASS')
TEST_MODE = os.getenv('TEST_MODE')


def host_command(command: str, timeout: float = None) -> str:
    """Sends a Linux command to the host and returns the response."""
    result = ''
    method = None
    if DOCKER:
        if HOSTPIPE_LOG:
            method = 'HOSTPIPE'
            kwargs = { 'test_mode': TEST_MODE is not None }
            if timeout:
                kwargs['timeout'] = timeout
            result = hostpipe.host_command(command, **kwargs)
        elif HOSTREQUEST_PORT:
            method = 'HOSTREQUEST'
            try:
                conn = http.client.HTTPConnection(host=HOSTREQUEST_HOST,
                                                port=HOSTREQUEST_PORT)
                headers = { 'Content-Type': 'text/plain' }
                conn.request('POST', '/', command, headers)
                result = conn.getresponse().read().decode()
            except ConnectionError:
                _log.error('Failed to reach HTTP server')
    elif SSH_HOST and SSH_USER and SSH_PASS:
        method = 'SSH'
        try:
            result = ssh_command(command)
        except (ModuleNotFoundError, ConnectionError):
            _log.error('Failed to access SSH')
    else:
        method = 'DIRECT'
        args = command if '|' in command else command.split(' ')
        shell = '|' in command
        res = subprocess.run(args, capture_output=True, shell=shell, check=True)
        result = res.stdout.decode() if res.stdout else res.stderr.decode()
    result = result.strip()
    if verbose_logging('host'):
        _log.debug('%s: %s -> %s', method, command, result)
    return result


def ssh_command(command: str) -> str:
    """Sends a host command via SSH."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS,
                    look_for_keys=False)
    _stdin, stdout, stderr = client.exec_command(command)
    res: 'list[str]' = stdout.readlines()
    if not res:
        res = stderr.readlines()
    client.close()
    return '\n'.join([l.strip() for l in res])
