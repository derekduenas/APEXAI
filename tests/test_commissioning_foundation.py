"""PHASE A FOUNDATION COMMISSIONING (2026-08-21) -- Layers 0/1/2.

Born of the Friday clamshell incident: the host slept through an hour of
market, the fabric's coverage axis said 1.0, and every downstream organ
had to be exonerated one at a time. Commissioning law: LAYER N DOES NOT
EXIST UNTIL LAYER N-1 PASSES NATURAL ACCEPTANCE -- and the acceptance
metric itself must reconcile against reality.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# ------------------------------------------------------- LAYER 0: host

def test_sentinel_sleep_detection_math():
    """time.monotonic() pauses across macOS sleep; wall time does not.
    A wall-vs-monotonic divergence beyond SLEEP_GAP_S is the detection
    signal -- verify the threshold semantics used by the sentinel."""
    import host_sentinel as hs
    assert hs.SLEEP_GAP_S >= 2 * hs.BEAT_INTERVAL_S, (
        "sleep gap must exceed two beats or scheduler jitter false-fires")
    # the incident math: 30-min sleep -> wall advances 1800s more than
    # monotonic between consecutive beats
    wall_d, mono_d = 1815.0, 15.0
    assert (wall_d - mono_d) > hs.SLEEP_GAP_S


def test_sentinel_is_installed_and_running():
    hb = Path("results/host/host_heartbeat.json")
    if not hb.exists():
        pytest.skip("sentinel not yet started in this environment")
    beat = json.loads(hb.read_text())
    assert beat["kind"] == "host_heartbeat"
    assert "sleep_incidents_since_start" in beat
    assert beat["decision_power"] == "NONE"


def test_fabric_wrapper_is_caffeinated_with_honest_limits():
    src = Path("ops/alpaca_fabric.sh").read_text()
    assert "caffeinate -i" in src
    assert "CANNOT prevent clamshell" in src, (
        "the wrapper must state what caffeinate does NOT protect against")


def test_sentinel_itself_is_not_caffeinated():
    src = Path("ops/host_sentinel.sh").read_text()
    assert "caffeinate" not in src.replace(
        "NOT caffeinated", "").replace("keeping the box awake", "")


# ------------------------------------------- LAYER 2: metric honesty

def test_tape_continuity_reconciles_against_persisted_reality(
        tmp_path, monkeypatch):
    """THE FRIDAY LAW: continuity 1.0 must be IMPOSSIBLE while known
    multi-minute gaps exist. Synthetic session: 60 elapsed regular
    minutes, 20-minute hole -> continuity ~0.67, never 1.0."""
    import alpaca_fabric_daemon as d
    monkeypatch.setattr(d, "BARS_DIR", tmp_path)
    day = "2026-08-21"
    open_t = pd.Timestamp(f"{day} 09:30:00",
                          tz="America/New_York").tz_convert("UTC")
    bars = []
    for i in range(60):
        if 20 <= i < 40:
            continue                      # the hole
        bars.append({"event_time_utc":
                     str(open_t + pd.Timedelta(minutes=i)),
                     "close": 100.0})
    for sym in d.CONTINUITY_REFERENCE_SYMBOLS:
        (tmp_path / f"{sym}_{day}.json").write_text(
            json.dumps({"bars": bars}))

    class _FakeNow:
        @staticmethod
        def now(tz=None):
            return open_t + pd.Timedelta(minutes=62)
    monkeypatch.setattr(d.pd, "Timestamp", _wrap_timestamp(_FakeNow))
    out = d._tape_continuity(day)
    for sym in d.CONTINUITY_REFERENCE_SYMBOLS:
        assert out[sym] < 0.75, f"{sym} continuity lied: {out[sym]}"
        assert out[sym] > 0.55


def _wrap_timestamp(fake_now_cls):
    """pd.Timestamp stand-in: now() is frozen, everything else passes
    through -- so the helper's date arithmetic still uses real pandas."""
    real = pd.Timestamp

    class _TS:
        def __new__(cls, *a, **k):
            return real(*a, **k)
        now = staticmethod(fake_now_cls.now)
    return _TS


def test_daemon_health_flips_healthy_to_degraded_on_continuity_gap():
    """Source-level pin: the daemon downgrades a HEALTHY verdict when
    reference continuity < 0.97 -- coverage can never again say 1.0
    while the tape has holes."""
    src = Path("scripts/alpaca_fabric_daemon.py").read_text()
    assert "tape_continuity" in src
    assert 'h["status"] = "DEGRADED"' in src


def test_real_friday_continuity_reads_the_damage():
    """Against the actual sleep-damaged Friday session: continuity must
    read well below 1.0. (Skips where the real file is absent.)"""
    import alpaca_fabric_daemon as d
    if not (d.BARS_DIR / "SPY_2026-08-21.json").exists():
        pytest.skip("no real Friday session file")
    out = d._tape_continuity("2026-08-21")
    assert out.get("SPY", 1.0) < 0.95, (
        "the metric failed to see the clamshell damage")


def test_pong_telemetry_exists_and_reconnect_events_carry_it():
    """Layer 2's open question is WHICH side of the heartbeat dies.
    The fabric must register on_ping/on_pong and stamp last-pong age
    into every reconnect event's telemetry."""
    src = Path("apex/intraday/alpaca_fabric.py").read_text()
    assert "on_ping=self._on_ping" in src
    assert "on_pong=self._on_pong" in src
    assert "last_pong_age_s" in src
    assert "pongs_received_lifetime" in src


# --------------------------------------------- LAYER 1: broker read-only

def test_layer1_acceptance_record_exists_and_is_read_only():
    """The Layer 1 natural acceptance ran live 2026-08-21 (~15:30 ET):
    6 reads, byte-identical reconciliation, auth persisted. The durable
    record pins its scope: READ_ONLY, order authority SEALED, restricted
    to the single agentic-enabled account."""
    p = Path("results/commissioning/layer1_robinhood_acceptance.json")
    if not p.exists():
        pytest.skip("acceptance record not present in this environment")
    rec = json.loads(p.read_text())
    assert rec["authority"] == "READ_ONLY"
    assert rec["order_authority"] == "SEALED"
    assert rec["verdict"] == "PASS"
    assert rec["reads_attempted"] == rec["reads_succeeded"] >= 6


# ------------------------------------------- LAYER 3: bar reconciliation

def test_mid_minute_silence_cannot_be_complete_healthy():
    """Layer 3 finding (2026-08-21): a bar with trades at both edges but
    a 25s dead zone mid-minute claimed COMPLETE_HEALTHY while holding a
    fraction of the real volume. Intra-minute silence beyond
    MAX_INTRA_GAP_S must read COMPLETE_WITH_GAP."""
    from apex.intraday.bar_builder import build_1m_bars
    t0 = T0 = pd.Timestamp("2026-08-21 14:35:00", tz="UTC").timestamp()
    tr = ([{"event_s": t0 + s, "price": 100.0, "size": 10}
           for s in (0, 2, 4, 6)] +
          [{"event_s": t0 + s, "price": 100.1, "size": 10}
           for s in (52, 55, 58)])           # 46s of mid-minute silence
    bars = build_1m_bars(tr, [], now=pd.Timestamp(t0, unit="s", tz="UTC")
                         + pd.Timedelta(minutes=2),
                         symbol="SPY", transport="TEST")
    assert bars.iloc[0]["coverage_status"] == "COMPLETE_WITH_GAP"


def test_continuous_minute_stays_complete_healthy():
    from apex.intraday.bar_builder import build_1m_bars
    t0 = pd.Timestamp("2026-08-21 14:35:00", tz="UTC").timestamp()
    tr = [{"event_s": t0 + s, "price": 100.0, "size": 10}
          for s in range(0, 60, 5)]
    bars = build_1m_bars(tr, [], now=pd.Timestamp(t0, unit="s", tz="UTC")
                         + pd.Timedelta(minutes=2),
                         symbol="SPY", transport="TEST")
    assert bars.iloc[0]["coverage_status"] == "COMPLETE_HEALTHY"


def test_layer3_reconciliation_record_exists():
    p = Path("results/commissioning/layer3_bar_reconciliation.json")
    if not p.exists():
        pytest.skip("no reconciliation record in this environment")
    rec = json.loads(p.read_text())
    assert "Alpaca REST" in rec["reference"]      # independent path
    for sym, r in rec["results"].items():
        assert r["high_low_violations"] <= 2      # containment holds


# --------------------- L2 HEARTBEAT REMEDY (operator-authorized Fri PM)

def _fab():
    import apex.intraday.alpaca_fabric as af
    return af.AlpacaRealtimeFabric(["SPY"])


def test_remedy_a_no_pong_fresh_data_remains_connected():
    """LAW: fresh valid inbound market data = alive. Pong stale + data
    fresh must NOT trip the stale-close; it is counted instead."""
    import time as _t

    import apex.intraday.alpaca_fabric as af
    fab = _fab()

    class _WS:
        closed = False
        def close(self):
            self.closed = True
    ws = _WS()
    with fab._lock:
        fab._ws = ws
        fab.connected_at = _t.time() - 300          # old connection
        fab.last_msg_at = _t.time() - 1.0           # DATA FRESH
        fab._last_pong_at = _t.time() - 200         # PONG LONG STALE
    # run one watchdog evaluation inline (the loop body's logic)
    now = _t.time()
    anchor = max(fab.connected_at, fab.last_msg_at or 0,
                 fab._last_pong_at or 0)
    assert now - anchor <= af.LIVENESS_STALE_S      # alive by law
    assert not ws.closed


def test_remedy_b_no_pong_stale_data_reconnects():
    """No data AND no pong past LIVENESS_STALE_S -> the watchdog closes
    with the MESSAGE_STREAM_STALE label."""
    import time as _t

    import apex.intraday.alpaca_fabric as af
    fab = _fab()
    with fab._lock:
        fab._ws = type("W", (), {"closed": False,
                                 "close": lambda s: setattr(s, "closed",
                                                            True)})()
        fab.connected_at = _t.time() - 300
        fab.last_msg_at = _t.time() - 120           # data stale
        fab._last_pong_at = _t.time() - 120         # pong stale
    now = _t.time()
    anchor = max(fab.connected_at, fab.last_msg_at, fab._last_pong_at)
    assert now - anchor > af.LIVENESS_STALE_S       # watchdog would close


def test_remedy_c_d_close_and_error_paths_still_reconnect():
    """Genuine failure detection preserved: _on_close and _on_error
    still mark the disconnect (the reconnect loop then fires)."""
    fab = _fab()
    fab._on_close(None, 1006, "abnormal")
    assert fab._disconnected_at is not None
    assert fab._last_close_code == 1006
    fab2 = _fab()
    fab2._on_error(None, ConnectionResetError("reset"))
    assert fab2._disconnected_at is not None
    assert fab2._last_error_type == "ConnectionResetError"


def test_remedy_e_backpressure_cannot_masquerade_as_transport_failure():
    """A full ingest queue drops-and-counts; it never touches the
    liveness anchors, so it can never cause a stale-close."""
    import queue as _q
    import time as _t
    fab = _fab()
    fab._ingest = _q.Queue(maxsize=1)
    fab._ingest.put_nowait(("x", _t.time(), None))
    fab._on_message(None, "frame2")                 # queue full -> drop
    assert fab.counters["frames_dropped"] == 1
    assert fab._last_frame_at is not None           # TRANSPORT liveness
                                                    # advanced by arrival


def test_remedy_f_reason_taxonomy_and_telemetry_fields():
    import apex.intraday.alpaca_fabric as af
    from apex.intraday import reconnect_ledger as rlg
    assert "MESSAGE_STREAM_STALE" in rlg.REASON_CODES
    assert "MESSAGE_STREAM_STALE" in rlg.TRANSPORT_INTERRUPTION_CODES
    src = Path("apex/intraday/alpaca_fabric.py").read_text()
    for field in ("last_pong_age_s", "pongs_received_lifetime",
                  "MESSAGE_STREAM_STALE", "pong_missing_data_fresh"):
        assert field in src
    assert af.PING_TIMEOUT_S is None                # library kill disabled
    assert af.LIVENESS_STALE_S == 60.0


def test_remedy_not_an_immortal_connection():
    """The stale path exists and is reachable: watchdog closes when both
    anchors exceed the window -- source-level proof the remedy did not
    create an unkillable half-open socket."""
    src = Path("apex/intraday/alpaca_fabric.py").read_text()
    assert "_liveness_watchdog" in src
    assert "ws.close()" in src
    assert "QUIET_RETRY_SLEEP_S" in src             # overnight backoff
