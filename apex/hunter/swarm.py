"""Research Swarm integration — the desk's research department, not its
trigger finger.

The deterministic Hunter is the FAST PATH: it never waits on an LLM, and
the market-state archive can never be blocked by one. The Swarm is an
OPTIONAL ENRICHMENT path over SERIOUS candidates only, returning a
structured SwarmAssessment (claims with provenance, disagreements,
adversarial flags) — never freeform narrative into Capital, never a vote,
never a stop change, never an execution instruction (the trade manager
rejects LLM-attributed mutations; broker stays sealed).

COMMISSIONED 2026-08-15 after operator CLI login (subscription auth, not
API billing — the operator's economics ruling). Transport: one `claude -p`
subprocess PER AGENT (role separation: no shared context, no prompt
overlap), cwd=/tmp (no repo context loaded), hard per-agent timeout,
strict JSON contract parsed defensively — unparseable output is a FAILED
status with zero claims, never a partial hallucination. Agents receive
ONLY structured candidate facts from our own ledger-bound state; every
claim must name its basis from those facts. LLM output is DATA: it can
raise adversarial flags (conservative-only downstream) and can never
touch a number, a stop, a size, or a status. Earlier forecasts are NEVER
retroactively enriched — assessments count prospectively from the swarm
producer's birth. V1 runs the two specialists that can reason from
quantitative context alone; the catalyst/fundamental chairs stay DORMANT
until timestamped event data exists.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from apex.hunter.forecast import SwarmAssessment

SWARM_VERSION = "hunter_swarm_producer_v1"
AUTH_MARKER = Path("ops/swarm_auth_ok")          # operator-managed marker
CLAUDE_BIN = Path.home() / ".local/bin/claude"

SPECIALISTS = ("CATALYST_ANALYST", "MARKET_STATE_ANALYST",
               "TECHNICAL_STRUCTURE_ANALYST", "FUNDAMENTAL_EVENT_ANALYST",
               "HISTORICAL_ANALOGUE_ANALYST", "QUANT_ANALYST",
               "ADVERSARIAL_TRADER", "RISK_ANALYST",
               "IMPLEMENTATION_ANALYST")
V1_ACTIVE_AGENTS = ("MARKET_STATE_ANALYST", "ADVERSARIAL_TRADER")

DEADLINE_SECONDS = 240                # total candidate budget for swarm
AGENT_TIMEOUT_SECONDS = 90

_PROMPT = """You are the {role} on the research desk of a systematic
trading system. You receive ONLY the structured facts below about one
intraday candidate. Do not assume any information beyond these facts.

FACTS:
{facts}

Task for MARKET_STATE_ANALYST: is there market/sector context in these
facts that weakens or strengthens the setup's stated mechanism?
Task for ADVERSARIAL_TRADER: you are on the other side of this trade.
What could make this setup deceptive? What is the strongest reason it
fails?

Respond with ONLY a JSON object, no other text:
{{"claims": [{{"claim": "<one sentence>", "basis": "<which fact>"}}],
  "adversarial_flags": ["<flag>", ...],
  "unresolved_questions": ["<question>", ...]}}
Empty lists are acceptable and often correct."""


def auth_available() -> bool:
    return AUTH_MARKER.exists()


def _candidate_facts(candidate: dict) -> str:
    keep = {k: candidate.get(k) for k in
            ("symbol", "playbook_id", "direction", "matched", "risk_frac")}
    ms = candidate.get("market_state") or {}
    keep["market"] = {k: ms.get(k) for k in
                      ("day_return", "realized_vol_ann", "above_vwap")}
    rs = candidate.get("relative_strength") or {}
    keep["relative_strength"] = {k: rs.get(k) for k in
                                 ("excess_market_60m", "excess_sector_60m",
                                  "cross_sectional_pct")}
    return json.dumps(keep, default=str)


def _invoke_agent(role: str, facts: str,
                  runner=None) -> tuple:
    """-> (claims, flags, questions) or raises. Output parsed defensively:
    anything but the exact contract is a failure, never a partial."""
    prompt = _PROMPT.format(role=role, facts=facts)
    if runner is None:
        def runner(p):
            r = subprocess.run([str(CLAUDE_BIN), "-p", p],
                               capture_output=True, text=True, cwd="/tmp",
                               timeout=AGENT_TIMEOUT_SECONDS)
            if r.returncode != 0:
                raise RuntimeError(f"claude exit {r.returncode}")
            return r.stdout
    raw = runner(prompt).strip()
    if raw.startswith("```"):
        raw = raw.strip("`\n")
        raw = raw[raw.find("{"):]
    obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    claims = tuple((role, str(c.get("claim", ""))[:300],
                    str(c.get("basis", ""))[:200])
                   for c in obj.get("claims", []) if isinstance(c, dict))
    flags = tuple(f"{role}: {str(f)[:200]}"
                  for f in obj.get("adversarial_flags", []))
    questions = tuple(f"{role}: {str(q)[:200]}"
                      for q in obj.get("unresolved_questions", []))
    return claims, flags, questions


def run_specialists(candidate: dict, *, as_of: str,
                    deadline_seconds: float = DEADLINE_SECONDS,
                    runner=None) -> SwarmAssessment:
    """Enrichment only. Non-OK statuses carry NO claims (contract-enforced:
    SwarmAssessment refuses claims on a non-OK status). `runner` is
    injectable for tests; production uses the real CLI."""
    cid = candidate.get("decision_id", "?")
    if not auth_available():
        return SwarmAssessment(candidate_id=cid, as_of=as_of,
                               status="BLOCKED_EXTERNAL_AUTH",
                               provenance={"iface": SWARM_VERSION,
                                           "marker": str(AUTH_MARKER)})
    # HERMETIC-TEST FIREWALL: a pytest process may never spawn a live LLM
    # (cost, nondeterminism, and 90s hangs inside a test suite). Tests
    # exercise the transport through an injected runner only.
    import os
    if runner is None and "PYTEST_CURRENT_TEST" in os.environ:
        return SwarmAssessment(
            candidate_id=cid, as_of=as_of, status="NOT_REQUESTED",
            provenance={"iface": SWARM_VERSION,
                        "reason": "live LLM calls forbidden in tests"})
    start = time.monotonic()
    facts = _candidate_facts(candidate)
    claims: list = []
    flags: list = []
    questions: list = []
    ran: list = []
    for role in V1_ACTIVE_AGENTS:
        if time.monotonic() - start > deadline_seconds:
            return SwarmAssessment(
                candidate_id=cid, as_of=as_of,
                status="NOT_AVAILABLE_IN_TIME",
                latency_seconds=round(time.monotonic() - start, 1),
                provenance={"iface": SWARM_VERSION, "agents_done": ran})
        try:
            c, f, q = _invoke_agent(role, facts, runner=runner)
            claims.extend(c); flags.extend(f); questions.extend(q)
            ran.append(role)
        except Exception as e:                              # noqa: BLE001
            return SwarmAssessment(
                candidate_id=cid, as_of=as_of, status="FAILED",
                latency_seconds=round(time.monotonic() - start, 1),
                provenance={"iface": SWARM_VERSION,
                            "failed_agent": role,
                            "error": type(e).__name__})
    return SwarmAssessment(
        candidate_id=cid, as_of=as_of, status="OK",
        agents_run=tuple(ran), claims=tuple(claims),
        adversarial_flags=tuple(flags),
        unresolved_questions=tuple(questions),
        latency_seconds=round(time.monotonic() - start, 1),
        provenance={"iface": SWARM_VERSION,
                    "dormant_agents": tuple(s for s in SPECIALISTS
                                            if s not in V1_ACTIVE_AGENTS)})
