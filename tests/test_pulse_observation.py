"""PULSE-008 -- OBSERVATION_TIME_CONTRACT_V1, the quote boundary, and the runner mode.

Deterministic: no network, no clock. The vendor is a fixture in every test
that touches it. Each defect this brick closed has a test that reproduces the
OLD behaviour explicitly, so neither can come back quietly.
"""
import copy
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apex.intraday.sessions import Session
from apex.pulse import freshness, historical as H, observation as OBS
from apex.pulse.mirror import TOLERANCE_BPS, TOLERANCE_REL
from apex.pulse.parity import MATRIX

REPO = Path(__file__).resolve().parents[1]
UTC = timezone.utc
SLOT = "2026-09-01T13:45:00+00:00"
CAP_START = "2026-09-01T13:45:00.995494+00:00"
CAP_END = "2026-09-01T13:45:01.804905+00:00"


def _spec(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def packet(quote_as_of="2026-09-01T13:45:01.669149633Z", *, subject="SPY", session="REGULAR",
           complete="2026-09-01T13:45:30.958344+00:00", extra=None, quote_quality="VALID"):
    """A packet shaped exactly like the sealed ones: the quote-derived block
    stamped with one NBBO instant, the bar block with its own."""
    f = {}
    for name in OBS.QUOTE_DERIVED_FIELDS:
        f[name] = {"v": 1.0, "q": quote_quality, "src": "alpaca_sip", "as_of": quote_as_of}
    f["prior_close"] = {"v": 767.05, "q": "VALID", "src": "alpaca_sip",
                        "as_of": "2026-08-31T04:00:00Z"}
    f["session_open"] = {"v": 762.01, "q": "VALID", "src": "alpaca_sip",
                         "as_of": "2026-09-01T04:00:00Z"}
    f.update(extra or {})
    return {"subject": subject, "scheduled_time": SLOT, "capture_start": CAP_START,
            "capture_end": CAP_END, "state_complete_time": complete, "known_from": complete,
            "market_session": session, "state_id": "sid_" + subject, "features": f}


# ---------------------------------------------------------------- the contract
def test_contract_is_stated_and_names_what_it_rejects():
    c = OBS.contract()
    assert c["contract"] == "OBSERVATION_TIME_CONTRACT_V1" == OBS.OBSERVATION_CONTRACT
    assert "features[*].as_of" in c["authoritative_timestamp"]
    for rejected in ("scheduled_time", "capture_start", "capture_end", "state_complete_time",
                     "known_from"):
        assert rejected in c["rejected_candidates"]
    assert set(c["failure_modes"]) == {OBS.MISSING, OBS.CONFLICTING, OBS.IMPOSSIBLE,
                                       OBS.STALE_BEYOND_POLICY}
    assert "quote ingredient only" in c["what_moves"]
    assert H.FACTORY_VERSION == "HISTORICAL_MARKET_TWIN_FACTORY_V0.2"
    assert "QUOTE-BOUNDARY-001" in H.FACTORY_HISTORY["V0.2"]


def test_observation_time_is_the_quote_block_as_of_not_any_packet_level_stamp():
    p = packet()
    r = OBS.observation_time(p)
    assert r["status"] == OBS.RESOLVED
    assert r["observation_time"] == "2026-09-01T13:45:01.669149633Z"
    assert r["observation_time"] not in (p["scheduled_time"], p["capture_start"],
                                         p["capture_end"], p["state_complete_time"])
    assert r["field_count"] == len(OBS.QUOTE_DERIVED_FIELDS)
    assert r["offset_from_scheduled_s"] == pytest.approx(1.669149, abs=1e-5)
    assert r["within_capture_window"] is True
    assert r["source"].startswith("features[*].as_of")


def test_scheduled_time_and_observation_time_are_different_questions():
    p = packet()
    r = OBS.observation_time(p)
    sch, obs = OBS._dt(p["scheduled_time"]), OBS._dt(r["observation_time"])
    assert obs > sch and (obs - sch).total_seconds() == pytest.approx(1.669, abs=1e-3)
    # and the packet still reports its slot unchanged -- the brick does not rewrite it
    assert p["scheduled_time"] == SLOT


def test_observation_before_the_slot_is_legitimate():
    """TDOC observed 7 ms BEFORE its scheduled slot. A contract that assumed
    'observation is always later' would mis-handle it."""
    p = packet("2026-09-01T13:44:59.993460487Z", subject="TDOC")
    r = OBS.observation_time(p)
    assert r["status"] == OBS.RESOLVED and r["offset_from_scheduled_s"] < 0
    assert r["within_capture_window"] is False        # older than the fetch, still valid


# ---------------------------------------------------------------- fail closed
def test_missing_observation_timestamp_fails_closed():
    p = packet()
    for name in OBS.QUOTE_DERIVED_FIELDS:
        p["features"][name] = {"v": None, "q": "STALE", "src": "alpaca_sip"}
    r = OBS.observation_time(p)
    assert r["status"] == OBS.MISSING and r["observation_time"] is None
    with pytest.raises(OBS.ObservationTimeUnavailable, match="MISSING"):
        OBS.require_observation_time(p)


def test_no_quote_derived_fields_at_all_fails_closed():
    p = packet()
    for name in OBS.QUOTE_DERIVED_FIELDS:
        del p["features"][name]
    assert OBS.observation_time(p)["status"] == OBS.MISSING


def test_conflicting_feature_timestamps_fail_closed():
    p = packet()
    p["features"]["nbbo_size_imbalance"]["as_of"] = "2026-09-01T13:45:01.111111111Z"
    r = OBS.observation_time(p)
    assert r["status"] == OBS.CONFLICTING and r["observation_time"] is None
    assert len(r["candidate_stamps"]) == 2
    with pytest.raises(OBS.ObservationTimeUnavailable, match="CONFLICTING"):
        OBS.require_observation_time(p)


def test_packet_level_and_feature_level_disagreement_does_not_silently_prefer_either():
    """capture_end says the fetch ended at 13:45:01.804905; a feature claiming
    13:45:05 cannot be an observation from that fetch."""
    p = packet("2026-09-01T13:45:05.000000000Z")
    r = OBS.observation_time(p)
    assert r["status"] == OBS.IMPOSSIBLE and r["observation_time"] is None
    assert "capture_end" in r["reason"]


def test_stale_beyond_the_governed_policy_fails_closed():
    """NKLA's sealed packet stamped its quote-derived fields 2025-02-26 and
    marked them VALID while marking the RAW quote fields STALE."""
    p = packet("2025-02-26T00:59:59.255814551Z", subject="NKLA")
    r = OBS.observation_time(p)
    assert r["status"] == OBS.STALE_BEYOND_POLICY and r["observation_time"] is None
    assert r["freshness_check"]["policy"] == freshness.FRESHNESS_POLICY_VERSION
    assert r["freshness_check"]["tolerance_s"] == freshness.tolerance_s("sip_quote", Session.REGULAR)
    assert r["freshness_check"]["fresh"] is False
    assert "DERIVED fields VALID" in r["reason"]


def test_the_freshness_bound_is_the_composers_own_number_not_a_new_one():
    tol = freshness.tolerance_s("sip_quote", Session.REGULAR)
    inside = packet((OBS._dt(CAP_END) - timedelta(seconds=tol - 1)).isoformat())
    outside = packet((OBS._dt(CAP_END) - timedelta(seconds=tol + 1)).isoformat())
    assert OBS.observation_time(inside)["status"] == OBS.RESOLVED
    assert OBS.observation_time(outside)["status"] == OBS.STALE_BEYOND_POLICY


@pytest.mark.parametrize("session,ok", [("REGULAR", False), ("PREMARKET", True)])
def test_the_bound_follows_the_session(session, ok):
    """600 s is stale in REGULAR and fresh in PREMARKET, per the policy."""
    p = packet((OBS._dt(CAP_END) - timedelta(seconds=300)).isoformat(), session=session)
    assert (OBS.observation_time(p)["status"] == OBS.RESOLVED) is ok


# ---------------------------------------------------------------- the quote boundary
class _Tape:
    """A vendor whose `end` bound EXCLUDES the boundary event, as measured."""

    def __init__(self, quotes, exclusive_end=True):
        self.quotes, self.exclusive_end, self.calls = quotes, exclusive_end, []

    def __call__(self, symbol, start, end, *, what="trades", limit=10000, max_pages=10):
        self.calls.append({"start": str(start), "end": str(end), "what": what})
        s, e = OBS._dt(start), OBS._dt(end)
        return [q for q in self.quotes
                if s <= OBS._dt(q["t"]) and (OBS._dt(q["t"]) < e if self.exclusive_end
                                             else OBS._dt(q["t"]) <= e)]


def _q(ts, bp, ap, bs, a_s):
    return {"t": ts, "bp": bp, "ap": ap, "bs": bs, "as": a_s}


BOUNDARY = "2026-09-01T13:45:01.669149633Z"
TAPE = [_q("2026-09-01T13:45:01.667545802Z", 761.90, 761.94, 240, 400),   # the event before
        _q(BOUNDARY, 761.90, 761.94, 160, 520),                            # what live used
        _q("2026-09-01T13:45:02.100000000Z", 761.91, 761.95, 300, 300)]    # the future


@pytest.fixture
def tape(monkeypatch):
    t = _Tape(TAPE)
    monkeypatch.setattr(H.ms, "fetch_ticks", t)
    return t


def test_QUOTE_BOUNDARY_001_old_end_equals_t_query_misses_the_boundary_event(tape):
    """The defect, reproduced: with end = t the vendor never returns the event
    AT t, so the previous one is selected and the SIZES differ."""
    t = OBS._dt(BOUNDARY)
    old = [q for q in tape(  # the V0.1 query shape
        "SPY", (t - timedelta(seconds=60)).isoformat(), t.isoformat(), what="quotes")
        if OBS._dt(q["t"]) <= t]
    assert old[-1]["t"] != BOUNDARY and (old[-1]["bs"], old[-1]["as"]) == (240, 400)
    got = H.quotes_as_of("SPY", BOUNDARY)                       # the repaired path
    assert got["t"] == BOUNDARY and (got["bs"], got["as"]) == (160, 520)


def test_the_boundary_margin_never_admits_a_later_event(tape):
    """The margin widens the QUERY; the local cutoff is what admits."""
    got = H.quotes_as_of("SPY", BOUNDARY)
    assert OBS._dt(got["t"]) <= OBS._dt(BOUNDARY)
    assert got["t"] != "2026-09-01T13:45:02.100000000Z"
    end_used = OBS._dt(tape.calls[-1]["end"])
    assert end_used > OBS._dt(BOUNDARY)                          # queried past it
    assert (end_used - OBS._dt(BOUNDARY)).total_seconds() == pytest.approx(1.0)


def test_no_future_data_crosses_the_cutoff_however_wide_the_query(tape):
    for margin in (0.0, 1.0, 5.0, 60.0):
        got = H.quotes_as_of("SPY", BOUNDARY, boundary_margin_s=margin)
        assert OBS._dt(got["t"]) <= OBS._dt(BOUNDARY), margin


def test_a_one_to_two_second_quote_update_burst_changes_sizes_not_prices(tape):
    """The exact scenario: live observed 1.669 s after the slot; between the
    slot and that instant the touch changed while the mid did not."""
    at_slot = H.quotes_as_of("SPY", "2026-09-01T13:45:01.667545802Z")
    at_obs = H.quotes_as_of("SPY", BOUNDARY)
    mid = lambda q: (q["bp"] + q["ap"]) / 2                      # noqa: E731
    assert mid(at_slot) == mid(at_obs)                           # prices identical
    assert (at_slot["bs"], at_slot["as"]) != (at_obs["bs"], at_obs["as"])
    imb = lambda q: (q["bs"] - q["as"]) / (q["bs"] + q["as"])    # noqa: E731
    assert round(imb(at_slot), 4) == -0.25 and round(imb(at_obs), 4) == -0.5294


def test_twin_as_of_pins_the_quote_without_moving_the_bars(monkeypatch, tape):
    seen = {}

    def fake_snapshot(symbol, t, **kw):
        seen["bar_cutoff"] = str(t)
        return {"_anchor_provenance": {}, "prevDailyBar": {"c": 767.05, "v": 1, "t": "2026-08-31T04:00:00Z"}}

    monkeypatch.setattr(H, "snapshot_as_of", fake_snapshot)
    monkeypatch.setattr(H, "compose", lambda **kw: _FakeState(kw))
    H.twin_as_of("SPY", SLOT, quote_as_of=BOUNDARY)
    assert seen["bar_cutoff"].startswith("2026-09-01 13:45:00")   # bars at the SLOT
    snap = _FakeState.last["snapshot"]
    assert snap["latestQuote"]["t"] == BOUNDARY                   # quote at the OBSERVATION
    prov = snap["_anchor_provenance"]["quote"]
    assert prov["exact_instant_reached"] is True and prov["gap_to_requested_ms"] == 0.0
    assert prov["boundary_defect_closed"] == "QUOTE-BOUNDARY-001"
    assert prov["offset_from_bar_cutoff_s"] == pytest.approx(1.669149, abs=1e-5)


def test_twin_as_of_default_is_unchanged_from_v0_1(monkeypatch, tape):
    monkeypatch.setattr(H, "snapshot_as_of", lambda s, t, **kw: {"_anchor_provenance": {}})
    monkeypatch.setattr(H, "compose", lambda **kw: _FakeState(kw))
    H.twin_as_of("SPY", BOUNDARY)
    snap = _FakeState.last["snapshot"]
    assert snap["_quote_selection"] == "reconstruction_time_t"
    assert snap["_quote_as_of_requested"].startswith("2026-09-01T13:45:01.669149")


class _FakeState:
    last = None

    def __init__(self, kw):
        _FakeState.last = kw
        self.sources, self.notes = {}, []

    def seal(self):
        return {"features": {}, "notes": self.notes, "sources": self.sources}


# ---------------------------------------------------------------- the runner mode
@pytest.fixture(scope="module")
def runner():
    return _spec("mirror_run_v2_p8", str(REPO / "scripts" / "mirror_run_v2.py"))


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
                    "original_violations": []})
    mp, pp = tmp_path / "m.json", tmp_path / "p.jsonl"
    mp.write_text(json.dumps(man)); pp.write_text("".join(lines))
    return str(mp), str(pp)


def test_runner_default_mode_is_still_scheduled(runner, tmp_path, monkeypatch):
    mp, pp = _frozen(tmp_path, [("c", packet())])
    seen = {}

    def fake(sym, t, quote_as_of=None):
        seen["t"], seen["q"] = t, quote_as_of
        return {"features": {}, "notes": []}

    monkeypatch.setattr(runner, "twin_as_of", fake)
    out = str(tmp_path / "a.json")
    runner.main(["--manifest", mp, "--packets", pp, "--out", out])
    assert seen["q"] is None and seen["t"] == SLOT
    assert json.load(open(out))["reconstruct_at"] == "scheduled"
    assert runner.RUNNER_VERSION == "MIRROR_RUN_V2.1"


def test_runner_observation_mode_passes_the_recorded_instant(runner, tmp_path, monkeypatch):
    mp, pp = _frozen(tmp_path, [("c", packet())])
    seen = {}

    def fake(sym, t, quote_as_of=None):
        seen["t"], seen["q"] = t, quote_as_of
        return {"features": {}, "notes": []}

    monkeypatch.setattr(runner, "twin_as_of", fake)
    out = str(tmp_path / "b.json")
    runner.main(["--manifest", mp, "--packets", pp, "--out", out,
                 "--reconstruct-at", "observation"])
    assert seen["q"] == BOUNDARY and seen["t"] == SLOT          # quote moves, bars do not
    d = json.load(open(out))
    assert d["reconstruct_at"] == "observation"
    assert d["observation_contract"] == "OBSERVATION_TIME_CONTRACT_V1"
    assert d["observation_times_used"] == {"c": BOUNDARY}
    assert d["results"][0]["observation_time_provenance"]["status"] == "RESOLVED"


@pytest.mark.parametrize("mutate,status", [
    (lambda p: [p["features"][f].update(q="STALE") for f in OBS.QUOTE_DERIVED_FIELDS], "MISSING"),
    (lambda p: p["features"]["mid"].update(as_of="2026-09-01T13:45:01.000000000Z"), "CONFLICTING"),
    (lambda p: [p["features"][f].update(as_of="2025-02-26T00:59:59.255814551Z")
                for f in OBS.QUOTE_DERIVED_FIELDS], "STALE_BEYOND_POLICY"),
])
def test_runner_fails_closed_when_the_observation_time_is_unusable(runner, tmp_path, monkeypatch,
                                                                   mutate, status):
    p = packet(); mutate(p)
    mp, pp = _frozen(tmp_path, [("c", p)])
    monkeypatch.setattr(runner, "twin_as_of",
                        lambda *a, **k: pytest.fail("must not reconstruct without an instant"))
    out = str(tmp_path / (status + ".json"))
    rc = runner.main(["--manifest", mp, "--packets", pp, "--out", out,
                      "--reconstruct-at", "observation"])
    d = json.load(open(out))
    assert rc == 3 and d["MIRROR_COVERAGE"] == "INCOMPLETE"
    assert d["reconstruction_failures"][0]["stage"] == "OBSERVATION_TIME"
    assert status in d["reconstruction_failures"][0]["error"]
    assert d["MIRROR_UNDER_ORIGINAL_DECLARATIONS"] == "BLOCKED"


def test_runner_records_per_field_before_after_against_a_baseline(runner, tmp_path, monkeypatch):
    mp, pp = _frozen(tmp_path, [("c", packet())])
    base = {"results": [{"subject_class": "c", "rows": [
        {"field": "nbbo_size_imbalance", "replay_value": -0.3333, "observed": "APPROXIMATE",
         "relative_difference": 0.37}]}]}
    bp = tmp_path / "base.json"; bp.write_text(json.dumps(base))
    monkeypatch.setattr(runner, "twin_as_of", lambda s, t, quote_as_of=None: {
        "features": {"nbbo_size_imbalance": {"v": 1.0, "q": "VALID", "src": "alpaca_sip"}},
        "notes": []})
    out = str(tmp_path / "d.json")
    runner.main(["--manifest", mp, "--packets", pp, "--out", out,
                 "--reconstruct-at", "observation", "--baseline", str(bp)])
    d = json.load(open(out))
    row = d["per_field_before_after"]["c"]["nbbo_size_imbalance"]
    assert row["replay_before"] == -0.3333 and row["replay_after"] == 1.0
    assert row["observed_before"] == "APPROXIMATE" and row["observed_after"] == "SEMANTICALLY_EQUIVALENT"


def test_runner_write_once_and_nonzero_exit_preserved(runner, tmp_path, monkeypatch):
    mp, pp = _frozen(tmp_path, [("c", packet())])
    monkeypatch.setattr(runner, "twin_as_of", lambda s, t, quote_as_of=None: {"features": {}, "notes": []})
    out = str(tmp_path / "once.json")
    assert runner.main(["--manifest", mp, "--packets", pp, "--out", out,
                        "--reconstruct-at", "observation"]) == 3
    assert oct(os.stat(out).st_mode)[-3:] == "444"
    assert runner.main(["--manifest", mp, "--packets", pp, "--out", out,
                        "--reconstruct-at", "observation"]) == 3      # refuses to overwrite


# ---------------------------------------------------------------- nothing was relaxed
def test_declarations_and_tolerances_are_untouched():
    assert TOLERANCE_BPS == 2.0 and TOLERANCE_REL == 0.002
    assert MATRIX["nbbo_size_imbalance"]["status"] == "SEMANTICALLY_EQUIVALENT"
    assert MATRIX["prior_close"]["status"] == "SEMANTICALLY_EQUIVALENT"
    assert MATRIX["cash_open_return_bps"]["status"] == "SEMANTICALLY_EQUIVALENT"
    assert MATRIX["ret_1m_bps"]["status"] == "LIVE_ONLY"
    assert MATRIX["session_vwap"]["status"] == "APPROXIMATE"


def test_the_frozen_packets_are_not_modified_by_any_of_this():
    p = packet()
    before = json.dumps(p, sort_keys=True)
    OBS.observation_time(p)
    OBS.quote_stamps(p)
    assert json.dumps(p, sort_keys=True) == before
