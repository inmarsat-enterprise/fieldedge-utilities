import json
import os
import pytest

from fieldedge_utilities import logger

TEST_STR = 'Testing basic logging functionality.'
TEST_FILE = './logs/test.log'


def test_stdout(capsys):
    log = logger.get_wrapping_logger('test')
    log.info(TEST_STR)
    captured = capsys.readouterr()
    parts = captured.out.split(',')
    assert len(parts) == 5
    (datetime, level, thread, module_function_line, message) = parts
    assert len(datetime) == 24
    assert level == '[INFO]'
    assert thread == '(MainThread)'
    assert 'test_log.test_stdout:' in module_function_line
    assert message == TEST_STR + '\n'


def test_stdout_json(capsys):
    log = logger.get_wrapping_logger('test', format='json')
    log.info(TEST_STR)
    captured = capsys.readouterr()
    json_dict = json.loads(captured.out)
    assert isinstance(json_dict['datetime'], str)
    assert len(json_dict['datetime']) == 24
    assert json_dict['level'] == 'INFO'
    assert json_dict['thread'] == 'MainThread'
    assert json_dict['module'] == 'test_log'
    assert json_dict['function'] == 'test_stdout_json'
    assert isinstance(json_dict['line'], int)
    assert json_dict['message'] == TEST_STR


def test_stderr(capsys):
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


def test_exception_singleline(capsys):
    log = logger.get_wrapping_logger(name='test', filename=TEST_FILE)
    try:
        log.info('A non-exception')
        x = 1/0
    except Exception as e:
        log.exception(e)
    f = open(TEST_FILE, 'r')
    assert 'ZeroDivisionError: ' in f.readlines()[1]
    os.remove(TEST_FILE)


def test_invalid_file_path(capsys):
    with pytest.raises(FileNotFoundError, match='Invalid logfile path'):
        log = logger.get_wrapping_logger(name='test',
                                         filename='/bad/path/test.log')
