"""BTC window resolver commissioning — maturity fence, cohort
denominators, episode convention, no trader surface.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scripts.btc_window_resolver as R

T0 = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def marks(hours=6, start=78000.0, drift=10.0):
    return [(T0 + timedelta(minutes=i), start + i * drift)
            for i in range(hours * 60)]


def decision(t, cohort="NONE_OBSERVED", direction="LONG"):
    return {"kind": "btc_paper_decision", "T": str(t),
            "cohort": cohort,
            "attack_geometry": {"direction": direction}}


def _write(p, rows):
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def test_no_trader_import_no_capital_import():
    src = Path(R.__file__).read_text()
    for n in ast.walk(ast.parse(src)):
        mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module or ""] if isinstance(n, ast.ImportFrom)
                else [])
        for m in mods:
            assert "btc_sleeve" not in m, "resolver imports the trader"
            assert "allocator" not in m and "book" not in m \
                and "arena" not in m, f"resolver reaches capital: {m}"


def test_young_windows_are_pending_never_partial(tmp_path):
    d = _write(tmp_path / "d.jsonl", [decision(T0)])
    o = tmp_path / "o.jsonl"
    r = R.resolve(now=T0 + timedelta(minutes=30), decisions=d,
                  outcomes=o, marks=marks())
    assert r["resolved"] == 0 and r["pending_maturity"] == 1
    assert not o.exists()


def test_mature_windows_resolve_with_aligned_geometry(tmp_path):
    d = _write(tmp_path / "d.jsonl",
               [decision(T0, cohort="SUSCEPTIBLE_NOT_TRIGGERED",
                         direction="SHORT")])
    o = tmp_path / "o.jsonl"
    r = R.resolve(now=T0 + timedelta(hours=5), decisions=d,
                  outcomes=o, marks=marks())
    assert r["resolved"] == 1
    row = json.loads(o.read_text().splitlines()[0])
    assert row["cohort"] == "SUSCEPTIBLE_NOT_TRIGGERED"
    assert row["fwd_return"]["60m"] > 0          # price rose
    assert row["aligned_mfe_4h"] <= 0            # SHORT-aligned: rally
    assert row["aligned_mae_4h"] < 0             # is all adverse
    # idempotent
    r2 = R.resolve(now=T0 + timedelta(hours=5), decisions=d,
                   outcomes=o, marks=marks())
    assert r2["resolved"] == 0


def test_missing_marks_are_unmeasurable_not_invented(tmp_path):
    d = _write(tmp_path / "d.jsonl", [decision(T0)])
    o = tmp_path / "o.jsonl"
    r = R.resolve(now=T0 + timedelta(hours=5), decisions=d,
                  outcomes=o, marks=[(T0 + timedelta(hours=9),
                                      80000.0)])
    assert r["unmeasurable"] == 1
    row = json.loads(o.read_text().splitlines()[0])
    assert row["eligible"] is False


def test_the_full_cohort_denominator_is_reported(tmp_path):
    rows = [decision(T0 + timedelta(minutes=15 * i),
                     cohort=("SUSCEPTIBLE_NOT_TRIGGERED" if i == 2
                             else "NONE_OBSERVED"))
            for i in range(4)]
    d = _write(tmp_path / "d.jsonl", rows)
    r = R.resolve(now=T0 + timedelta(hours=6), decisions=d,
                  outcomes=tmp_path / "o.jsonl", marks=marks(hours=8))
    assert r["denominator_by_cohort"] == {
        "NONE_OBSERVED": 3, "SUSCEPTIBLE_NOT_TRIGGERED": 1}


def test_episodes_are_contiguous_runs_first_window_convention(
        tmp_path):
    """96 NONE windows then 3 SUSCEPTIBLE then 1 NONE = 3 episodes,
    never 100 observations."""
    seq = (["NONE_OBSERVED"] * 6 + ["SUSCEPTIBLE_NOT_TRIGGERED"] * 3
           + ["NONE_OBSERVED"])
    rows = [decision(T0 + timedelta(minutes=15 * i), cohort=c)
            for i, c in enumerate(seq)]
    d = _write(tmp_path / "d.jsonl", rows)
    o = tmp_path / "o.jsonl"
    R.resolve(now=T0 + timedelta(hours=12), decisions=d, outcomes=o,
              marks=marks(hours=14))
    rep = R.report(outcomes=o)
    assert rep["raw_windows"] == 10
    assert rep["episodes_first_window_convention"] == 3
    assert rep["independent_episodes"] == "NOT_ESTIMABLE"
    assert rep["cohorts"]["SUSCEPTIBLE_NOT_TRIGGERED"]["episodes"] == 1
    assert rep["cohorts"]["SUSCEPTIBLE_NOT_TRIGGERED"][
        "raw_windows"] == 3
