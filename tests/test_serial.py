from fieldedge_utilities import serial


def test_validate_basic():
    port_exists = serial.is_valid('/dev/ttyUSB0')
    assert port_exists == False

def test_get_devices():
    devices = serial.get_devices()
    for device in devices:
        assert isinstance(device, serial.SerialDevice)
