import pytest
from unittest import mock
from fieldedge_utilities.gnss import GnssLocation
from fieldedge_utilities.egnss import Egnss


nmea_sentences = [
    b'$GPTXT,01,01,02,u-blox ag - www.u-blox.com*50\r\n',
    b'$GPTXT,01,01,02,HW  UBX-G70xx   00070000 *77\r\n',
    b'$GPTXT,01,01,02,ROM CORE 1.00 (59842) Jun 27 2012 17:43:52*59\r\n',
    b'$GPTXT,01,01,02,PROTVER 14.00*1E\r\n',
    b'$GPTXT,01,01,02,ANTSUPERV=AC SD PDoS SR*20\r\n',
    b'$GPTXT,01,01,02,ANTSTATUS=OK*3B\r\n',
    b'$GPTXT,01,01,02,LLC FFFFFFFF-FFFFFFFD-FFFFFFFF-FFFFFFFF-FFFFFFF9*53\r\n',
    b'$GPRMC,115959.00,V,,,,,,,180425,,,N*73\r\n',
    b'$GPRMC,120000,A,3307.782,N,11716.026,W,000.0,000.0,010125,,,A*68',
    b'$GPGGA,120000,3307.782,N,11716.026,W,1,08,0.9,50.0,M,-34.0,M,,*43',
    b'$GPGSA,A,3,01,02,03,04,05,06,07,08,,,,,1.5,0.9,1.2*34',
    b'$GPGSV,3,1,12,01,45,083,41,02,17,273,37,03,15,312,36,04,35,123,39*7A',
    b'$GPGSV,3,2,12,05,10,045,35,06,65,200,42,07,12,150,30,08,22,090,38*70',
    b'$GPGSV,3,3,12,09,05,180,27,10,25,135,33,11,55,015,40,12,33,210,36*7E',
    b'$GPRMC,120001,A,3307.782,N,11716.026,W,000.0,000.0,010125,,,A*69',
]

@pytest.fixture
def mocked_serial():
    mock_serial = mock.MagicMock()
    mock_serial.in_waiting = True
    mock_serial.readline.side_effect = nmea_sentences + [b''] * 10
    return mock_serial


@mock.patch('fieldedge_utilities.egnss.serial.Serial')
def test_gnss_location_parsing(mock_serial_class, mocked_serial):
    mock_serial_class.return_value = mocked_serial
    gnss = Egnss(port='/dev/ttyUSB0')
    location = gnss.get_location(timeout=90)
    assert isinstance(location, GnssLocation)
    assert location.latitude == 33.1297
    assert location.longitude == -117.2671
    assert location.altitude == 50.0
    assert location.speed == 0.0
    assert location.heading == 0.0
    assert location.hdop == 0.9
    assert location.pdop == 1.5
    assert location.vdop == 1.2
    assert location.satellites == 8
    assert location.timestamp == 1735732800
    assert location.fix_type == 3
    assert location.fix_quality == 1


def test_invalid_refresh_raises():
    with pytest.raises(ValueError):
        Egnss('/dev/ttyUSB0', refresh=100)


@mock.patch('fieldedge_utilities.egnss.serial.Serial')
def test_get_utc_iso(mock_serial_class, mocked_serial):
    mock_serial_class.return_value = mocked_serial
    gnss = Egnss('/dev/ttyUSB0')
    utc_time = gnss.get_utc(iso_time=True)
    assert utc_time == '2025-01-01T12:00:00Z'
