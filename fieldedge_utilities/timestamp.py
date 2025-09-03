"""Helpers for managing unambiguous timestamps and date representation.

"""
import time
from datetime import datetime, timezone
from typing import Optional, Union


def is_millis(timestamp: Union[int, float],
              epoch_year: Optional[int] = None) -> bool:
    """Return True if timestamp looks like milliseconds since epoch."""
    if not isinstance(timestamp, (int, float)) or timestamp < 0:
        raise ValueError('Invalid timestamp must be positive int or float')
    now_sec = time.time()
    if isinstance(epoch_year, int):
        if epoch_year < 1970:
            raise ValueError('Invalid epoch year must be 1970 or later')
        elif epoch_year > 1970:
            target = datetime(epoch_year, 1, 1, tzinfo=timezone.utc)
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            delta = target - epoch
            now_sec -= int(delta.total_seconds())
    now_ms = now_sec * 1000
    diff_sec = abs(timestamp - now_sec)
    diff_ms = abs(timestamp - now_ms)
    return diff_ms < diff_sec


def ts_to_iso(timestamp: Union[float, int], include_ms: bool = False) -> str:
    """Converts a unix timestamp to ISO 8601 format (UTC).
    
    Args:
        timestamp: A unix timestamp.
        include_ms: Flag indicating whether to include milliseconds in response
    
    Returns:
        ISO 8601 UTC format e.g. `YYYY-MM-DDThh:mm:ss[.sss]Z`

    """
    iso_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    if not include_ms:
        return f'{iso_time[:19]}Z'
    return f'{iso_time[:23]}Z'


def iso_to_ts(iso_time: str, include_ms: bool = False) -> Union[int, float]:
    """Converts a ISO 8601 timestamp (UTC) to unix timestamp in seconds.
    
    Args:
        iso_time: An ISO 8601 UTC datetime `YYYY-MM-DDThh:mm:ss[.sss]Z`.
        include_ms: Flag indicating whether to include milliseconds in response.
    
    Returns:
        Unix UTC timestamp as an integer, or float if `include_ms` flag is set.

    """
    if '.' not in iso_time:
        iso_time = iso_time.replace('Z', '.000Z')
    utc_dt = datetime.strptime(iso_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    ts = (utc_dt - datetime(1970, 1, 1)).total_seconds()
    return int(ts) if not include_ms else ts
