"""External GNSS feature for IoT modems without integrated GNSS."""

import logging
import threading
import time

import serial

from fieldedge_utilities.gnss import GnssLocation, parse_nmea_to_location
from fieldedge_utilities.microservice import Feature
from fieldedge_utilities.properties import json_compatible, ConfigurableProperty
from fieldedge_utilities.timer import RepeatingTimer

_log = logging.getLogger(__name__)

SERIAL_KWARGS = ['baudrate', 'bytesize', 'parity', 'stopbits', 'timeout',
                 'xonoff', 'rtscts', 'write_timeout', 'dsrdtr',
                 'inter_byte_timeout']


class Egnss(Feature):
    """A `microservice.Feature` interfacing to a GNSS module via serial.
    
    Attributes:
        refresh (int): The refresh interval in seconds for location updates.
            0 disables refresh. Maximum 30 seconds. Default 1 second.
    """
    def __init__(self, port: str, **kwargs):
        super().__init__(**kwargs)
        ser_kwargs = { k: v for k, v in kwargs if k in SERIAL_KWARGS }
        self._ser = serial.Serial(port, **ser_kwargs)   # type: ignore
        self._location = GnssLocation()
        self._initial_fix: bool = False
        self._refresh: int = 0
        self.refresh = kwargs.get('refresh', 0)
        self._lock = threading.Lock()
        self._reader_thread = RepeatingTimer(self.refresh,
                                             target=self._read_gnss,
                                             name='EgnssReaderThread',
                                             auto_start=True)
        _log.info('GNSS reader started with refresh %d seconds', self.refresh)
    
    @property
    def port(self) -> 'str|None':
        return self._ser.port
    
    @property
    def refresh(self) -> int:
        return self._refresh
    
    @refresh.setter
    def refresh(self, value: int):
        if not isinstance(value, int) or value not in range(0, 31):
            raise ValueError('Invalid refresh interval must be 0..30')
        if value != self._refresh:
            self._refresh = value
            self._reader_thread.change_interval(value, trigger_immediate=True)
    
    def isc_configurable(self) -> 'dict[str, ConfigurableProperty]':
        return { 'refresh': ConfigurableProperty('int', min=0, max=30) }
    
    def on_isc_message(self, topic, message) -> bool:
        return super().on_isc_message(topic, message)
    
    def properties_list(self, **kwargs) -> 'list[str]':
        return super().properties_list(**kwargs)
    
    def status(self, **kwargs) -> dict:
        return super().status(**kwargs)
    
    def _read_gnss(self, timeout: float = 30):
        """Background reader updating location.
        
        Parse available NMEA output from the serial port until it repeats RMC
        
        Args:
            timeout (float): The maximum time to parse strings before exiting.
        """
        try:
            req_time = time.time()
            with self._lock:
                rmc_found = False
                while self._ser.in_waiting and time.time() - req_time < timeout:
                    line = self._ser.readline().decode('utf-8', errors='ignore')
                    line = line.strip()
                    if line[3:6] == 'RMC' and ',V,' not in line:   # ignore Void
                        if rmc_found:
                            break
                        rmc_found = True
                    if not rmc_found:
                        # _log.debug('Skipping: %s', line)
                        continue
                    if line.startswith(('$GN', '$GP')):
                        self._location = parse_nmea_to_location(line,
                                                                self._location) # type: ignore
                        if (self._location.latitude is not None and             # type: ignore
                            not self._initial_fix):
                            self._initial_fix = True
                            _log.info('Initial GNSS fix acquired')
                if self._location.latitude is None:                             # type: ignore
                    _log.debug('No location determined')
        except (serial.SerialException, ValueError) as exc:
            _log.error(exc)
        
    def get_location(self, timeout: int = 35) -> GnssLocation:
        """Get the current location.
        
        The returned `GnssLocation` properties may be `None` if no fix was
        obtained within the timeout.
        
        Args:
            timeout (int)
        
        Returns:
            `GnssLocation`
        """
        if not isinstance(timeout, (int, float)) or timeout < 0:
            raise ValueError('Invalid timeout')
        if self.refresh == 0:
            self._location = GnssLocation()   # Clear previous
            start_time = time.time()
            while (self._location.latitude is None and 
                   time.time() - start_time < timeout):
                self._read_gnss(timeout)
        _log.info('Queried location: %s', json_compatible(self._location))
        return self._location   # type: ignore
    
    def get_utc(self, iso_time: bool = False) -> int|str|None:
        """Get the current UTC timestamp in seconds since 1970-01-01T00:00:00.
        
        Args:
            iso_time (bool): If True return ISO8601 e.g. `2020-01-01T00:00:00Z`
        
        Returns:
            Integer timestamp in seconds, or ISO8601 string
        """
        self._read_gnss(timeout=1)
        _log.info('Queried unix timestamp: %s', self._location.timestamp)   # type: ignore
        if not isinstance(self._location, GnssLocation):
            return None
        if iso_time:
            return self._location.iso_time
        return self._location.timestamp
