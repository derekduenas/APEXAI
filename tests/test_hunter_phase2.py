"""Phase 2 counterexamples: baselines through the SAME machinery,
N_effective caps, scoreboard eligibility/identical-subject discipline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apex.hunter.baselines import (baseline_decisions, baseline_directions,
                                   random_direction)
from apex.hunter.chartstate import compute_chart_state
from apex.hunter.forward_pass import resolve_decision
from apex.hunter.neff import effective_sample
from apex.hunter.relstrength import compute_relative_strength
from hunter_scoreboard import build_scoreboard
from tests.test_hunter_p1b import T, bars, ctx


def _states():
    cs = compute_chart_state("AMD", bars("AMD", drift=0.06, seed=1), T,
                             ctx("AMD"))
    mkt = compute_chart_state("SPY", bars("SPY", drift=-0.01, seed=2), T,
                              ctx("SPY"))
    return cs, compute_relative_strength(cs, mkt), mkt


BIRTHS = {
    "HUNTER-FORWARD-PROTOCOL_v1": {"birth_time_utc": "2026-08-01T00:00:00+00:00",
                                   "artifact_hash": "a",
                                   "dependency_kind": "protocol"},
    "hunter_feature_schema_v1": {"birth_time_utc": "2026-08-01T00:00:00+00:00",
                                 "artifact_hash": "b",
                                 "dependency_kind": "feature_schema"},
    "hunter_rule_model_v1": {"birth_time_utc": "2026-08-01T00:00:00+00:00",
                             "artifact_hash": "c", "dependency_kind": "model"},
    "HUNTER-BASELINES_v1": {"birth_time_utc": "2026-08-01T00:00:00+00:00",
                            "artifact_hash": "d",
                            "dependency_kind": "playbook"},
}


def test_random_baseline_is_deterministic_not_rerollable():
    assert (random_direction("2026-08-17", "AMD")
            == random_direction("2026-08-17", "AMD"))
    flips = {random_direction("2026-08-17", s)
             for s in ("AMD", "TSLA", "AAPL", "NVDA", "META", "AMZN")}
    assert flips == {"LONG", "SHORT"}          # it is a coin, not a constant


def test_baseline_directions_fail_closed_on_missing_inputs():
    cs, rs, _ = _states()
    d = baseline_directions("2026-08-10", "AMD", cs, rs, None)
    assert d["BASELINE-MARKET"] is None        # no market state -> no call
    assert d["BASELINE-MOMENTUM"] in ("LONG", "SHORT")


def test_baseline_records_same_machinery_and_dedupe():
    cs, rs, mkt = _states()
    seen: set = set()
    recs = baseline_decisions(T, "2026-08-10", ("AMD",), {"AMD": cs},
                              {"AMD": rs}, mkt, BIRTHS, seen)
    assert {r["playbook_id"] for r in recs} == {
        "BASELINE-RANDOM", "BASELINE-MARKET", "BASELINE-MOMENTUM",
        "BASELINE-RELSTRENGTH"}
    assert all(r["kind"] == "decision" and r["stop"] is None for r in recs)
    assert all(r["forward_eligibility"] == "FORWARD_ELIGIBLE" for r in recs)
    again = baseline_decisions(T, "2026-08-10", ("AMD",), {"AMD": cs},
                               {"AMD": rs}, mkt, BIRTHS, seen)
    assert again == []                         # first formation wins


def test_baseline_realization_skips_geometry():
    f = bars(drift=0.02)
    d = {"decision_id": "b1", "session_date": "2026-08-10",
         "playbook_id": "BASELINE-MOMENTUM", "symbol": "TEST",
         "direction": "LONG", "t_utc": str(T), "entry": 100.0,
         "stop": None, "target": None}
    r = resolve_decision(d, f)
    assert r["resolvable"] and "target_before_stop" not in r
    assert isinstance(r["ret_60m"], float)


def test_neff_caps_by_session_day_cells():
    recs = ([{"session_date": "2026-08-17", "playbook_id": "HUNTER-001_v1",
              "symbol": s} for s in ("A", "B", "C", "D", "E")]
            + [{"session_date": "2026-08-17", "playbook_id": "HUNTER-002_v1",
                "symbol": "F"}])
    acct = effective_sample(recs)
    assert acct["n_raw"] == 6
    assert acct["n_effective"] == 1            # one session caps everything
    assert acct["per_playbook"]["HUNTER-001_v1"]["n_effective"] == 1


def _entry(kind, **kw):
    return {"kind": kind, "evidence_class": "EODHD_FORWARD_OBSERVATION",
            **kw}


def test_scoreboard_scores_only_eligible_and_restricts_subjects():
    kinds = {"forward_state": [], "scan": [], "decision": [], "realization": []}
    kinds["decision"] = [
        _entry("decision", decision_id="d1", session_date="2026-08-17",
               symbol="AMD", playbook_id="HUNTER-001_v1", direction="LONG",
               forward_eligibility="FORWARD_ELIGIBLE"),
        _entry("decision", decision_id="d2", session_date="2026-08-17",
               symbol="TSLA", playbook_id="HUNTER-001_v1", direction="LONG",
               forward_eligibility="NOT_FORWARD_ELIGIBLE"),
        _entry("decision", decision_id="d3", session_date="2026-08-17",
               symbol="AMD", playbook_id="BASELINE-RANDOM",
               direction="SHORT", forward_eligibility="FORWARD_ELIGIBLE"),
        _entry("decision", decision_id="d4", session_date="2026-08-17",
               symbol="NVDA", playbook_id="BASELINE-RANDOM",
               direction="LONG", forward_eligibility="FORWARD_ELIGIBLE"),
    ]
    kinds["realization"] = [
        _entry("realization", decision_id=i, resolvable=True, ret_60m=0.01,
               ret_15m=0.002) for i in ("d1", "d2", "d3", "d4")]
    sb = build_scoreboard(kinds)
    assert sb["decisions_ineligible"] == 1
    assert sb["scoreboard"]["HUNTER-001_v1"]["n_raw"] == 1   # d2 never scored
    assert sb["scoreboard"]["HUNTER-001_v1"]["status"] == "PRELIMINARY"
    comp = sb["identical_subject_comparisons"]["HUNTER-001_v1"]
    assert comp["n_subjects"] == 1
    # NVDA baseline row excluded from the identical-subject comparison
    b = comp["baselines_on_identical_subjects"]["BASELINE-RANDOM"]["60m"]
    assert b["n"] == 1
    assert sb["no_trade_row"]["mean_ret"] == 0.0


def test_scoreboard_refuses_mixed_evidence():
    import pytest

    from apex.hunter.evidence import EvidenceViolation
    kinds = {"forward_state": [], "scan": [], "realization": [],
             "decision": [
                 _entry("decision", decision_id="d1",
                        session_date="2026-08-17", symbol="A",
                        playbook_id="HUNTER-001_v1", direction="LONG",
                        forward_eligibility="FORWARD_ELIGIBLE"),
                 {**_entry("decision", decision_id="d2",
                           session_date="2026-08-17", symbol="B",
                           playbook_id="HUNTER-001_v1", direction="LONG",
                           forward_eligibility="FORWARD_ELIGIBLE"),
                  "evidence_class": "EODHD_HISTORICAL_EXPLORATORY"}]}
    with pytest.raises(EvidenceViolation):
        build_scoreboard(kinds)


def test_ledger_roundtrip_flat_shape(tmp_path):
    """decision -> chain append (FLAT) -> unrealized -> resolve -> scored."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from nightly_pull import _chain_append

    from apex.hunter.forward_pass import unrealized_decisions
    led = tmp_path / "ledger.jsonl"
    _chain_append(led, {"kind": "decision", "decision_id": "z9",
                        "session_date": "2026-08-10", "symbol": "TEST",
                        "playbook_id": "BASELINE-MOMENTUM",
                        "direction": "LONG", "t_utc": str(T), "entry": 100.0,
                        "stop": None, "target": None,
                        "evidence_class": "EODHD_FORWARD_OBSERVATION"})
    pending = unrealized_decisions("2026-08-10", led)
    assert len(pending) == 1
    rec = resolve_decision(pending[0], bars())
    _chain_append(led, rec)
    assert unrealized_decisions("2026-08-10", led) == []
    lines = [json.loads(x) for x in led.read_text().splitlines()]
    assert lines[1]["prev_hash"] == lines[0]["entry_hash"]
