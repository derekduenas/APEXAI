"""Research Swarm integration — the desk's research department, not its
trigger finger.

The deterministic Hunter is the FAST PATH: it never waits on an LLM, and
the market-state archive can never be blocked by one. The Swarm is an
OPTIONAL ENRICHMENT path over SERIOUS candidates only, returning a
structured SwarmAssessment (claims with provenance, disagreements,
adversarial flags) — never freeform narrative into Capital, never a vote,
never a stop change, never an execution instruction (the trade manager
rejects LLM-attributed mutations; broker stays sealed).

AUTH REALITY: the Claude CLI is not authenticated headlessly on this
machine (standing operator act). Status is read from an explicit marker
file the operator updates after `/login` — probing with live LLM calls
from the clock would be slow, flaky, and a lie waiting to happen. Until
the marker says otherwise: BLOCKED_EXTERNAL_AUTH, with zero fabricated
responses. If auth arrives, run_specialists gains a real transport;
earlier forecasts are NEVER retroactively enriched.
"""

from __future__ import annotations

import time
from pathlib import Path

from apex.hunter.forecast import SwarmAssessment

SWARM_VERSION = "hunter_swarm_iface_v1"
AUTH_MARKER = Path("ops/swarm_auth_ok")          # operator-managed marker

SPECIALISTS = ("CATALYST_ANALYST", "MARKET_STATE_ANALYST",
               "TECHNICAL_STRUCTURE_ANALYST", "FUNDAMENTAL_EVENT_ANALYST",
               "HISTORICAL_ANALOGUE_ANALYST", "QUANT_ANALYST",
               "ADVERSARIAL_TRADER", "RISK_ANALYST",
               "IMPLEMENTATION_ANALYST")

DEADLINE_SECONDS = 120                # candidate decision deadline for swarm


def auth_available() -> bool:
    return AUTH_MARKER.exists()


def run_specialists(candidate: dict, *, as_of: str,
                    deadline_seconds: float = DEADLINE_SECONDS) -> SwarmAssessment:
    """Enrichment only. Non-OK statuses carry NO claims (contract-enforced:
    SwarmAssessment refuses claims on a non-OK status)."""
    cid = candidate.get("decision_id", "?")
    if not auth_available():
        return SwarmAssessment(candidate_id=cid, as_of=as_of,
                               status="BLOCKED_EXTERNAL_AUTH",
                               provenance={"iface": SWARM_VERSION,
                                           "marker": str(AUTH_MARKER)})
    # transport commissioned only after auth exists; until an integration
    # smoke has run under real auth, a present marker still yields a typed
    # non-answer rather than an untested call path
    start = time.monotonic()
    elapsed = time.monotonic() - start
    return SwarmAssessment(candidate_id=cid, as_of=as_of,
                           status="NOT_AVAILABLE_IN_TIME"
                           if elapsed > deadline_seconds else "NOT_REQUESTED",
                           latency_seconds=round(elapsed, 3),
                           provenance={"iface": SWARM_VERSION,
                                       "note": ("auth marker present but "
                                                "transport not smoke-tested; "
                                                "refusing untested path")})
