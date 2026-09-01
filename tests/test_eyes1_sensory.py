"""EYES-1 WS4/WS5 — microscope selection law and FastWatch containment.

The tests that matter: the selector is deterministic and LLM-free, the
microscope cannot fabricate an empty book, and FastWatch structurally
cannot write official records, mint matches, or reach the forward
reserve.
"""
from __future__ import annotations

import json

import pytest

from apex.hunter.microscope import (MAX_L2_TARGETS, MAX_QUOTE_TARGETS,
                                    record_result, select_targets)

from apex.hunter.watchlist import make_entry  # noqa: E402

DEC = [{"kind": "decision", "decision_id": f"D{i}", "symbol": s,
        "playbook_id": "HUNTER-001_v1", "t_utc": f"2026-08-17T15:{i:02d}:00Z"}
       for i, s in enumerate(["NVDA.US", "AMD.US"])]
BASE = [{"kind": "decision", "decision_id": "B1", "symbol": "MSFT.US",
         "playbook_id": "BASELINE-RANDOM", "t_utc": "2026-08-17T15:30:00Z"}]
# NATURAL SHAPE: the REAL persisted form (apex/hunter/watchlist.py), never
# a handcrafted positional tuple -- that mismatch is exactly what let the
# 2026-08-17 production defect hide in this file's tests for months.
SCANS = [{"kind": "scan", "watchlist": [
    make_entry("TSLA.US", ["OR_BREAK", "RVOL"], 3.1).as_record(),
    make_entry("AAPL.US", ["RVOL"], 2.0).as_record(),
    make_entry("META.US", ["OR_BREAK", "RVOL", "RS"], 2.4).as_record()]}]


def test_selection_is_deterministic_and_prioritizes_real_candidates():
    a, err_a = select_targets(decisions=DEC + BASE, scans=SCANS)
    b, err_b = select_targets(decisions=DEC + BASE, scans=SCANS)
    assert not err_a and not err_b
    assert [t.symbol for t in a] == [t.symbol for t in b]
    # newest hunter candidate first; baselines never selected as candidates
    assert a[0].symbol == "AMD.US" and "hunter_candidate" in a[0].reason_selected
    assert a[1].symbol == "NVDA.US"
    assert all(t.symbol != "MSFT.US" or "hunter" not in t.reason_selected
               for t in a)
    # watchlist ranked by signal count then rvol: META(3) before TSLA(2,3.1)
    watch = [t for t in a if t.reason_selected.startswith("watchlist")]
    assert [w.symbol for w in watch][:2] == ["META.US", "TSLA.US"]


def test_l2_is_bounded_to_four_and_quotes_to_twenty():
    scans = [{"kind": "scan", "watchlist": [
        make_entry(f"S{i:02d}.US", ["RVOL"], 2.0 + i * 0.01).as_record()
        for i in range(30)]}]
    targets, errors = select_targets(decisions=[], scans=scans)
    assert not errors
    assert len(targets) <= MAX_QUOTE_TARGETS
    assert sum(t.wants_l2 for t in targets) <= MAX_L2_TARGETS
    assert all(t.wants_l2 == (t.priority <= MAX_L2_TARGETS) for t in targets)


def test_no_llm_participates_in_selection():
    import apex.hunter.microscope as m
    from apex.audit.execution_path import executable_source
    code = executable_source(open(m.__file__).read())
    for token in ("swarm", "claude", "llm", "run_specialists", "runner"):
        assert token not in code.lower()


def test_a_missing_book_is_unknown_never_zero_imbalance():
    from apex.hunter.microscope import MicroscopeTarget
    t = MicroscopeTarget(symbol="NVDA.US", priority=1,
                         reason_selected="hunter_candidate:D1", wants_l2=True)
    rec = record_result(t, request_time="t0", response_time="t1",
                        transport="CLAIMED_MCP", quote=None, l2=None)
    assert rec["l2"] == {"status": "UNKNOWN"}
    assert rec["quote"] == {"status": "UNKNOWN"}
    rec2 = record_result(t, request_time="t0", response_time="t1",
                         transport="CLAIMED_MCP",
                         l2={"bid_depth": 100, "imbalance": None})
    assert rec2["l2"]["imbalance"] == "UNKNOWN_NOT_ZERO"
    assert rec["decision_power"] == "NONE_OBSERVATIONAL_EPOCH1"


# ---------------- FastWatch containment ------------------------------------

def test_fastwatch_writes_only_to_its_own_ledger():
    src = open("scripts/fastwatch.py").read()
    assert 'FW_LEDGER = Path("results/hunter/fastwatch_ledger.jsonl")' in src
    seg = src.split("def _append", 1)[1].split("def ", 1)[0]
    assert "FW_LEDGER" in seg and "OFFICIAL_LEDGER" not in seg, (
        "FastWatch's writer can reach the official ledger")


def test_fastwatch_cannot_mint_official_record_kinds():
    src = open("scripts/fastwatch.py").read()
    for forbidden in ('"kind": "decision"', '"kind": "scan"',
                      '"kind": "realization"', '"kind": "capital_decision"',
                      "FORWARD_ELIGIBLE"):
        assert forbidden not in src, (
            f"FastWatch can write {forbidden} — it could impersonate the "
            f"official experiment")
    assert "fastwatch_condition_observed" in src
    assert "not a Hunter match" in src or "not \\na Hunter match" in src


def test_fastwatch_spends_from_the_lab_budget_only():
    """The LAB-07 guarantee applied to the new consumer: purpose=LAB means
    the shared ledger stops it at limit - reserve, structurally."""
    src = open("scripts/fastwatch.py").read()
    assert 'purpose="LAB"' in src
    assert 'purpose="FORWARD"' not in src


def test_fastwatch_observation_carries_the_latency_fields():
    src = open("scripts/fastwatch.py").read()
    for field in ("official_last_seen_at", "elapsed_since_official_tick_s",
                  "last_market_timestamp", "observed_at"):
        assert field in src, f"latency answer needs {field}"


def test_official_pipeline_is_byte_identical_with_fastwatch_present():
    """The decisive independence proof: nothing in the frozen pipeline
    imports or reads FastWatch."""
    from pathlib import Path
    for f in ("apex/hunter/forward_pass.py", "apex/hunter/capital.py",
              "apex/hunter/playbooks_v1.py", "scripts/hunter_forward_clock.py"):
        src = Path(f).read_text()
        assert "fastwatch" not in src.lower(), f"{f} consumes FastWatch"


# ---------------- Mission Control obeys INSTR-01 ---------------------------

def test_mission_control_measures_every_row():
    """Every dynamic row goes through _probe(fn); the only literals are the
    two structural locks whose state IS the literal (paper/credit)."""
    src = open("scripts/mission_control.py").read()
    rows_seg = src.split("def rows()", 1)[1].split("def main", 1)[0]
    import re
    typed_greens = re.findall(r'\(\"[A-Z ()/5]+\", \"(READY|HEALTHY|RUNNING|'
                              r'ARMED|VALID|PASS)', rows_seg)
    assert not typed_greens, f"hardcoded green rows: {typed_greens}"
    assert "_probe(" in rows_seg
    assert rows_seg.count("_probe(") >= 18


def test_mission_control_flags_and_exits_nonzero_on_unmeasured_rows():
    # sys.executable, not a hardcoded .venv path: the suite runs
    # on both the Mac dev host and the cloud canonical host.
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "scripts/mission_control.py"],
                       capture_output=True, text=True, timeout=300)
    # tonight the forward ledger is legitimately absent -> flags -> exit 1;
    # what we pin is the MECHANISM: flags present iff exit nonzero
    flagged = "row(s) flagged" in r.stdout
    assert (r.returncode == 1) == flagged
    # NOT_LOADED joined this set on 2026-08-26: with DigitalOcean
    # canonical and MAC_RUNTIME_AUTHORITY = NONE, an empty Mac
    # launchd roster is the CORRECT reading for a dev console, and
    # mission_control rightly flags it as unmeasured rather than
    # calling an absent scheduler healthy.
    assert ("UNKNOWN" in r.stdout or "ABSENT" in r.stdout
            or "NOT_LOADED" in r.stdout or flagged is False)
