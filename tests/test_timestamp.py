from time import time

from fieldedge_utilities import timestamp


def test_ts_to_iso():
    ts = time()
    iso = timestamp.ts_to_iso(ts)
    assert isinstance(iso, str)
    assert len(iso) == 20
    iso_ms = timestamp.ts_to_iso(ts, include_ms=True)
    assert len(iso_ms) == 24
    ts_spec = 1609459200
    iso_spec = timestamp.ts_to_iso(ts_spec)
    assert iso_spec == '2021-01-01T00:00:00Z'


def test_iso_to_ts():
    iso = '2021-01-01T00:00:00Z'
    ts = timestamp.iso_to_ts(iso)
    assert isinstance(ts, int)
    assert ts == 1609459200
    iso_ms = '2021-01-01T00:00:00.123Z'
    ts = timestamp.iso_to_ts(iso_ms)
    assert ts == 1609459200
    ts_ms = timestamp.iso_to_ts(iso_ms, include_ms=True)
    assert ts_ms == 1609459200.123

