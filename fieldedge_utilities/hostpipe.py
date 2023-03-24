"""Operations for interacting with the hostpipe service from a Docker container.

Since commands passed in this way will be run as root, they are preambled by
`runuser -u {user} --` unless they begin with `sudo` in which case `sudo` will
be removed and the command run directly as root.

It assumes the architecture runs from a directory structure where the hostpipe
fifo is called ./hostpipe/pipe relative to the main app launch directory.

Hostpipe log entries are comma-separated values structured as:
`<iso_timestamp>,[<log_level>],<command or result>=<data>`

References environment variables:

* `HOST_USER` (default: fieldedge)
* `HOSTPIPE_TIMEOUT` float (default: 0.25)
* `MAX_FILE_SIZE` int MegaBytes (default 2)

"""
import logging
import os
from datetime import datetime
from logging import DEBUG
from subprocess import TimeoutExpired, run
from time import sleep, time

from .logger import verbose_logging

_log = logging.getLogger(__name__)

APP_ENV = os.getenv('APP_ENV', 'docker')
HOST_USER = os.getenv('HOST_USER', 'fieldedge')
HOSTPIPE_PATH = os.getenv('HOSTPIPE_PATH', './hostpipe/pipe')
HOSTPIPE_LOG = os.getenv('HOSTPIPE_LOG', './logs/hostpipe.log')
CMD_TAG = ',command='
RES_TAG = ',result='

HOSTPIPE_TIMEOUT = float(os.getenv('HOSTPIPE_TIMEOUT', 0.25))
MAX_FILE_SIZE = int(os.getenv('HOSTPIPE_LOGFILE_SIZE', 2)) * 1024 * 1024
HOSTPIPE_LOG_ITERATION_MAX = int(os.getenv('HOSTPIPE_LOG_ITERATION_MAX', 15))


def host_command(command: str,
                 noresponse: bool = False,
                 timeout: float = HOSTPIPE_TIMEOUT,
                 pipelog: str = None,
                 test_mode: bool = False,
                 ) -> str:
    """Sends a host command to a pipe (from the Docker container).
    
    The response is read from the hostpipe.log file assuming the fieldedge-core
    script is in place to echo command and response into a log.
    Care should be taken to ensure the timeout is sufficient for the response,
    and the calling function must handle an empty string response.
    
    `HOSTPIPE_TIMEOUT` is 0.25 seconds by default, configurable via environment.

    Args:
        command: The command to be executed on the host.
        noresponse: Flag if set don't look for a response.
        timeout: The time in seconds to wait for a response (default 0.25).
        pipelog: Override default hostpipe.log, typically used with test_mode.
        test_mode: Boolean to mock responses.
    
    Returns:
        A string with the command response, or empty if no response received.
    
    Raises:
        TimeoutError if hostpipe does not respond within timeout.
        FileNotFoundError if the hostpipe log cannot be found.

    """
    modcommand = _apply_preamble(command)
    command_time = time()
    if not test_mode:
        _log.debug(f'Sending {modcommand} to hostpipe via shell')
        try:
            run(f'echo "{_escaped_command(modcommand)}" > {HOSTPIPE_PATH} &',
                shell=True,
                timeout=timeout)
        except TimeoutExpired:
            err = f'Command {command} timed out waiting for hostpipe'
            _log.error(err)
            raise TimeoutError(err)
    else:
        _log.info(f'test_mode received command: {command}')
    if noresponse:
        return f'{command} sent'
    pipelog = pipelog or HOSTPIPE_LOG
    if not os.path.isfile(pipelog):
        raise FileNotFoundError(f'Could not find file {pipelog}')
    response_str = host_get_response(command,
                                     command_time=command_time,
                                     pipelog=pipelog,
                                     timeout=timeout,
                                     test_mode=test_mode,
                                     ).strip()
    deleted_count = _maintain_pipelog(pipelog)
    if deleted_count > 0:
        _log.info(f'Removed {deleted_count} oldest lines from {pipelog}')
    if _log.getEffectiveLevel() == DEBUG:
        if response_str == '':
            abv_response = '<no response>'
        elif len(response_str) < 25:
            abv_response = response_str.replace('\n', ';')
        else:
            abv_response = response_str[:20].replace("\n", ";") + '...'
        _log.debug(f'Hostpipe: {command} -> {abv_response}')
    return response_str


def _apply_preamble(command: str) -> str:
    if '$HOME' in command:
        command = command.replace('$HOME', f'/home/{HOST_USER}')
    if APP_ENV.lower() != 'docker':
        return command
    preamble = ''
    if command.startswith('sudo '):
        command = command.replace('sudo ', '')
    elif 'runuser' not in command:
        preamble = f'runuser -u {HOST_USER} -- '
    return f'{preamble}{command}'


def _escaped_command(command: str) -> str:
    escaped_command = ''
    for c in command:
        if c == '"':
            escaped_command += r'\\\"'
        else:
            escaped_command += c
    return escaped_command


def _get_line_ts(line: str) -> float:
    iso_time = line.split(',')[0]
    if '.' not in iso_time:
        iso_time = iso_time.replace('Z', '.000Z')
    utc_dt = datetime.strptime(iso_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    return (utc_dt - datetime(1970, 1, 1)).total_seconds()


def host_get_response(command: str,
                      command_time: float = None,
                      pipelog: str = None,
                      timeout: float = HOSTPIPE_TIMEOUT,
                      test_mode: bool = False,
                      ) -> str:
    """Retrieves the response to the command from the host pipe _log.
    
    `HOSTPIPE_TIMEOUT` is 0.25 seconds by default, configurable via environment.
    
    Args:
        command: The host command sent previously.
        timeout: The maximum time in seconds to try for a response.
    
    Returns:
        A string concatenating all the response lines following the command.
        Newline separates each response line if multiple exist.

    Raises:
        FileNotFoundError if the hostpipe log cannot be found.

    """
    calltime = time()
    modcommand = _apply_preamble(command)
    if pipelog is None:
        pipelog = './logs/hostpipe.log'
    if not os.path.isfile(pipelog):
        raise FileNotFoundError(f'Could not find file {pipelog}')
    _log.debug(f'Searching {pipelog} for {modcommand}')
    response: 'list[str]' = []
    filepass = 0
    while len(response) == 0:
        # test_mode assumes manual step through will usually violate timeout
        if not test_mode and time() > calltime + timeout:
            _log.warning(f'Response to {command} timed out'
                         f' after {timeout} seconds')
            break
        filepass += 1
        if filepass > HOSTPIPE_LOG_ITERATION_MAX:
            _log.warning(f'Exceeded max={HOSTPIPE_LOG_ITERATION_MAX} iterations'
                         ' on hostpipe log')
            break
        if _vlog():
            _log.debug(f'{pipelog} read iteration {filepass}')
        lines = open(pipelog, 'r').readlines()
        for line in reversed(lines):
            if (not test_mode and
                command_time is not None and
                _get_line_ts(line) < command_time):
                # older command, skip this pass
                sleep(0.1)
                break
            if CMD_TAG in line:
                logged_command = line.split(CMD_TAG)[1].strip()
                if _vlog():
                    _log.debug(f'Found command {logged_command} in {pipelog}'
                               f'({_get_line_ts(line)})'
                               f' with {len(response)} response lines')
                if logged_command != modcommand:
                    # wrong command/response so dump parsed lines so far
                    cts = _get_line_ts(line)
                    to_remove = []
                    for resline in response:
                        rts = _get_line_ts(resline)
                        if rts == cts:
                            to_remove.append(resline)
                    if _vlog():
                        _log.debug(f'Mismatch: {logged_command} != {modcommand}'
                                   f' -> drop {len(to_remove)} response lines')
                    response = [l for l in response if l not in to_remove]
                else:
                    # we reached the original command so can stop parsing response
                    if _vlog():
                        _log.debug(f'Found target {modcommand}'
                                   f' with {len(response)} response lines')
                    response = [l.split(RES_TAG, 1)[1].strip() for l in response]
                    break
            elif RES_TAG in line:
                response.append(line)
        if not test_mode:
            sleep(timeout / 2)
    response.reverse()
    return '\n'.join(response)


def _maintain_pipelog(pipelog: str,
                      max_file_size: int = MAX_FILE_SIZE,
                      test_mode: bool = False,
                      ) -> int:
    """Deletes log entries if over a maximum size and returns the count deleted.

    Deletes both the command and its response.

    Returns the number of lines deleted.
    """
    # TODO: spin a thread to do this in background? or manage in bash/linux
    if not(os.path.isfile(pipelog)):
        raise FileNotFoundError(f'Could not find {pipelog}')
    to_delete = []
    if os.path.getsize(pipelog) > max_file_size:
        lines = open(pipelog, 'r').readlines()
        while os.path.getsize(pipelog) > max_file_size:
            for line in lines:
                if RES_TAG in line:
                    to_delete.append(line)
                elif CMD_TAG in line:
                    if len(to_delete) == 0:
                        to_delete.append(line)
                    else:
                        break
            with open(pipelog, 'w') as f:
                for line in lines:
                    if line not in to_delete:
                        f.write(line)
        if len(to_delete) > 0 and test_mode:
            with open(pipelog, 'w') as f:
                f.writelines(lines)
    return len(to_delete)


def _vlog() -> bool:
    return verbose_logging('hostpipe')
