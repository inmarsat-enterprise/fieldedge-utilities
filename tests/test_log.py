import os

from fieldedge_utilities import logger

TEST_STR = 'Testing basic logging functionality.'
TEST_FILE = './logs/test.log'

def test_info(capsys):
    log = logger.get_wrapping_logger('test')
    log.info(TEST_STR)
    captured = capsys.readouterr()
    parts = captured.out.split(',')
    assert len(parts) == 5
    assert len(parts[0]) == 24
    assert parts[1] == '[INFO]'
    assert parts[2] == '(MainThread)'
    assert parts[3] == 'test_log.test_info:10'
    assert parts[4] == TEST_STR + '\n'


def test_warning(capsys):
    log = logger.get_wrapping_logger('test')
    log.warning(TEST_STR)
    captured = capsys.readouterr()
    assert captured.err != ''


def test_file(capsys):
    log = logger.get_wrapping_logger(name='test', filename=TEST_FILE)
    log.info(TEST_STR)
    captured = capsys.readouterr()
    assert TEST_STR in captured.out
    assert os.path.isfile(TEST_FILE)
    f = open(TEST_FILE, 'r')
    assert TEST_STR in f.readline()
    os.remove(TEST_FILE)
