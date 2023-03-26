import json
import logging
import os
import pytest
from time import sleep

from fieldedge_utilities import logger
from fieldedge_utilities import timer

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
    assert 'test_logger.test_stdout:' in module_function_line
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
    assert json_dict['module'] == 'test_logger'
    assert json_dict['function'] == 'test_stdout_json'
    assert isinstance(json_dict['line'], int)
    assert json_dict['message'] == TEST_STR


def test_stderr(capsys):
    log = logger.get_wrapping_logger('test')
    log.warning(TEST_STR)
    captured = capsys.readouterr()
    assert captured.err != ''


def create_test_file_dir(filename) -> 'str|None':
    if not os.path.isdir(os.path.dirname(filename)):
        newdir = os.path.dirname(TEST_FILE)
        os.mkdir(newdir)
        return newdir


def test_file(capsys):
    newdir = create_test_file_dir(TEST_FILE)
    log = logger.get_wrapping_logger(name='test', filename=TEST_FILE)
    log.info(TEST_STR)
    captured = capsys.readouterr()
    assert TEST_STR in captured.out
    assert os.path.isfile(TEST_FILE)
    f = open(TEST_FILE, 'r')
    assert TEST_STR in f.readline()
    os.remove(TEST_FILE)
    if newdir: os.rmdir(newdir)


def test_exception_singleline(capsys):
    newdir = create_test_file_dir(TEST_FILE)
    log = logger.get_wrapping_logger(name='test', filename=TEST_FILE)
    try:
        log.info('A non-exception')
        x = 1/0
    except Exception as e:
        log.exception(e)
    f = open(TEST_FILE, 'r')
    assert 'ZeroDivisionError: ' in f.readlines()[1]
    os.remove(TEST_FILE)
    if newdir: os.rmdir(newdir)


def test_invalid_file_path(capsys):
    bad_path = '/bad/path/test.log'
    with pytest.raises(FileNotFoundError, match=f'Path {bad_path} not found'):
        log = logger.get_wrapping_logger(name='test', filename=bad_path)


log = logging.getLogger()
timer_cycles = 0


def timer_callback():
    global timer_cycles
    log.info('Timer called me')
    timer_cycles += 1


def test_library_log(capsys):
    global timer_cycles
    newdir = create_test_file_dir(TEST_FILE)
    testlog = logger.get_wrapping_logger(name='test', filename=TEST_FILE)
    for h in testlog.handlers:
        logger.add_handler(log, h)
    logger.apply_formatter(log, logger.get_formatter())
    testlog.warning('This is a test warning')
    rt = timer.RepeatingTimer(seconds=2, target=timer_callback)
    rt.start()
    rt.start_timer()
    while timer_cycles < 2:
        sleep(1)
    assert True
    os.remove(TEST_FILE)
    if newdir: os.rmdir(newdir)
