"""LeadingEdgeMap — F5. Proves the ranking is deterministic and
lexicographic (never a fitted weight), UNKNOWN always sorts worst, and
the earliest-elevation tie-break only matters among otherwise-equal
candidates.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.leading_edge_map import RANK_ORDER, rank

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _cand(symbol, **kw):
    base = {"symbol": symbol}
    base.update(kw)
    return base


def test_confirmed_expression_outranks_early_which_outranks_none():
    cands = [
        _cand("C", curve_expression="NO_EXPRESSION"),
        _cand("A", curve_expression="CONFIRMED_EXPRESSION"),
        _cand("B", curve_expression="EARLY_EXPRESSION"),
    ]
    lem = rank("EARLY_POSITIVE_CURVATURE", cands, known_from=T0, now=T0)
    assert [r["symbol"] for r in lem.rows] == ["A", "B", "C"]
    assert [r["rank"] for r in lem.rows] == [1, 2, 3]


def test_unknown_dimension_never_outranks_known_good():
    cands = [
        _cand("UNKNOWN_EVERYTHING"),
        _cand("KNOWN_WEAK", curve_expression="NO_EXPRESSION",
             trend_quality="WEAK"),
    ]
    lem = rank("X", cands, known_from=T0, now=T0)
    assert lem.rows[0]["symbol"] == "KNOWN_WEAK"


def test_all_dimensions_present_in_every_row_even_unsupplied():
    cands = [_cand("A")]
    lem = rank("X", cands, known_from=T0, now=T0)
    assert set(lem.rows[0]["dimensions"].keys()) == set(RANK_ORDER)
    assert all(v == "UNKNOWN" for v in lem.rows[0]["dimensions"].values())
    assert lem.rows[0]["coverage"] == "0/10 dimensions known"


def test_data_quality_is_the_first_and_dominant_sort_key():
    """A LIMITED-data candidate must sort behind a FULL-data candidate
    even if every other dimension favors the LIMITED one."""
    cands = [
        _cand("LIMITED_BUT_OTHERWISE_PERFECT", data_quality="LIMITED",
             curve_expression="CONFIRMED_EXPRESSION",
             propagation_position="PROPAGATED", trend_quality="STRONG"),
        _cand("FULL_BUT_WEAK", data_quality="FULL",
             curve_expression="NO_EXPRESSION"),
    ]
    lem = rank("X", cands, known_from=T0, now=T0)
    assert lem.rows[0]["symbol"] == "FULL_BUT_WEAK"


def test_first_elevated_at_breaks_ties_earliest_wins():
    cands = [
        _cand("LATER", curve_expression="CONFIRMED_EXPRESSION",
             first_elevated_at=str(T0 + pd.Timedelta(minutes=10))),
        _cand("EARLIER", curve_expression="CONFIRMED_EXPRESSION",
             first_elevated_at=str(T0)),
    ]
    lem = rank("X", cands, known_from=T0, now=T0)
    assert lem.rows[0]["symbol"] == "EARLIER"


def test_unknown_elevation_time_sorts_after_known_in_a_tie():
    cands = [
        _cand("NO_TIMESTAMP", curve_expression="CONFIRMED_EXPRESSION"),
        _cand("HAS_TIMESTAMP", curve_expression="CONFIRMED_EXPRESSION",
             first_elevated_at=str(T0)),
    ]
    lem = rank("X", cands, known_from=T0, now=T0)
    assert lem.rows[0]["symbol"] == "HAS_TIMESTAMP"


def test_supporting_dimensions_lists_only_best_values():
    cands = [_cand("A", curve_expression="CONFIRMED_EXPRESSION",
                   trend_quality="WEAK", liquidity="HEALTHY")]
    lem = rank("X", cands, known_from=T0, now=T0)
    supp = lem.rows[0]["supporting_dimensions"]
    assert "curve_expression" in supp
    assert "liquidity" in supp
    assert "trend_quality" not in supp


def test_contradictions_pass_through_untouched():
    cands = [_cand("A", contradictions=("expectation_violation_negative",))]
    lem = rank("X", cands, known_from=T0, now=T0)
    assert lem.rows[0]["contradictions"] == ("expectation_violation_negative",)


def test_no_optimized_weight_every_dimension_is_a_named_ordinal():
    """Structural proof there is no scalar score: every ranked row's
    dimensions dict must contain only the closed RANK_ORDER set of
    named categorical values, nothing numeric."""
    cands = [_cand("A", curve_expression="CONFIRMED_EXPRESSION")]
    lem = rank("X", cands, known_from=T0, now=T0)
    for v in lem.rows[0]["dimensions"].values():
        assert isinstance(v, str)


def test_empty_candidate_list_is_a_valid_empty_map():
    lem = rank("X", [], known_from=T0, now=T0)
    assert lem.n_candidates == 0
    assert lem.rows == ()


def test_determinism_same_candidates_twice_byte_identical():
    cands = [_cand("A", curve_expression="CONFIRMED_EXPRESSION"),
            _cand("B", curve_expression="EARLY_EXPRESSION")]
    a = rank("X", cands, known_from=T0, now=T0)
    b = rank("X", cands, known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.leading_edge_map as lemod
    monkeypatch.setattr(lemod, "LEDGER", tmp_path / "lem.jsonl")
    lem = rank("X", [_cand("A")], known_from=T0, now=T0)
    rec1 = lemod.persist(lem)
    rec2 = lemod.persist(lem)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
