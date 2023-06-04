import logging
import os
from fieldedge_utilities import host

logger = logging.getLogger()


def test_ssh_single():
    """Requires env variables SSH_HOST, SSH_USER, SSH_PASS"""
    assert os.getenv('SSH_HOST')
    assert os.getenv('SSH_USER')
    assert os.getenv('SSH_PASS')
    cmd = 'cat /etc/os-release'
    res = host.host_command(cmd)
    assert isinstance(res, str)


def test_ssh_session():
    """Requires env variables SSH_HOST, SSH_USER, SSH_PASS"""
    assert os.getenv('SSH_HOST')
    assert os.getenv('SSH_USER')
    assert os.getenv('SSH_PASS')
    ssh_client = host.get_ssh_session()
    cmd_1 = 'cat /etc/os-release'
    res = host.host_command(cmd_1, ssh_client=ssh_client)
    assert isinstance(res, str)
    cmd_2 = 'ls -la'
    res_2 = host.host_command(cmd_2, ssh_client=ssh_client)
    assert isinstance(res_2, str)
    ssh_client.close()


def test_hostpipe_test():
    assert os.getenv('DOCKER') == '1'
    assert os.getenv('HOSTPIPE_LOG')
    TESTAPPDIR = '/home/fieldedge/fieldedge'
    LOGDIR = './tests/hostpipe_logs'
    command = f'bash {TESTAPPDIR}/bgan-simulator/mimicbgan.sh status'
    pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-enabled.log'
    res = host.host_command(command, pipelog=pipelog, test_mode=True)
    assert isinstance(res, str)
