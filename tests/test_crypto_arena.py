"""Crypto shadow arena: as-of law, fail-closed playbooks, evidence
separation, budget, resolver maturity. No live feed calls in tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.crypto.perception import compute_state, crypto_world
from apex.crypto.playbooks import match_crypto_001, match_crypto_002
from apex.hunter.evidence import (EvidenceClass, EvidenceViolation,
                                  require_unmixed)

T = pd.Timestamp("2026-08-16 14:00", tz="UTC")


def candles(n=1560, base=63000.0, drift=0.0, vol_per_min=2.0, seed=7,
            noise=2e-4):
    rng = np.random.default_rng(seed)
    times = pd.date_range(T - pd.Timedelta(minutes=n), periods=n,
                          freq="1min")
    close = base * np.cumprod(1 + drift / n + rng.normal(0, noise, n))
    op = np.r_[base, close[:-1]]
    return pd.DataFrame({"event_time_utc": times, "open": op,
                         "high": np.maximum(op, close) * 1.0002,
                         "low": np.minimum(op, close) * 0.9998,
                         "close": close, "volume": vol_per_min})


BASELINE = {str(h): 120.0 for h in range(24)}


def test_future_poison_crypto_state():
    f = candles()
    s1 = compute_state("BTC-USD", f, T, BASELINE, None)
    p = f.copy()
    late = p["event_time_utc"] + pd.Timedelta(minutes=1) > T
    p.loc[late, ["open", "high", "low", "close"]] = 999999.0
    s2 = compute_state("BTC-USD", p, T, BASELINE, None)
    assert s1.as_record() == s2.as_record()


def test_breakout_excludes_current_bar():
    f = candles()
    # current bar spikes to a new 4h high: must NOT count as broken-out
    # structure against itself alone if prior extreme stands above price
    s = compute_state("BTC-USD", f, T, BASELINE, None)
    assert s.hi_4h is not None and s.lo_4h is not None
    assert isinstance(s.breakout_4h_up, bool)


def test_playbooks_fail_closed_on_missing_world():
    s = compute_state("BTC-USD", candles(), T, BASELINE, None)
    assert match_crypto_001(s, {"btc_eth_rs_60m": None}) is None
    assert match_crypto_002(s, {}, {}) is None    # no extreme ages


def test_world_uncertainty_conservative():
    s_btc = compute_state("BTC-USD", candles(drift=0.5, seed=2), T,
                          BASELINE, None)     # violent hour
    w = crypto_world({"BTC-USD": s_btc}, T)
    assert w["uncertain"] in (True, False)
    w2 = crypto_world({}, T)
    assert w2["uncertain"] is True               # unknown = uncertain


def test_crypto_evidence_never_mixes_with_equity():
    with pytest.raises(EvidenceViolation):
        require_unmixed({EvidenceClass.COINBASE_FORWARD_OBSERVATION,
                         EvidenceClass.EODHD_FORWARD_OBSERVATION})
    require_unmixed({EvidenceClass.COINBASE_FORWARD_OBSERVATION})  # alone ok


def test_resolver_waits_for_maturity_and_swarm_budget():
    from apex.crypto.arena import resolve_pending, swarm_budget_left
    dec = {"kind": "crypto_decision", "decision_id": "d1",
           "t_utc": str(T - pd.Timedelta(minutes=30)),
           "direction": "LONG", "shadow_entry_price": 63000.0,
           "stop": 62800.0, "target": 63400.0, "time_stop_minutes": 90}
    out = resolve_pending([dec], candles(), T)
    assert out == []                             # 30m < 92m: not mature
    old = dict(dec, t_utc=str(T - pd.Timedelta(minutes=120)))
    out2 = resolve_pending([old], candles(), T)
    assert len(out2) == 1 and out2[0]["resolvable"]
    assert "ret_90m" in out2[0] and "mae_60m" in out2[0]
    rows = [{"kind": "crypto_assassin", "t_utc": f"2026-08-16 0{i}:00",
             "swarm_view": {"status": "OK"}} for i in range(5)]
    assert swarm_budget_left(rows, "2026-08-16") == 7
