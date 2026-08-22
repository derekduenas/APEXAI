"""Stress matrix (F O21), OPTIONS_BEFORE_CARD (F O25/O26), and the
prospective outcome resolver (F O20)."""
from __future__ import annotations

import pandas as pd
import pytest

from apex.options_research import before_card as before_card_mod
from apex.options_research import outcome as outcome_mod
from apex.options_research.before_card import BeforeCardError, seal
from apex.options_research.outcome import (RESOLUTION_HORIZONS, OutcomeError,
                                            resolve_all_due_horizons,
                                            resolve_horizon)
from apex.options_research.stress import (COST_MULTIPLIERS,
                                           ENTRY_DELAY_MINUTES, StressError,
                                           build_stress_matrix)

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


# ---- stress matrix -------------------------------------------------------

def test_stress_matrix_covers_full_grid():
    m = build_stress_matrix(subject="AAPL", expression_type="LONG_CALL",
                            base_spread_cost=0.10, base_fees=0.65,
                            base_net_expectancy=5.0, decay_per_minute=0.1,
                            known_from=T0)
    assert len(m.cells) == len(COST_MULTIPLIERS) * len(ENTRY_DELAY_MINUTES)


def test_stress_matrix_zero_delay_base_cost_matches_canonical():
    m = build_stress_matrix(subject="AAPL", expression_type="LONG_CALL",
                            base_spread_cost=0.10, base_fees=0.65,
                            base_net_expectancy=5.0, decay_per_minute=0.1,
                            known_from=T0)
    base_zero = [c for c in m.cells
                if c.cost_label == "BASE" and c.entry_delay_minutes == 0][0]
    assert base_zero.adjusted_net_expectancy == pytest.approx(5.0)


def test_stress_matrix_no_decay_rate_leaves_delayed_cells_unknown():
    m = build_stress_matrix(subject="AAPL", expression_type="LONG_CALL",
                            base_spread_cost=0.10, base_fees=0.65,
                            base_net_expectancy=5.0, decay_per_minute=None,
                            known_from=T0)
    delayed = [c for c in m.cells if c.entry_delay_minutes == 15]
    assert all(c.adjusted_net_expectancy is None for c in delayed)


def test_stress_matrix_wrong_cell_count_refused():
    from apex.options_research.stress import StressMatrix
    with pytest.raises(StressError):
        StressMatrix(subject="AAPL", expression_type="LONG_CALL", cells=(),
                    known_from=str(T0))


def test_worst_case_net_expectancy_is_the_minimum():
    m = build_stress_matrix(subject="AAPL", expression_type="LONG_CALL",
                            base_spread_cost=0.10, base_fees=0.65,
                            base_net_expectancy=5.0, decay_per_minute=0.5,
                            known_from=T0)
    worst = m.worst_case_net_expectancy()
    all_known = [c.adjusted_net_expectancy for c in m.cells
                if c.adjusted_net_expectancy is not None]
    assert worst == min(all_known)


# ---- OPTIONS_BEFORE_CARD --------------------------------------------------

def test_seal_writes_a_card_with_no_outcome_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(before_card_mod, "LEDGER", tmp_path / "before_cards.jsonl")
    card = seal(opportunity_id="OPP-1", subject="AAPL", known_from=T0,
               underlying_thesis={"direction": "UP"}, direction_quality="MODERATE",
               transition_quality="EARLY", horizon={"dte_required_minutes": 120},
               surface_snapshot={"atm_iv": {"status": "NO_SUPPORT"}},
               cohort="COHORT_A_HUNTER_ACTIVE_FRONTIER_CONFIRMING",
               eligible_structures=("LONG_CALL", "STOCK", "NO_TRADE"),
               rejected_structures=({"expression_type": "LONG_STRADDLE",
                                     "gate": "REFUSE_NO_OPTION_ADVANTAGE_MECHANISM",
                                     "reason": "OPT-003 conditions not met"},),
               shadow_expression_ranking=("STOCK", "LONG_CALL"),
               ranking_rationale="structural: STOCK ranked first, no live pricing yet",
               now=T0)
    assert card.opportunity_id == "OPP-1"
    fields = set(card.__dataclass_fields__)
    assert not any("outcome" in f or "realized" in f or "pnl" in f for f in fields)


def test_ranking_must_be_subset_of_eligible():
    with pytest.raises(BeforeCardError):
        from apex.options_research.before_card import OptionsBeforeCard
        OptionsBeforeCard(
            opportunity_id="OPP-2", subject="AAPL", known_from=str(T0),
            underlying_thesis={}, direction_quality="MODERATE",
            transition_quality="EARLY", horizon={}, surface_snapshot={},
            cohort="COHORT_D_HUNTER_SILENT_FRONTIER_SILENT",
            eligible_structures=("NO_TRADE",),
            rejected_structures=(), shadow_expression_ranking=("LONG_CALL",),
            ranking_rationale="bad", sealed_at=str(T0))


# ---- prospective outcome resolver -----------------------------------------

def test_resolve_horizon_rejects_unknown_horizon():
    with pytest.raises(OutcomeError):
        resolve_horizon(opportunity_id="OPP-1", subject="AAPL", horizon="90m",
                        horizon_timestamp=T0, now=T0,
                        underlying_price_at_horizon=230.0,
                        structure_net_pnl={"LONG_CALL": 1.0}, known_from=T0)


def test_resolve_all_due_horizons_only_resolves_the_past(tmp_path, monkeypatch):
    monkeypatch.setattr(outcome_mod, "LEDGER", tmp_path / "outcomes.jsonl")
    now = T0 + pd.Timedelta(minutes=20)
    horizon_timestamps = {
        "5m": T0 + pd.Timedelta(minutes=5),
        "15m": T0 + pd.Timedelta(minutes=15),
        "60m": T0 + pd.Timedelta(minutes=60),   # not yet due
    }

    def price_and_pnl(h, ts):
        return 231.0, {"LONG_CALL": 2.0}

    out = resolve_all_due_horizons(opportunity_id="OPP-1", subject="AAPL", now=now,
                                   known_from=T0, horizon_timestamps=horizon_timestamps,
                                   price_and_pnl_fn=price_and_pnl)
    assert {o.horizon for o in out} == {"5m", "15m"}


def test_resolve_all_due_horizons_never_cherry_picks(tmp_path, monkeypatch):
    """All due horizons are resolved together in one call, regardless
    of whether the caller's price_and_pnl_fn returns favorable or
    unfavorable outcomes -- there is no path to resolve only one."""
    monkeypatch.setattr(outcome_mod, "LEDGER", tmp_path / "outcomes.jsonl")
    now = T0 + pd.Timedelta(minutes=20)
    horizon_timestamps = {"5m": T0 + pd.Timedelta(minutes=5),
                          "15m": T0 + pd.Timedelta(minutes=15)}
    calls = []

    def price_and_pnl(h, ts):
        calls.append(h)
        return 229.0, {"LONG_CALL": -1.0}

    resolve_all_due_horizons(opportunity_id="OPP-1", subject="AAPL", now=now,
                             known_from=T0, horizon_timestamps=horizon_timestamps,
                             price_and_pnl_fn=price_and_pnl)
    assert set(calls) == {"5m", "15m"}
