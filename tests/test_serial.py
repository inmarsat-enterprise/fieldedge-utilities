import pytest
import fieldedge_utilities
from unittest import mock
from fieldedge_utilities import serial


def make_serial_side_effect(success_ports: 'list[str]'):
    def side_effect(port, *args, **kwargs):
        if port in success_ports:
            mock_ctx = mock.MagicMock()
            mock_ctx.__enter__.return_value = mock_ctx
            mock_ctx.__exit__.return_value = None
            return mock_ctx
        raise serial.SerialException('Port error')
    return side_effect


@mock.patch('platform.system', return_value='Linux')
@mock.patch('glob.glob')
@mock.patch('fieldedge_utilities.serial.Serial')
def test_linux_ports(mock_serial, mock_glob, mock_system):
    visible = ['/dev/ttyUSB0', '/dev/ttyCH9344USB0', '/dev/ttyAMA0', '/dev/ttyS0']
    valid = ['/dev/ttyUSB0', '/dev/ttyCH9344USB0', '/dev/ttyS0']
    mock_glob.return_value = visible
    mock_serial.side_effect = make_serial_side_effect(valid)
    ports = serial.list_available_serial_ports()
    assert ports == valid


@mock.patch('platform.system', return_value='Darwin')
@mock.patch('glob.glob')
@mock.patch('fieldedge_utilities.serial.Serial')
def test_darwin_ports(mock_serial, mock_glob, mock_system):
    visible = ['/dev/tty.Bluetooth-Incoming-Port', '/dev/tty.debug-console',
               '/dev/tty.usbserial-2210']
    valid = ['/dev/tty.usbserial-2210']
    mock_glob.return_value = visible
    mock_serial.side_effect = make_serial_side_effect(valid)
    ports = serial.list_available_serial_ports()
    assert ports == valid


@mock.patch('platform.system', return_value='Windows')
@mock.patch('fieldedge_utilities.serial.serial.tools.list_ports.comports')
def test_windows_ports(mock_comports, mock_system):
    mock_comports.return_value = [
        mock.Mock(device='COM1'),
        mock.Mock(device='COM2')
    ]
    ports = serial.list_available_serial_ports()
    assert ports == ['COM1', 'COM2']


def test_get_devices():
    devices = serial.get_devices()
    for device in devices:
        assert isinstance(device, serial.SerialDevice)
