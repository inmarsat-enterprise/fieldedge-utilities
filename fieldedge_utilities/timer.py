"""A threaded timer class that allows flexible reconfiguration.

"""
import logging
import threading
import time
from typing import Callable, Optional

from .logger import verbose_logging
from .properties import pascal_case


_log = logging.getLogger(__name__)


class RepeatingTimer(threading.Thread):
    """A background repeating interval that calls a function on schedule.
    
    Can be stopped/restarted/changed.
    
    Optional auto_start feature starts the thread and the timer, in this case 
    the user doesn't need to explicitly start() then start_timer().

    Attributes:
        seconds (float|int): Repeating timer interval in seconds (0=disabled).
        target (Callable): The function to call each interval.
        args (tuple): If present, stores the arguments to call with.
        kwargs (dict): If present, stores the kwargs to decompose/call with.
        name (str): A descriptive name for the Thread. Defaults
            to the function name as: `<Function>TimerThread`
        sleep_chunk (float): The fraction of seconds between verbose tick logs.
        max_drift (float): If present and the called function execution
            exceeds this time, resync the interval from the function completion
            time.
        defer (bool): Waits until the first interval before triggering the
            target function (default = True)

    """

    def __init__(
        self,
        seconds: float|int,
        target: Callable,
        args: Optional[tuple] = None,
        kwargs: Optional[dict] = None,
        name: Optional[str] = None,
        sleep_chunk: float = 0.25,
        max_drift: Optional[float] = None,
        auto_start: bool = False,
        defer: bool = True,
        daemon: bool = True,
    ):
        self._validate_interval(seconds)
        if not callable(target):
            raise ValueError('target must be a callable method')
        if not (isinstance(sleep_chunk, (int, float)) and sleep_chunk > 0):
            raise ValueError('sleep_chunk must be > 0')
        self.target_name = getattr(target, '__name__', str(target))
        if not isinstance(name, str) or len(name) == 0:
            name = (f'{pascal_case(self.target_name)}TimerThread')
        super().__init__(name=name, daemon=daemon)
        # if 0 < seconds < 0.05:
        #     _log.warning('Short interval may be unreliable due to GIL')
        self._interval: float|int = seconds
        self.target = target
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.defer = defer
        self.max_drift = max_drift  # seconds allowed before resync
        self.sleep_chunk = float(sleep_chunk)

        self._start_event = threading.Event()
        self._reset_event = threading.Event()
        self._terminate_event = threading.Event()
        self._lock = threading.Lock()

        # Absolute scheduling anchors
        self._next_deadline: Optional[float] = None
        self._last_fire: Optional[float] = None

        if auto_start:
            self.start()
            self.start_timer()

    def _validate_interval(self, seconds: float|int):
        if not isinstance(seconds, (float, int)) or seconds < 0:
            raise ValueError('seconds must be >= 0')
        if 0 < seconds < 0.05:
            _log.warning('Short interval may be unreliable due to GIL')
    
    # ----- Properties -----

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    @property
    def is_running(self) -> bool:
        return self._start_event.is_set()

    # ----- Core scheduling helpers -----

    def _schedule_from_now(self):
        """Reset the cadence to `now + interval`."""
        if not self.is_running or self.interval <= 0:
            self._next_deadline = None
            return
        now = time.monotonic()
        self._next_deadline = now + self.interval
        _log.debug('Resync next trigger in %0.1f seconds', self.interval)

    def _advance_on_schedule(self, scheduled: Optional[float], finished: float):
        """Advance deadline after target execution.
        
        - If lateness exceeds max_drift abandon cadence and resync from now.
        - Else if still within interval bump to the next interval.
        - Else skip missed slots but keep original cadence.
        """
        if not self.is_running or self.interval <= 0 or scheduled is None:
            self._next_deadline = None
            return
        next_deadline = scheduled + self.interval
        if finished <= next_deadline:
            self._next_deadline = next_deadline
        elif (self.max_drift is not None and
            (finished - scheduled) > self.interval + self.max_drift):
            self._schedule_from_now()
        else:
            adjust = max(0, finished - next_deadline)
            self._next_deadline = finished + adjust
    
    def _call_target(self):
        try:
            if _vlog():
                _log.debug('Calling %s with args=%s kwargs=%s',
                           self.target_name,
                           self.args,
                           self.kwargs)
            self.target(*self.args, **self.kwargs)
        except Exception as exc:
            _log.exception('%s exception: %s', self.target_name, exc)
            raise

    # ----- Thread loop -----

    def run(self):
        while not self._terminate_event.is_set():
            # Wait until started
            self._start_event.wait()
            if self._terminate_event.is_set():
                break

            with self._lock:
                interval = self._interval

            if interval <= 0:
                # Timer disabled: wait for interval change
                self._reset_event.wait(timeout=0.2)
                self._reset_event.clear()
                continue

            now = time.monotonic()
            if self._next_deadline is None:
                # Set initial deadline
                self._next_deadline = now + interval if self.defer else now
                if not self.defer:
                    self._last_fire = now
                    self._next_deadline = now + interval
                    self._call_target()

            while self.is_running and not self._terminate_event.is_set():
                now = time.monotonic()
                remaining = (self._next_deadline or now) - now

                # Wait in small chunks, wake on reset
                while (remaining > 0 and self.is_running and
                       not self._terminate_event.is_set()):
                    if _vlog():
                        _log.debug('%s countdown: %.2fs', self.name, remaining)
                    timeout = min(self.sleep_chunk, remaining)
                    if self._reset_event.wait(timeout):
                        self._reset_event.clear()
                        self._schedule_from_now()
                        break
                    now = time.monotonic()
                    remaining = (self._next_deadline or now) - now
                else:
                    # Time elapsed
                    if not self.is_running or self._terminate_event.is_set():
                        break

                    with self._lock:
                        interval = self._interval

                    if interval <= 0:
                        # Interval became 0 while waiting, disable timer
                        self._next_deadline = None
                        break

                    now = time.monotonic()
                    scheduled = self._next_deadline
                    self._last_fire = now
                    self._call_target()
                    self._advance_on_schedule(scheduled, time.monotonic())
                
    # ----- External controls -----

    def start_timer(self):
        self._start_event.set()
        if _vlog():
            _log.debug('Interval start requested (%0.3f)', time.monotonic())

    def stop_timer(self, notify: bool = True):
        self._start_event.clear()
        if notify:
            _log.info('Interval stopped (%0.3f)', time.monotonic())

    def restart_timer(self,
                      trigger_immediate: Optional[bool] = None,
                      notify: bool = True):
        """Restart the timer.
        
        If `trigger_immediate` is True, fire now else wait one full interval.
        Default is the opposite of `defer` configuration.
        """
        if trigger_immediate is None:
            trigger_immediate = not self.defer
        with self._lock:
            interval = self._interval
            if interval <= 0:
                self._next_deadline = None
            else:
                now = time.monotonic()
                scheduled = now + interval
                self._last_fire = None
                self._next_deadline = now if trigger_immediate else scheduled    
        if notify:
            _log.info('Restarted interval=%0.1f%s', interval,
                      ', immediate trigger' if trigger_immediate else '')

    def change_interval(self, seconds: float|int, trigger_immediate: bool = False):
        """Change the interval of the timer and restart it.
        
        Args:
            seconds (float|int): The new value of the interval.
            trigger_immediate (bool): If True the target is called during the
                restart.
        """
        self._validate_interval(seconds)
        with self._lock:
            old = self._interval
            self._interval = seconds
            self._next_deadline = None
            self._last_fire = None
        # wake timer thread to pick up new interval
        self._reset_event.set()
        if seconds > 0:
            self.restart_timer(trigger_immediate, notify=False)
            _log.info('Interval changed (old: %0.1f s; new: %0.1f s)'
                      ' (trigger_immediate=%s)', old, seconds, trigger_immediate)
        else:
            _log.info('Interval disabled (was %0.1f)', old)

    def terminate(self):
        self.stop_timer(notify=False)
        self._terminate_event.set()
        self._reset_event.set()
        _log.info('Timer terminated (%0.3f)', time.monotonic())


def _vlog() -> bool:
    return verbose_logging('timer')
