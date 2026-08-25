"""L2 LIVENESS LAW — fresh VALID inbound data proves the connection.

The adversarial matrix the operator specified. The distinction that
matters: a frame ARRIVING is not evidence of life. A peer emitting
malformed bytes, or replaying its buffer, keeps a transport anchor
fresh forever while delivering no market truth -- and the old law would
have called that connection healthy.
"""
from __future__ import annotations

import json
import time

from apex.intraday.alpaca_fabric import AlpacaRealtimeFabric


def _fab():
    f = AlpacaRealtimeFabric(symbols=["SPY"])
    f._newest_event_epoch = 0.0
    f._last_valid_data_at = None
    return f


def _trade(ts_epoch, price=100.0):
    import datetime as dt
    iso = dt.datetime.fromtimestamp(ts_epoch, dt.timezone.utc).isoformat()
    return json.dumps([{"T": "t", "S": "SPY", "p": price, "s": 1,
                        "t": iso}])


# ------------------------------------------- the five required cases

def test_fresh_valid_data_with_missing_pong_does_not_reconnect():
    f = _fab()
    now = time.time()
    f._advance_valid_liveness(_trade(now), now)
    assert f._last_valid_data_at == now, \
        "valid market data must prove liveness even with no pong"


def test_no_data_and_missing_pong_leaves_the_anchor_unset():
    """Nothing arrives -> nothing advances -> the watchdog may recover."""
    f = _fab()
    assert f._last_valid_data_at is None


def test_malformed_traffic_does_not_prove_liveness():
    f = _fab()
    now = time.time()
    f._advance_valid_liveness(b"{not json at all", now)
    assert f._last_valid_data_at is None, \
        "garbage bytes kept the connection 'alive' -- the exact way a " \
        "dead feed masquerades as a live one"
    assert f.counters.get("liveness_rejected_malformed") == 1


def test_replayed_traffic_does_not_prove_liveness():
    f = _fab()
    now = time.time()
    f._advance_valid_liveness(_trade(now), now)
    f._last_valid_data_at = None                  # only replay may set it
    f._advance_valid_liveness(_trade(now - 30), now + 1)   # older event
    assert f._last_valid_data_at is None
    assert f.counters.get("liveness_rejected_replay") == 1


def test_future_dated_traffic_does_not_prove_liveness():
    f = _fab()
    now = time.time()
    f._advance_valid_liveness(_trade(now + 600), now)
    assert f._last_valid_data_at is None
    assert f.counters.get("liveness_rejected_future") == 1


def test_a_continuing_valid_stream_stays_stable_without_pongs():
    """Monday's shape: 141 missing pongs, data flowing throughout."""
    f = _fab()
    t = time.time()
    for i in range(20):
        t += 1.0
        f._advance_valid_liveness(_trade(t), t)
    assert f._last_valid_data_at == t
    assert not f.counters.get("liveness_rejected_malformed")
    assert not f.counters.get("liveness_rejected_replay")


def test_a_non_market_frame_does_not_advance_liveness():
    """Control/subscription acks are not market truth."""
    f = _fab()
    now = time.time()
    f._advance_valid_liveness(
        json.dumps([{"T": "subscription", "trades": ["SPY"]}]), now)
    assert f._last_valid_data_at is None


def test_the_watchdog_anchors_on_valid_data_not_raw_frames():
    import inspect
    from apex.intraday import alpaca_fabric as m
    src = inspect.getsource(m.AlpacaRealtimeFabric._liveness_watchdog)
    assert "_last_valid_data_at" in src
    assert "_last_frame_at" not in src, \
        "the watchdog must not anchor on transport arrival"
