"""A threaded timer class that allows flexible reconfiguration.

"""
import logging
import threading
from time import time

_log = logging.getLogger(__name__)


class RepeatingTimer(threading.Thread):
    """A repeating thread to call a function, can be stopped/restarted/changed.
    
    Embedded tasks can use threading for continuous repeated operations.  A
    *RepeatingTimer* can be started, stopped, restarted and reconfigured.

    A Thread that counts down seconds using sleep increments, then calls back 
    to a function with any provided arguments.
    Optional auto_start feature starts the thread and the timer, in this case 
    the user doesn't need to explicitly start() then start_timer().

    Attributes:
        name (str): An optional descriptive name for the Thread.
        interval (int): Repeating timer interval in seconds (0=disabled).
        sleep_chunk (float): The fraction of seconds between processing ticks.

    """
    def __init__(self,
                 seconds: int,
                 target: callable,
                 args: tuple = (),
                 kwargs: dict = {},
                 name: str = None,
                 sleep_chunk: float = 0.25,
                 max_drift: int = None,
                 auto_start: bool = False,
                 defer: bool = True,
                 daemon: bool = True,
                 verbose_debug: bool = False,
                 ):
        """Sets up a RepeatingTimer thread.

        Args:
            seconds: Interval for timer repeat.
            target: The function to execute each timer expiry.
            args: Positional arguments required by the target.
            kwargs: Optional keyword arguments to pass into the target.
            name: Optional thread name.
            sleep_chunk: Tick seconds between expiry checks.
            max_drift: Number of seconds clock drift to tolerate.
            auto_start: Starts the thread and timer when created.
            defer: Set if first target waits for timer expiry.
            daemon: Set if thread is a daemon (default)
            verbose_debug: verbose logging of tick count

        Raises:
            ValueError if seconds is not an integer.
        """
        if not (isinstance(seconds, int) and seconds >= 0):
            err_str = 'RepeatingTimer seconds must be integer >= 0'
            raise ValueError(err_str)
        super().__init__(daemon=daemon)
        self.name = name or f'{target.__name__}_timer_thread'
        self.interval = seconds
        if target is None:
            _log.warning(f'No target specified for RepeatingTimer {self.name}')
        self.target = target
        self._exception = None
        self.args = args
        self.kwargs = kwargs
        self.sleep_chunk = sleep_chunk
        self._defer = defer
        self._verbose_debug = verbose_debug
        self._terminate_event = threading.Event()
        self._start_event = threading.Event()
        self._reset_event = threading.Event()
        self._count = self.interval / self.sleep_chunk
        self._timesync = time()
        self.max_drift = max_drift
        if auto_start:
            self.start()
            self.start_timer()

    @property
    def sleep_chunk(self) -> float:
        return self._sleep_chunk

    @sleep_chunk.setter
    def sleep_chunk(self, value: float):
        if 1 % value != 0:
            raise ValueError('sleep_chunk must evenly divide 1 second')
        self._sleep_chunk = value

    @property
    def is_running(self) -> bool:
        return self._start_event.is_set()

    def _resync(self, max_drift: int = None) -> int:
        """Used to adjust the next countdown to account for drift.
        
        NOTE: Untested.
        """
        if max_drift is not None:
            drift = time() - self._timesync % self.interval
            max_drift = 0 if max_drift < 1 else max_drift
            if drift > max_drift:
                _log.warning(f'Detected drift of {drift}s')
                return drift
        return 0

    def run(self):
        """*Note: runs automatically, not meant to be called explicitly.*
        
        Counts down the interval, checking every ``sleep_chunk`` for expiry.
        """
        while not self._terminate_event.is_set():
            while (self._count > 0
                   and self._start_event.is_set()
                   and self.interval > 0):
                if self._verbose_debug:
                    if (self._count * self.sleep_chunk
                        - int(self._count * self.sleep_chunk)
                        == 0.0):
                        #: log debug message at reasonable interval
                        _log.debug(f'{self.name} countdown:'
                                   f' {self._count}'
                                   f' ({self.interval}s'
                                   f' @ step {self.sleep_chunk})')
                if self._reset_event.wait(self.sleep_chunk):
                    self._reset_event.clear()
                    self._count = self.interval / self.sleep_chunk
                self._count -= 1
                if self._count <= 0:
                    try:
                        self.target(*self.args, **self.kwargs)
                        drift_adjust = (self.interval
                                        - self._resync(self.max_drift))
                        self._count = drift_adjust / self.sleep_chunk
                    except BaseException as e:
                        self._exception = e

    def start_timer(self):
        """Initially start the repeating timer."""
        self._timesync = time()
        if not self._defer and self.interval > 0:
            self.target(*self.args, **self.kwargs)
        self._start_event.set()
        if self.interval > 0:
            _log.info(f'{self.name} timer started ({self.interval} s)')
        else:
            _log.warning(f'{self.name} timer cannot trigger (interval=0)')

    def stop_timer(self):
        """Stop the repeating timer."""
        self._start_event.clear()
        _log.info(f'{self.name} timer stopped ({self.interval} s)')
        self._count = self.interval / self.sleep_chunk

    def restart_timer(self):
        """Restart the repeating timer (after an interval change)."""
        if not self._defer and self.interval > 0:
            self.target(*self.args, **self.kwargs)
        if self._start_event.is_set():
            self._reset_event.set()
        else:
            self._start_event.set()
        if self.interval > 0:
            _log.info(f'{self.name} timer restarted ({self.interval} s)')
        else:
            _log.warning(f'{self.name} timer cannot trigger (interval=0)')

    def change_interval(self, seconds: int):
        """Change the timer interval and restart it.
        
        Args:
            seconds (int): The new interval in seconds.
        
        Raises:
            ValueError if seconds is not an integer.

        """
        if (isinstance(seconds, int) and seconds >= 0):
            _log.info(f'{self.name} timer interval changed'
                      f' (old:{self.interval} s new:{seconds} s)')
            self.interval = seconds
            self._count = self.interval / self.sleep_chunk
            self.restart_timer()
        else:
            err_str = 'RepeatingTimer seconds must be integer >= 0'
            _log.error(err_str)
            raise ValueError(err_str)

    def terminate(self):
        """Terminate the timer. (Cannot be restarted)"""
        self.stop_timer()
        self._terminate_event.set()
        _log.info(f'{self.name} timer terminated')
    
    def join(self):
        super(RepeatingTimer, self).join()
        if self._exception:
            raise self._exception
        return self.target
