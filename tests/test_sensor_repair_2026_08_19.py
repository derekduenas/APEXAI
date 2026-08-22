"""THE 2026-08-19 SENSOR REPAIR — P0-1 and P0-2.

Two failures cost the first natural-acceptance session 45% of its tape,
and both are tested here for the way they actually presented, not for a
tidy abstraction of them.

P0-1  The reader thread starved its own heartbeat.
      352 reconnects, every one closing with exception=None, intervals
      clustered at PING_INTERVAL multiples, rate tracking message volume.
      on_message parsed ~32M events inline on the same thread the
      websocket library uses to answer pings.

P0-2  Bar persistence overwrote the session file with a rolling window,
      so SPY/QQQ lost 09:30-11:39 ET from disk *during* the session.

The tests below are written so that reverting either fix fails loudly.
"""
from __future__ import annotations

import json
import queue
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from apex.intraday import alpaca_fabric as af  # noqa: E402


# ------------------------------------------------------------ P0-1
def test_on_message_does_no_parsing_on_the_reader_thread():
    """The whole fix. If on_message ever parses again, the pong deadline
    is back in the hands of the market's message rate."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(af.AlpacaRealtimeFabric._on_message)))
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "loads" not in calls, "json.loads is back on the reader thread"
    for forbidden in ("_apply_trade", "_apply_quote", "_subscribe_all"):
        assert forbidden not in calls, f"{forbidden} back on the reader thread"
    assert "put_nowait" in calls, "reader no longer enqueues"


def test_reader_enqueues_and_worker_parses():
    fab = af.AlpacaRealtimeFabric(["SPY"])
    frame = json.dumps([{"T": "t", "S": "SPY", "p": 100.0, "s": 5,
                         "t": "2026-08-19T14:00:00Z", "i": 1}])
    fab._on_message(None, frame)
    assert fab.counters["messages"] == 1
    assert fab._ingest.qsize() == 1
    assert fab.counters["trades"] == 0, "reader must not have applied it"
    assert fab._pump() == 1
    assert fab.counters["trades"] == 1, "worker must apply it"


def test_full_queue_drops_and_counts_rather_than_blocking(monkeypatch):
    """Blocking here would push backpressure onto the reader and rebuild
    the exact starvation being fixed. Dropping is the lesser evil ONLY
    because the drop is counted."""
    fab = af.AlpacaRealtimeFabric(["SPY"])
    monkeypatch.setattr(fab, "_ingest", queue.Queue(maxsize=1))
    fab._on_message(None, "a")
    t0 = time.time()
    fab._on_message(None, "b")
    assert time.time() - t0 < 0.5, "reader blocked on a full queue"
    assert fab.counters["frames_dropped"] == 1


def test_dropped_frames_are_visible_in_health():
    """Silent data loss is the failure mode this whole session was about."""
    fab = af.AlpacaRealtimeFabric(["SPY"])
    h = fab.health()
    assert "frames_dropped" in h["counters"]
    assert "ingest_queue_depth_max" in h
    assert "worker_lag_s_max" in h


def test_ping_timeout_is_margin_not_the_fix():
    """SUPERSEDED by the L2 heartbeat remedy (operator-authorized
    2026-08-21): the library pong-kill is DISABLED (ping_timeout=None)
    because measured evidence proved the server drops pongs under load
    while data flows. Liveness is now the application-level watchdog
    (frame arrival OR pong within LIVENESS_STALE_S)."""
    assert af.PING_TIMEOUT_S is None
    assert af.LIVENESS_STALE_S > af.PING_INTERVAL_S


def test_worker_survives_a_poison_frame():
    fab = af.AlpacaRealtimeFabric(["SPY"])
    fab._on_message(None, "{not json")
    fab._pump()                            # must not raise
    fab._on_message(None, json.dumps([{"T": "t", "S": "SPY", "p": 1.0, "s": 1,
                                       "t": "2026-08-19T14:00:00Z", "i": 2}]))
    fab._pump()
    assert fab.counters["trades"] == 1, "ingestion died on a bad frame"


def test_worker_thread_starts_before_the_reader():
    """A reader with nowhere to put a frame drops it. Order matters."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(af.AlpacaRealtimeFabric.start)))
    targets = [n.value.keywords for n in ast.walk(tree)
               if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)]
    names = []
    for kws in targets:
        for k in kws:
            if k.arg == "target" and isinstance(k.value, ast.Attribute):
                names.append(k.value.attr)
    assert names[:2] == ["_drain", "_run"], f"start order is {names}"


def test_stop_wakes_and_joins_the_worker():
    fab = af.AlpacaRealtimeFabric(["SPY"])
    fab._stop = False
    import threading
    fab._worker = threading.Thread(target=fab._drain, daemon=True)
    fab._worker.start()
    fab.stop()
    time.sleep(0.1)
    assert not fab._worker.is_alive(), "worker did not exit on stop()"


# ------------------------------------------------------------ P0-2
def test_bar_window_covers_a_whole_session_not_400_minutes():
    """08:14 ET premarket start to 19:14 ET post-close is 660 minutes."""
    assert af.AlpacaRealtimeFabric.SESSION_BAR_WINDOW_MIN >= 720


def _bar(ts, close):
    return {"event_time_utc": ts, "open": close, "high": close,
            "low": close, "close": close, "volume": 1.0, "trades": 1,
            "coverage_status": "COMPLETE_HEALTHY", "gap_duration_ms": 0,
            "symbol": "SPY", "transport": "ALPACA_WEBSOCKET_SIP_V1"}


class _FakeFab:
    symbols = ["SPY"]

    def __init__(self, bars):
        self._bars = bars

    def bars_1m(self, sym):
        return pd.DataFrame(self._bars)


def test_persist_merges_and_never_erases_earlier_bars(tmp_path, monkeypatch):
    """THE 2026-08-19 FAILURE, reproduced. The ring rolls forward; the
    morning must survive on disk."""
    import alpaca_fabric_daemon as dmn
    monkeypatch.setattr(dmn, "BARS_DIR", tmp_path)

    morning = [_bar("2026-08-19T13:30:00.000Z", 770.0),
               _bar("2026-08-19T13:31:00.000Z", 770.1)]
    dmn.persist_bars(_FakeFab(morning), "2026-08-19")

    # the ring has now rolled: it can no longer see the morning at all
    afternoon = [_bar("2026-08-19T18:00:00.000Z", 769.0),
                 _bar("2026-08-19T18:01:00.000Z", 769.2)]
    written = dmn.persist_bars(_FakeFab(afternoon), "2026-08-19")

    d = json.loads((tmp_path / "SPY_2026-08-19.json").read_text())
    times = [b["event_time_utc"] for b in d["bars"]]
    assert len(times) == 4, f"session evidence lost: {times}"
    assert times == sorted(times)
    assert "2026-08-19T13:30:00.000Z" in times, "the OPEN was erased again"
    assert d["retention_model"] == "ACCUMULATING_SESSION_STREAM"
    assert d["bars_retained_from_disk"] == 2
    assert written["SPY"] == 4


def test_the_forming_minute_is_superseded_not_duplicated(tmp_path, monkeypatch):
    import alpaca_fabric_daemon as dmn
    monkeypatch.setattr(dmn, "BARS_DIR", tmp_path)
    partial = _bar("2026-08-19T13:30:00.000Z", 770.0)
    partial["volume"] = 100.0
    dmn.persist_bars(_FakeFab([partial]), "2026-08-19")
    complete = _bar("2026-08-19T13:30:00.000Z", 770.5)
    complete["volume"] = 456906.0
    dmn.persist_bars(_FakeFab([complete]), "2026-08-19")
    d = json.loads((tmp_path / "SPY_2026-08-19.json").read_text())
    assert len(d["bars"]) == 1
    assert d["bars"][0]["volume"] == 456906.0, "fresh bar must win"


def test_an_unreadable_session_file_is_never_overwritten(tmp_path, monkeypatch):
    """Corrupt-on-read must not become corrupt-on-disk. Skipping the
    write loses one cycle; overwriting loses the session."""
    import alpaca_fabric_daemon as dmn
    monkeypatch.setattr(dmn, "BARS_DIR", tmp_path)
    bad = tmp_path / "SPY_2026-08-19.json"
    bad.write_text("{ this is not json")
    written = dmn.persist_bars(_FakeFab([_bar("2026-08-19T18:00:00.000Z", 1.0)]),
                               "2026-08-19")
    assert written["SPY"] == -1
    assert bad.read_text() == "{ this is not json", "unreadable file clobbered"


def test_empty_ring_does_not_truncate_an_existing_session_file(tmp_path,
                                                               monkeypatch):
    import alpaca_fabric_daemon as dmn
    monkeypatch.setattr(dmn, "BARS_DIR", tmp_path)
    dmn.persist_bars(_FakeFab([_bar("2026-08-19T13:30:00.000Z", 770.0)]),
                     "2026-08-19")
    dmn.persist_bars(_FakeFab([]), "2026-08-19")
    d = json.loads((tmp_path / "SPY_2026-08-19.json").read_text())
    assert len(d["bars"]) == 1, "an empty ring wiped the session file"


def test_trade_buffer_is_large_enough_for_a_full_session():
    """SPY alone exceeded the old 400k trade cap by late morning, which
    is WHY the ring could not rebuild the open even before persistence
    overwrote it."""
    import inspect
    sig = inspect.signature(af.AlpacaRealtimeFabric.__init__)
    assert sig.parameters["max_trades"].default >= 1_000_000


# ---------------------------------------------- Phase 11/12 (2026-08-20)

def _fab():
    return af.AlpacaRealtimeFabric(["SPY"])


def test_reconnect_reason_is_no_longer_hardcoded():
    """644 lifetime events carried the literal reason=NETWORK_RECONNECT
    regardless of what happened. The reason is now DERIVED; the literal
    may only appear as a branch outcome, never an unconditional kwarg."""
    import ast
    src = Path("apex/intraday/alpaca_fabric.py").read_text()
    assert 'reason="NETWORK_RECONNECT",' not in src
    assert "UNKNOWN_CAUSE" in src            # honest no-evidence label
    assert "HEARTBEAT_TIMEOUT" in src        # ping/pong now attributable


def test_on_error_is_separate_from_on_close():
    """on_error was aliased to _on_close, discarding the exception --
    the single most diagnostic fact about a reconnect."""
    fab = _fab()
    assert hasattr(fab, "_on_error")
    class FakeTimeout(Exception):
        pass
    fab._on_error(None, FakeTimeout("ping/pong timed out"))
    assert fab._last_error_type == "FakeTimeout"
    assert "ping/pong" in fab._last_error_repr


def test_close_frame_is_captured():
    fab = _fab()
    fab._on_close(None, 1006, "abnormal closure")
    assert fab._last_close_code == 1006
    assert fab._last_close_msg == "abnormal closure"


def test_reconnect_event_accepts_telemetry():
    import pandas as pd

    from apex.intraday import reconnect_ledger as rlg
    ev = rlg.make_event(
        event_id="T-1", event_time=pd.Timestamp("2026-08-20", tz="UTC"),
        known_from=pd.Timestamp("2026-08-20", tz="UTC"),
        reason="UNKNOWN_CAUSE", source="test",
        telemetry={"close_code": None, "queue_depth_at_event": 0})
    rec = ev.as_record()
    assert rec["telemetry"]["queue_depth_at_event"] == 0
    assert ev.is_transport_interruption()


def test_health_is_multi_axis_transport_churn_is_degraded_not_failed():
    """Phase 12: a sensor preserving every frame through transport churn
    is DEGRADED (transport axis), never FAILED. FAILED now means the
    sensor is not doing its job (dropping frames)."""
    fab = _fab()
    with fab._lock:
        fab.authorized = True
        fab.subscribed = True
        fab.last_msg_at = __import__("time").time()
        fab._symbols_with_trades = set(fab.symbols)
        fab.counters["reconnects"] = 500          # heavy churn
    h = fab.health()
    assert h["status"] == "DEGRADED"
    assert h["health_axes"]["data_preservation"] is True
    assert h["health_axes"]["transport_stability"] is False

    with fab._lock:
        fab.counters["frames_dropped"] = 10       # NOW it failed its job
    h2 = fab.health()
    assert h2["status"] == "FAILED"
    assert h2["health_axes"]["data_preservation"] is False


def test_quiet_transport_full_coverage_is_healthy():
    fab = _fab()
    with fab._lock:
        fab.authorized = True
        fab.subscribed = True
        fab.last_msg_at = __import__("time").time()
        fab._symbols_with_trades = set(fab.symbols)
        fab.counters["reconnects"] = 0
    assert fab.health()["status"] == "HEALTHY"
