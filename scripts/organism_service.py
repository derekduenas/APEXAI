"""ORGANISM SERVICE — the allocator loop, plus health and the CIO tick.

Consumes the three sleeve streams through durable cursors, allocates
paper capital through arena + kernel, attaches outcomes as sleeve
resolutions appear, rebuilds the experience graph, and seals a CIO
directive at the close.

Startup is a RECONCILIATION, not a fresh start: the book ledger is the
state, cursors resume where they committed, and funding is idempotent
on candidate_id -- so a crash or restart can duplicate nothing.

decision_power: PAPER_ALLOCATION_ONLY. No real order surface.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.ops.heartbeat import Heartbeat  # noqa: E402
from apex.ops.orchestrator import session_bounds  # noqa: E402
from apex.ops.outbox import Cursor, consume  # noqa: E402
from apex.ops.timebase import ET  # noqa: E402
from apex.organism import allocator, book, cio, experience  # noqa: E402
from apex.organism import health as org_health  # noqa: E402

SERVICE = "organism"
CURSORS = {"options": Path("results/organism/cursor_options.json"),
           "equity": Path("results/organism/cursor_equity.json")}
BTC_SEEN = Path("results/organism/btc_seen.json")
POLL_S = 60


def release_sha() -> str:
    try:
        return json.loads(Path("/opt/apex/current/RELEASE.json")
                          .read_text()).get("commit", "UNKNOWN")
    except (OSError, json.JSONDecodeError):
        return "UNKNOWN"


def _session() -> str:
    return datetime.now(timezone.utc).astimezone(ET).strftime("%Y-%m-%d")


def drain_new_candidates() -> list:
    """New attack records only, via durable cursors (options/equity)
    and a seen-set for the BTC ledger (which is not an ops outbox)."""
    from apex.organism.candidate import (BTC_ATTACK_COHORTS,
                                         CandidateViolation,
                                         from_btc, from_equity,
                                         from_options)
    envs = []

    def opt_handler(rec):
        p = rec.get("payload") or {}
        if rec.get("record_kind") == "options_evaluation" \
                and p.get("verdict") == "PAPER_ATTACKED":
            try:
                envs.append(from_options(rec))
            except CandidateViolation:
                pass                      # adapter errors surface in
        return 0                          # the allocation run record

    def eq_handler(rec):
        p = rec.get("payload") or {}
        if rec.get("record_kind") == "equity_shadow_decision" \
                and p.get("decision") == "ATTACK_READY_SHADOW":
            try:
                envs.append(from_equity(rec))
            except CandidateViolation:
                pass
        return 0

    ob = allocator.V1_OUTBOX
    if ob.exists():
        consume(ob, Cursor(CURSORS["options"], "organism_options"),
                opt_handler)
    eq = allocator.EQUITY_OUTBOX
    if eq.exists():
        consume(eq, Cursor(CURSORS["equity"], "organism_equity"),
                eq_handler)

    seen = set()
    if BTC_SEEN.exists():
        try:
            seen = set(json.loads(BTC_SEEN.read_text()))
        except (OSError, json.JSONDecodeError):
            seen = set()
    if allocator.BTC_LEDGER.exists():
        for line in allocator.BTC_LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "btc_paper_decision" \
                    and rec.get("cohort") in BTC_ATTACK_COHORTS \
                    and str(rec.get("T")) not in seen:
                seen.add(str(rec.get("T")))
                try:
                    envs.append(from_btc(rec))
                except CandidateViolation:
                    pass
        BTC_SEEN.parent.mkdir(parents=True, exist_ok=True)
        BTC_SEEN.write_text(json.dumps(sorted(seen)))
    return envs


def attach_new_outcomes(session: str) -> int:
    """Join sleeve resolution artifacts onto funded positions.

    Reuses each sleeve's own resolution stream -- the organism does not
    re-execute anything; it accounts for what the specialist resolved.
    """
    st = book.state(session=session)
    open_ids = {p["candidate_id"]: p for p in st["positions"]}
    if not open_ids:
        return 0
    attached = 0

    eq_out = Path("results/equities/shadow_outcomes.jsonl")
    if eq_out.exists():
        for line in eq_out.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = r.get("decision_id")
            if cid in open_ids and r.get("resolvable"):
                book.attach_outcome(
                    candidate_id=cid, session=session,
                    executable_pnl=r.get("executable_pnl"),
                    outcome_class=("NO_REAL_FAILURE"
                                   if isinstance(r.get("executable_pnl"),
                                                 (int, float))
                                   and r["executable_pnl"] > 0
                                   else "THESIS_FAILURE"),
                    detail={"exit_reason": r.get("exit_reason"),
                            "R": r.get("R"),
                            "source": "equity_shadow_outcome"})
                attached += 1
                open_ids.pop(cid)
    return attached


def tick(beat=None) -> dict:
    session = _session()
    envs = drain_new_candidates()
    out = {"session": session, "new_candidates": len(envs),
           "funded_or_refused": 0, "outcomes_attached": 0}
    if envs:
        run = allocator.allocate(envs, session=session,
                                 release_sha=release_sha())
        out["funded_or_refused"] = len(run["results"])
        out["fail_closed"] = run.get("fail_closed", False)
    out["outcomes_attached"] = attach_new_outcomes(session)
    if beat is not None and (envs or out["outcomes_attached"]):
        beat.work(f"candidates={len(envs)} "
                  f"outcomes={out['outcomes_attached']}")
    elif beat is not None:
        beat.beat()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--book", action="store_true")
    ap.add_argument("--directive", action="store_true")
    ap.add_argument("--rebuild-graph", action="store_true")
    ap.add_argument("--follow", action="store_true")
    a = ap.parse_args()

    if a.health:
        print(json.dumps(org_health.organism_health(), indent=1))
        return 0
    if a.book:
        print(json.dumps(book.state(session=_session()), indent=1))
        return 0
    if a.directive:
        print(json.dumps(cio.daily_directive(session=_session()),
                         indent=1))
        return 0
    if a.rebuild_graph:
        print(json.dumps(experience.rebuild(), indent=1))
        return 0
    if a.once or not a.follow:
        print(json.dumps(tick(), indent=1))
        return 0

    beat = Heartbeat(SERVICE)
    last_directive_session = None
    while True:
        try:
            tick(beat)
            session = _session()
            b = session_bounds(session)
            now = datetime.now(timezone.utc)
            if (b["trading_day"] and b["close_utc"]
                    and now > b["close_utc"]
                    and last_directive_session != session):
                experience.rebuild()
                cio.daily_directive(session=session)
                last_directive_session = session
                beat.work(f"CIO directive sealed for {session}")
        except Exception as e:                          # noqa: BLE001
            beat.error(f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
