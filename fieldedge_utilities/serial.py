"""Helpers for managing serial ports on the system.

"""
import glob
# import logging
import platform
from typing import Optional

import serial.tools.list_ports
from serial import Serial, SerialException
from serial.tools.list_ports_common import ListPortInfo

# _log = logging.getLogger(__name__)


class SerialDevice:
    """A serial port device.

    Created by passing in a pyserial ListPortInfo and simplifies it.
    
    Attributes:
        name (str): The name of the interface
        manufacturer (str): The manufacturer of the device
        driver (str): The driver description
        vid (int): The registered vendor ID
        pid (int): The registered product ID
        serial_number (str): The serial number of the device

    """
    def __init__(self, port_info: ListPortInfo) -> None:
        self._name: str = port_info.device
        self._manufacturer: Optional[str] = port_info.manufacturer
        self._driver: str = port_info.description
        self._vid: int = port_info.vid
        self._pid: int = port_info.pid
        self._serial_number: Optional[str] = port_info.serial_number

    @property
    def name(self) -> str:
        return self._name

    @property
    def manufacturer(self) -> str|None:
        return self._manufacturer

    @property
    def driver(self) -> str:
        return self._driver

    @property
    def vid(self) -> int:
        return self._vid

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def serial_number(self) -> str|None:
        return self._serial_number


def is_valid(target: str) -> bool:
    """Validates a given serial port as available on the host.

    Args:
        target: Target port name e.g. `/dev/ttyUSB0`
    
    Returns:
        True if found on the host.
    """
    if not isinstance(target, str) or len(target) == 0:
        raise ValueError('Invalid serial port target')
    return target in list_available_serial_ports()


def get_devices(target: Optional[str] = None) -> list:
    """Returns a list of serial device information.
    
    Args:
        target: Optional device name to filter on.
    
    Returns:
        A list of `SerialDevice` objects describing each port.

    """
    devices = [SerialDevice(p) for p in serial.tools.list_ports.comports()]
    if target is not None:
        for device in devices:
            if device.name != target:
                devices.remove(device)
    return devices


def list_available_serial_ports(skip: Optional[list[str]] = None) -> list[str]:
    """Get a list of the available serial ports.
    
    Args:
        skip (list): Optional list of port names to skip when testing validity.
            Primarily to skip port(s) already in use by the application.
        
    Returns:
        `list` of valid serial port names.
    """
    if platform.system() in ('Linux', 'Darwin'):
        if (skip is not None and 
            not (isinstance(skip, list) and all(isinstance(x, str) 
                                                for x in skip))):
            raise ValueError('Invalid skip list')
        if skip is None:
            skip = []
        candidates = glob.glob('/dev/tty[A-Z]*' if platform.system() == 'Linux'
                               else '/dev/tty.[A-Za-z]*')
        available = []
        for port in candidates:
            if port not in skip:
                try:
                    with Serial(port):
                        available.append(port)
                except (OSError, SerialException):
                    pass
        return available
    return [p.device for p in serial.tools.list_ports.comports()]
