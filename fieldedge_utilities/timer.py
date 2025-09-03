"""A threaded timer class that allows flexible reconfiguration.

"""
import logging
import math
import threading
import time
from typing import Callable, Optional

from .logger import verbose_logging


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
        seconds: float,
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
        if not isinstance(seconds, (float, int)) or seconds < 0:
            raise ValueError('seconds must be >= 0')
        if not callable(target):
            raise ValueError('target must be a callable method')
        if not (isinstance(sleep_chunk, (int, float)) and sleep_chunk > 0):
            raise ValueError('sleep_chunk must be > 0')
        self.target_name = getattr(target, '__name__', str(target))
        if not isinstance(name, str) or len(name) == 0:
            name = (f'{self.target_name[0].upper() + self.target_name[1:]}'
                    'TimerThread')
        super().__init__(name=name, daemon=daemon)
        
        self._interval = seconds
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

    # ----- Properties -----

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    @interval.setter
    def interval(self, val: int):
        if not isinstance(val, int) or val < 0:
            raise ValueError('interval must be integer >= 0')
        with self._lock:
            self._interval = val

    @property
    def is_running(self) -> bool:
        return self._start_event.is_set()

    # ----- Core scheduling helpers -----

    def _schedule_from_now(self):
        """Reset the cadence to `now + interval`."""
        if not self.is_running:
            return
        now = time.monotonic()
        self._next_deadline = now + self.interval
        _log.debug('Resync next trigger at %.3f (%0.3f)',
                   self._next_deadline, now)

    def _advance_on_schedule(self, scheduled: float, finished: float):
        """Advance deadline after target execution.
        
        - If lateness exceeds max_drift abandon cadence and resync from now.
        - Else if still within interval bump to the next interval.
        - Else skip missed slots but keep original cadence.
        """
        if not self.is_running:
            return
        now = time.monotonic()
        next_deadline = scheduled + self.interval
        if finished <= next_deadline:
            # Still on track
            self._next_deadline = next_deadline
        elif (self.max_drift is not None and
              (finished - scheduled) > self.interval + self.max_drift):
                # Too late: abandon original cadence, resync from now
                self._schedule_from_now()
        else:
            # Missed one or more slots jump forward but preserve cadence
            adjust = max(0, finished - next_deadline)
            self._next_deadline = finished + adjust
            if self._last_fire:
                elapsed = finished - self._last_fire
                intervals_missed = math.floor(elapsed / self.interval)
                _log.debug('Missed %d interval(s) (%0.3f)', intervals_missed, now)

    def _call_target(self):
        try:
            if _vlog():
                _log.debug('Calling %s (%0.3f) with args=%s kwargs=%s',
                           self.target_name,
                           time.monotonic(),
                           self.args,
                           self.kwargs)
            self.target(*self.args, **self.kwargs)
        except Exception as exc:
            _log.exception('%s exception: %s', self.target_name, exc)
            raise

    # ----- Thread loop -----

    def run(self):
        initial_trigger = False
        while not self._terminate_event.is_set():
            self._start_event.wait()
            if self._terminate_event.is_set():
                break

            if self.interval <= 0:
                # Disabled: wait for changes/restart
                self._reset_event.wait(timeout=0.2)
                self._reset_event.clear()
                continue

            # Initialize next deadline if missing
            if self._next_deadline is None:
                now = time.monotonic()
                _log.info('%d-second interval started (%0.3f)',
                          self.interval, now)
                if not self.defer:
                    initial_trigger = True
                    self._last_fire = now
                    self._next_deadline = self._last_fire + self.interval
                    self._call_target()
                else:
                    self._next_deadline = now + self.interval

            # Main loop while running
            while self.is_running and not self._terminate_event.is_set():
                now = time.monotonic()
                remaining = (self._next_deadline or now) - now

                # Wait in small chunks so we can log/observe resets
                while (remaining > 0 and
                       self.is_running and
                       not self._terminate_event.is_set()):
                    if _vlog():
                        _log.debug('%s countdown: %.2fs',
                                   self.name, remaining)
                    # Non-busy sleep but Wake early if reset arrives
                    if self._reset_event.wait(timeout=min(self.sleep_chunk,
                                                          remaining)):
                        self._reset_event.clear()
                        self._schedule_from_now()
                        break
                    now = time.monotonic()
                    remaining = (self._next_deadline or now) - now
                else:
                    # Either time elapsed or we stopped/terminated
                    if not self.is_running or self._terminate_event.is_set():
                        break
                    now = time.monotonic()
                    if not initial_trigger:
                        self._last_fire = now
                        self._call_target()
                    finished = time.monotonic()
                    self._advance_on_schedule(self._next_deadline, finished)
                    initial_trigger = False
                    if _vlog():
                        _log.debug('Triggered %s at %0.3f (duration %0.2f)'
                                   ' next trigger in %0.3f',
                                   self.target_name,
                                   self._last_fire,
                                   finished - (self._last_fire or now),
                                   self._next_deadline - time.monotonic())

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
        now = time.monotonic()
        if trigger_immediate is None or not isinstance(trigger_immediate, bool):
            trigger_immediate = not self.defer
        self._start_event.set()
        self._reset_event.set()
        if trigger_immediate and self.interval > 0:
            self._call_target()
            self._last_fire = now
            self._next_deadline = self._last_fire + self.interval
        if notify:
            _log.info('%d-second interval restarted %s(%0.3f)',
                      self.interval,
                      '(immediate trigger) ' if trigger_immediate else '',
                      now)

    def change_interval(self, seconds: int, trigger_immediate: Optional[bool] = None):
        if not isinstance(seconds, int) or seconds < 0:
            raise ValueError('seconds must be integer >= 0')
        with self._lock:
            old = self._interval
            self._interval = seconds
        _log.info('Interval changed (old: %0.1f s; new: %0.1f s)'
                  ' (trigger_immediate=%s)', old, seconds, trigger_immediate)
        if trigger_immediate is None or not isinstance(trigger_immediate, bool):
            trigger_immediate = not self.defer
        self.restart_timer(trigger_immediate, notify=False)

    def terminate(self):
        self.stop_timer(notify=False)
        self._terminate_event.set()
        self._reset_event.set()
        _log.info('Interval terminated (%0.3f)', time.monotonic())


def _vlog() -> bool:
    return verbose_logging('timer')
