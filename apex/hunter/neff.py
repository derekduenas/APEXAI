"""Effective-sample accounting (protocol §8) — N_raw and N_effective are
never reported apart.

Frozen conservative rule: N_effective = number of distinct
(session-day x playbook) cells holding at least one SCORED decision,
further capped by the number of distinct sessions. Ten correlated
candidates on one semiconductor afternoon are one observation of one
market event, not ten independent confirmations — the cap is the point,
not a technicality.
"""

from __future__ import annotations


def effective_sample(decision_records: list) -> dict:
    """decision_records: decision dicts that HAVE a realization (scored).
    Returns global and per-playbook accounting."""
    sessions = {r["session_date"] for r in decision_records}
    cells = {(r["session_date"], r["playbook_id"]) for r in decision_records}
    per: dict = {}
    for r in decision_records:
        p = per.setdefault(r["playbook_id"],
                           {"n_raw": 0, "sessions": set(), "symbols": set()})
        p["n_raw"] += 1
        p["sessions"].add(r["session_date"])
        p["symbols"].add(r["symbol"])
    return {
        "n_raw": len(decision_records),
        # protocol §8 literal: cells, further capped by distinct sessions
        "n_effective": min(len(cells), len(sessions)),
        "n_sessions": len(sessions),
        "per_playbook": {
            pid: {"n_raw": p["n_raw"],
                  "n_effective": len(p["sessions"]),   # cells for one playbook
                  "n_sessions": len(p["sessions"]),
                  "n_symbols": len(p["symbols"])}
            for pid, p in sorted(per.items())}}
