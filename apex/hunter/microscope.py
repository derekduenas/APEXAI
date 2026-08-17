"""The Candidate Microscope — deterministic target selection + record law.

EYES-1 WS4. Binoculars scan the battlefield (the 150-name universe via
EODHD); the microscope examines what they find (Robinhood quote/L2/
context on the serious 1-4 names).

Two structural facts shape this module:

1. THE SELECTOR IS DETERMINISTIC. No LLM chooses who gets L2. Priority is
   a pure function of persisted records, so the same ledger always yields
   the same targets and the choice is auditable forever.

2. EPOCH-1 IMPLEMENTATION: AGENT-SESSION ACTIVITY. The launchd Python
   process holds no OAuth grant — that lives in the Claude Code client —
   so for Epoch 1 an agent session (or probe file) supplies the broker
   data and the archive stamps which transport spoke. A persistent
   autonomous MCP client is a FUTURE architectural option (Robinhood's
   MCP supports third-party MCP-capable platforms) that requires an
   explicitly governed headless-authentication design; it is deliberately
   not being invented hours before the experiment.

Everything here is decision_power = NONE_OBSERVATIONAL_EPOCH1. L2 cannot
alter an Epoch-1 decision; it exists to be studied prospectively.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

OBSERVATIONAL = "NONE_OBSERVATIONAL_EPOCH1"
MAX_L2_TARGETS = 4          # platform bound: real-time books for <=4 names
MAX_QUOTE_TARGETS = 20      # platform bound: real-time quotes for <=20

LEDGER = Path("results/hunter/microscope_ledger.jsonl")


@dataclass(frozen=True)
class MicroscopeTarget:
    symbol: str
    priority: int                     # 1 = highest
    reason_selected: str
    wants_l2: bool

    def as_record(self) -> dict:
        return asdict(self)


def select_targets(*, decisions: list, scans: list,
                   board: dict | None = None) -> tuple:
    """Deterministic priority: (1) actual Hunter candidates, newest first;
    (2) strongest watchlist near-candidates by signal count then RVOL;
    (3) Opportunity Board rank; ties broken lexicographically by symbol.

    Returns at most MAX_QUOTE_TARGETS targets, of which the first
    MAX_L2_TARGETS carry wants_l2=True.
    """
    ranked: list = []
    seen: set = set()

    # 1. real Hunter candidates (never baselines), newest decision first
    playbook = [d for d in decisions
                if not str(d.get("playbook_id", "")).startswith("BASELINE-")]
    for d in sorted(playbook, key=lambda d: (str(d.get("t_utc", "")),
                                             d.get("symbol", "")),
                    reverse=True):
        s = d.get("symbol")
        if s and s not in seen:
            seen.add(s)
            ranked.append((s, f"hunter_candidate:{d.get('decision_id')}"))

    # 2. watchlist near-candidates: most signals, then rvol, then name
    wl: dict = {}
    for scan in scans:
        for entry in scan.get("watchlist") or []:
            try:
                sym, sigs, rvol = entry[0], entry[1], entry[2]
            except (IndexError, TypeError):
                continue
            n = len(sigs) if isinstance(sigs, (list, tuple)) else 0
            r = float(rvol) if isinstance(rvol, (int, float)) else 0.0
            cur = wl.get(sym)
            if cur is None or (n, r) > cur:
                wl[sym] = (n, r)
    for sym, (n, r) in sorted(wl.items(),
                              key=lambda kv: (-kv[1][0], -kv[1][1], kv[0])):
        if sym not in seen:
            seen.add(sym)
            ranked.append((sym, f"watchlist:signals={n},rvol={r:.2f}"))

    # 3. opportunity board order, as persisted
    for row in (board or {}).get("ranked", []):
        sym = row.get("symbol") if isinstance(row, dict) else None
        if sym and sym not in seen:
            seen.add(sym)
            ranked.append((sym, "opportunity_board"))

    out = []
    for i, (sym, why) in enumerate(ranked[:MAX_QUOTE_TARGETS]):
        out.append(MicroscopeTarget(symbol=sym, priority=i + 1,
                                    reason_selected=why,
                                    wants_l2=i < MAX_L2_TARGETS))
    return tuple(out)


def record_request(target: MicroscopeTarget, *, request_time: str,
                   transport: str) -> dict:
    return {"kind": "microscope_request", **target.as_record(),
            "request_time": request_time, "transport": transport,
            "decision_power": OBSERVATIONAL}


def record_result(target: MicroscopeTarget, *, request_time: str,
                  response_time: str, transport: str,
                  quote: dict | None = None, l2: dict | None = None,
                  context: dict | None = None,
                  status: str = "OK") -> dict:
    """The persisted enrichment. Absence rules (LAB-04 / INSTR-01):
    a missing book is UNKNOWN, never a zero-imbalance book; a missing
    quote is UNKNOWN, never last=0."""
    if l2 is not None and "imbalance" in l2 and l2["imbalance"] is None:
        l2 = {**l2, "imbalance": "UNKNOWN_NOT_ZERO"}
    return {"kind": "microscope_result", **target.as_record(),
            "request_time": request_time, "response_time": response_time,
            "transport": transport, "status": status,
            "quote": quote if quote is not None else {"status": "UNKNOWN"},
            "l2": l2 if l2 is not None else {"status": "UNKNOWN"},
            "context": context or {"status": "NOT_REQUESTED"},
            "decision_power": OBSERVATIONAL}
