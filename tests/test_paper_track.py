"""The live paper track: frozen set, holdout guard, and selection logic.

The tracker itself needs a populated lake; these tests pin the pure pieces
that make it governable: the portfolio set is frozen with its denominator,
the holdout boundary is the protocol's, an empty lake is refused, and the
per-portfolio selection does what its name says on hand-built rows.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "paper_track", Path(__file__).resolve().parent.parent / "scripts" / "paper_track.py")
pt = importlib.util.module_from_spec(_SPEC)
sys.modules["paper_track"] = pt
_SPEC.loader.exec_module(pt)


def test_the_portfolio_set_is_frozen_with_its_denominator():
    assert pt.PORTFOLIOS == ("H1-A", "H1-B", "H1-E", "H3-QV-T", "H3-QV-B", "CONTROL")
    assert len(set(pt.PORTFOLIOS)) == 6


def test_the_holdout_boundary_is_the_protocols():
    """Marks strictly AFTER 2026-06-30 -- where holdout and snapshot both end."""
    assert pt.HOLDOUT_END == pd.Timestamp("2026-06-30")


def test_an_empty_lake_is_refused_with_the_arming_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "LAKE", tmp_path / "no_such_lake")
    with pytest.raises(SystemExit, match="arm the nightly pull"):
        pt.build_paper_root()


# --- selection logic on hand-built rows -------------------------------------

SCORE = pd.Series({"A": 95.0, "B": 80.0, "C": 55.0, "D": 30.0, "E": 5.0})
DECILE = pd.Series({"A": 1.0, "B": 2.0, "C": 5.0, "D": 8.0, "E": 10.0})
COMP = pd.Series({"A": 0.9, "B": 0.5, "C": 0.95, "D": 0.2, "E": 0.1})


def test_h1_a_takes_exactly_the_top_decile():
    assert pt.target_names("H1-A", SCORE, DECILE, COMP, []) == ["A"]


def test_h1_b_takes_the_top_three_deciles():
    assert sorted(pt.target_names("H1-B", SCORE, DECILE, COMP, [])) == ["A", "B"]


def test_h1_e_banding_holds_a_name_that_slipped_to_decile_5():
    """The hysteresis that halved turnover in the study: C entered earlier,
    now sits in decile 5 -- kept, not sold; a fresh selection would drop it."""
    held = ["A", "C"]
    names = pt.target_names("H1-E", SCORE, DECILE, COMP, held)
    assert "C" in names and "A" in names and "B" in names
    assert pt.target_names("H1-E", SCORE, DECILE, COMP, []) == ["A", "B"]


def test_h3_takes_the_composite_top_not_the_gp_top():
    """C is mediocre on GP (decile 5) but best on the COMPOSITE -- the whole
    point of quality-conditioned value. If H3 selected by GP, it would be
    H1 wearing a different name."""
    assert pt.target_names("H3-QV-T", SCORE, DECILE, COMP, []) == ["C"]


def test_control_holds_the_whole_eligible_universe():
    assert sorted(pt.target_names("CONTROL", SCORE, DECILE, COMP, [])) == \
        ["A", "B", "C", "D", "E"]
