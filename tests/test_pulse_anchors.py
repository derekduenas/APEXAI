"""PULSE-007 -- PULSE_ANCHOR_CONTRACT_V1 and the fail-closed mirror runner.

Every test here is deterministic: vendor bars are fixtures, no network, no
clock. The two defects these cover were measured against six sealed live
packets from 2026-09-01T13:45:00Z, and each has a test that reproduces the
OLD behaviour explicitly so the repair cannot silently regress.
"""
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.intraday.sessions import Session, classify
from apex.pulse import anchors
from apex.pulse import historical as H

REPO = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def _spec(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def daily(date, close, open_=None):
    """A vendor daily bar, stamped the way Alpaca stamps one: at the
    session's ET midnight, which is 04:00Z under EDT and 05:00Z under EST."""
    d = datetime.fromisoformat(date).replace(tzinfo=UTC)
    off = 4 if "-03-" <= date[4:8] <= "-11-" else 5
    return {"t": (d + timedelta(hours=off)).isoformat().replace("+00:00", "Z"),
            "o": open_ if open_ is not None else close, "h": close, "l": close,
            "c": close, "v": 1000, "vw": close}


def minute(ts, o, c=None, v=100):
    return {"t": ts, "o": o, "h": max(o, c or o), "l": min(o, c or o),
            "c": c if c is not None else o, "v": v, "vw": o}


# ---------------------------------------------------------------- contract shape
def test_contract_is_stated_and_names_the_defects_it_closes():
    c = anchors.contract()
    assert c["contract"] == "PULSE_ANCHOR_CONTRACT_V1" == anchors.ANCHOR_CONTRACT
    assert set(c["defects_closed"]) == {"ANCHOR-001", "ANCHOR-002"}
    assert c["price_convention"].startswith("RAW")
    assert c["leak_discipline"]["current_session_daily_bar_fields_used"] == ["o"]
    assert set(c["leak_discipline"]["rebuilt_from_minute_bars"]) == {"h", "l", "c", "v", "vw"}
    assert "does NOT establish as-known-at" in c["correction_availability"]
    # the factory version advances with later bricks; what PULSE-007 pins is that
    # V0.1 exists and still records the two defects it closed.
    assert H.FACTORY_VERSION.startswith("HISTORICAL_MARKET_TWIN_FACTORY_V0.")
    assert "ANCHOR-001" in H.FACTORY_HISTORY["V0"] and "ANCHOR-002" in H.FACTORY_HISTORY["V0"]
    assert "apex.pulse.anchors" in H.FACTORY_HISTORY["V0.1"]


# ---------------------------------------------------------------- session windows
@pytest.mark.parametrize("date,open_utc,close_utc", [
    ("2026-09-01", "2026-09-01T13:30:00+00:00", "2026-09-01T20:00:00+00:00"),   # EDT
    ("2026-01-05", "2026-01-05T14:30:00+00:00", "2026-01-05T21:00:00+00:00"),   # EST
    ("2026-03-09", "2026-03-09T13:30:00+00:00", "2026-03-09T20:00:00+00:00"),   # first Mon after DST start
    ("2026-11-02", "2026-11-02T14:30:00+00:00", "2026-11-02T21:00:00+00:00"),   # first Mon after DST end
    ("2026-11-27", "2026-11-27T14:30:00+00:00", "2026-11-27T18:00:00+00:00"),   # early close 13:00 ET
    ("2026-12-24", "2026-12-24T14:30:00+00:00", "2026-12-24T18:00:00+00:00"),   # early close
])
def test_regular_window_is_dst_and_early_close_correct(date, open_utc, close_utc):
    o, c = anchors.regular_window(date)
    assert o.isoformat() == open_utc and c.isoformat() == close_utc
    assert classify(o) is Session.REGULAR
    assert classify(c - timedelta(minutes=1)) is Session.REGULAR
    assert classify(c) is not Session.REGULAR                      # the close is exclusive


@pytest.mark.parametrize("date", ["2026-09-05", "2026-09-06", "2026-09-07", "2026-01-01", "2026-12-25"])
def test_non_sessions_have_no_window(date):
    assert not anchors.is_trading_day(date)
    with pytest.raises(anchors.AnchorViolation):
        anchors.regular_window(date)


def test_session_date_is_exchange_local_not_utc():
    # 2026-09-01T00:30Z is 20:30 ET on 2026-08-31 -- the PREVIOUS session date.
    assert anchors.session_date("2026-09-01T00:30:00Z") == "2026-08-31"
    assert anchors.session_date("2026-09-01T13:45:00Z") == "2026-09-01"
    assert anchors.session_date("2026-09-01T23:59:00Z") == "2026-09-01"


# ---------------------------------------------------------------- ANCHOR-001
def test_prior_daily_selects_the_last_completed_session():
    bars = [daily("2026-08-27", 10), daily("2026-08-28", 11), daily("2026-08-31", 12),
            daily("2026-09-01", 13)]
    got = anchors.select_prior_daily(bars, "2026-09-01T13:45:00Z")
    assert anchors.session_date(got["t"]) == "2026-08-31" and got["c"] == 12


def test_ANCHOR_001_old_stamp_plus_24h_rule_would_have_picked_the_session_before():
    """The exact defect, reproduced. Keep this test: it is the only thing
    that stops the arithmetic coming back."""
    bars = [daily("2026-08-28", 11), daily("2026-08-31", 12)]
    t = anchors._dt("2026-09-01T13:45:00Z")
    day_start = t.replace(hour=0, minute=0, second=0, microsecond=0)
    old = [b for b in bars if anchors._dt(b["t"]) + timedelta(days=1) <= day_start]
    assert old[-1]["c"] == 11 and anchors.session_date(old[-1]["t"]) == "2026-08-28"   # WRONG
    assert anchors.select_prior_daily(bars, t)["c"] == 12                              # RIGHT


def test_prior_daily_skips_weekend_and_holiday_without_a_calendar_lookup():
    # 2026-09-07 is Labor Day; the session before Tuesday 09-08 is Friday 09-04.
    bars = [daily("2026-09-03", 20), daily("2026-09-04", 21)]
    got = anchors.select_prior_daily(bars, "2026-09-08T13:45:00Z")
    assert anchors.session_date(got["t"]) == "2026-09-04"
    assert not anchors.is_trading_day("2026-09-07")                # cross-checked by the calendar


def test_prior_daily_ignores_the_current_session_and_anything_after_it():
    bars = [daily("2026-08-31", 12), daily("2026-09-01", 13), daily("2026-09-02", 14)]
    got = anchors.select_prior_daily(bars, "2026-09-01T13:45:00Z")
    assert got["c"] == 12


def test_missing_prior_anchor_is_absent_not_substituted():
    assert anchors.select_prior_daily([], "2026-09-01T13:45:00Z") is None
    assert anchors.select_prior_daily([daily("2026-09-01", 13)], "2026-09-01T13:45:00Z") is None


def test_prior_daily_is_order_independent():
    bars = [daily("2026-08-31", 12), daily("2026-08-27", 10), daily("2026-08-28", 11)]
    assert anchors.select_prior_daily(bars, "2026-09-01T13:45:00Z")["c"] == 12
    assert anchors.select_prior_daily(list(reversed(bars)), "2026-09-01T13:45:00Z")["c"] == 12


# ---------------------------------------------------------------- ANCHOR-002
def test_regular_minute_bars_exclude_extended_hours_and_unclosed_bars():
    bars = [minute("2026-09-01T00:00:00Z", 99),      # 20:00 ET on 08-31: prior post-market
            minute("2026-09-01T08:00:00Z", 98),      # 04:00 ET: premarket
            minute("2026-09-01T13:29:00Z", 97),      # 09:29 ET: still premarket
            minute("2026-09-01T13:30:00Z", 100),     # the cash open minute
            minute("2026-09-01T13:44:00Z", 101),     # closed at 13:45
            minute("2026-09-01T13:45:00Z", 102)]     # closes at 13:46 -- the future
    got = anchors.regular_minute_bars(bars, "2026-09-01T13:45:00Z")
    assert [b["o"] for b in got] == [100, 101]


def test_ANCHOR_002_old_utc_midnight_window_would_have_opened_on_a_premarket_bar():
    """The second defect, reproduced."""
    bars = [minute("2026-09-01T08:00:00Z", 98), minute("2026-09-01T13:30:00Z", 100)]
    t = anchors._dt("2026-09-01T13:45:00Z")
    old_window_first = [b for b in bars
                        if anchors._dt(b["t"]) >= t.replace(hour=0, minute=0, second=0, microsecond=0)][0]
    assert classify(anchors._dt(old_window_first["t"])) is Session.PREMARKET      # WRONG
    assert classify(anchors._dt(anchors.regular_minute_bars(bars, t)[0]["t"])) is Session.REGULAR


def test_cash_open_comes_from_the_current_session_daily_bar_open_only():
    d = [daily("2026-08-31", 12), {**daily("2026-09-01", 13), "o": 9.5, "h": 99, "l": 1, "v": 10 ** 9}]
    o, prov = anchors.select_current_daily_open(d, "2026-09-01T13:45:00Z")
    assert o == 9.5 and prov["fields_used"] == ["o"] and prov["session_date"] == "2026-09-01"
    agg = anchors.rebuild_session_aggregate(
        [minute("2026-09-01T13:30:00Z", 10, 11, v=5), minute("2026-09-01T13:31:00Z", 11, 12, v=5)],
        open_price=o, open_provenance=prov)
    # the daily bar's completed-day fields must NOT reach the aggregate
    assert agg["o"] == 9.5 and agg["h"] == 12 and agg["l"] == 10 and agg["v"] == 10
    assert agg["h"] != 99 and agg["l"] != 1 and agg["v"] != 10 ** 9


def test_cash_open_falls_back_to_the_first_regular_minute_and_says_so():
    o, why = anchors.select_current_daily_open([daily("2026-08-31", 12)], "2026-09-01T13:45:00Z")
    assert o is None and "no daily bar for the current session" in why
    agg = anchors.rebuild_session_aggregate([minute("2026-09-01T13:30:00Z", 100, 101)])
    assert agg["o"] == 100
    assert agg["_open_provenance"]["source"] == "first_regular_minute_bar_open"
    assert "opening auction" in agg["_open_provenance"]["limitation"]


def test_no_minute_bars_means_no_aggregate():
    assert anchors.rebuild_session_aggregate([]) is None
    assert anchors.regular_minute_bars([], "2026-09-01T13:45:00Z") == []


def test_early_close_session_still_opens_at_0930_and_stops_at_the_early_close():
    bars = [minute("2026-11-27T14:30:00Z", 50), minute("2026-11-27T17:59:00Z", 51),
            minute("2026-11-27T18:00:00Z", 52)]     # after the 13:00 ET close
    got = anchors.regular_minute_bars(bars, "2026-11-27T20:00:00Z")
    assert [b["o"] for b in got] == [50, 51]


# ---------------------------------------------------------------- snapshot_as_of, no network
class _Vendor:
    """Deterministic stand-in for the bars endpoint."""

    def __init__(self, daily_bars, minute_bars):
        self.daily, self.minute, self.calls = daily_bars, minute_bars, []

    def __call__(self, symbol, start, end, timeframe="1Min", limit=10000, closed_only=True):
        self.calls.append({"timeframe": timeframe, "start": str(start), "end": str(end)})
        if timeframe == "1Day":
            return list(self.daily)
        cutoff = anchors._dt(end)
        return [b for b in self.minute
                if anchors._dt(start) <= anchors._dt(b["t"])
                and (not closed_only or anchors._dt(b["t"]) + timedelta(minutes=1) <= cutoff)]


@pytest.fixture
def vendor(monkeypatch):
    v = _Vendor([daily("2026-08-28", 11), daily("2026-08-31", 12),
                 {**daily("2026-09-01", 13), "o": 100.0, "h": 999, "l": 0.5, "v": 10 ** 9}],
                [minute("2026-09-01T00:00:00Z", 90), minute("2026-09-01T08:00:00Z", 95),
                 minute("2026-09-01T13:30:00Z", 100, 101), minute("2026-09-01T13:44:00Z", 101, 102)])
    monkeypatch.setattr(H, "_bars", v)
    return v


def test_snapshot_as_of_regular_session_uses_the_repaired_anchors(vendor):
    snap = H.snapshot_as_of("TEST", "2026-09-01T13:45:00Z")
    assert snap["prevDailyBar"]["c"] == 12                                  # 08-31, not 08-28
    assert snap["_anchor_provenance"]["prior_close"]["session_date"] == "2026-08-31"
    assert snap["dailyBar"]["o"] == 100.0                                   # the cash open
    assert snap["_anchor_provenance"]["cash_open"]["source"] == "vendor_daily_bar_open"
    assert snap["dailyBar"]["h"] == 102 and snap["dailyBar"]["l"] == 100    # rebuilt, not the day's
    assert snap["dailyBar"]["v"] == 200
    assert snap["_anchor_provenance"]["session_aggregate"]["minute_bars_used"] == 2
    assert snap["_anchor_contract"] == "PULSE_ANCHOR_CONTRACT_V1"
    assert snap["_session"] == "REGULAR" and snap["_session_date"] == "2026-09-01"
    # the minute query starts at the cash open, never at UTC midnight
    mins = [c for c in vendor.calls if c["timeframe"] == "1Min"]
    assert mins and mins[0]["start"].startswith("2026-09-01 13:30") or "13:30" in mins[0]["start"]


def test_snapshot_as_of_premarket_builds_no_session_aggregate(vendor):
    snap = H.snapshot_as_of("TEST", "2026-09-01T12:00:00Z")                 # 08:00 ET
    assert snap["_session"] == "PREMARKET"
    assert "dailyBar" not in snap and "minuteBar" not in snap and "latestTrade" not in snap
    assert "no cash open has occurred" in snap["_anchor_provenance"]["session_aggregate"]["absent"]
    assert snap["prevDailyBar"]["c"] == 12                                  # the anchor still resolves


def test_snapshot_as_of_closed_session_builds_no_session_aggregate(vendor):
    snap = H.snapshot_as_of("TEST", "2026-09-05T15:00:00Z")                 # a Saturday
    assert snap["_session"] == "CLOSED" and "dailyBar" not in snap


def test_snapshot_as_of_without_a_prior_session_reports_absence(monkeypatch):
    v = _Vendor([], [minute("2026-09-01T13:30:00Z", 100)])
    monkeypatch.setattr(H, "_bars", v)
    snap = H.snapshot_as_of("NEWCO", "2026-09-01T13:45:00Z")
    assert "prevDailyBar" not in snap
    assert "no regular session in the lookback window" in snap["_anchor_provenance"]["prior_close"]["absent"]


def test_snapshot_as_of_never_admits_a_bar_that_closes_after_the_moment(monkeypatch):
    v = _Vendor([daily("2026-08-31", 12)],
                [minute("2026-09-01T13:30:00Z", 100, 101), minute("2026-09-01T13:45:00Z", 500, 900)])
    monkeypatch.setattr(H, "_bars", v)
    snap = H.snapshot_as_of("TEST", "2026-09-01T13:45:00Z")
    assert snap["dailyBar"]["h"] == 101 and snap["dailyBar"]["c"] == 101


def test_daily_bars_are_not_width_filtered_by_the_fetcher(monkeypatch):
    """_bars must hand daily bars to the selector unfiltered; the width
    filter on daily bars WAS ANCHOR-001."""
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return {"bars": [daily("2026-08-31", 12)]}

    monkeypatch.setattr(H.ms, "_get", fake_get)
    got = H._bars("TEST", "2026-08-20T00:00:00Z", "2026-09-01T00:00:00Z", timeframe="1Day")
    assert len(got) == 1 and got[0]["c"] == 12
    assert "adjustment=raw" in captured["url"] and "feed=sip" in captured["url"]


def test_minute_bars_are_still_closed_filtered(monkeypatch):
    monkeypatch.setattr(H.ms, "_get", lambda url: {"bars": [
        minute("2026-09-01T13:44:00Z", 1), minute("2026-09-01T13:45:00Z", 2)]})
    got = H._bars("TEST", "2026-09-01T13:30:00Z", "2026-09-01T13:45:00Z", timeframe="1Min")
    assert [b["o"] for b in got] == [1]


# ---------------------------------------------------------------- mirror runner: fail-closed
@pytest.fixture(scope="module")
def runner():
    return _spec("mirror_run_v2", str(REPO / "scripts" / "mirror_run_v2.py"))


def _frozen(tmp_path, packets):
    import hashlib
    man, lines = [], []
    for cls, p in packets:
        line = json.dumps(p) + "\n"
        lines.append(line)
        man.append({"subject": p["subject"], "scheduled_time": p["scheduled_time"],
                    "subject_class": cls, "state_id": p.get("state_id"),
                    "line_sha256": hashlib.sha256(line.encode()).hexdigest(),
                    "original_verdict": "DECLARATION_CONTRADICTED_BY_REALITY",
                    "original_violations": ["prior_close: ..."]})
    mp = tmp_path / "man.json"; pp = tmp_path / "pk.jsonl"
    mp.write_text(json.dumps(man)); pp.write_text("".join(lines))
    return str(mp), str(pp)


def _packet(sym, **features):
    f = {k: {"v": v, "q": "VALID", "src": "alpaca_sip", "as_of": "2026-09-01T13:45:00Z"}
         for k, v in features.items()}
    return {"subject": sym, "scheduled_time": "2026-09-01T13:45:00+00:00",
            "state_id": "sid_" + sym, "market_session": "REGULAR", "features": f}


def test_runner_reports_pass_only_when_everything_compares(runner, tmp_path, monkeypatch):
    live = _packet("AAA", prior_close=10.0, mid=10.1)
    mp, pp = _frozen(tmp_path, [("only_class", live)])
    monkeypatch.setattr(runner, "twin_as_of", lambda s, t: {
        "features": {"prior_close": {"v": 10.0, "q": "VALID", "src": "alpaca_sip"},
                     "mid": {"v": 10.1, "q": "VALID", "src": "alpaca_sip"}}, "notes": []})
    out = str(tmp_path / "ok.json")
    rc = runner.main(["--manifest", mp, "--packets", pp, "--out", out])
    d = json.load(open(out))
    assert rc == 0 and d["MIRROR_COVERAGE"] == "COMPLETE"
    assert d["ANCHOR_STATUS"] == "PASS" and d["MIRROR_UNDER_ORIGINAL_DECLARATIONS"] == "PASS"


def test_runner_refuses_to_pass_when_a_reconstruction_raises(runner, tmp_path, monkeypatch):
    """The V0 behaviour: skip the exception, then report consistency."""
    live = _packet("AAA", prior_close=10.0, mid=10.1)
    mp, pp = _frozen(tmp_path, [("only_class", live)])

    def boom(sym, t):
        raise RuntimeError("vendor timeout")

    monkeypatch.setattr(runner, "twin_as_of", boom)
    out = str(tmp_path / "boom.json")
    rc = runner.main(["--manifest", mp, "--packets", pp, "--out", out])
    d = json.load(open(out))
    assert rc == 3 and d["MIRROR_COVERAGE"] == "INCOMPLETE"
    assert d["executed_comparisons"] == 0 and len(d["reconstruction_failures"]) == 1
    assert d["reconstruction_failures"][0]["stage"] == "RECONSTRUCTION"
    assert "vendor timeout" in d["reconstruction_failures"][0]["error"]
    assert d["ANCHOR_STATUS"] == "BLOCKED" and d["MIRROR_UNDER_ORIGINAL_DECLARATIONS"] == "BLOCKED"


def test_runner_refuses_to_pass_when_history_reconstructs_nothing(runner, tmp_path, monkeypatch):
    """NKLA on 2026-09-01: every field LIVE_ONLY, zero violations, and V0
    called that MIRROR_CONSISTENT."""
    live = _packet("DEAD", prior_close=0.25, mid=0.23)
    mp, pp = _frozen(tmp_path, [("elevated_mover", live)])
    monkeypatch.setattr(runner, "twin_as_of", lambda s, t: {"features": {}, "notes": []})
    out = str(tmp_path / "empty.json")
    rc = runner.main(["--manifest", mp, "--packets", pp, "--out", out])
    d = json.load(open(out))
    assert rc == 3 and d["MIRROR_COVERAGE"] == "INCOMPLETE"
    assert d["empty_comparisons"] == ["elevated_mover"]
    assert d["results"][0]["verdict"] == "MIRROR_CONSISTENT"          # the old signal, now not enough
    assert d["results"][0]["fields_compared_on_both_sides"] == 0
    assert d["MIRROR_UNDER_ORIGINAL_DECLARATIONS"] == "BLOCKED"


def test_runner_detects_a_swapped_frozen_packet(runner, tmp_path, monkeypatch):
    live = _packet("AAA", prior_close=10.0, mid=10.1)
    mp, pp = _frozen(tmp_path, [("only_class", live)])
    swapped = json.loads(Path(pp).read_text())
    swapped["features"]["prior_close"]["v"] = 11.0
    Path(pp).write_text(json.dumps(swapped) + "\n")
    monkeypatch.setattr(runner, "twin_as_of", lambda s, t: {"features": {}, "notes": []})
    out = str(tmp_path / "swap.json")
    rc = runner.main(["--manifest", mp, "--packets", pp, "--out", out])
    d = json.load(open(out))
    assert rc == 3 and d["reconstruction_failures"][0]["stage"] == "FROZEN_INPUT"
    assert "bytes changed" in d["reconstruction_failures"][0]["error"]


def test_runner_reports_anchor_and_full_status_separately(runner, tmp_path, monkeypatch):
    live = _packet("AAA", prior_close=10.0, mid=10.1, nbbo_size_imbalance=0.5)
    mp, pp = _frozen(tmp_path, [("only_class", live)])
    monkeypatch.setattr(runner, "twin_as_of", lambda s, t: {
        "features": {"prior_close": {"v": 10.0, "q": "VALID", "src": "alpaca_sip"},
                     "mid": {"v": 10.1, "q": "VALID", "src": "alpaca_sip"},
                     "nbbo_size_imbalance": {"v": -0.5, "q": "VALID", "src": "alpaca_sip"}},
        "notes": []})
    out = str(tmp_path / "split.json")
    rc = runner.main(["--manifest", mp, "--packets", pp, "--out", out])
    d = json.load(open(out))
    assert rc == 2 and d["MIRROR_COVERAGE"] == "COMPLETE"
    assert d["ANCHOR_STATUS"] == "PASS"                                # anchors are clean
    assert d["MIRROR_UNDER_ORIGINAL_DECLARATIONS"] == "FAIL"           # a quote field is not
    assert "only_class" in d["declaration_violations"]


def test_runner_refuses_to_overwrite_existing_evidence(runner, tmp_path, monkeypatch):
    live = _packet("AAA", prior_close=10.0)
    mp, pp = _frozen(tmp_path, [("only_class", live)])
    monkeypatch.setattr(runner, "twin_as_of", lambda s, t: {"features": {}, "notes": []})
    out = str(tmp_path / "once.json")
    runner.main(["--manifest", mp, "--packets", pp, "--out", out])
    assert runner.main(["--manifest", mp, "--packets", pp, "--out", out]) == 3
    assert oct(os.stat(out).st_mode)[-3:] == "444"


def test_runner_does_not_relax_any_declaration(runner):
    from apex.pulse.mirror import TOLERANCE_BPS, TOLERANCE_REL
    from apex.pulse.parity import MATRIX as M
    assert TOLERANCE_BPS == 2.0 and TOLERANCE_REL == 0.002
    assert M["prior_close"]["status"] == "SEMANTICALLY_EQUIVALENT"
    assert M["nbbo_size_imbalance"]["status"] == "SEMANTICALLY_EQUIVALENT"
    assert M["ret_1m_bps"]["status"] == "LIVE_ONLY"
    assert runner.ANCHOR_FIELDS == ("prior_close", "prior_close_return_bps",
                                    "cash_open_return_bps", "overnight_gap_bps")
