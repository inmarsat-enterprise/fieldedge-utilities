import logging
from time import sleep, time

from fieldedge_utilities import timer

call_count = 0


def trigger_function(arg = None, kwarg = None):
    global call_count
    call_count += 1


def test_timer_basic():
    global call_count
    start_time = time()
    test_interval = 1
    test_cycles = 3
    auto_start = True
    defer = False
    daemon = True
    arg = 'test_arg'
    kwargs = {'kwarg': True}
    t = timer.RepeatingTimer(seconds=test_interval,
                             target=trigger_function,
                             args=(arg,),
                             kwargs=kwargs,
                             name='test_create',
                             auto_start=auto_start,
                             defer=defer,
                             daemon=daemon,
                             )
    if not auto_start:
        t.start()
        t.start_timer()
    assert isinstance(t, timer.RepeatingTimer)
    while call_count < test_cycles:
        assert t.is_running
        sleep(1)
    stop_time = time()
    t.stop_timer()
    assert call_count == test_cycles
    run_time = int(stop_time - start_time)
    assert run_time == test_interval * test_cycles + test_interval * defer
    if not daemon:
        t.terminate()

def test_change_interval():
    global call_count
    initial_interval = 3
    new_interval = 1
    test_cycles = 4
    start_time = time()
    t = timer.RepeatingTimer(seconds=initial_interval,
                             target=trigger_function,
                             auto_start=True,
                             defer=True,
                             )
    while call_count < test_cycles:
        if call_count == 1:
            t.change_interval(new_interval)
        if call_count < 1:
            assert t.interval == initial_interval
        else:
            assert t.interval == new_interval
        sleep(1)
    end_time = time()
    run_time = int(end_time - start_time)
    assert run_time == initial_interval + new_interval * test_cycles


def sim_delay(delay: int = 3):
    global call_count
    log = logging.getLogger()
    log.info('Delay called')
    sleep(delay)
    log.info('Delay complete')
    call_count += 1


def test_drift(caplog):
    t = timer.RepeatingTimer(seconds=5,
                             target=sim_delay,
                             args=(0,),
                             defer=False,
                             max_drift=0)
    t.start()
    t.start_timer()
    while call_count < 5:
        pass
    # for record in caplog.records:
    #     if record.levelname == 'DEBUG':
    #         assert 'Compensating' in record.message


# def test_start_timer_previously_started():
#     pass

# def test_restart_timer():
#     pass

# def test_stop_start_timer():
#     pass
