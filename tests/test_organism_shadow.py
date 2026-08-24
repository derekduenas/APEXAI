"""The V2 organism scaffolds: shadow-only, and provably non-interfering.

The single most important test in this file is the first one -- the
freeze of the incumbent decision paths is enforced structurally, not
promised.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apex.organism.calibration import (
    CalibrationViolation, UncertaintyState, register, reliability,
    resolve)
from apex.organism.cross_predator import (
    REDUNDANCY, SleeveObservation, assemble)
from apex.organism.path_intelligence import (
    PathForecast, PedigreeViolation, realized_path)

REPO = Path(__file__).resolve().parents[1]

INCUMBENT_DECISION_PATHS = [
    "scripts/options_paper_session.py",
    "scripts/btc_paper_session.py",
    "apex/predators/options/attack_geometry.py",
    "apex/predators/options/expression.py",
    "apex/predators/options/paper_execution.py",
    "apex/btc_sleeve/participant_state.py",
    "apex/btc_sleeve/forced_action.py",
    "apex/btc_sleeve/attack_geometry.py",
    "apex/btc_sleeve/paper_execution.py",
]


# ------------------------------------------ THE NON-INTERFERENCE LAW

def test_no_incumbent_decision_path_imports_the_organism():
    """The Monday baseline stays clean because it CANNOT read the new
    faculties, not because we promised not to let it."""
    for rel in INCUMBENT_DECISION_PATHS:
        src = (REPO / rel).read_text()
        assert "apex.organism" not in src, (
            f"{rel} imports the organism layer -- the incumbent "
            f"decision path is frozen and this would contaminate the "
            f"prospective baseline")


def test_every_organism_output_is_powerless():
    ctx = assemble([])
    assert ctx.decision_power == "NONE_SHADOW"
    f = PathForecast(subject="X", T="t")
    assert f.decision_power == "NONE_SHADOW"
    assert "answers none of them" in UncertaintyState().law


# ------------------------------------------ cross-predator (shadow)

def _obs(sleeve, subject, view):
    return SleeveObservation(sleeve=sleeve, subject=subject, T="t",
                             direction_view=view)


def test_same_underlying_agreement_is_an_echo_not_confirmation():
    ctx = assemble([_obs("equity", "NVDA", "LONG"),
                    _obs("options", "NVDA", "LONG")])
    r = ctx.relations[0]
    assert r.relation == "CONFIRMS"
    assert r.redundancy == "HIGHLY_REDUNDANT"
    assert "echo" in " ".join(r.why)
    assert ("equity:NVDA", "options:NVDA") in \
        ctx.shared_underlying_risks
    assert ctx.confirmation_claims_permitted is False


def test_unmeasured_pairs_default_to_unknown_not_independent():
    ctx = assemble([_obs("equity", "NVDA", "LONG"),
                    _obs("btc", "PBTCUCZ50", "LONG")])
    r = ctx.relations[0]
    assert r.redundancy == "UNKNOWN"
    assert "may not be assumed" in " ".join(r.why)


def test_contradiction_is_observed_not_scored():
    """A contradiction is recorded; no score, no confidence adjustment,
    no numeric field summarizing agreement exists anywhere in the
    record."""
    import json
    ctx = assemble([_obs("equity", "NVDA", "LONG"),
                    _obs("options", "NVDA", "SHORT")])
    assert ctx.relations[0].relation == "CONTRADICTS"
    rec = ctx.as_record()
    assert rec["evidence_class"] == "SHADOW_OBSERVATION"

    # ban scored FIELDS, not prose: the record's own law text is
    # allowed to say "no confidence adjustment" -- what it may never
    # have is a key that IS one.
    def _keys(d):
        if isinstance(d, dict):
            for k, v in d.items():
                yield k.lower()
                yield from _keys(v)
        elif isinstance(d, (list, tuple)):
            for v in d:
                yield from _keys(v)
    banned = {"confidence", "conviction", "score", "agreement_score"}
    hit = banned & set(_keys(rec))
    assert not hit, (f"a cross-predator record may not carry scored "
                     f"fields {hit} -- observation only")


def test_a_sleeve_with_no_view_relates_to_nothing():
    ctx = assemble([_obs("equity", "NVDA", "LONG"),
                    _obs("btc", "PBTCUCZ50", "NOT_ESTIMABLE")])
    assert ctx.relations[0].relation == "NOT_ESTIMABLE"
    assert ctx.relations[0].redundancy in REDUNDANCY


# ------------------------------------------ path contract (shadow)

def test_numbers_may_not_outrun_pedigree():
    with pytest.raises(PedigreeViolation) as e:
        PathForecast(subject="X", T="t", pedigree="NOT_ESTIMABLE",
                     quantities={"p_plus1R_before_minus1R": 0.7})
    assert "invented number" in str(e.value)


def test_undeclared_quantities_are_refused():
    with pytest.raises(PedigreeViolation):
        PathForecast(subject="X", T="t",
                     pedigree="ESTIMABLE_UNCALIBRATED",
                     quantities={"p_moon": 0.9})


def test_an_uncalibrated_estimate_is_allowed_but_labelled():
    f = PathForecast(subject="X", T="t",
                     pedigree="ESTIMABLE_UNCALIBRATED",
                     quantities={"p_plus1R_before_minus1R": 0.55})
    assert "no decision authority" in f.law


def test_realized_path_refuses_an_undeclared_denominator():
    r = realized_path(outcome_record={"pnl_usd": 100.0},
                      declared_1R=None)
    assert r["pnl_R"] == "NOT_ESTIMABLE"
    assert "manufactures precision" in r["refusal"]


def test_realized_path_records_what_happened_in_R():
    r = realized_path(
        outcome_record={"kind": "btc_paper_outcome", "pnl_usd": -80.0,
                        "exit_reason": "INVALIDATED",
                        "evidence_class": "PROSPECTIVE_PAPER"},
        declared_1R=75.0)
    assert r["pnl_R"] == pytest.approx(-1.0667, abs=1e-3)
    assert r["reached_minus1R"] is True
    assert r["evidence_class"] == "PROSPECTIVE_PAPER"


# ------------------------------------------ calibration (shadow)

def test_the_single_confidence_number_is_refused_by_construction():
    with pytest.raises(CalibrationViolation):
        UncertaintyState(notes={"confidence": 0.87})
    with pytest.raises(CalibrationViolation):
        UncertaintyState(notes={"OVERALL": "high"})


def test_the_five_ignorances_are_named_axes():
    u = UncertaintyState(epistemic="HIGH", aleatoric="LOW")
    rec = u.as_record()
    for ax in ("data", "epistemic", "aleatoric", "execution",
               "mechanism"):
        assert ax in rec
    assert rec["epistemic"] == "HIGH"


def test_resolution_refuses_an_unregistered_claim(tmp_path):
    led = tmp_path / "cal.jsonl"
    with pytest.raises(CalibrationViolation) as e:
        resolve(led, claim_id="ghost", occurred=True)
    assert "not a forecast" in str(e.value)


def test_a_claim_resolves_once_and_only_once(tmp_path):
    led = tmp_path / "cal.jsonl"
    register(led, claim_id="c1", p=0.6, event="x", sleeve="btc",
             pedigree="ESTIMABLE_UNCALIBRATED")
    r = resolve(led, claim_id="c1", occurred=True)
    assert r["brier"] == pytest.approx(0.16)
    with pytest.raises(CalibrationViolation):
        resolve(led, claim_id="c1", occurred=False)


def test_values_outside_the_unit_interval_are_not_probabilities(
        tmp_path):
    led = tmp_path / "cal.jsonl"
    for p in (-0.1, 1.3):
        with pytest.raises(CalibrationViolation):
            register(led, claim_id="c", p=p, event="x", sleeve="btc",
                     pedigree="ESTIMABLE_UNCALIBRATED")


def test_certainty_must_be_earned_not_banned(tmp_path):
    """Corrected law: 0 and 1 are mathematically valid probabilities.
    What is prohibited is UNSUPPORTED certainty -- an empirical model
    claiming the boundary it has not earned."""
    led = tmp_path / "cal.jsonl"
    # a model claiming certainty -> refused
    with pytest.raises(CalibrationViolation) as e:
        register(led, claim_id="hubris", p=1.0, event="+2R before -1R",
                 sleeve="btc", pedigree="ESTIMABLE_UNCALIBRATED")
    assert "certainty must be earned" in str(e.value)
    # a deterministic fact -> legitimate, and flagged as extreme
    rec = register(led, claim_id="fact", p=1.0,
                   event="option expires by its expiration timestamp",
                   sleeve="options",
                   pedigree="DETERMINISTIC_BY_CONSTRUCTION")
    assert rec["certainty_flag"] == "EXTREME_CERTAINTY_CLAIM"
    # ordinary probabilities carry the ordinary flag
    rec2 = register(led, claim_id="ordinary", p=0.6, event="x",
                    sleeve="btc", pedigree="ESTIMABLE_UNCALIBRATED")
    assert rec2["certainty_flag"] == "VALID_PROBABILITY"


def test_reliability_refuses_to_draw_a_curve_through_noise(tmp_path):
    led = tmp_path / "cal.jsonl"
    for i in range(5):
        register(led, claim_id=f"c{i}", p=0.6, event="x", sleeve="btc",
                 pedigree="ESTIMABLE_UNCALIBRATED", session=f"s{i}")
        resolve(led, claim_id=f"c{i}", occurred=(i < 3))
    rep = reliability(led)
    assert rep["n_raw"] == 5
    assert rep["buckets"][0]["observed_freq"] == "INSUFFICIENT_SAMPLE"
    assert rep["verdict"] == "INSUFFICIENT_SAMPLE_EVERYWHERE"
    assert rep["min_bucket_n_classification"] == \
        "REPORTING_SUFFICIENCY_PRIOR"


def test_dependent_observations_do_not_impersonate_a_sample(tmp_path):
    """25 correlated claims from ONE session must not clear a floor
    meant for independent calibration events."""
    led = tmp_path / "cal.jsonl"
    for i in range(25):
        register(led, claim_id=f"c{i}", p=0.6, event="x", sleeve="btc",
                 pedigree="ESTIMABLE_UNCALIBRATED",
                 session="2026-08-25")               # all one session
        resolve(led, claim_id=f"c{i}", occurred=(i < 15))
    rep = reliability(led)
    row = rep["buckets"][0]
    assert row["n_raw"] == 25
    assert row["n_effective_lower_bound"] == 1
    assert row["observed_freq"] == "INSUFFICIENT_SAMPLE"
    assert rep["independent_session_count"] == 1


def test_reliability_measures_when_independent_sessions_allow(tmp_path):
    led = tmp_path / "cal.jsonl"
    for i in range(25):
        register(led, claim_id=f"c{i}", p=0.6, event="x", sleeve="btc",
                 pedigree="ESTIMABLE_UNCALIBRATED", session=f"day{i}",
                 regime_tags=["QUIET" if i % 2 else "NORMAL"])
        resolve(led, claim_id=f"c{i}", occurred=(i < 15))   # 60%
    rep = reliability(led)
    row = rep["buckets"][0]
    assert row["n_raw"] == 25
    assert row["n_effective_lower_bound"] == 25
    assert row["observed_freq"] == 0.6
    assert abs(row["gap"]) < 0.01
    assert isinstance(row["regime_concentration"], float)
    assert rep["verdict"] == "CALIBRATION_MEASURABLE"
