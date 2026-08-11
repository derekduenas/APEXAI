"""The three corrections the production data forced. Reporting-neutral fixes."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.data.snapshot_loader import adjust_high_low


def test_high_low_are_put_on_the_adjusted_scale():
    """Sharadar publishes high/low UNADJUSTED and closeadj ADJUSTED.

    Measured on AIV 2008-10-01: high 45.251 against closeadj 0.928 -- a 37x
    scale mismatch that drove ATR/Close to 89.
    """
    prices = pd.DataFrame({
        "high": [45.251], "low": [43.042], "close": [44.242], "closeadj": [0.928],
    })

    out = adjust_high_low(prices)
    factor = 0.928 / 44.242

    assert out["high_adj"].iloc[0] == pytest.approx(45.251 * factor)
    assert out["low_adj"].iloc[0] == pytest.approx(43.042 * factor)


def test_adjusted_high_low_bracket_the_adjusted_close():
    """Unit consistency: after scaling, low_adj <= closeadj <= high_adj."""
    prices = pd.DataFrame({
        "high": [45.251], "low": [43.042], "close": [44.242], "closeadj": [0.928],
    })
    out = adjust_high_low(prices)

    assert out["low_adj"].iloc[0] <= out["closeadj"].iloc[0] <= out["high_adj"].iloc[0]


def test_no_cross_scale_mixing_the_ratio_is_invariant():
    """The whole point: the true-range/close RATIO must not depend on the
    adjustment vintage. Two securities with identical raw bars but different
    cumulative factors must produce the same ATR/Close."""
    a = adjust_high_low(pd.DataFrame({"high":[45.251],"low":[43.042],"close":[44.242],"closeadj":[0.928]}))
    b = adjust_high_low(pd.DataFrame({"high":[45.251],"low":[43.042],"close":[44.242],"closeadj":[44.242]}))

    ra = (a["high_adj"] - a["low_adj"]).iloc[0] / a["closeadj"].iloc[0]
    rb = (b["high_adj"] - b["low_adj"]).iloc[0] / b["closeadj"].iloc[0]

    assert ra == pytest.approx(rb), "range/close must be invariant to adjustment vintage"


def test_an_unadjusted_series_would_have_produced_the_bug():
    """Guards the guard: the OLD mapping really was broken by ~37x."""
    broken = 45.251 / 0.928          # raw high over adjusted close
    fixed = adjust_high_low(
        pd.DataFrame({"high":[45.251],"low":[43.042],"close":[44.242],"closeadj":[0.928]})
    )["high_adj"].iloc[0] / 0.928

    assert broken > 45
    assert fixed == pytest.approx(45.251 / 44.242)
    assert broken / fixed == pytest.approx(44.242 / 0.928, rel=1e-9)


def test_a_zero_close_does_not_produce_infinity():
    out = adjust_high_low(pd.DataFrame({"high":[1.0],"low":[0.5],"close":[0.0],"closeadj":[0.0]}))
    assert not np.isfinite(out["high_adj"].iloc[0])


def test_reits_are_typed_non_common_so_section_3_excludes_them():
    """Section 3 excludes REITs. Sharadar's `category` is SHARE CLASS; REIT
    status lives in `sector`. Filtering on category alone admitted 628 REITs."""
    from apex.config import load_config
    from apex.data.snapshot_loader import load_master
    from pathlib import Path

    root = Path("data/snapshots/sharadar/current")
    if not (root / "raw" / "TICKERS" / "TICKERS.csv").exists():
        pytest.skip("production snapshot not present")

    master = load_master(root, load_config("experiment", "costs", "synthetic", "sharadar"))
    reits = master[master["sector"] == "Real Estate"]

    assert len(reits) > 0, "no REITs in the master -- the test would be vacuous"
    assert (reits["security_type_apex"] == "reit").all()
    assert (master.loc[master["sector"] != "Real Estate", "security_type_apex"] == "common").all()
