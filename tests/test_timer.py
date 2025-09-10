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


@pytest.fixture
def dummy_target():
    calls = []
    def _target(*args, **kwargs):
        calls.append((args, kwargs, time.monotonic()))
    return _target, calls


@pytest.mark.parametrize("defer,interval", [(True, 0.05), (False, 0.05), (True, 0)])
def test_basic_timer_variants(dummy_target, defer, interval):
    target, calls = dummy_target
    timer = RepeatingTimer(interval, target, defer=defer, auto_start=True)
    timer.start_timer()
    time.sleep(0.12)
    timer.terminate()
    timer.join(timeout=1)
    if interval == 0:
        assert len(calls) == 0
    else:
        assert len(calls) >= 2


def test_basic_short_interval(dummy_target, caplog):
    target, calls = dummy_target
    timer = RepeatingTimer(0.04, target, defer=False, auto_start=True)
    timer.start_timer()
    time.sleep(0.12)
    timer.terminate()
    timer.join(timeout=1)
    assert len(calls) >= 2
    assert calls[0][2] <= calls[1][2]
    assert any('GIL' in rec.message for rec in caplog.records)


def test_basic_negative_interval(dummy_target):
    target, calls = dummy_target
    with pytest.raises(ValueError) as exc_info:
        timer = RepeatingTimer(-1, target, defer=True, auto_start=True)
    assert '>= 0' in str(exc_info.value)


def test_interval_zero(dummy_target):
    target, calls = dummy_target
    timer = RepeatingTimer(0, target, auto_start=True)
    timer.start_timer()
    time.sleep(0.05)
    timer.terminate()
    timer.join(timeout=1)
    assert len(calls) == 0


def test_change_interval_zero_to_nonzero(dummy_target):
    target, calls = dummy_target
    timer = RepeatingTimer(0, target, auto_start=True)
    timer.start_timer()
    time.sleep(0.05)
    timer.change_interval(0.03)
    time.sleep(0.1)
    timer.terminate()
    timer.join(timeout=1)
    assert len(calls) >= 3


def test_change_interval_nonzero_to_zero(dummy_target):
    target, calls = dummy_target
    timer = RepeatingTimer(0.03, target, auto_start=True)
    timer.start_timer()
    time.sleep(0.08)
    timer.change_interval(0)
    count_after = len(calls)
    time.sleep(0.05)
    timer.terminate()
    timer.join(timeout=1)
    assert len(calls) == count_after


def test_restart_timer_immediate(dummy_target):
    target, calls = dummy_target
    timer = RepeatingTimer(0.05, target, defer=True, auto_start=True)
    timer.start_timer()
    time.sleep(0.06)
    timer.restart_timer(trigger_immediate=True)
    time.sleep(0.06)
    timer.terminate()
    timer.join(timeout=1)
    assert len(calls) >= 2


def test_restart_timer_non_immediate(dummy_target):
    target, calls = dummy_target
    timer = RepeatingTimer(0.05, target, defer=True, auto_start=True)
    timer.start_timer()
    time.sleep(0.02)
    timer.restart_timer(trigger_immediate=False)
    time.sleep(0.06)
    timer.terminate()
    timer.join(timeout=1)
    assert len(calls) >= 1


def test_restart_while_running(dummy_target):
    target, calls = dummy_target
    timer = RepeatingTimer(0.05, target, defer=True, auto_start=True)
    timer.start_timer()
    time.sleep(0.06)
    timer.restart_timer(trigger_immediate=True)
    time.sleep(0.06)
    timer.restart_timer(trigger_immediate=False)
    time.sleep(0.06)
    timer.terminate()
    timer.join(timeout=1)
    assert len(calls) >= 3


def test_basic_interval_regular_firing(dummy_target):
    """Verify timer fires repeatedly at roughly the interval."""
    target, calls = dummy_target
    timer = RepeatingTimer(0.05, target, defer=True, auto_start=True)
    timer.start_timer()
    time.sleep(0.25)
    timer.terminate()
    timer.join(timeout=1)
    # Should have fired 3-4 times
    assert 4 <= len(calls) <= 6
    diffs = [calls[i+1][2] - calls[i][2] for i in range(len(calls)-1)]
    # Each interval roughly 0.03s
    assert all(0.02 <= d <= 0.06 for d in diffs)


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
    timer.join(timeout=1)

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
    timer.join(timeout=1)

    # Because target takes longer than interval, it should fire immediately after previous finish
    for i in range(1, len(calls)):
        assert calls[i] >= calls[i-1]  # monotonically increasing
        # Next fire should not be less than previous start
        assert calls[i] - calls[i-1] >= 1.5 - 0.1
    
    resync = any('Resync' in rec.message for rec in log_capture.records)
    assert not resync


def test_resync_when_late(caplog):
    caplog.set_level(logging.DEBUG)
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
        auto_start=True,
    )
    time.sleep(3.5)
    timer.terminate()
    timer.join(timeout=1)
    resync = [rec.message for rec in caplog.records if 'Resync' in rec.message]
    assert resync, 'Expected at least one Resync log'
