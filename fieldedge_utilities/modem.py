"""Classes for managing satellite modem interaction and metrics.

`ConnectionManager` provides housekeeping for attempting to connect to a
modem that may have transient connectivity to the microcontroller.
It allows for backing off from retrying connection, counting timeouts and CRC
errors from AT command responses and threshold maximums for each.

`QosMetricsManager` provides housekeeping for sample and metrics publishing
intervals that are interdependent.

"""
import logging
from dataclasses import dataclass

__all__ = ['ConnectionManager', 'QosMetricsManager']

_log = logging.getLogger(__name__)


@dataclass
class ConnectionManager:
    """Counters for connection management.
    
    The invoking application is expected to increment the counters accordingly.
    
    """
    retry_interval: int = 30
    backoff_interval: int = 30
    init_attempts: int = 0
    at_timeouts: int = 0
    max_at_timeouts: int = 3
    at_crc_errors: int = 0
    max_crc_errors: int = 5

    def __post_init__(self):
        if self.backoff_interval != self.retry_interval:
            self.backoff_interval = self.retry_interval

    def timeouts_exceeded(self) -> bool:
        """Returns True if at_timeouts >= max_at_timeouts."""
        return self.at_timeouts >= self.max_at_timeouts

    def crc_exceeded(self) -> bool:
        """Returns True if at_crc_errors >= max_crc_errors."""
        return self.at_crc_errors >= self.max_crc_errors

    def reset(self) -> None:
        """Resets all counters to zero."""
        self.init_attempts = 0
        self.at_timeouts = 0
        self.at_crc_errors = 0
        self.backoff_interval = self.retry_interval

    def backoff(self) -> None:
        """Increases the backoff_interval for initialization retries.
        
        Every 3 attempts, the backoff_interval will double up to a maximum
        of one day (86400 seconds).
        
        """
        if self.init_attempts > 3 and self.init_attempts % 3 == 0:
            if self.backoff_interval * 2 <= 86400:
                self.backoff_interval = self.backoff_interval * 2


class QosMetricsManager:
    """Manages settings and counters for QoS metrics.
    
    The invoking application is expected to increment the counters accordingly.
    
    """
    def __init__(self,
                 sample_interval: int = 12,
                 metrics_interval: int = 300) -> None:
        """Initializes the metrics manager."""
        self._metrics_interval: int = 300
        self.metrics_interval = metrics_interval
        self._sample_interval: int = 12
        self.sample_interval = sample_interval
        self.sample_count: int = 0
        self.metrics_count: int = 0

    @property
    def metrics_interval(self) -> int:
        """The metrics publish interval in seconds. (0..86400)"""
        return self._metrics_interval

    @metrics_interval.setter
    def metrics_interval(self, value: int):
        if not isinstance(value, int) or value not in range (0, 86401):
            raise ValueError('value must be integer 0..86400')
        self._metrics_interval = value

    def reset_counters(self) -> None:
        """Resets the metrics counters."""
        self.metrics_count = 0
        self.sample_count = 0

    @property
    def sample_interval(self) -> int:
        """The metrics sample interval in seconds. (0..86400)"""
        return self._sample_interval

    @sample_interval.setter
    def sample_interval(self, value: int):
        if (not isinstance(value, int) or
            value < 0 or
            value > self.metrics_interval):
            # Invalid
            raise ValueError('value must be integer 0..metrics_interval')
        if value > 0 and self.metrics_interval % value != 0:
            value = int(self.metrics_interval / value)
            _log.warning('Adjusted sample_interval to %s', value)
        self._sample_interval = value
