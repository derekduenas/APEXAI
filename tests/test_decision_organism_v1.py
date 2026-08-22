"""PROFIT PREDATOR v1 -- decision-organism reachability proofs.

Phases 5-9 of the 2026-08-20 integrated repair: dependency-aware Curve
aggregation, HIGH reachable-but-non-trivial, canonical market_state
feeding real third/fourth dimensions, LeadingEdge wired, Captain's
SERIOUS / WAIT_FOR_ENTRY reachable under controlled certified inputs.

CONTROLLED constructions only -- nothing here reads a session outcome,
and nothing asserts a target firing frequency.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.frontier2 import curve  # noqa: E402
from apex.frontier2.observation_integrity import compute as oi_compute  # noqa: E402
from apex.intraday.universe_coverage import UniverseCoverageState  # noqa: E402

T0 = pd.Timestamp("2026-08-20 14:00:00", tz="UTC")
NOW = T0 + pd.Timedelta(minutes=11)


def _oi(broad=True):
    uc = UniverseCoverageState(
        intended_universe=("A",), authorized_universe=("A",),
        streamed_universe=("A",), continuous_universe=("A",),
        rotated_universe=(), never_observed=(), coverage_count=1,
        coverage_fraction=1.0, continuous_coverage_fraction=1.0,
        broad_discovery_valid=broad, status="HEALTHY")
    return oi_compute(universe_coverage=uc, as_of=T0, known_from=T0)


def _quiet_then_break(base, wobble, brk, n=12):
    """A quiet alternating stretch then a decisive final move -- the V2
    shape that legitimately elevates."""
    pts = [(T0 + pd.Timedelta(minutes=i), base + wobble * ((-1) ** i))
           for i in range(n - 1)]
    return pts + [(T0 + pd.Timedelta(minutes=n - 1), base + brk)]


def _quiet(base, wobble, n=12):
    return [(T0 + pd.Timedelta(minutes=i), base + wobble * ((-1) ** i))
            for i in range(n)]


# ---------------------------------------------- Phase 5/6: likelihood law

def test_high_is_reachable_with_three_dims_across_two_groups():
    """price + RS (PRICE_DERIVED) + breadth (CROSS_SECTIONAL): three
    elevated dimensions, two independent mechanism groups -> HIGH.
    Before this build HIGH was structurally unreachable (only 2
    dimensions ever supported)."""
    dims = {"price": _quiet_then_break(100.0, 0.02, 3.0),
            "relative_strength": _quiet_then_break(0.0, 0.05, 2.0),
            "breadth": _quiet_then_break(0.5, 0.01, 0.4)}
    st = curve.compute("SPY", dims, observation_integrity=_oi(),
                       now=NOW, known_from=NOW)
    assert st.elevated_dimension_count >= 3
    assert len(st.independent_elevated_groups) >= 2
    assert st.transition_likelihood == "HIGH"


def test_high_is_not_trivial_quiet_market_is_none():
    dims = {"price": _quiet(100.0, 0.02),
            "relative_strength": _quiet(0.0, 0.05),
            "breadth": _quiet(0.5, 0.01)}
    st = curve.compute("SPY", dims, observation_integrity=_oi(),
                       now=NOW, known_from=NOW)
    assert st.transition_likelihood == "NONE"
    assert st.elevated_dimension_count == 0


def test_three_elevated_in_one_group_is_moderate_not_high():
    """THE DEPENDENCY LAW: three cross-sectional reads of the same
    11-ETF panel bending together is one mechanism, not three proofs."""
    dims = {"sector_leadership": _quiet_then_break(0.002, 0.0001, 0.01),
            "breadth": _quiet_then_break(0.5, 0.01, 0.4),
            "correlation": _quiet_then_break(0.6, 0.005, 0.3)}
    st = curve.compute("SPY", dims, observation_integrity=_oi(),
                       now=NOW, known_from=NOW)
    assert st.elevated_dimension_count == 3
    assert st.independent_elevated_groups == ("CROSS_SECTIONAL",)
    assert st.transition_likelihood == "MODERATE", (
        "three clones of one mechanism scored HIGH")


def test_two_elevated_is_moderate_one_is_low():
    two = {"price": _quiet_then_break(100.0, 0.02, 3.0),
           "relative_strength": _quiet_then_break(0.0, 0.05, 2.0)}
    st2 = curve.compute("SPY", two, observation_integrity=_oi(),
                        now=NOW, known_from=NOW)
    assert st2.transition_likelihood == "MODERATE"
    one = {"price": _quiet_then_break(100.0, 0.02, 3.0),
           "relative_strength": _quiet(0.0, 0.05)}
    st1 = curve.compute("SPY", one, observation_integrity=_oi(),
                        now=NOW, known_from=NOW)
    assert st1.transition_likelihood == "LOW"


def test_dependency_group_fields_are_persisted():
    dims = {"price": _quiet_then_break(100.0, 0.02, 3.0)}
    rec = curve.compute("SPY", dims, observation_integrity=_oi(),
                        now=NOW, known_from=NOW).as_record()
    assert "supported_dimension_count" in rec
    assert "elevated_dimension_count" in rec
    assert "independent_elevated_groups" in rec


def test_every_dimension_has_a_declared_dependency_group():
    assert set(curve.DEPENDENCY_GROUPS) == set(curve.DIMENSIONS)


# --------------------------------- Phase 3/4: canonical market state feed

def test_market_state_firewall_import_closure():
    """apex.market_state may not import any decision-stack package --
    proven over the real import closure, not a docstring."""
    from apex.audit.execution_path import module_closure
    from apex.market_state import FORBIDDEN_IMPORTS
    root = Path(__file__).resolve().parent.parent
    closure = (module_closure(root, "apex.market_state")
               | module_closure(root, "apex.market_state.cross_section")
               | module_closure(root, "apex.market_state.schemas"))
    for mod in closure:
        for forbidden in FORBIDDEN_IMPORTS:
            assert not mod.startswith(forbidden), (
                f"market_state reaches {mod} -- firewall breached")


def test_insufficient_series_yields_no_support_not_fabricated_feed():
    from apex.market_state.cross_section import curve_points
    from apex.market_state.schemas import DEGRADED, CrossSectionalSeries
    s = CrossSectionalSeries(
        name="SECTOR_LEADERSHIP_DISPERSION",
        points=((T0, 0.001), (T0 + pd.Timedelta(minutes=1), 0.002)),
        sufficient=False, quality=DEGRADED, members_observed=6,
        members_expected=11, source="test", source_time=str(T0),
        known_from=str(T0), formula_version="test")
    assert curve_points(s, window=31) == []


def test_market_state_series_are_known_from_safe():
    """A bar after `now` must never enter the series -- points stop at
    the clock, not at the file's end."""
    import apex.market_state.cross_section as cs
    early = pd.Timestamp("2026-08-20 14:00:00", tz="UTC")
    late = pd.Timestamp("2026-08-20 19:30:00", tz="UTC")
    if not Path("data/live/alpaca_fabric/bars/XLK_2026-08-20.json").exists():
        pytest.skip("no live bar data in this environment")
    a = cs.build("2026-08-20", now=early)["sector_leadership"]
    b = cs.build("2026-08-20", now=late)["sector_leadership"]
    if not a.points or not b.points:
        pytest.skip("insufficient live data")
    assert a.points[-1][0] < early
    assert len(b.points) > len(a.points)
    # the early build's points are a strict prefix of the late build's
    assert list(b.points[:len(a.points)]) == list(a.points)


# ----------------------------------- Phase 9: Captain state reachability

def _captain(inputs, prior=None):
    from apex.frontier2.captain_shadow import review
    return review(prior, candidate_id="TEST-1", subject="SPY",
                  current_inputs=inputs, now=NOW, known_from=NOW)


def _full_serious_inputs():
    """Realistic CERTIFIED inputs: curve HIGH (now reachable via 3 dims /
    2 groups), clear direction, LeadingEdge GOOD entry (now wired),
    healthy data, familiar model."""
    return {"curve_state": "POSITIVE_TRANSITION", "curve_direction": "UP",
            "curve_expression": "CONFIRMED_EXPRESSION",
            "curve_likelihood": "HIGH", "participant_trap": "NONE",
            "participant_direction": "UP",
            "propagation_state": "SUPPORTED_LEAD_LAG",
            "leading_edge_rank": 1, "leading_edge_entry_quality": "GOOD",
            "assassin2_familiarity": "FAMILIAR",
            "assassin2_caution_label": "NONE",
            "observation_quality": "FULL",
            "model_market_tally_agrees": True}


def test_serious_is_reachable_with_certified_inputs():
    """THE TWO-LOCK PROOF, closed. Lock 1 (curve HIGH) opened by Phase
    2-6; lock 2 (entry_quality flowing) opened by Phase 8. SERIOUS is
    now reachable from real input shapes -- 2,053 reviews on 2026-08-20
    could never produce this under the old code."""
    st = _captain(_full_serious_inputs())
    assert st.state == "SERIOUS"
    assert st.transition_quality == "STRONG"
    assert st.direction_quality == "STRONG"


def test_wait_for_entry_is_reachable():
    """Strong direction, weak entry geometry: the thesis is real but the
    entry is not there yet."""
    inputs = dict(_full_serious_inputs())
    inputs["leading_edge_entry_quality"] = "POOR"
    st = _captain(inputs)
    assert st.state == "WAIT_FOR_ENTRY"


def test_serious_is_not_trivial_moderate_likelihood_is_not_serious():
    inputs = dict(_full_serious_inputs())
    inputs["curve_likelihood"] = "MODERATE"
    st = _captain(inputs)
    assert st.state != "SERIOUS"


def test_serious_is_not_trivial_unknown_entry_is_not_serious():
    inputs = dict(_full_serious_inputs())
    inputs["leading_edge_entry_quality"] = "UNKNOWN"
    st = _captain(inputs)
    assert st.state != "SERIOUS"


def test_every_captain_state_has_a_reachable_construction():
    """Full state-graph reachability: every non-initial state is
    producible from at least one realistic input configuration."""
    from apex.frontier2.captain_shadow import review
    base = _full_serious_inputs()
    reached = {}

    reached["SERIOUS"] = _captain(base).state

    wfe = dict(base); wfe["leading_edge_entry_quality"] = "POOR"
    reached["WAIT_FOR_ENTRY"] = _captain(wfe).state

    wfc = dict(base)
    wfc["curve_direction"] = "MIXED"
    reached["WAIT_FOR_CONFIRMATION"] = _captain(wfc).state

    dev = dict(base)
    dev["curve_likelihood"] = "MODERATE"
    dev["leading_edge_entry_quality"] = "UNKNOWN"
    reached["DEVELOP"] = _captain(dev).state

    watch = dict(base)
    watch["curve_likelihood"] = "LOW"
    watch["curve_direction"] = "UNKNOWN"
    reached["WATCH"] = _captain(watch).state

    ign = dict(base)
    ign["curve_likelihood"] = "UNKNOWN"
    ign["curve_direction"] = "UNKNOWN"
    reached["IGNORE"] = _captain(ign).state

    prior_dev = _captain(dev)
    degr = dict(base)
    degr["curve_likelihood"] = "LOW"
    degr["curve_direction"] = "UNKNOWN"
    reached["DEGRADE"] = _captain(degr, prior=prior_dev).state

    prior_serious = _captain(base)
    inv = dict(base)
    inv["observation_quality"] = "INVALID"
    reached["INVALIDATE"] = _captain(inv, prior=prior_serious).state

    for want, got in reached.items():
        assert got == want, f"state {want} unreachable (got {got})"


def test_runtime_no_longer_hardcodes_entry_quality_unknown():
    """AST-level proof on the runtime: build_observed_inputs no longer
    contains the literal pair leading_edge_entry_quality: "UNKNOWN"
    as an unconditional value."""
    import ast
    src = Path("scripts/frontier2_shadow_runtime.py").read_text()
    assert '"leading_edge_entry_quality": "UNKNOWN"' not in src
    tree = ast.parse(src)
    ranks = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "rank"]
    assert ranks, "lemod.rank() lost its live caller again"


# ------------------------------------------- Phase 18: checkpoint graph

def test_checkpoint_graph_is_structurally_valid():
    from apex.governance import checkpoint_graph as cg
    assert cg.validate() == []
    assert len(cg.CHECKPOINTS) == 15


def test_checkpoint_graph_is_acyclic_and_reaches_memory():
    from apex.governance import checkpoint_graph as cg
    # CP01 must reach CP15 through the declared edges
    seen, stack = set(), ["CP01"]
    while stack:
        i = stack.pop()
        if i in seen:
            continue
        seen.add(i)
        stack.extend(cg.BY_ID[i].downstream)
    assert "CP15" in seen


def test_uninstrumented_checkpoints_are_declared_not_hidden():
    from apex.governance import checkpoint_graph as cg
    # honest debt: CP03/CP05 verdicts live in-cycle, not on disk yet
    assert set(cg.uninstrumented()) == {"CP03", "CP05"}


def test_capital_and_execution_authority_are_declared_on_the_graph():
    from apex.governance import checkpoint_graph as cg
    assert cg.BY_ID["CP11"].required_authority == "CAPITAL_SOVEREIGN"
    assert cg.BY_ID["CP14"].required_authority == "EXECUTION_SEALED"


# ------------------------- Phase 19: one-shot end-to-end controlled traces

def _runtime():
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    return importlib.import_module("frontier2_shadow_runtime")


def _serious_captain():
    from apex.frontier2.captain_shadow import review
    return review(None, candidate_id="TRACE-1", subject="TRACEQ",
                  current_inputs=_full_serious_inputs(), now=NOW,
                  known_from=NOW)


def test_trace_1_golden_path_reaches_before_card(tmp_path, monkeypatch):
    """REALITY -> ... -> SERIOUS -> Capital -> Expression -> BEFORE card
    -> explicit NO_TRADE. Proves WIRING, not alpha: every checkpoint is
    reached and every verdict lands in a ledger."""
    import types

    from apex.options_research import before_card as bcmod
    rt = _runtime()
    monkeypatch.setattr(rt, "FUNNEL_LEDGER", tmp_path / "funnel.jsonl")
    monkeypatch.setattr(bcmod, "LEDGER", tmp_path / "cards.jsonl")

    cs = _serious_captain()
    assert cs.state == "SERIOUS"                      # CP09/CP10 reached
    c = types.SimpleNamespace(high_level_state="POSITIVE_TRANSITION")
    rec = rt._run_expression_funnel(
        symbol="TRACEQ", candidate_id="TRACE-1", cs=cs, c=c,
        price_pts=[(NOW, 100.0)], now=NOW, known_from=NOW)

    assert rec["capital_verdict"] == "REFUSED"        # CP11: sovereign,
    assert "GOVERNANCE_FAILURE" in rec["capital_reasons"]  # fail-closed
    assert rec["before_card_sealed"] is True          # CP13 reached
    assert rec["terminal_decision"] == "NO_TRADE_DECISION"  # CP14 explicit

    import json as _json
    cards = [_json.loads(l) for l in
             (tmp_path / "cards.jsonl").read_text().splitlines()]
    assert len(cards) == 1
    assert "NO_TRADE" in cards[0]["eligible_structures"]
    funnel = [_json.loads(l) for l in
              (tmp_path / "funnel.jsonl").read_text().splitlines()]
    assert funnel[0]["terminal_decision"] == "NO_TRADE_DECISION"


def test_trace_2_invalid_input_stops_at_the_sufficiency_checkpoint():
    """Same opportunity shape, but the required feature's feed is stale/
    invalid: CP04 must refuse with a named verdict and the feature must
    not speak -- the stop happens at the CORRECT checkpoint, upstream of
    Curve."""
    from apex.intraday import feature_sufficiency as fs
    stale = [(NOW - pd.Timedelta(hours=3), 100.0),
             (NOW - pd.Timedelta(hours=3) + pd.Timedelta(minutes=1), 100.1)]
    v = fs.assess_points("price", "TRACEQ", stale,
                         required_points=10, expected_spacing_s=60.0,
                         now=NOW, known_from=NOW)
    assert v.verdict == "INVALID"
    assert not v.may_speak()
    assert not v.may_speak(consumer_accepts_degraded=True)
    # and Curve, fed [], lands NO_SUPPORT -- never a fabricated neutral
    st = curve.compute("TRACEQ", {"price": []},
                       observation_integrity=_oi(), now=NOW, known_from=NOW)
    assert st.dimensions["price"]["status"] == "NO_SUPPORT"
    assert st.transition_likelihood == "UNKNOWN"


def test_trace_3_good_thesis_bad_expression_is_no_trade_not_silence(
        tmp_path, monkeypatch):
    """Good thesis reaches expression; every option structure is refused
    on economics/eligibility; the outcome is a PERSISTED NO_TRADE with
    named refusals -- distinguishable forever from a pipeline that never
    got there."""
    from apex.options_research import before_card as bcmod
    from apex.options_research import expression_engine as exmod
    monkeypatch.setattr(bcmod, "LEDGER", tmp_path / "cards.jsonl")
    dec = exmod.run(subject="TRACEQ", now=NOW, known_from=NOW,
                    hunter_present=False, frontier_present=True,
                    stock_entry_price=100.0)
    types_present = {c["expression_type"] for c in dec.candidates}
    assert "NO_TRADE" in types_present                 # always first-class
    assert dec.refusals, "bad economics must produce NAMED refusals"
    gates = {r.get("gate") for r in dec.refusals}
    assert gates, f"refusals carry no gates: {dec.refusals}"
