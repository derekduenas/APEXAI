"""Market Fabric: health authority, sequence gaps, book walking, own
bars from the trade stream. No network calls (synthetic messages)."""

from __future__ import annotations

import json
import time

from apex.crypto.fabric import BookState, MarketFabric


def _l2(product, updates, typ="update", seq=1):
    return json.dumps({"channel": "l2_data", "sequence_num": seq,
                       "events": [{"type": typ, "product_id": product,
                                   "updates": updates}]})


def _upd(side, price, qty):
    return {"side": side, "price_level": str(price),
            "new_quantity": str(qty)}


def test_book_apply_and_zero_removes_level():
    b = BookState()
    b.apply("bid", 100.0, 2.0)
    b.apply("ask", 101.0, 3.0)
    assert b.snapshot()["status"] == "OK"
    b.apply("bid", 100.0, 0.0)                    # zero removes
    assert b.snapshot()["status"] == "EMPTY"


def test_book_walk_slippage_and_insufficient_depth():
    b = BookState()
    for i, (p, q) in enumerate([(100.0, 1.0), (100.5, 1.0), (101.0, 5.0)]):
        b.apply("ask", p, q)
    b.apply("bid", 99.5, 10.0)
    w = b.walk("BUY", 150)                        # 1.5 units at ~100.17
    assert w["status"] == "OK" and w["slippage_bps"] > 0
    assert w["top_of_book"] == 100.0
    assert b.walk("BUY", 10_000_000)["status"] == \
        "INSUFFICIENT_DISPLAYED_DEPTH"


def test_sequence_gap_revokes_microstructure_authority():
    f = MarketFabric(products=("BTC-USD",), archive=False)
    f._on_message(None, _l2("BTC-USD", [_upd("bid", 100, 1),
                                        _upd("ask", 101, 1)], seq=1))
    assert f.microstructure_authorized() is True
    f._on_message(None, _l2("BTC-USD", [_upd("bid", 100, 2)], seq=5))
    assert f.health["gaps_detected"] == 1
    assert f.health["book_health"] == "DEGRADED_SEQUENCE_GAP"
    assert f.microstructure_authorized() is False   # authority revoked


def test_stale_feed_degrades_never_assumes_unchanged():
    f = MarketFabric(products=("BTC-USD",), archive=False)
    f._on_message(None, _l2("BTC-USD", [_upd("bid", 100, 1),
                                        _upd("ask", 101, 1)], seq=1))
    f.health["last_msg"] = time.time() - 120       # simulate silence
    f._refresh_book_health(time.time())
    assert f.health["book_health"] == "DEGRADED_STALE"
    assert f.microstructure_authorized() is False


def test_own_bars_from_trade_stream_completed_only():
    import pandas as pd
    f = MarketFabric(products=("BTC-USD",), archive=False)
    now = pd.Timestamp.now(tz="UTC")
    msgs = []
    for i in range(120):
        ts = (now - pd.Timedelta(minutes=3) + pd.Timedelta(seconds=i)
              ).isoformat().replace("+00:00", "Z")
        msgs.append({"product_id": "BTC-USD", "price": str(63000 + i),
                     "size": "0.01", "side": "BUY", "time": ts})
    f._on_message(None, json.dumps(
        {"channel": "market_trades", "sequence_num": 1,
         "events": [{"trades": msgs}]}))
    bars = f.bars_1m("BTC-USD")
    assert len(bars) >= 1
    assert {"open", "high", "low", "close", "volume", "trades",
            "buy_volume"} <= set(bars.columns)
    cur = now.floor("1min")
    assert (bars["event_time_utc"] < cur).all()    # completed only


def test_gap_authority_returns_only_after_snapshot_resync():
    f = MarketFabric(products=("BTC-USD",), archive=False)
    f._on_message(None, _l2("BTC-USD", [_upd("bid", 100, 1),
                                        _upd("ask", 101, 1)],
                            typ="snapshot", seq=1))
    assert f.microstructure_authorized()
    f._on_message(None, _l2("BTC-USD", [_upd("bid", 100, 2)], seq=9))
    assert not f.microstructure_authorized()      # gap
    f._on_message(None, _l2("BTC-USD", [_upd("bid", 100, 3)], seq=10))
    assert not f.microstructure_authorized()      # increments do NOT heal
    f._on_message(None, _l2("BTC-USD", [_upd("bid", 100, 1),
                                        _upd("ask", 101, 1)],
                            typ="snapshot", seq=11))
    assert f.microstructure_authorized()          # snapshot heals


def test_lab06_archive_is_bounded_and_excludes_l2_firehose():
    """The research archive must never be able to starve production of
    disk: L2 is live state only; trades/ticker are archived with
    rotation, 72h retention, and a hard size cap."""
    import apex.crypto.fabric as fab
    assert "l2_data" not in fab.ARCHIVE_CHANNELS
    assert set(fab.ARCHIVE_CHANNELS) == {"market_trades", "ticker"}
    assert fab.ARCHIVE_MAX_MB <= 500 and fab.ARCHIVE_RETAIN_HOURS <= 168
    f = fab.MarketFabric(products=("BTC-USD",), archive=True)
    f._archive_event({"channel": "l2_data", "events": []})
    assert f._archive_writes == 0                 # firehose never written


def test_disk_governor_sovereignty_ladder():
    """Free disk is sovereign like API quota: crypto yields before
    production. Graduated: HEALTHY -> TRIM -> MINIMAL -> SUSPEND."""
    import apex.crypto.diskgov as dg

    def state(free):
        avail = free - dg.PRODUCTION_RESERVE - dg.CRITICAL_SERVICE_RESERVE
        return {"mode": ("HEALTHY" if avail >= dg.CRYPTO_TRIM_BELOW
                         else "TRIM" if avail >= dg.CRYPTO_MINIMAL_BELOW
                         else "MINIMAL" if avail > 0 else "SUSPEND"),
                "free_gb": free / 1e9}
    healthy = state(10_000_000_000)
    trim = state(3_900_000_000)
    minimal = state(3_600_000_000)
    dead = state(3_000_000_000)
    assert dg.may_archive_raw(healthy) and not dg.may_archive_raw(trim)
    assert dg.may_snapshot(minimal) and not dg.may_snapshot(dead)
    assert dg.snapshot_interval_s(minimal) > dg.snapshot_interval_s(healthy)
    assert dg.must_suspend(dead) and not dg.must_suspend(minimal)
    live = dg.disk_state()                        # real machine
    assert live["mode"] in ("HEALTHY", "TRIM", "MINIMAL", "SUSPEND")
    assert live["production_reserve_bytes"] >= 2_000_000_000


def test_decision_book_snapshot_preserves_the_ladder():
    b = BookState()
    for i in range(40):
        b.apply("bid", 100.0 - i * 0.1, 1.0 + i)
        b.apply("ask", 101.0 + i * 0.1, 2.0 + i)
    snap = b.decision_snapshot(depth=30)
    assert snap["status"] == "OK" and len(snap["top_bids"]) == 30
    assert snap["depth5_bid"] > 0 and snap["depth10_ask"] > 0
    # the walk must be reproducible from the retained ladder
    walk = b.walk("BUY", 5_000)
    assert walk["status"] == "OK"
    assert snap["top_asks"][0][0] == walk["top_of_book"]


def test_bar_provenance_marks_gapped_and_thin_bars():
    import pandas as pd
    f = MarketFabric(products=("BTC-USD",), archive=False)
    now = pd.Timestamp.now(tz="UTC")
    base = now.floor("1min") - pd.Timedelta(minutes=3)
    msgs = []
    for i in range(60):                            # dense healthy minute
        ts = (base + pd.Timedelta(seconds=i)).isoformat().replace(
            "+00:00", "Z")
        msgs.append({"product_id": "BTC-USD", "price": "63000",
                     "size": "0.01", "side": "BUY", "time": ts})
    thin = (base + pd.Timedelta(minutes=1, seconds=30)).isoformat(
        ).replace("+00:00", "Z")
    msgs.append({"product_id": "BTC-USD", "price": "63010",
                 "size": "0.01", "side": "SELL", "time": thin})
    f._on_message(None, json.dumps({"channel": "market_trades",
                                    "sequence_num": 1,
                                    "events": [{"trades": msgs}]}))
    # inject a feed outage covering the second minute
    b1 = (base + pd.Timedelta(minutes=1)).timestamp()
    f._outages.append((b1 + 5, b1 + 22))
    bars = f.bars_1m("BTC-USD")
    assert "coverage_status" in bars.columns
    statuses = set(bars["coverage_status"])
    assert statuses <= {"COMPLETE_HEALTHY", "COMPLETE_WITH_GAP",
                        "INCOMPLETE"}
    gapped = bars[bars["coverage_status"] == "COMPLETE_WITH_GAP"]
    assert len(gapped) >= 1 and gapped["gap_duration_ms"].iloc[0] > 10_000
