"""ReunderwriteTrigger + reunderwrite ledger — the fix for the
2026-08-18 Captain freeze. Tests encode the DEADLOCK that was measured
live so it can never silently return.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2 import reunderwrite_ledger as rl
from apex.frontier2 import reunderwrite_trigger as rt

T0 = pd.Timestamp("2026-08-18T13:43:16Z")

BASE_INPUTS = {
    "curve_state": "POSITIVE_TRANSITION", "curve_direction": "UP",
    "curve_expression": "CONFIRMED_EXPRESSION", "curve_likelihood": "LOW",
    "participant_trap": "NONE", "participant_direction": "UNKNOWN",
    "propagation_state": "UNKNOWN", "leading_edge_rank": "UNKNOWN",
    "leading_edge_entry_quality": "UNKNOWN",
    "assassin2_familiarity": "STRUCTURAL_RISK",
    "assassin2_caution_label": "HIGH", "observation_quality": "LIMITED",
    "model_market_tally_agrees": None,
}


def test_never_reviewed_always_triggers():
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE", prior_inputs=None,
                    current_inputs=BASE_INPUTS, prior_state=None,
                    seconds_since_last_review=None, known_from=T0, now=T0)
    assert d.should_review is True
    assert "NEVER_REVIEWED" in d.triggers


def test_curve_state_change_triggers_review():
    changed = {**BASE_INPUTS, "curve_state": "NEGATIVE_TRANSITION",
              "curve_direction": "DOWN"}
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                    prior_inputs=BASE_INPUTS, current_inputs=changed,
                    prior_state="WATCH", seconds_since_last_review=30.0,
                    known_from=T0, now=T0)
    assert d.should_review is True
    assert "CURVE_STATE_CHANGE" in d.triggers
    assert "DIRECTION_QUALITY_CHANGE" in d.triggers


def test_identical_inputs_inside_heartbeat_window_does_not_review():
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                    prior_inputs=BASE_INPUTS, current_inputs=dict(BASE_INPUTS),
                    prior_state="WATCH", seconds_since_last_review=30.0,
                    known_from=T0, now=T0)
    assert d.should_review is False
    assert d.triggers == ()
    assert len(d.unchanged_inputs) == len(BASE_INPUTS)


def test_heartbeat_fires_after_staleness_interval():
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                    prior_inputs=BASE_INPUTS, current_inputs=dict(BASE_INPUTS),
                    prior_state="WATCH",
                    seconds_since_last_review=rt.RUNTIME_STALENESS_SAFETY_INTERVAL_S + 1,
                    known_from=T0, now=T0)
    assert d.should_review is True
    assert d.triggers == ("RUNTIME_STALENESS_SAFETY_INTERVAL",)


def test_the_2026_08_18_deadlock_cannot_recur():
    """THE REGRESSION TEST. Live on 2026-08-18, a subject that entered at
    WATCH was never re-reviewed for the rest of the session because
    compute_router2 only grants tier 4 to SERIOUS/WAIT_FOR_ENTRY, and
    Captain could only reach SERIOUS by being invoked. Re-underwriting
    eligibility must NOT depend on the prior state's seriousness."""
    for stuck_state in ("WATCH", "DEVELOP"):
        changed = {**BASE_INPUTS, "curve_state": "NEGATIVE_TRANSITION"}
        d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                        prior_inputs=BASE_INPUTS, current_inputs=changed,
                        prior_state=stuck_state, seconds_since_last_review=25.0,
                        known_from=T0, now=T0)
        assert d.should_review is True, (
            f"a {stuck_state} subject with a real Curve state change must be "
            f"re-reviewable -- this is exactly the 2026-08-18 freeze")


def test_terminal_invalidate_never_resurrects():
    changed = {**BASE_INPUTS, "curve_state": "POSITIVE_TRANSITION",
              "curve_likelihood": "HIGH"}
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                    prior_inputs=BASE_INPUTS, current_inputs=changed,
                    prior_state="INVALIDATE", seconds_since_last_review=9999.0,
                    known_from=T0, now=T0)
    assert d.is_terminal is True
    assert d.should_review is False


def test_new_thesis_lineage_required_after_invalidate():
    new_id = rt.new_thesis_lineage_id("SPY", generation=2)
    assert new_id == "SPY-LIVE-GEN2"
    with pytest.raises(rt.ReunderwriteTriggerError):
        rt.new_thesis_lineage_id("SPY", generation=1)


def test_assassin_refresh_required_on_evidence_change():
    changed = {**BASE_INPUTS, "curve_state": "NEGATIVE_TRANSITION"}
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                    prior_inputs=BASE_INPUTS, current_inputs=changed,
                    prior_state="WATCH", seconds_since_last_review=30.0,
                    known_from=T0, now=T0)
    assert rt.requires_fresh_assassin(d) is True


def test_assassin_refresh_not_required_on_rank_only_change():
    changed = {**BASE_INPUTS, "leading_edge_rank": "2"}
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                    prior_inputs=BASE_INPUTS, current_inputs=changed,
                    prior_state="WATCH", seconds_since_last_review=30.0,
                    known_from=T0, now=T0)
    assert d.triggers == ("RANK_CHANGE",)
    assert rt.requires_fresh_assassin(d) is False


def test_should_review_true_requires_a_named_trigger():
    with pytest.raises(rt.ReunderwriteTriggerError):
        rt.ReunderwriteDecision(
            subject="SPY", candidate_id="SPY-LIVE", should_review=True,
            triggers=(), changed_inputs=(), unchanged_inputs=(),
            prior_state="WATCH", seconds_since_last_review=1.0,
            is_terminal=False, known_from=str(T0), as_of=str(T0))


def test_unknown_trigger_kind_refused():
    with pytest.raises(rt.ReunderwriteTriggerError):
        rt.ReunderwriteDecision(
            subject="SPY", candidate_id="SPY-LIVE", should_review=True,
            triggers=("MADE_UP_TRIGGER",), changed_inputs=(), unchanged_inputs=(),
            prior_state="WATCH", seconds_since_last_review=1.0,
            is_terminal=False, known_from=str(T0), as_of=str(T0))


# ---- ledger: "nothing changed" vs "never called" -------------------------

def test_review_without_state_change_is_captain_review():
    rec = rl.record(candidate_id="SPY-LIVE", subject="SPY", review_number=2,
                    review_time=T0, trigger=("RUNTIME_STALENESS_SAFETY_INTERVAL",),
                    previous_captain_state="WATCH", current_captain_state="WATCH",
                    changed_inputs=(), unchanged_inputs=("curve_state",),
                    known_from=T0)
    assert rec.record_kind == "CAPTAIN_REVIEW"


def test_review_with_state_change_is_captain_state_change():
    rec = rl.record(candidate_id="SPY-LIVE", subject="SPY", review_number=3,
                    review_time=T0, trigger=("CURVE_STATE_CHANGE",),
                    previous_captain_state="WATCH", current_captain_state="DEVELOP",
                    changed_inputs=({"field": "curve_state", "was": "A", "now": "B"},),
                    unchanged_inputs=(), known_from=T0)
    assert rec.record_kind == "CAPTAIN_STATE_CHANGE"


def test_mislabeled_state_change_refused():
    with pytest.raises(rl.ReunderwriteLedgerError):
        rl.ReunderwriteRecord(
            record_kind="CAPTAIN_STATE_CHANGE", candidate_id="X", subject="SPY",
            review_number=1, review_time=str(T0), trigger=("CURVE_STATE_CHANGE",),
            previous_captain_state="WATCH", current_captain_state="WATCH",
            changed_inputs=(), unchanged_inputs=(), current_curve=None,
            current_ev=None, current_pressure=None, current_propagation=None,
            current_assassin=None, current_system_cognition=None, support=(),
            objections=(), direction_quality="UNKNOWN", transition_quality="UNKNOWN",
            entry_quality="UNKNOWN", data_quality="UNKNOWN", assassin_refreshed=False,
            known_from=str(T0), artifact_refs=())


def test_review_counts_distinguish_reviews_from_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "LEDGER", tmp_path / "reunderwrite.jsonl")
    rl.persist(rl.record(candidate_id="SPY-LIVE", subject="SPY", review_number=1,
                        review_time=T0, trigger=("NEVER_REVIEWED",),
                        previous_captain_state=None, current_captain_state="WATCH",
                        changed_inputs=(), unchanged_inputs=(), known_from=T0))
    rl.persist(rl.record(candidate_id="SPY-LIVE", subject="SPY", review_number=2,
                        review_time=T0, trigger=("RUNTIME_STALENESS_SAFETY_INTERVAL",),
                        previous_captain_state="WATCH", current_captain_state="WATCH",
                        changed_inputs=(), unchanged_inputs=(), known_from=T0))
    counts = rl.review_counts_by_subject(tmp_path / "reunderwrite.jsonl")
    assert counts["SPY"]["reviews"] == 2
    assert counts["SPY"]["state_changes"] == 1   # None -> WATCH counts as a move


def test_degrade_is_heartbeat_eligible_not_frozen():
    """DEGRADE is NOT terminal. Leaving it out of HEARTBEAT_STATES
    recreated the freeze for degrading subjects in the Phase 1.0 dry
    run -- caught live, encoded here."""
    assert "DEGRADE" in rt.HEARTBEAT_STATES
    assert "DEGRADE" not in rt.TERMINAL_STATES
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE",
                    prior_inputs=BASE_INPUTS, current_inputs=dict(BASE_INPUTS),
                    prior_state="DEGRADE",
                    seconds_since_last_review=rt.RUNTIME_STALENESS_SAFETY_INTERVAL_S + 1,
                    known_from=T0, now=T0)
    assert d.should_review is True


def test_runtime_no_longer_gates_captain_behind_compute_tier():
    """THE ROOT-CAUSE REGRESSION TEST. The live 2026-08-18 freeze was
    caused by this exact source line in the runtime:

        if route.tier >= 4 or symbol not in state.captain_state:

    Captain/Assassin invocation must never again be gated on compute
    tier, because tier 4 required a seriousness only Captain could
    grant."""
    from pathlib import Path
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()
    assert "if route.tier >= 4 or symbol not in state.captain_state:" not in src
    assert "rumod.evaluate(" in src, (
        "the runtime must decide re-underwriting via ReunderwriteTrigger")
    assert "rumod.requires_fresh_assassin(decision)" in src, (
        "Assassin must be re-run before Captain when evidence changed")


def test_trigger_comparison_uses_identical_key_sets():
    """The Phase 1.0 dry run caught a phantom ASSASSIN_WOUND_CHANGE
    firing every cycle because the observed snapshot omitted the
    assassin keys the stored prior snapshot carried -- absence
    masquerading as change. The runtime must seed both assassin fields
    into the comparison snapshot."""
    snap = _build_snapshot()
    assert "assassin2_familiarity" in snap
    assert "assassin2_caution_label" in snap
    # and absent -> a REAL value, never a dropped key
    absent = _build_snapshot(a2=None)
    assert set(absent) == set(snap)
    assert absent["assassin2_familiarity"] == "UNKNOWN"
    assert absent["assassin2_caution_label"] == "NONE"


def test_decision_power_never_grants_authority():
    d = rt.evaluate(subject="SPY", candidate_id="SPY-LIVE", prior_inputs=None,
                    current_inputs=BASE_INPUTS, prior_state=None,
                    seconds_since_last_review=None, known_from=T0, now=T0)
    assert d.decision_power == "NONE_FRONTIER_SHADOW"


# ---- decision adaptation latency (Phase 1.1, operator request #3) --------

def test_adaptation_latency_measures_the_full_chain():
    rec = rl.record(
        candidate_id="SPY-LIVE", subject="SPY", review_number=2,
        review_time=T0 + pd.Timedelta(seconds=45),
        trigger=("CURVE_STATE_CHANGE",), previous_captain_state="WATCH",
        current_captain_state="DEVELOP",
        changed_inputs=({"field": "curve_state", "was": "A", "now": "B"},),
        unchanged_inputs=(), known_from=T0,
        upstream_event_time=T0,
        assassin_review_time=T0 + pd.Timedelta(seconds=30))
    lat = rec.adaptation_latency_s()
    assert lat["upstream_to_assassin_s"] == pytest.approx(30.0)
    assert lat["upstream_to_captain_review_s"] == pytest.approx(45.0)
    assert lat["upstream_to_state_change_s"] == pytest.approx(45.0)
    assert lat["assassin_to_captain_s"] == pytest.approx(15.0)
    assert lat["integrity"] == "OK"


def test_no_state_change_has_no_state_change_time():
    rec = rl.record(
        candidate_id="SPY-LIVE", subject="SPY", review_number=3,
        review_time=T0 + pd.Timedelta(seconds=10),
        trigger=("RUNTIME_STALENESS_SAFETY_INTERVAL",),
        previous_captain_state="WATCH", current_captain_state="WATCH",
        changed_inputs=(), unchanged_inputs=(), known_from=T0,
        upstream_event_time=T0)
    assert rec.state_change_time is None
    assert rec.adaptation_latency_s()["upstream_to_state_change_s"] is None


def test_negative_latency_is_flagged_not_averaged():
    """A bar stamped ahead of the clock is a data-integrity fault, not a
    fast system. It must surface, never quietly enter a latency stat."""
    rec = rl.record(
        candidate_id="SPY-LIVE", subject="SPY", review_number=4,
        review_time=T0, trigger=("CURVE_STATE_CHANGE",),
        previous_captain_state="WATCH", current_captain_state="DEVELOP",
        changed_inputs=(), unchanged_inputs=(), known_from=T0,
        upstream_event_time=T0 + pd.Timedelta(hours=3))
    lat = rec.adaptation_latency_s()
    assert lat["integrity"] == "NEGATIVE_LATENCY_UPSTREAM_AHEAD_OF_CLOCK"
    assert "upstream_to_captain_review_s" in lat["negative_legs"]


def test_missing_upstream_time_yields_none_not_zero():
    rec = rl.record(
        candidate_id="SPY-LIVE", subject="SPY", review_number=5,
        review_time=T0, trigger=("NEVER_REVIEWED",),
        previous_captain_state=None, current_captain_state="WATCH",
        changed_inputs=(), unchanged_inputs=(), known_from=T0)
    lat = rec.adaptation_latency_s()
    assert lat["upstream_to_captain_review_s"] is None
    assert lat["integrity"] == "OK"


def test_tier_oscillation_must_not_create_phantom_triggers():
    """AUDIT FINDING 2026-08-18. EV/PP/Propagation only compute at
    compute-tier >= 2. When a subject falls back to tier 1 they stop
    being computed; substituting UNKNOWN into the trigger snapshot reads
    as a material change even though the market never moved, producing a
    self-sustaining review loop driven by our own compute budget. Same
    class as the assassin phantom. The runtime must CARRY FORWARD the
    last computed value instead."""
    from pathlib import Path
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()
    assert "TIER-OSCILLATION GUARD" in src
    for carry in ("state.last_ev.get(symbol)", "state.last_pp.get(symbol)",
                  "state.last_edge.get(symbol)"):
        assert carry in src, f"missing carry-forward: {carry}"
    # and the values must be stored when they ARE computed
    for store in ("state.last_ev[symbol] = ev", "state.last_pp[symbol] = pp",
                  "state.last_edge[symbol] = edge"):
        assert store in src, f"missing carry-store: {store}"


def test_captain_gate_never_reintroduces_a_tier_dependency():
    """The Phase 1.0 deadlock must not creep back via a new tier gate."""
    from pathlib import Path
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()
    block = src.split("# --- RE-UNDERWRITING")[1]
    captain_gate = block.split("if decision is not None and decision.should_review:")[0]
    code_lines = [l for l in captain_gate.splitlines()
                  if "route.tier" in l and not l.strip().startswith("#")]
    assert code_lines == [], f"tier dependency back in the captain gate: {code_lines}"


# ---------------------------------------------------------------------
# BEHAVIOURAL phantom-trigger proof (Final Closure, 2026-08-18). The
# source-scanning tests above prove the guard is WRITTEN; these run the
# real snapshot builder and the real trigger evaluator and prove it
# WORKS -- a compute-budget change alone, with the market held perfectly
# still, must emit nothing.
# ---------------------------------------------------------------------

def _runtime():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import frontier2_shadow_runtime as mod
    return mod


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_CURVE = _Stub(high_level_state="DEVELOPING", transition_direction="UP",
               expression="COILED", transition_likelihood="MODERATE")
_EV = _Stub(state="EXPECTATION_MET")
_PP = _Stub(trap_state="NONE", pressure_direction="BUYERS")
_EDGE = _Stub(status="LEADS")
_OI = _Stub(quality="GOOD")
_SC = _Stub(overall_quality="COHERENT")
_A2 = _Stub(familiarity="FAMILIAR", caution_label="MODERATE")


def _build_snapshot(**over):
    kw = {"curve": _CURVE, "ev": _EV, "pp": _PP, "edge": _EDGE,
          "oi": _OI, "sc": _SC, "a2": _A2}
    kw.update(over)
    return _runtime().build_observed_inputs(**kw)


def test_compute_tier_drop_alone_emits_no_trigger():
    """The market does not move. APEX merely demotes the subject from
    compute tier 2 to tier 1, so ExpectationViolation / ParticipantPressure
    / Propagation are not recomputed this cycle. With the runtime's
    carry-forward applied the snapshot must be byte-identical, and
    evaluate() must refuse to review."""
    tier2 = _build_snapshot()

    # exactly what the runtime does: this cycle computed nothing, so the
    # last computed organ states are substituted before comparison.
    last_ev, last_pp, last_edge = {"AAPL": _EV}, {"AAPL": _PP}, {"AAPL": _EDGE}
    ev = pp = edge = None
    if ev is None:
        ev = last_ev.get("AAPL")
    if pp is None:
        pp = last_pp.get("AAPL")
    if edge is None:
        edge = last_edge.get("AAPL")
    tier1 = _build_snapshot(ev=ev, pp=pp, edge=edge)

    assert tier1 == tier2, "carry-forward failed to reproduce the snapshot"
    d = rt.evaluate(subject="AAPL", candidate_id="AAPL-LIVE",
                    prior_inputs=tier2, current_inputs=tier1,
                    prior_state="WATCH", seconds_since_last_review=10.0,
                    known_from=T0, now=T0)
    assert d.should_review is False
    assert d.triggers == ()


def test_uncarried_tier_drop_would_have_fired_all_three():
    """Proves the guard is load-bearing rather than decorative: WITHOUT
    the carry-forward -- writing UNKNOWN where the organ merely was not
    recomputed -- the same motionless market emits three triggers."""
    tier2 = _build_snapshot()
    uncarried = _build_snapshot(ev=None, pp=None, edge=None)
    d = rt.evaluate(subject="AAPL", candidate_id="AAPL-LIVE",
                    prior_inputs=tier2, current_inputs=uncarried,
                    prior_state="WATCH", seconds_since_last_review=10.0,
                    known_from=T0, now=T0)
    assert d.should_review is True
    fired = set(d.triggers)
    for expected in ("EXPECTATION_VIOLATION_CHANGE",
                     "PARTICIPANT_PRESSURE_CHANGE", "PROPAGATION_CHANGE"):
        assert expected in fired, f"{expected} not in {sorted(fired)}"


def test_snapshot_key_set_is_invariant_to_every_absent_organ():
    """The original assassin phantom was an ABSENT KEY, not a changed
    value. No combination of missing organs may change the key set."""
    import itertools
    full = _build_snapshot()
    names = ["ev", "pp", "edge", "a2"]
    for r in range(len(names) + 1):
        for combo in itertools.combinations(names, r):
            snap = _build_snapshot(**{k: None for k in combo})
            assert set(snap) == set(full), f"key set changed when {combo} absent"


def test_runtime_calls_the_shared_snapshot_builder():
    """The behavioural tests are only meaningful if the live runtime uses
    this same function -- not a divergent inline copy."""
    from pathlib import Path
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()
    assert "observed_inputs = build_observed_inputs(" in src
    assert "observed_inputs = {" not in src, "inline snapshot dict reintroduced"
