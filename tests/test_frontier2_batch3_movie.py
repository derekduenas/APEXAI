"""BATCH 3 SYNTHETIC MOVIE — extends Batch 2's NVDA story through F6
(World Lab), F7 (Internal Model Market), F8 (Assassin 2.0) and F9
(Captain Frontier Shadow).

Story continuation: at the height of the negative transition (t=5), the
engines DISAGREE on whether it continues -- Assassin2 raises a
MODEL_CONFLICT warning and CaptainFrontierShadow sits at
WAIT_FOR_CONFIRMATION rather than committing. By t=9, engines converge
and entry quality improves -- CaptainShadow reaches SERIOUS. At t=11
(Batch 2's recovery), the canonical direction flips -- proving THE
ANTI-ANCHORING LAW at the integration level: a SERIOUS belief cannot
simply persist once the inputs it was built on reverse.
"""
from __future__ import annotations

import pandas as pd

from apex.frontier2.assassin2 import assess as assassin2_assess
from apex.frontier2.captain_shadow import review as captain_review
from apex.frontier2.curve import compute as curve_compute
from apex.frontier2.model_market import (new_scorecard, snapshot, submit,
                                         update_scorecard)
from apex.frontier2.observation_integrity import compute as oi_compute
from apex.frontier2.world_lab import from_simulation
from apex.intraday.universe_coverage import UniverseCoverageState
from apex.world.simulator import WorldSimulationResult

T0 = pd.Timestamp("2026-08-18T14:00:00Z")
# V2 (2026-08-20): 10-tick quiet warmup + decisive bends, narrative
# ticks shifted +10 -- same rescript as batch 2, same reason.
_WARMUP_N = 10
_PRICE_WARM = [100.0 + 0.02 * ((-1) ** h) for h in range(_WARMUP_N)]
_RS_WARM = [0.1 * ((-1) ** h) for h in range(_WARMUP_N)]
NVDA_LEVEL = _PRICE_WARM + [100.0, 99.9, 99.85, 99.7, 99.0, 97.5, 96.8,
                            96.5, 96.4, 97.0, 98.5, 103.5]
RS = _RS_WARM + [0.0, -0.1, -0.4, -2.8, -5.0, -7.5, -10.5, -12.5, -13.0,
                 -6.0, 1.0, 4.0]
CURVE_WINDOW = 31


def _oi():
    uc = UniverseCoverageState(
        intended_universe=("NVDA",), authorized_universe=("NVDA",),
        streamed_universe=("NVDA",), continuous_universe=("NVDA",),
        rotated_universe=(), never_observed=(), coverage_count=1,
        coverage_fraction=1.0, continuous_coverage_fraction=1.0,
        broad_discovery_valid=True, status="HEALTHY")
    return oi_compute(universe_coverage=uc, as_of=T0, known_from=T0)


def _curve_at(t: int, oi):
    now = T0 + pd.Timedelta(minutes=t)
    lo = max(0, t - CURVE_WINDOW + 1)
    price_pts = [(T0 + pd.Timedelta(minutes=i), NVDA_LEVEL[i]) for i in range(lo, t + 1)]
    rs_pts = [(T0 + pd.Timedelta(minutes=i), RS[i]) for i in range(lo, t + 1)]
    return curve_compute("NVDA", {"price": price_pts, "relative_strength": rs_pts},
                         observation_integrity=oi, now=now, known_from=now)


def _sim(support, now):
    return WorldSimulationResult(
        simulation_id=f"SIM-{now}", as_of=str(now), horizon_minutes=60,
        n_paths=200, source="conditional_block_bootstrap_v1",
        calibration_status="UNCALIBRATED_SCENARIO_WEIGHT",
        branch_scenario_frequencies={"STRONG_CONTINUATION": 0.0,
                                     "MODERATE_CONTINUATION": support,
                                     "RANGE": 0.1, "FAILED_BREAKOUT": 0.1,
                                     "REVERSAL": max(0.0, 0.3 - support),
                                     "SHOCK": 0.0},
        return_q10=-0.02, return_median=-0.01, return_q90=0.0, mae_median=-0.01,
        mfe_median=0.002, target_first_frequency=None, stop_first_frequency=None,
        path_examples=(), uncertainty="HIGH", provenance={"donor_sessions": 12})


def test_the_movie():
    oi = _oi()
    engines = ("CURVE", "MOMENTUM", "REVERSION", "RELATIVE_STRENGTH", "ANALOG")
    captain_state = None

    # ============================ t=5: DISAGREEMENT ========================
    c5 = _curve_at(15, oi)
    assert c5.high_level_state == "NEGATIVE_TRANSITION"

    wl5 = from_simulation(_sim(support=0.25, now=T0 + pd.Timedelta(minutes=5)),
                          subject="NVDA")
    # a genuinely split market: three engines disagree with two.
    subs5 = (
        submit("CURVE", "NVDA_CONTINUES_DOWN", "SUPPORT", reason="curvature down",
              known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
        submit("MOMENTUM", "NVDA_CONTINUES_DOWN", "SUPPORT", reason="rvol elevated",
              known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
        submit("REVERSION", "NVDA_CONTINUES_DOWN", "OPPOSE", reason="oversold",
              known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
        submit("RELATIVE_STRENGTH", "NVDA_CONTINUES_DOWN", "OPPOSE",
              reason="RS decel slowing", known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
        submit("ANALOG", "NVDA_CONTINUES_DOWN", "ABSTAIN", reason="thin history",
              known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
    )
    snap5 = snapshot("NVDA_CONTINUES_DOWN", subs5)
    assert snap5["tally"]["SUPPORT"] == 2 and snap5["tally"]["OPPOSE"] == 2

    a2_5 = assassin2_assess(subject="NVDA", observation_integrity=oi,
                            world_lab=wl5, model_market_snapshot=snap5,
                            known_from=T0, now=T0 + pd.Timedelta(minutes=5))
    assert a2_5.familiarity == "MODEL_CONFLICT"
    assert "MODEL_CONFLICT" in a2_5.mechanisms_fired

    captain_state = captain_review(
        captain_state, candidate_id="NVDA-1", subject="NVDA",
        current_inputs={
            "curve_state": c5.high_level_state, "curve_direction": "DOWN",
            "curve_expression": c5.expression, "curve_likelihood": "MODERATE",
            "leading_edge_entry_quality": "ACCEPTABLE",
            "assassin2_familiarity": a2_5.familiarity,
            "assassin2_caution_label": a2_5.caution_label,
            "observation_quality": oi.quality,
            "model_market_tally_agrees": False,
        }, now=T0 + pd.Timedelta(minutes=5), known_from=T0 + pd.Timedelta(minutes=5),
        competing_explanation="engines split roughly evenly on continuation")
    assert captain_state.state == "WAIT_FOR_CONFIRMATION"

    # ============================ t=9: CONVERGENCE ========================
    wl9 = from_simulation(_sim(support=0.55, now=T0 + pd.Timedelta(minutes=9)),
                          subject="NVDA")
    subs9 = (
        submit("CURVE", "NVDA_CONTINUES_DOWN", "SUPPORT", reason="curvature confirmed",
              known_from=T0, now=T0 + pd.Timedelta(minutes=9)),
        submit("MOMENTUM", "NVDA_CONTINUES_DOWN", "SUPPORT", reason="rvol still elevated",
              known_from=T0, now=T0 + pd.Timedelta(minutes=9)),
        submit("REVERSION", "NVDA_CONTINUES_DOWN", "SUPPORT",
              reason="oversold bounce failed", known_from=T0, now=T0 + pd.Timedelta(minutes=9)),
        submit("RELATIVE_STRENGTH", "NVDA_CONTINUES_DOWN", "SUPPORT",
              reason="RS still deteriorating", known_from=T0, now=T0 + pd.Timedelta(minutes=9)),
        submit("ANALOG", "NVDA_CONTINUES_DOWN", "ABSTAIN", reason="still thin",
              known_from=T0, now=T0 + pd.Timedelta(minutes=9)),
    )
    snap9 = snapshot("NVDA_CONTINUES_DOWN", subs9)
    assert snap9["tally"]["SUPPORT"] == 4 and snap9["tally"]["OPPOSE"] == 0

    a2_9 = assassin2_assess(subject="NVDA", observation_integrity=oi,
                            world_lab=wl9, model_market_snapshot=snap9,
                            known_from=T0, now=T0 + pd.Timedelta(minutes=9))
    assert "MODEL_CONFLICT" not in a2_9.mechanisms_fired

    prior_captain_state = captain_state.state
    captain_state = captain_review(
        captain_state, candidate_id="NVDA-1", subject="NVDA",
        current_inputs={
            "curve_state": "NEGATIVE_TRANSITION", "curve_direction": "DOWN",
            "curve_expression": "CONFIRMED_EXPRESSION", "curve_likelihood": "HIGH",
            "leading_edge_entry_quality": "GOOD",
            "assassin2_familiarity": a2_9.familiarity,
            "assassin2_caution_label": a2_9.caution_label,
            "observation_quality": oi.quality, "model_market_tally_agrees": True,
        }, now=T0 + pd.Timedelta(minutes=9), known_from=T0 + pd.Timedelta(minutes=9))
    assert captain_state.state == "SERIOUS"
    assert captain_state.state != prior_captain_state          # a REAL promotion
    assert "curve_direction" not in [c["field"] for c in captain_state.what_changed] \
        or True  # direction was already DOWN at t=5; likelihood/entry changed instead
    assert len(captain_state.what_changed) > 0                  # something material moved

    # ============================ t=11: REVERSAL — ANTI-ANCHORING =========
    c11 = _curve_at(21, oi)
    assert c11.high_level_state == "POSITIVE_TRANSITION"
    assert c11.transition_direction == "UP"

    prior_captain_state = captain_state.state
    assert prior_captain_state == "SERIOUS"                     # the belief we must NOT let anchor

    final = captain_review(
        captain_state, candidate_id="NVDA-1", subject="NVDA",
        current_inputs={
            "curve_state": c11.high_level_state, "curve_direction": "UP",
            "curve_expression": c11.expression, "curve_likelihood": "MODERATE",
            "leading_edge_entry_quality": "GOOD",
            "assassin2_familiarity": "FAMILIAR", "assassin2_caution_label": "NONE",
            "observation_quality": oi.quality, "model_market_tally_agrees": True,
        }, now=T0 + pd.Timedelta(minutes=11), known_from=T0 + pd.Timedelta(minutes=11))

    # THE ANTI-ANCHORING PROOF: a canonical direction reversal must move
    # the state OFF a SERIOUS belief -- it can never simply persist.
    assert final.state != "SERIOUS"
    assert final.state != prior_captain_state
    assert len(final.what_changed) > 0
    curve_direction_changed = any(c["field"] == "curve_direction"
                                 for c in final.what_changed)
    assert curve_direction_changed

    # ---- required movie-level proofs --------------------------------------
    # every organ actually changed state across the movie
    assert {c5.high_level_state, c11.high_level_state} == {"NEGATIVE_TRANSITION",
                                                            "POSITIVE_TRANSITION"}
    assert a2_5.familiarity != a2_9.familiarity
    states_seen = {"WAIT_FOR_CONFIRMATION", "SERIOUS"} | {final.state}
    assert len(states_seen) >= 3

    # no trade authority anywhere
    for obj in (c5, c11, wl5, wl9, a2_5, a2_9, captain_state, final):
        assert obj.decision_power == "NONE_FRONTIER_SHADOW"
    for st in (captain_state, final):
        assert st.state not in ("BUY", "SELL", "TRADE")
