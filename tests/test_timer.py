import logging
import time

import pytest

from fieldedge_utilities import RepeatingTimer

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)


@pytest.fixture
def log_capture(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def test_regular_interval():
    calls = []

    def target():
        calls.append(time.monotonic())

    timer = RepeatingTimer(
        seconds=1,
        target=target,
        # sleep_chunk=0.05,
        # auto_start=True,
    )
    assert timer.name == 'TargetTimerThread'
    assert timer.target_name == target.__name__
    timer.start()
    timer.start_timer()

    time.sleep(3.2)  # allow 3+ firings
    timer.terminate()

    assert len(calls) >= 3
    # Verify approximate intervals (within 0.1s tolerance)
    for i in range(1, len(calls)):
        assert abs(calls[i] - calls[i-1] - 1) < 0.15


def test_long_running_target(log_capture):
    calls = []

    def target():
        calls.append(time.monotonic())
        logger.info('Target executing...')
        time.sleep(1.5)  # longer than timer interval
        logger.info('Target completed')

    timer = RepeatingTimer(
        seconds=1,
        target=target,
        # sleep_chunk=0.05,
        # auto_start=True,
    )
    timer.start()
    timer.start_timer()

    time.sleep(5)  # allow multiple firings
    timer.terminate()

    # Because target takes longer than interval, it should fire immediately after previous finish
    for i in range(1, len(calls)):
        assert calls[i] >= calls[i-1]  # monotonically increasing
        # Next fire should not be less than previous start
        assert calls[i] - calls[i-1] >= 1.5 - 0.1
    
    resync = any('Resync' in rec.message for rec in log_capture.records)
    assert not resync


def test_resync_when_late(caplog):
    calls = []
    
    def slow_task():
        calls.append(time.monotonic())
        logger.info('Target executing...')
        time.sleep(1.6)
        logger.info('Target complete')
    
    timer = RepeatingTimer(
        seconds=1,
        target=slow_task,
        max_drift=0.5,
        defer=False,
    )
    timer.start()
    timer.start_timer()
    time.sleep(2.5)
    timer.terminate()
    timer.join(timeout=1)
    resync = [rec.message for rec in caplog.records if 'Resync' in rec.message]
    assert resync, 'Expected at least one Resync log'


def test_restart_and_change_interval():
    calls = []

    def target():
        calls.append(time.monotonic())

    timer = RepeatingTimer(
        seconds=1,
        target=target,
        # sleep_chunk=0.05,
    )
    timer.start()
    timer.start_timer()
    time.sleep(2.2)

    timer.change_interval(2, trigger_immediate=True)
    time.sleep(2.2)
    timer.terminate()

    assert len(calls) >= 3  # 2 initial + 1+ after interval change


def test_logging_next_trigger(log_capture):
    calls = []

    def target():
        calls.append(time.monotonic())
        time.sleep(0.2)

    timer = RepeatingTimer(
        seconds=1,
        target=target,
        # sleep_chunk=0.05,
        # auto_start=True,
    )
    timer.start()
    timer.start_timer()
    time.sleep(1.5)
    timer.terminate()

    found = any('next trigger' in rec.message for rec in log_capture.records)
    assert found
