"""The six directive-mandated test families for Track 2 (v3.1 §3.6), in one
module with one family per section: construction, beta neutralization,
turnover accounting, cost application, borrow constraints, evidence tagging.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.portfolio import construction as C

DATES = pd.bdate_range("2020-01-01", periods=720)
NAMES = [f"S{i}" for i in range(20)]


def _panel():
    """Names carry REAL market beta (~1) plus idiosyncratic noise, so the
    beta-neutralisation rungs have actual exposure to neutralise."""
    rng = np.random.default_rng(11)
    mkt = rng.normal(0.0003, 0.008, len(DATES))
    idio = rng.normal(0.0, 0.006, (len(DATES), 20))
    px = pd.DataFrame(100 * np.cumprod(1 + mkt[:, None] + idio, axis=0),
                      index=DATES, columns=NAMES)

    class P:
        close_adj = px
        close_unadj = px
        benchmark_tr = pd.Series(100 * np.cumprod(1 + mkt), index=DATES)
    return P()


def _decile():
    # S0..S1 top decile (1), S18..S19 bottom (10), rest middle
    row = pd.Series(5.0, index=pd.Index(NAMES))
    row[["S0", "S1"]] = 1.0
    row[["S18", "S19"]] = 10.0
    return pd.DataFrame([row] * len(DATES), index=DATES)


SECTOR = pd.Series({n: ("TECH" if i % 2 == 0 else "ENERGY")
                    for i, n in enumerate(NAMES)})
ADDV = pd.DataFrame(5e6, index=DATES, columns=NAMES)
GRID = DATES[200::20]


# --- 1. construction --------------------------------------------------------

def test_long_only_weights_sum_to_one_and_ls_books_balance():
    d = _decile().iloc[0]
    w, _ = C.build_weights(1, d, SECTOR, pd.Series(dtype=float),
                           pd.Series(True, index=pd.Index(NAMES)))
    assert w.sum() == pytest.approx(1.0) and (w > 0).all()

    w2, _ = C.build_weights(2, d, SECTOR, pd.Series(dtype=float),
                            pd.Series(True, index=pd.Index(NAMES)))
    assert w2[w2 > 0].sum() == pytest.approx(C.LONG_GROSS)
    assert w2[w2 < 0].sum() == pytest.approx(-C.SHORT_GROSS)
    assert w2.abs().sum() == pytest.approx(1.0), "no unintended leverage"


# --- 2. beta neutralization -------------------------------------------------

def test_beta_neutral_scaling_hand_computed():
    d = _decile().iloc[0]
    betas = pd.Series(1.0, index=pd.Index(NAMES))
    betas[["S0", "S1"]] = 1.2          # long book beta 1.2
    betas[["S18", "S19"]] = 2.0        # short book beta 2.0
    w, diag = C.build_weights(3, d, SECTOR, betas,
                              pd.Series(True, index=pd.Index(NAMES)))
    # s = 0.5*1.2 / (0.5*2.0) = 0.6 -> short gross 0.3; portfolio beta = 0
    assert -w[w < 0].sum() == pytest.approx(0.3)
    assert float((w * betas.reindex(w.index)).sum()) == pytest.approx(0.0)
    assert diag["beta_cap_hit"] == 0


def test_counterexample_the_scale_cap_binds_and_is_reported():
    d = _decile().iloc[0]
    betas = pd.Series(1.0, index=pd.Index(NAMES))
    betas[["S0", "S1"]] = 3.0          # would need s = 1.5 > cap 1.0
    w, diag = C.build_weights(3, d, SECTOR, betas,
                              pd.Series(True, index=pd.Index(NAMES)))
    assert -w[w < 0].sum() == pytest.approx(C.SHORT_SCALE_CAP[1] * C.SHORT_GROSS)
    assert diag["beta_cap_hit"] == 1, "a binding cap must be surfaced, not smoothed"


def test_realized_beta_is_reported_separately_from_ex_ante():
    """Both series exist; the ex-ante target is ~0 (estimation noise only);
    the divergence between them is REPORTED, never smoothed away."""
    r3 = C.run_rung(3, "x", GRID, _decile(), SECTOR, _panel(), ADDV)
    r2 = C.run_rung(2, "x", GRID, _decile(), SECTOR, _panel(), ADDV)
    assert r3.realized_beta == r3.realized_beta          # not NaN
    assert abs(r3.ex_ante_beta_mean) < 0.15, "neutralisation missed its target"
    assert abs(r3.realized_beta) < abs(r2.realized_beta) + 0.25, (
        "rung 3 must not be MORE exposed than unconstrained rung 2")


# --- 3. turnover accounting -------------------------------------------------

def test_turnover_matches_a_hand_computed_rebalance():
    d = _decile().copy()
    # from the second grid date on, the top decile changes one of two names:
    # S1 out, S2 in -> one-sided turnover = 0.25 of the (1.0-gross) long book
    d.loc[GRID[1]:, ["S1", "S2"]] = d.loc[GRID[1]:, ["S2", "S1"]].values
    res = C.run_rung(1, "x", GRID[:3], d, SECTOR, _panel(), ADDV)
    # long-only book: |w_new - w_old|/2 = (0.5+0.5)/2 * (1/1)... hand:
    # weights are 0.5/0.5 per name; replacing one name moves 0.5 out and 0.5
    # in -> L1=1.0 -> one-sided 0.5
    assert res.turnover_per_rebalance == pytest.approx(0.5)


def test_a_static_book_has_zero_turnover():
    res = C.run_rung(1, "x", GRID[:3], _decile(), SECTOR, _panel(), ADDV)
    assert res.turnover_per_rebalance == 0.0


# --- 4. cost application ----------------------------------------------------

def test_costs_apply_to_realized_turnover_never_assumed():
    static = C.run_rung(1, "x", GRID[:3], _decile(), SECTOR, _panel(), ADDV)
    # zero realized turnover -> the net numbers EQUAL the gross numbers
    assert static.ann_return_net_20bp == pytest.approx(static.ann_return_gross)
    assert static.ann_return_net_40bp == pytest.approx(static.ann_return_gross)

    d = _decile().copy()
    d.loc[GRID[1]:, ["S1", "S2"]] = d.loc[GRID[1]:, ["S2", "S1"]].values
    churn = C.run_rung(1, "x", GRID[:3], d, SECTOR, _panel(), ADDV)
    drag20 = churn.ann_return_gross - churn.ann_return_net_20bp
    drag40 = churn.ann_return_gross - churn.ann_return_net_40bp
    assert drag20 == pytest.approx(0.5 * 0.0020 * 252 / 20, rel=1e-6)
    assert drag40 == pytest.approx(2 * drag20, rel=1e-6)


# --- 5. borrow constraints --------------------------------------------------

def test_unavailable_borrow_excludes_never_silently_shorts():
    d = _decile().iloc[0]
    shortable = pd.Series(True, index=pd.Index(NAMES))
    shortable["S18"] = False
    w, diag = C.build_weights(5, d, SECTOR, pd.Series(1.0, index=pd.Index(NAMES)),
                              shortable)
    assert "S18" not in w.index[w < 0], "unavailable borrow was silently shorted"
    assert diag["borrow_excluded"] == 1


def test_borrow_carry_reduces_rung5_returns():
    r4 = C.run_rung(4, "x", GRID, _decile(), SECTOR, _panel(), ADDV)
    r5 = C.run_rung(5, "x", GRID, _decile(), SECTOR, _panel(), ADDV)
    # identical books here (all shortable), so the only delta is carry
    assert r5.ann_return_gross < r4.ann_return_gross


# --- 6. evidence tagging ----------------------------------------------------

def test_a_design_layer_result_cannot_reach_a_table_untagged():
    res = C.run_rung(0, "x", GRID[:3], _decile(), SECTOR, _panel(), ADDV)
    row = res.as_row()
    assert row["evidence_class"] == "engineering_measurement"
    C.results_table([row])                     # tagged: accepted

    naked = {k: v for k, v in row.items() if k != "evidence_class"}
    with pytest.raises(C.UntaggedResult):
        C.results_table([naked])
    with pytest.raises(C.UntaggedResult):
        C.results_table([{**row, "evidence_class": "evidence_of_edge"}])


def test_counterexample_a_beta_one_book_reports_beta_near_one():
    """The alignment bug this pins: benchmark returns labeled at period END
    against portfolio returns labeled at FORMATION date made a long-only
    beta-1 book report realized beta ~0. Phase-aligned, it must be ~1."""
    res = C.run_rung(1, "x", GRID, _decile(), SECTOR, _panel(), ADDV)
    assert 0.7 < res.realized_beta < 1.3, (
        f"long-only beta-1 book reported {res.realized_beta}; "
        f"benchmark/portfolio series are misaligned")
