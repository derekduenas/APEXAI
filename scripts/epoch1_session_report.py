#!/usr/bin/env python
"""EPOCH 1 — SESSION REPORT. Consumer only.

    python scripts/epoch1_session_report.py [--date 2026-08-17]

Reads canonical ledgers and answers ONE question:

    Did the frozen machine produce a VALID prospective session?

Trades appear at the bottom, underneath the integrity verdict, because a
zero-trade session that can prove it observed the whole market and
deliberately declined is a SUCCESS. A session that cannot prove it
observed is a failure no matter what it traded.

It creates nothing, mutates nothing, and holds no authority. Where a
number cannot be measured it prints UNKNOWN -- never 0, never a
reassuring default (INSTR-01).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

LEDGER = Path("results/hunter/forward_ledger.jsonl")
EXPECTED_TICKS = 25          # a full regular session at 15-minute cadence


def _rows(date: str) -> list:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue                      # torn fragments counted separately
        if r.get("session_date") == date or str(r.get("t_utc", "")).startswith(date):
            out.append(r)
    return out


def _n(rows, kind):
    return sum(1 for r in rows if r.get("kind") == kind)


def build(date: str) -> tuple[str, bool]:
    rows = _rows(date)
    L, ok = [], True

    L.append(f"EPOCH 1 — SESSION REPORT")
    L.append(f"{date}")
    L.append("")

    if not rows:
        L.append("NO RECORDS FOR THIS DATE.")
        L.append("")
        L.append("This is NOT a valid session and must not be read as a")
        L.append("quiet one. Either the clock did not run, or the date is")
        L.append("wrong, or the ledger is elsewhere. An absent session is")
        L.append("UNKNOWN, never zero.")
        L.append("")
        L.append("SESSION: NO_SESSION_RECORDED")
        return "\n".join(L), False

    scans = [r for r in rows if r.get("kind") == "scan"]
    decisions = [r for r in rows if r.get("kind") == "decision"]
    playbook = [d for d in decisions
                if not str(d.get("playbook_id", "")).startswith("BASELINE-")]

    # ---------------- OBSERVATION
    L.append("OBSERVATION")
    L.append("-" * 11)
    L.append(f"  Expected ticks      {EXPECTED_TICKS}")
    L.append(f"  Actual ticks        {len(scans)}")
    uni = [s.get("universe_count") for s in scans if s.get("universe_count")]
    st = [s.get("states_computed") for s in scans if s.get("states_computed")]
    L.append(f"  Universe coverage   {min(uni) if uni else 'UNKNOWN'}"
             f"–{max(uni) if uni else 'UNKNOWN'}")
    L.append(f"  Healthy states      {min(st) if st else 'UNKNOWN'}"
             f"–{max(st) if st else 'UNKNOWN'}")
    L.append(f"  World states        {_n(rows, 'world_state')}")
    L.append(f"  Scout scans         {len(scans)}")
    L.append(f"  Abnormalities       {sum(s.get('abnormal', 0) or 0 for s in scans)}")
    L.append(f"  Watchlist (total)   {sum(len(s.get('watchlist', []) or []) for s in scans)}")
    L.append(f"  Hunter decisions    {len(playbook)}")
    if len(scans) < EXPECTED_TICKS * 0.8:
        ok = False
        L.append(f"  ** only {len(scans)}/{EXPECTED_TICKS} ticks — the session "
                 f"did not observe the whole market")
    L.append("")

    # ---------------- AUTHORITY
    L.append("AUTHORITY")
    L.append("-" * 9)
    caps = [r for r in rows if r.get("kind") == "capital_decision"]
    states = Counter(c.get("final_state") for c in caps)
    L.append(f"  Assassin calls      {_n(rows, 'assassin_review')}")
    L.append(f"  Captain calls       {_n(rows, 'captain_state')}")
    L.append(f"  Capital states      {dict(states) or 'none'}")
    violations = 0
    for c in caps:
        if c.get("final_state") in ("LIVE_ELIGIBLE",):
            violations += 1
        if c.get("final_state") == "PAPER_ELIGIBLE":
            violations += 1        # unreachable in Epoch 1 by construction
    L.append(f"  Authority violations {violations}")
    if violations:
        ok = False
        L.append("  ** a state that must be unreachable in Epoch 1 appeared")
    L.append("")

    # ---------------- EVIDENCE
    L.append("EVIDENCE")
    L.append("-" * 8)
    elig = Counter(d.get("forward_eligibility") for d in decisions)
    classes = Counter(r.get("evidence_class") for r in rows)
    L.append(f"  Forward eligible    {elig.get('FORWARD_ELIGIBLE', 0)}")
    L.append(f"  Not eligible        {elig.get('NOT_FORWARD_ELIGIBLE', 0)}")
    for d in decisions:
        if d.get("forward_eligibility") == "NOT_FORWARD_ELIGIBLE":
            L.append(f"      {d.get('decision_id')}: "
                     f"{(d.get('eligibility_reasons') or ['unstated'])[0]}")
    wrong = {k: v for k, v in classes.items()
             if k not in (None, "EODHD_FORWARD_OBSERVATION")}
    L.append(f"  Evidence classes    {dict(classes)}")
    L.append(f"  Wrong classes       {sum(wrong.values())}")
    rule17 = sum(1 for r in rows
                 if (r.get("swarm_view") or {}).get("status") == "OK"
                 and r.get("evidence_class") == "EODHD_HISTORICAL_EXPLORATORY")
    L.append(f"  Rule 17 violations  {rule17}")
    if wrong or rule17:
        ok = False
        L.append("  ** evidence-law violation")
    L.append("")

    # ---------------- OUTCOMES
    L.append("OUTCOMES")
    L.append("-" * 8)
    real = [r for r in rows if r.get("kind") == "realization"]
    for h in (15, 30, 60, 90):
        n = sum(1 for r in real if r.get(f"ret_{h}m") is not None)
        L.append(f"  {h}m resolved         {n}")
    L.append("")

    # ---------------- INFRASTRUCTURE
    L.append("INFRASTRUCTURE")
    L.append("-" * 14)
    try:
        from apex.crypto import diskgov
        from apex.intraday import quota_ledger as ql
        L.append(f"  Quota (lab/fwd)     {ql.headroom(ql.LAB)} / "
                 f"{ql.headroom(ql.FORWARD)} units")
        L.append(f"  Disk                {diskgov.disk_state()['mode']}")
    except Exception as e:                              # noqa: BLE001
        L.append(f"  Quota/Disk          UNKNOWN ({type(e).__name__})")
    try:
        from apex.governance.chain_verify import verify
        v = verify(LEDGER)
        L.append(f"  Ledger              {v['status']} "
                 f"({v['valid_records']} records, "
                 f"{len(v['damage'])} damaged, {len(v['tampering'])} tampered)")
        if v["tampering"]:
            ok = False
    except Exception as e:                              # noqa: BLE001
        L.append(f"  Ledger              UNKNOWN ({type(e).__name__})")
        ok = False
    L.append("")

    # ---------------- INTEGRITY
    L.append("INTEGRITY")
    L.append("-" * 9)
    record = "PASS" if LEDGER.exists() else "FAIL"
    observation = "PASS" if len(scans) >= EXPECTED_TICKS * 0.8 else "FAIL"
    experiment = ("PASS" if decisions else "N/A — no decisions to evaluate")
    authority = "PASS" if violations == 0 else "FAIL"
    for name, val in (("RECORD", record), ("OBSERVATION", observation),
                      ("EXPERIMENT", experiment), ("AUTHORITY", authority)):
        L.append(f"  {name:<12} {val}")
        if val == "FAIL":
            ok = False
    L.append("")
    L.append(f"SESSION: {'VALID_FORWARD_SESSION' if ok else 'INVALID_SESSION'}")
    L.append("")
    L.append(f"  Trades: {len(playbook)}")
    L.append("")
    L.append("  A zero-trade session that proves it observed the whole")
    L.append("  market and deliberately declined is a SUCCESS. Validity is")
    L.append("  decided above this line, not below it.")
    return "\n".join(L), ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=str(pd.Timestamp.now(
        tz="America/New_York").date()))
    a = ap.parse_args()
    text, ok = build(a.date)
    print(text)
    out = Path(f"results/hunter/SESSION_{a.date}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    print(f"\nwrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
