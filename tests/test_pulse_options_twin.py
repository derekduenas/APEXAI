"""M2 — PULSE ingestion, the Digital Market Twin snapshot, one feature implementation, the
frozen-artifact inference adapter and the provider adapters, on synthetic fixtures only.

Establishes: availability/receipt clocks; dedupe, out-of-order, late and REVISED data never
presented as contemporaneously known; prefix invariance (observations after t cannot change the
state or forecast at t); replay/live parity; DST, early close, gaps; parity of the feature recipe
with exp001b.observable_rows; exact params_hash recomputation of the EXP-002 artifact and
reproduction of its reference forecasts through the experiment's own model code; provider parsing
on fixture responses; production connectivity disabled without switch + credentials; and a full
isolated run through the real entry point with twin-backed synthetic sources and no geometry
fallback. It establishes nothing about edge."""
import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from apex.options_pilot import ledger as L
from apex.options_pilot import entrypoint as E
from apex.options_pilot.clock import Clock
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0
from apex.pulse_options import features as F, inference as I, ingest as G, providers as P, snapshot as SN
from apex.pulse_options.sources import TwinSources, synthetic_twin_sources
from apex.world_model.exp001b import bars as XB
from apex.world_model.exp002 import models as XM
from scripts import options_paper_session as sess

ET = ZoneInfo("America/New_York")


def _epoch(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


REG = _epoch("2026-09-10T14:30:00Z")          # 10:30 ET, regular session, EDT


def _bars(n=70, start=REG - 70 * 60, seed=3):
    return P.SyntheticBarProvider(seed=seed).bars("SPY", start_epoch=start, end_epoch=start + n * 60)


def _store(bars):
    st = G.BarStore("SPY", source="SYNTHETIC_FIXTURE")
    P.load_bars(st, bars)
    return st


# ================================================================== ingestion clocks

def test_bars_have_availability_and_receipt_clocks_and_are_never_early(tmp_path):
    st = _store(_bars())
    bars = st.bars_available_by(REG)
    assert all(b["available"] == max(b["bar_complete"], b["last_receipt"]) for b in bars)
    assert all(b["available"] >= b["event_time"] + 60 for b in bars)
    # a provider bar 'received' before its completion or published before completion is refused, not accepted early
    with pytest.raises(G.IngestRefused, match="RECEIVED_BEFORE_COMPLETE"):
        st.add_provider_bar(event_time=REG, open=1, high=1, low=1, close=1, volume=1, receipt_time=REG + 30)
    with pytest.raises(G.IngestRefused, match="PUBLISHED_BEFORE_COMPLETE"):
        st.add_provider_bar(event_time=REG, open=1, high=1, low=1, close=1, volume=1, receipt_time=REG + 61, publication_time=REG + 59)
    with pytest.raises(G.IngestRefused, match="BAR_NOT_ON_MINUTE"):
        st.add_provider_bar(event_time=REG + 7, open=1, high=1, low=1, close=1, volume=1, receipt_time=REG + 70)
    with pytest.raises(G.IngestRefused, match="BAR_INCONSISTENT"):
        st.add_provider_bar(event_time=REG, open=1, high=0.5, low=1, close=1, volume=1, receipt_time=REG + 70)
    assert st.counters["rejected"] == 4


def test_trades_build_completed_bars_with_dedupe_out_of_order_and_late_arrivals():
    st = G.BarStore("SPY", source="SYNTHETIC_TRADES")
    t0 = REG
    st.add_trade(event_time=t0 + 1, price=645.0, size=100, receipt_time=t0 + 1.2, provider_seq=1)
    st.add_trade(event_time=t0 + 30, price=645.5, size=50, receipt_time=t0 + 30.1, provider_seq=2)
    st.add_trade(event_time=t0 + 59, price=645.2, size=10, receipt_time=t0 + 59.1, provider_seq=3)
    assert st.add_trade(event_time=t0 + 30, price=645.5, size=50, receipt_time=t0 + 30.3, provider_seq=2)["accepted"] is False   # duplicate
    st.add_trade(event_time=t0 + 61, price=645.3, size=10, receipt_time=t0 + 61.1, provider_seq=5)
    late = st.add_trade(event_time=t0 + 10, price=644.9, size=5, receipt_time=t0 + 75.0, provider_seq=4)   # out of order AND late
    assert late["late"] is True and st.counters["out_of_order"] == 1 and st.counters["duplicates"] == 1 and st.counters["late"] == 1
    b = [x for x in st.bars_available_by(t0 + 200) if x["event_time"] == t0][0]
    assert b["open"] == 645.0 and b["close"] == 645.2 and b["low"] == 644.9 and b["trades"] == 4 and b["late_prints"] == 1
    assert b["available"] == t0 + 75.0                                       # the late print moved the availability clock
    # as of t0+70 the bar existed WITHOUT the late print, and that is what a snapshot then would have seen
    early = [x for x in st.bars_available_by(t0 + 70) if x["event_time"] == t0][0]
    assert early["trades"] == 3 and early["low"] == 645.0 and early["available"] == t0 + 60


def test_revisions_are_retained_and_invisible_before_their_receipt():
    st = _store(_bars())
    target = REG - 10 * 60
    first = [b for b in st.bars_available_by(REG) if b["event_time"] == target][0]
    r = st.add_provider_bar(event_time=target, open=first["open"], high=first["high"] * 1.001, low=first["low"], close=first["close"] * 1.0005,
                            volume=first["volume"] + 1, receipt_time=REG + 30)
    assert r["accepted"] and r["revision"] == 1 and st.counters["revisions"] == 1
    assert len(st.versions(target)) == 2
    before = [b for b in st.bars_available_by(REG) if b["event_time"] == target][0]
    after = [b for b in st.bars_available_by(REG + 31) if b["event_time"] == target][0]
    assert before["close"] == first["close"] and before["revision_count"] == 0
    assert after["close"] == first["close"] * 1.0005 and after["revision_count"] == 1 and after["revised_at"] == REG + 30
    # identical re-delivery is a duplicate, not a revision
    assert st.add_provider_bar(event_time=target, open=after["open"], high=after["high"], low=after["low"], close=after["close"],
                               volume=after["volume"], receipt_time=REG + 40)["accepted"] is False


# ================================================================== snapshot: causality, DST, early close, gaps

def test_prefix_invariance_observations_after_t_cannot_change_the_state_or_forecast_at_t():
    bars = _bars(n=80)
    st = _store(bars[:65])
    as_of = bars[64]["available"] + 5.0
    s1 = SN.compose(symbol="SPY", as_of=as_of, bars=st.bars_available_by(as_of), source="SYNTHETIC_FIXTURE")
    art = I.default_artifact()
    f1 = art.forecast(s1, created_epoch=as_of)
    # now the world moves on: 15 more bars, a late print, a revision of an EARLIER bar after as_of
    P.load_bars(st, bars[65:])
    st.add_provider_bar(event_time=bars[60]["event_time"], open=bars[60]["open"], high=bars[60]["high"] * 1.01, low=bars[60]["low"],
                        close=bars[60]["close"] * 1.002, volume=bars[60]["volume"], receipt_time=as_of + 100)
    s2 = SN.compose(symbol="SPY", as_of=as_of, bars=st.bars_available_by(as_of), source="SYNTHETIC_FIXTURE")
    f2 = art.forecast(s2, created_epoch=as_of)
    assert s1["state_hash"] == s2["state_hash"] and s1["fields"] == s2["fields"]
    assert {k: f1[k] for k in ("location", "scale", "inputs")} == {k: f2[k] for k in ("location", "scale", "inputs")}
    # a later snapshot DOES see the revision, and says so
    s3 = SN.compose(symbol="SPY", as_of=as_of + 200, bars=st.bars_available_by(as_of + 200), source="SYNTHETIC_FIXTURE")
    assert s3["state_hash"] != s1["state_hash"]
    # compose refuses a bar that claims to be available after as_of
    with pytest.raises(ValueError, match="FUTURE_BAR_IN_SNAPSHOT"):
        SN.compose(symbol="SPY", as_of=as_of, bars=st.bars_available_by(as_of + 200), source="x")


def test_replay_and_live_parity_same_inputs_same_state():
    bars = _bars(n=70)
    batch = _store(bars)
    stream = G.BarStore("SPY", source="SYNTHETIC_FIXTURE")
    for b in sorted(bars, key=lambda x: x["receipt_time"]):                 # arrival order, one at a time
        stream.add_provider_bar(event_time=b["event_time"], open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                                volume=b["volume"], receipt_time=b["receipt_time"], vwap=b.get("vwap"), trades=b.get("trades"))
    as_of = bars[-1]["available"] + 1.0
    a = SN.compose(symbol="SPY", as_of=as_of, bars=batch.bars_available_by(as_of), source="SYNTHETIC_FIXTURE")
    b_ = SN.compose(symbol="SPY", as_of=as_of, bars=stream.bars_available_by(as_of), source="SYNTHETIC_FIXTURE")
    assert a["state_hash"] == b_["state_hash"]
    assert F.feature_vector(a) == F.feature_vector(b_) == F.features_from_bars(bars, as_of=as_of)


def test_feature_recipe_matches_exp001b_observable_rows():
    """The twin's ret_1/ret_5/rv_30 equal the experiment's own recipe on the same synthetic session."""
    bars = _bars(n=70)
    rows = [{"event_time": b["event_time"], "close": b["close"], "open": b["open"], "minute": i, "bar_complete": b["bar_complete"],
             "assumed_available": b["available"]} for i, b in enumerate(bars)]
    session = {"rows": rows, "bounds": {"open_utc": bars[0]["event_time"], "close_utc": bars[-1]["event_time"] + 3600}}
    ref = [r for r in XB.observable_rows(session) if r["features"] is not None]
    assert ref, "warm-up left no rows"
    for r in ref[::7]:
        as_of = r["assumed_available"]
        ours = F.features_from_bars(bars, as_of=as_of)
        for k in ("ret_1", "ret_5", "rv_30"):
            assert ours[k] == pytest.approx(r["features"][k], rel=0, abs=1e-15), k


def test_missing_minute_refuses_windows_and_stale_bars_are_stale():
    bars = _bars(n=70)
    gapped = [b for b in bars if b["event_time"] != REG - 20 * 60]           # drop one minute 20 min back
    st = _store(gapped)
    as_of = bars[-1]["available"] + 1
    s = SN.compose(symbol="SPY", as_of=as_of, bars=st.bars_available_by(as_of), source="SYNTHETIC_FIXTURE")
    assert s["fields"]["ret_15"]["quality"] == "VALID" and s["fields"]["ret_30"]["quality"] == "NOT_ESTIMABLE"
    assert s["fields"]["rv_30"]["quality"] == "NOT_ESTIMABLE" and s["fields"]["rv_60"]["quality"] == "NOT_ESTIMABLE"
    with pytest.raises(F.FeaturesRefused, match="FEATURE_UNAVAILABLE: rv_30 is NOT_ESTIMABLE"):
        F.feature_vector(s)
    # stale: as_of long after the last bar -> STALE, not a number
    s2 = SN.compose(symbol="SPY", as_of=as_of + 600, bars=st.bars_available_by(as_of + 600), source="SYNTHETIC_FIXTURE")
    assert s2["fields"]["last_bar_close"]["quality"] == "STALE" and s2["fields"]["ret_1"]["quality"] == "STALE"
    assert s2["fields"]["last_bar_close"].get("value") is None


@pytest.mark.parametrize("utc, phase, minute", [
    ("2026-03-06T14:30:00Z", "REGULAR", 0),        # EST: 09:30 ET = 14:30 UTC
    ("2026-03-09T14:30:00Z", "REGULAR", 60),       # after DST start (2026-03-08): 14:30 UTC = 10:30 EDT
    ("2026-03-09T13:30:00Z", "REGULAR", 0),        # 09:30 EDT
    ("2026-11-02T14:30:00Z", "REGULAR", 0),        # after DST end (2026-11-01): back to EST
    ("2026-11-27T17:30:00Z", "REGULAR", 180),      # early close day, 12:30 ET is still regular
    ("2026-11-27T18:30:00Z", "POSTMARKET", None),  # 13:30 ET after the 13:00 early close
    ("2026-09-07T15:00:00Z", "CLOSED", None),      # Labor Day
    ("2026-09-10T12:00:00Z", "PREMARKET", None),
])
def test_session_phase_and_minute_of_session_are_dst_and_early_close_aware(utc, phase, minute):
    s = SN.compose(symbol="SPY", as_of=_epoch(utc), bars=[], source="x")
    assert s["fields"]["session_phase"]["value"] == phase
    if minute is None:
        assert s["fields"]["minute_of_session"]["quality"] == "SESSION_INAPPLICABLE"
    else:
        assert s["fields"]["minute_of_session"]["value"] == minute


def test_book_context_events_and_prior_close_are_clocked_and_absent_when_not_available():
    st = _store(_bars())
    as_of = REG + 1
    bars = st.bars_available_by(as_of)
    book = {"bid": 645.1, "ask": 645.12, "bid_size": 300, "ask_size": 200, "as_of": as_of - 1, "available": as_of - 0.5, "source": "nbbo"}
    events = [{"type": "FOMC_STATEMENT", "scheduled_epoch": as_of + 3600, "schedule_known_from": as_of - 86400, "source": "calendar"},
              {"type": "CPI", "scheduled_epoch": as_of + 60, "schedule_known_from": as_of + 10, "source": "calendar"}]   # schedule not yet known
    ctx = {"qqq_ret_15": {"value": 0.001, "as_of": as_of - 30, "available": as_of - 20, "source": "twin:QQQ"},
           "iwm_ret_15": {"value": 0.002, "as_of": as_of - 30, "available": as_of + 20, "source": "twin:IWM"}}          # not yet available
    pc = {"close": 640.0, "as_of": as_of - 70000, "available": as_of - 69000, "source": "eod"}
    s = SN.compose(symbol="SPY", as_of=as_of, bars=bars, source="SYNTHETIC_FIXTURE", book=book, events=events, context=ctx, prior_close=pc)
    f = s["fields"]
    assert f["underlying_spread_bps"]["quality"] == "VALID" and f["underlying_bid_size"]["value"] == 300
    assert f["next_scheduled_event_type"]["value"] == "FOMC_STATEMENT" and f["seconds_to_next_scheduled_event"]["value"] == 3600
    assert f["ctx_qqq_ret_15"]["value"] == 0.001 and f["ctx_iwm_ret_15"]["quality"] == "UNKNOWN"
    assert f["prior_close"]["value"] == 640.0 and f["gap_from_prior_close_bps"]["quality"] == "VALID"
    stale_book = {**book, "available": as_of - 20}
    s2 = SN.compose(symbol="SPY", as_of=as_of, bars=bars, source="SYNTHETIC_FIXTURE", book=stale_book)
    assert s2["fields"]["underlying_bid"]["quality"] == "STALE" and s2["fields"]["underlying_bid"].get("value") is None
    s3 = SN.compose(symbol="SPY", as_of=as_of, bars=bars, source="SYNTHETIC_FIXTURE")
    assert s3["fields"]["underlying_bid"]["quality"] == "NOT_AVAILABLE" and s3["fields"]["next_scheduled_event_type"]["quality"] == "NOT_AVAILABLE"
    assert s3["missingness"] > 0 and "NOT_AVAILABLE" in s3["quality_census"]


# ================================================================== frozen artifact

def test_artifact_params_hash_recomputes_exactly_and_provenance_is_carried():
    art = I.default_artifact()
    assert art.params_hash == "ca04fc6e713e1a5c" == I.params_hash(art.params)
    d = art.describe()
    assert d["provenance"]["development_status"] == "INVALID_NULL_CONTROL" and d["provenance"]["validated_edge_claim"] is False
    assert d["provenance"]["source_record_sha256"].startswith("0c397d70")
    assert d["feature_order"] == ["ret_1", "ret_5", "rv_30"] and d["family"] == "STUDENT_T" and d["nu"] == 6.384478029123821
    doc = json.loads(I.ARTIFACT_PATH.read_text())
    doc["params"]["L"]["beta"][1] *= 1.0001
    with pytest.raises(I.ArtifactRefused, match="PARAMS_HASH_DISAGREES"):
        I.FrozenArtifact(doc)
    with pytest.raises(I.ArtifactRefused, match="ARM_NOT_SUPPORTED"):
        I.FrozenArtifact(json.loads(I.ARTIFACT_PATH.read_text()), arm="C")


def test_adapter_reproduces_the_experiments_reference_forecasts():
    """Controlled inputs through the adapter equal apex.world_model.exp002.models.forecast('L', ...)."""
    art = I.default_artifact()
    for f in ({"ret_1": 1.0e-4, "ret_5": -2.0e-4, "rv_30": 1.0e-4}, {"ret_1": -3.0e-4, "ret_5": 5.0e-4, "rv_30": 2.5e-4},
              {"ret_1": 0.0, "ret_5": 0.0, "rv_30": 5.0e-5}):
        row = {"features": f, "assumed_available": REG + 60, "event_time": REG, "bar_complete": REG + 60}
        ref = XM.forecast("L", art.params, row, input_id="x", input_hash="y", creation_time=REG + 61)
        assert art.location(f) == pytest.approx(XM._mean_of(art.params["L"], f), abs=0, rel=1e-15)
        assert art.location(f) == pytest.approx(ref.distribution.expected_return, abs=1e-18)
        assert art.scale(f) == pytest.approx(ref.calibration_metadata["scale"], abs=1e-18)
        assert art.nu == ref.calibration_metadata["nu"]
    # and through a snapshot the forecast record carries the same numbers with the causal clocks
    bars = _bars(n=70)
    st = _store(bars)
    as_of = bars[-1]["available"] + 2
    snap = SN.compose(symbol="SPY", as_of=as_of, bars=st.bars_available_by(as_of), source="SYNTHETIC_FIXTURE")
    fc = art.forecast(snap, created_epoch=as_of, direction_signal="LONG")
    fv = F.feature_vector(snap)
    assert fc["location"] == art.location(fv) and fc["scale"] == fv["rv_30"] * art.s and fc["params_hash"] == "ca04fc6e713e1a5c"
    assert fc["input_cutoff_utc"] == snap["fields"]["ret_1"]["known_from"] and fc["reference_time_utc"].startswith("2026-09-10T14:29:00")
    assert fc["validation_status"].startswith("NOT_VALIDATED: EXP-002 development result INVALID_NULL_CONTROL")
    assert fc["inputs"]["state_hash"] == snap["state_hash"]
    with pytest.raises(I.ArtifactRefused, match="CREATED_BEFORE_INPUT_AVAILABLE"):
        art.forecast(snap, created_epoch=as_of - 10)


# ================================================================== providers

ALPACA_BARS = json.dumps({"bars": [
    {"t": "2026-09-10T14:28:00Z", "o": 645.0, "h": 645.3, "l": 644.9, "c": 645.2, "v": 1200, "n": 30, "vw": 645.1},
    {"t": "2026-09-10T14:29:00Z", "o": 645.2, "h": 645.4, "l": 645.0, "c": 645.1, "v": 900, "n": 22, "vw": 645.2}], "symbol": "SPY", "next_page_token": None})
ALPACA_NBBO = json.dumps({"symbol": "SPY", "quote": {"t": "2026-09-10T14:30:00.123456Z", "bp": 645.1, "bs": 3, "ap": 645.12, "as": 2, "c": ["R"]}})
THETA_CHAIN = json.dumps([{"strike": 645.0, "right": "C", "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp": "2026-09-10T10:29:59"},
                          {"strike": 645.0, "right": "P", "bid": 2.1, "ask": 2.2, "bid_size": 4, "ask_size": 6, "timestamp": "2026-09-10T10:29:58"}])


def test_provider_parsers_preserve_source_timestamps_and_convert_et_naive_quotes():
    gate = P.LiveGate(env={P.LIVE_SWITCH: "ENABLED", "ALPACA_API_KEY_ID": "x", "ALPACA_API_SECRET_KEY": "y"})
    calls = []
    def http_get(url, headers=None):
        calls.append(url)
        return ALPACA_BARS if "/bars" in url else ALPACA_NBBO if "/quotes/latest" in url else THETA_CHAIN
    a = P.AlpacaBarsAdapter(gate=gate, http_get=http_get, headers_fn=lambda: {"APCA-API-KEY-ID": "x"}, clock=lambda: REG + 5)
    bars = a.bars("SPY", start_epoch=REG - 600, end_epoch=REG)
    assert [b["event_time"] for b in bars] == [_epoch("2026-09-10T14:28:00Z"), _epoch("2026-09-10T14:29:00Z")]
    assert bars[0]["receipt_time"] == REG + 5 and bars[0]["publication_time"] is None and bars[0]["provider"] == "ALPACA_DATA_V2"
    st = G.BarStore("SPY", source="ALPACA_DATA_V2")
    assert P.load_bars(st, bars)["accepted"] == 2
    nb = a.nbbo("SPY")
    assert nb["bid"] == 645.1 and nb["ask_size"] == 2 and nb["as_of"] == pytest.approx(_epoch("2026-09-10T14:30:00.123456Z")) and nb["available"] == REG + 5
    th = P.ThetaChainAdapter(gate=gate, http_get=http_get, clock=lambda: REG + 6)
    ch = th.chain("SPY", "2026-10-09")
    assert ch[0]["right"] == "CALL" and ch[1]["right"] == "PUT"
    assert ch[0]["timestamp_epoch"] == datetime(2026, 9, 10, 10, 29, 59, tzinfo=ET).timestamp() == _epoch("2026-09-10T14:29:59Z")
    assert ch[0]["timestamp_raw"] == "2026-09-10T10:29:59" and "America/New_York" in ch[0]["timestamp_convention"]
    # the EST/EDT conversion is date-aware
    assert P.ThetaChainAdapter.et_naive_to_epoch("2026-12-10T10:00:00") == _epoch("2026-12-10T15:00:00Z")
    assert len(calls) == 3


def test_production_connectivity_is_disabled_without_switch_and_credentials():
    hits = []
    def http_get(url, headers=None):
        hits.append(url); return "{}"
    for env in ({}, {P.LIVE_SWITCH: "ENABLED"}, {"ALPACA_API_KEY_ID": "x", "ALPACA_API_SECRET_KEY": "y"}, {P.LIVE_SWITCH: "yes"}):
        gate = P.LiveGate(env=env)
        a = P.AlpacaBarsAdapter(gate=gate, http_get=http_get, headers_fn=lambda: {})
        with pytest.raises(P.ProviderUnavailable, match="LIVE_DATA_DISABLED|CREDENTIALS_ABSENT"):
            a.bars("SPY", start_epoch=0, end_epoch=60)
        with pytest.raises(P.ProviderUnavailable):
            P.ThetaChainAdapter(gate=gate, http_get=http_get).chain("SPY", "2026-10-09")
    assert hits == []                                                      # nothing was contacted
    st = P.LiveGate(env={}).status()
    assert st["enabled"] is False and st["credentials_present"] == {"ALPACA_API_KEY_ID": False, "ALPACA_API_SECRET_KEY": False}


# ================================================================== the real entry point on twin-backed sources

class _TwinProvider:
    provenance = "SYNTHETIC_FIXTURE"

    def __init__(self, twin: TwinSources):
        self.twin = twin
        self.clock, self.risk_authority, self.fee_schedule, self.sleep_fn = twin.clock, twin.risk_authority, twin.fee_schedule, twin.sleep_fn

    def sources(self):
        return self.twin.sources()


def test_full_isolated_run_through_the_entry_point_on_twin_sources(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LEGACY GEOMETRY PATH CALLED")
    monkeypatch.setattr(sess, "_scan_symbol", boom)
    monkeypatch.setattr(sess.paper_execution, "simulate_entry", boom)
    monkeypatch.setattr(sess, "seal_before_card", boom)
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="TWIN-1", t0=REG + 1.0)          # quotes/chain fixtures + controlled clock
    twin = synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn, sleep_fn=h.advance)
    argv = ["--ledger", str(led), "--out", str(tmp_path / "out.json"), "--symbols", "SPY", "--dry-run", "--pilot-boundary",
            "--pilot-session-id", "TWIN-1", "--pilot-release", "synthetic-release"]
    assert sess.main(argv, pilot_sources=_TwinProvider(twin)) == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    rows = L.read_all(led)
    fc = [r for r in rows if r["kind"] == "pilot_forecast"][0]
    assert fc["model_id"] == "EXP002_L" and fc["params_hash"] == "ca04fc6e713e1a5c" and fc["data_provenance"] == "SYNTHETIC_FIXTURE"
    assert fc["validation_status"].startswith("NOT_VALIDATED") and fc["inputs"]["state_hash"]
    assert fc["direction_signal"] in ("LONG", "SHORT") and fc["drives_expression_selection"] is False
    d = rep["decisions"][0]
    assert d["decision"] in ("TRADE", "WAIT", "REFUSE") and d["decision_persisted"] is True
    if d["decision"] == "TRADE":
        it = [r for r in rows if r["kind"] == "pilot_intent"][0]
        assert it["signal_used"] == fc["direction_signal"] and it["risk"]["risk_provenance"] == "CERTIFIED_KERNEL"
        assert rep["completion"] == "CLOSED_CLEAN" and rep["book"]["cash_identity"]["holds"] is True
    assert rep["risk_authority"] == "CertifiedRiskAuthority" and rep["fee_schedule"]["provenance"] == "SYNTHETIC_FIXTURE"
    assert not any(k.startswith("options_live") for k in [r["kind"] for r in rows])
    L.verify_chain(led)


def test_production_route_refuses_before_any_network_access(tmp_path, monkeypatch):
    monkeypatch.delenv(P.LIVE_SWITCH, raising=False)
    led = tmp_path / "led.jsonl"
    argv = ["--ledger", str(led), "--out", str(tmp_path / "out.json"), "--symbols", "SPY", "--dry-run", "--pilot-boundary",
            "--pilot-session-id", "PROD-TWIN", "--pilot-release", "r"]
    assert sess.main(argv) == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    d = rep["decisions"][0]
    assert d["decision"] == "REFUSE" and "LIVE_DATA_DISABLED" in d["why"] and d["refusal_persisted"] is True
    assert rep["data_provenance"] == "LIVE_FEED" and rep["fee_schedule"]["provenance"] == "PROVIDER_VERIFIED"
    rows = L.read_all(led)
    assert not any(r["kind"] in ("pilot_forecast", "pilot_intent", "pilot_fill") for r in rows)
