import os
from datetime import datetime
from logging import Logger

import pytest
from fieldedge_utilities import hostpipe
from fieldedge_utilities.hostpipe import (COMMAND_PREFIX, RESPONSE_PREFIX,
                                          TIMESTAMP_FMT)

LOGDIR = './tests/hostpipe_logs'

MOCK_BGAN_SIM = str(os.getenv('MOCK_BGAN_SIM')).lower() == 'true'
mock_bgan_sim_state = False
MOCK_BIG_FILE = str(os.getenv('MOCK_BIG_FILE')).lower() == 'true'
MOCK_NTP_ENABLED = str(os.getenv('MOCK_NTP_ENABLED')).lower() == 'true'

def _mock_host_command(command: str, log: Logger = None) -> str:
    """Mocks responses for testing."""
    global mock_bgan_sim_state
    if 'ufw status' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-ufw-status.log'
    elif '"A POSTROUTING"' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-ufw-nat.log'
    elif 'ip addr show' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-ipaddrshow.log'
    elif 'grep -nr \"cache-size=\"' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-dns-get.log'
    elif 'systemctl status chrony' in command:
        if MOCK_NTP_ENABLED:
            pipelog = f'{LOGDIR}/hostpipe-test-ntp-enabled.log'
        else:
            pipelog = f'{LOGDIR}/hostpipe-test-ntp-disabled.log'
    elif 'grep -nr \"pool pool.ntp.org' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-ntp-get.log'
    elif 'bgan_simulator.sh' in command:
        if 'status' in command:
            if MOCK_BGAN_SIM and mock_bgan_sim_state:
                pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-enabled.log'
            else:
                pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-disabled.log'
        elif 'enable' in command:
            pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-enable.log'
            mock_bgan_sim_state = True
        else:
            pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-disable.log'
            mock_bgan_sim_state = False
    elif 'capture.sh' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-capture.log'
        iface = command.split('-i')[1].split(' ')[1]
        dur = command.split('-t')[1].split(' ')[1]
        mock_response = [
            f'Starting wireshark capture on {iface} for {dur} seconds.',
            f'Completed wireshark capture /home/pi/fieldedge/capture/capture_YYYYmmdd/capture_YYYYmmddTHHMMSS_{dur}',
        ]
        interleave_command = 'some random command'
        interleave_response = [
            'random response line 1',
            'random response line 2',
        ]
        _mock_host_response(pipelog, command, mock_response, interleave_command, interleave_response)
    elif 'tshark -r' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-tsharkr.log'
        _mock_host_response(pipelog, command, [])
    elif 'editcap' in command:
        pipelog = f'{LOGDIR}/hostpipe-test-editcap.log'
        _mock_host_response(pipelog, command, [])
    else:
        pipelog = f'{LOGDIR}/hostpipe.log'
        _mock_host_response(pipelog, command, ['test response'])
    return pipelog

def _mock_host_response(pipelog: str,
                        command: str,
                        response: list,
                        interleave_cmd: str = None,
                        interleave_res: list = None,
                        overwrite: bool = True,
                        ) -> None:
    """Used for test purposes only."""
    lines_to_write = []
    req_time = datetime.utcnow()
    req_iso = req_time.isoformat()[0:len(TIMESTAMP_FMT) - 1] + 'Z'
    mockcmd = (f'{COMMAND_PREFIX.replace(TIMESTAMP_FMT,req_iso)}'
        f'{command}\n')
    lines_to_write.append(mockcmd)
    secs = int(req_iso[-3:-1])
    adjust = secs + 1
    i_req_iso = req_iso.replace(f'{secs}Z', f'{adjust}Z')
    if interleave_cmd is not None:
        i_mockcmd = (f'{COMMAND_PREFIX.replace(TIMESTAMP_FMT,i_req_iso)}'
            f'{interleave_cmd}\n')
        lines_to_write.append(i_mockcmd)
    if interleave_res is not None:
        for ir in interleave_res:
            i_mockres = (f'{RESPONSE_PREFIX.replace(TIMESTAMP_FMT,i_req_iso)}'
                f'{ir}\n')
            lines_to_write.append(i_mockres)
    for resline in response:
        mockres = (f'{RESPONSE_PREFIX.replace(TIMESTAMP_FMT,req_iso)}'
            f'{resline}\n')
        lines_to_write.append(mockres)
    if overwrite:
        logfile = open(pipelog, 'w')
    else:
        logfile = open(pipelog, 'a')
    logfile.writelines(lines_to_write)
    logfile.close()

def test_host_command_bgan_simulator():
    command = 'bash $HOME/fieldedge/bgan_simulator/bgan_simulator.sh status'
    pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-enabled.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert isinstance(res, str)
    assert any(x in res.lower() for x in ['delay', 'enabled'])
    pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-disabled.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert isinstance(res, str)
    assert not any(x in res.lower() for x in ['delay', 'enabled'])
    pipelog = f'{LOGDIR}/hostpipe-test-bgan-simulator-enable.log'
    command = 'bash $HOME/fieldedge/bgan_simulator/bgan_simulator.sh enable'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert 'abl' in res

def test_host_command_manual_tshark():
    command = (f'nohup bash $HOME/fieldedge/capture/capture.sh'
        f' -t 60 -i eth1'
        ' | sed -e "s/^/$(date -u +%Y-%m-%dT%H:%M:%SZ),[INFO],result=/"'
        ' &>> $HOME/fieldedge/logs/hostpipe.log &')
    pipelog = f'{LOGDIR}/hostpipe-test-capture.log'
    res = hostpipe.host_command(command, noresponse=True, test_mode=True)
    # some timer thread expires in real world
    res = hostpipe.host_get_response(command, pipelog=pipelog, test_mode=True)
    assert 'completed wireshark' in res.lower()

# def test_host_command_tshark_corrupt():
#     pass

def test_host_command_shutdown():
    command = 'sudo shutdown -P 1'
    res = hostpipe.host_command(command, noresponse=True)
    assert res == f'{command} sent'

def test_host_command_ip_addr_show():
    command = 'ip addr show'
    command = 'ip a show | egrep \' eth| en| wlan\' | awk \'{$1=$1};1\''
    pipelog = f'{LOGDIR}/hostpipe-test-ipaddrshow.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert any(x in res.lower() for x in ['eth', 'en', 'wlan'])

def test_host_command_ufw_status_verbose():
    command = 'sudo ufw status verbose'
    pipelog = f'{LOGDIR}/hostpipe-test-ufw-status.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert 'Status' in res
 
def test_host_command_forwarding_rules():
    command = 'grep -nr \"A POSTROUTING\" /etc/ufw/before.rules'
    pipelog = f'{LOGDIR}/hostpipe-test-ufw-nat.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert 'MASQUERADE' in res

def test_host_command_dns_cache():
    command = 'grep -nr \"cache-size=\" /etc/dnsmasq.conf'
    pipelog = f'{LOGDIR}/hostpipe-test-dns-get.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert 'cache-size=' in res
    assert int(res.split('=')[1].strip()) == 150

def test_host_command_ntp_cache():
    command = 'systemctl | grep chrony | tr -s [:blank:]'
    # command = 'systemctl | grep chrony'
    pipelog = f'{LOGDIR}/hostpipe-test-ntp-installed.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert 'active' in res.lower()
    command = 'grep -nr \"pool pool.ntp.org\" /etc/chrony/chrony.conf'
    pipelog = f'{LOGDIR}/hostpipe-test-ntp-get.log'
    res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
    assert 'minpoll' in res

def test__maintain_pipelog():
    pipelog = f'{LOGDIR}/hostpipe-test-bigfile.log'
    test_size = os.path.getsize(pipelog) - 1
    lines_deleted = hostpipe._maintain_pipelog(pipelog, test_size, True)
    assert lines_deleted == 14

def test_tooclose():
    with pytest.raises(Exception):
        command = 'grep -nr \"cache-size=\" /etc/dnsmasq.conf'
        pipelog = f'{LOGDIR}/hostpipe-test-dns-tooclose.log'
        res = hostpipe.host_command(command, pipelog=pipelog, test_mode=True)
        cache_size = int(res.split('=')[1].strip())
