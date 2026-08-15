"""Research Swarm producer v2 — the charter's trade moment, in code.

The desk's job (docs/SWARM-CHARTER.md): not "which stocks should we buy"
but "here is everything APEX knows at T — attack the thesis." Four live
seats, each with its OWN prompt (role separation; only the Synthesis seat
sees other agents' outputs, because synthesis IS its job):

  THESIS_ANALYST        the strongest coherent mechanism, not a direction
  MARKET_CONTEXT_ANALYST  interpretation of the Twin's facts in interaction
  ADVERSARIAL_TRADER    the #1 seat: why should APEX NOT take this trade?
                        structured leveled flags + PRIMARY_OBJECTION +
                        VERDICT (NO_MATERIAL_OBJECTION|MATERIAL_OBJECTION)
  SYNTHESIS_ANALYST     names unresolved contradictions across the views

CATALYST/FUNDAMENTAL seats stay DORMANT until timestamped event data.
DISCOVERY and REVIEW moments (charter) are separate future producers
behind their own context walls and births.

Transport: one `claude -p` subprocess PER seat, cwd=/tmp, 90s/agent
timeout, strict JSON parsed defensively (garbage = FAILED, zero claims).
Agents receive ONLY structured candidate facts; every claim names its
basis. Forbidden by charter and by construction: chart math, TP/SL
numbers, sizing, authorization. A MATERIAL_OBJECTION verdict flows into
disagreement and can only ADD caution downstream. If the per-candidate
deadline hits mid-desk, the completed seats stand and the skipped ones
are named — partial honesty over wholesale loss. Hermetic-test firewall:
pytest can never spawn a live LLM (injected runners only). Prospective
from the producer's birth; no retroactive enrichment, ever.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from apex.hunter.forecast import SwarmAssessment

SWARM_VERSION = "hunter_swarm_producer_v3"
AUTH_MARKER = Path("ops/swarm_auth_ok")          # operator-managed marker
CLAUDE_BIN = Path.home() / ".local/bin/claude"

SPECIALISTS = ("CATALYST_ANALYST", "MARKET_CONTEXT_ANALYST",
               "TECHNICAL_STRUCTURE_ANALYST", "FUNDAMENTAL_EVENT_ANALYST",
               "HISTORICAL_ANALOGUE_ANALYST", "THESIS_ANALYST",
               "ADVERSARIAL_TRADER", "RISK_ANALYST",
               "IMPLEMENTATION_ANALYST", "SYNTHESIS_ANALYST")
# TIERED SCHEDULING (charter refinement): Tier 1 is the ASSASSIN — the
# fastest credible reason this trade is deceptive. A MATERIAL_OBJECTION
# ends the desk right there (kill cheaply; the objection already carries
# maximum caution downstream). Only survivors get the investment
# committee. Claude is a scarce reasoning resource spent in proportion
# to how interested APEX is.
TIER1_AGENTS = ("ADVERSARIAL_TRADER", "MARKET_CONTEXT_ANALYST")
TIER2_AGENTS = ("THESIS_ANALYST", "SYNTHESIS_ANALYST")
V2_ACTIVE_AGENTS = TIER1_AGENTS + TIER2_AGENTS      # full desk, in tier order

TIER1_DEADLINE_SECONDS = 120          # the assassin must be fast
DEADLINE_SECONDS = 300                # total per-candidate desk budget
AGENT_TIMEOUT_SECONDS = 90

VERDICTS = ("NO_MATERIAL_OBJECTION", "MATERIAL_OBJECTION")
ADVERSARY_FLAG_AXES = ("CHASE_RISK", "SECTOR_CONFIRMATION",
                       "MARKET_SUPPORT", "EXTENSION_RISK")

_HEADER = """You are the {role} on the research desk of a systematic
trading system. You receive ONLY the structured facts below about one
intraday candidate the quantitative system has already selected. Do not
assume any information beyond these facts. You do not pick stocks, set
stops, size positions, or authorize trades. Time matters on a trading
desk: think hard but answer tersely — every sentence tight, nothing
beyond the requested JSON.

FACTS:
{facts}
"""

_CONTRACT = """Respond with ONLY a JSON object, no other text:
{{"claims": [{{"claim": "<one sentence>", "basis": "<which fact>"}}],
  "adversarial_flags": ["<flag>", ...],
  "unresolved_questions": ["<question>", ...]}}
Empty lists are acceptable and often correct."""

ROLE_PROMPTS = {
    "THESIS_ANALYST": _HEADER + """
Your task: state the strongest COHERENT MECHANISM for why this setup
should continue (or revert) — price discovery, information repricing,
flow completion, etc. Not "bullish/bearish": the mechanism, and which
facts support or undercut it.
""" + _CONTRACT,
    "MARKET_CONTEXT_ANALYST": _HEADER + """
Your task: interpret what these facts mean IN INTERACTION — market vs
sector vs symbol, participation vs displacement, what the combination
implies that no single number shows. Flag context that weakens the setup.
""" + _CONTRACT,
    "ADVERSARIAL_TRADER": _HEADER + """
Your task: you are on the OTHER SIDE of this trade. Actively try to kill
it. Is it late/chased? Is sector confirmation actually weak? Could this
be short covering or index masking? Is the extension already spent? What
single fragile assumption does the thesis depend on?

Respond with ONLY a JSON object, no other text:
{{"flags": {{"CHASE_RISK": "HIGH|MODERATE|LOW",
            "SECTOR_CONFIRMATION": "HIGH|MODERATE|LOW",
            "MARKET_SUPPORT": "HIGH|MODERATE|LOW",
            "EXTENSION_RISK": "HIGH|MODERATE|LOW"}},
  "primary_objection": "<one sentence, or empty string>",
  "verdict": "MATERIAL_OBJECTION" or "NO_MATERIAL_OBJECTION",
  "claims": [{{"claim": "<one sentence>", "basis": "<which fact>"}}]}}""",
    "SYNTHESIS_ANALYST": _HEADER + """
The other desk seats produced the following views:
{prior_views}

Your task: you are NOT a voter. Name the important CONTRADICTIONS that
remain unresolved across these views and the facts, and give a one-line
synthesis (e.g. "directional thesis stronger than entry thesis").

Respond with ONLY a JSON object, no other text:
{{"contradictions": ["<one sentence>", ...],
  "synthesis": "<one line>",
  "claims": [{{"claim": "<one sentence>", "basis": "<which view/fact>"}}]}}""",
}


_CLI_IDENTITY: list = []


def _cli_identity() -> str:
    """CLI version string, probed once per process (telemetry only)."""
    if not _CLI_IDENTITY:
        try:
            r = subprocess.run([str(CLAUDE_BIN), "--version"],
                               capture_output=True, text=True, timeout=10)
            _CLI_IDENTITY.append(r.stdout.strip()[:60] or "unknown")
        except Exception:                                   # noqa: BLE001
            _CLI_IDENTITY.append("unknown")
    return _CLI_IDENTITY[0]


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
    cs = candidate.get("chart_state") or {}
    keep["chart"] = {k: cs.get(k) for k in
                     ("rvol_tod", "position_in_or", "distance_to_vwap",
                      "range_vs_atr", "minutes_into_session")}
    return json.dumps(keep, default=str)


def _run_cli(prompt: str) -> str:
    r = subprocess.run([str(CLAUDE_BIN), "-p", prompt],
                       capture_output=True, text=True, cwd="/tmp",
                       timeout=AGENT_TIMEOUT_SECONDS)
    if r.returncode != 0:
        raise RuntimeError(f"claude exit {r.returncode}")
    return r.stdout


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`\n")
    obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    if not isinstance(obj, dict):
        raise ValueError("non-object response")
    return obj


def _std_views(role: str, obj: dict) -> tuple:
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
                    allow_deep: bool = True,
                    runner=None) -> SwarmAssessment:
    """The trade-moment desk. Non-OK statuses carry NO claims
    (contract-enforced). `runner` is injectable for tests; production
    uses the real CLI. If the deadline hits mid-desk, completed seats
    stand and skipped seats are named."""
    cid = candidate.get("decision_id", "?")
    if not auth_available():
        return SwarmAssessment(candidate_id=cid, as_of=as_of,
                               status="BLOCKED_EXTERNAL_AUTH",
                               provenance={"iface": SWARM_VERSION,
                                           "marker": str(AUTH_MARKER)})
    # HERMETIC-TEST FIREWALL: a pytest process may never spawn a live LLM
    import os
    if runner is None and "PYTEST_CURRENT_TEST" in os.environ:
        return SwarmAssessment(
            candidate_id=cid, as_of=as_of, status="NOT_REQUESTED",
            provenance={"iface": SWARM_VERSION,
                        "reason": "live LLM calls forbidden in tests"})
    call = runner or _run_cli
    start = time.monotonic()
    facts = _candidate_facts(candidate)
    claims: list = []
    flags: list = []
    questions: list = []
    disagreements: list = []
    ran: list = []
    skipped: list = []
    agent_ms: dict = {}
    verdict = None
    adversary_axes_out: dict = {}
    prior_views: list = []

    tier_completed = "NONE"
    fast_kill = False
    for role in V2_ACTIVE_AGENTS:
        # tier gate: the committee convenes only if the assassin failed
        if role in TIER2_AGENTS:
            if fast_kill or not allow_deep:
                skipped = [r for r in TIER2_AGENTS if r not in ran]
                break
            if time.monotonic() - start > deadline_seconds:
                skipped = [r for r in TIER2_AGENTS if r not in ran]
                break
        elif time.monotonic() - start > TIER1_DEADLINE_SECONDS and ran:
            skipped = [r for r in V2_ACTIVE_AGENTS if r not in ran]
            break
        prompt = (ROLE_PROMPTS[role].format(
            role=role, facts=facts,
            prior_views=json.dumps(prior_views, default=str))
            if role == "SYNTHESIS_ANALYST"
            else ROLE_PROMPTS[role].format(role=role, facts=facts))
        try:
            a0 = time.monotonic()
            obj = _parse_json(call(prompt))
            agent_ms[role] = round((time.monotonic() - a0) * 1000)
        except Exception as e:                              # noqa: BLE001
            return SwarmAssessment(
                candidate_id=cid, as_of=as_of, status="FAILED",
                latency_seconds=round(time.monotonic() - start, 1),
                provenance={"iface": SWARM_VERSION, "failed_agent": role,
                            "error": type(e).__name__})
        if role == "ADVERSARIAL_TRADER":
            v = str(obj.get("verdict", "")).upper()
            verdict = v if v in VERDICTS else None
            adversary_axes = {}
            for axis in ADVERSARY_FLAG_AXES:
                level = str((obj.get("flags") or {}).get(axis, "")).upper()[:12]
                if level:
                    adversary_axes[axis] = level
                # only a HIGH risk axis is an adversarial SIGNAL; a LOW
                # level is reassurance and must not trigger caution.
                # (SECTOR_CONFIRMATION/MARKET_SUPPORT invert: LOW is bad.)
                bad = (level == "LOW" if axis in ("SECTOR_CONFIRMATION",
                                                 "MARKET_SUPPORT")
                       else level == "HIGH")
                if bad:
                    flags.append(f"ADVERSARIAL_TRADER: {axis}={level}")
            adversary_axes_out = adversary_axes
            prior_views.append({"role": role, "axes": adversary_axes})
            po = str(obj.get("primary_objection", ""))[:300]
            if po:
                claims.append(("ADVERSARIAL_TRADER",
                               f"PRIMARY_OBJECTION: {po}", "desk"))
            c, f, q = _std_views(role, obj)
            claims.extend(c); flags.extend(f); questions.extend(q)
            prior_views[-1].update({"verdict": verdict,
                                    "primary_objection": po})
            if verdict == "MATERIAL_OBJECTION":
                fast_kill = True          # the assassin ends the desk
        elif role == "SYNTHESIS_ANALYST":
            for x in obj.get("contradictions", []):
                disagreements.append(f"SYNTHESIS: {str(x)[:250]}")
            syn = str(obj.get("synthesis", ""))[:250]
            if syn:
                claims.append(("SYNTHESIS_ANALYST", syn, "desk views"))
            c, f, q = _std_views(role, obj)
            claims.extend(c); flags.extend(f); questions.extend(q)
        else:
            c, f, q = _std_views(role, obj)
            claims.extend(c); flags.extend(f); questions.extend(q)
            prior_views.append({"role": role,
                                "claims": [x[1] for x in c][:4]})
        ran.append(role)
        tier_completed = ("TIER1" if all(r in ran for r in TIER1_AGENTS)
                          and not all(r in ran for r in TIER2_AGENTS)
                          else ("FULL_DESK" if all(r in ran
                                for r in V2_ACTIVE_AGENTS) else "PARTIAL"))

    if not ran:
        return SwarmAssessment(
            candidate_id=cid, as_of=as_of, status="NOT_AVAILABLE_IN_TIME",
            latency_seconds=round(time.monotonic() - start, 1),
            provenance={"iface": SWARM_VERSION, "skipped": skipped})
    # the charter's conservative-only law: MATERIAL_OBJECTION must be
    # visible to disagreement even if no other flag was raised
    if verdict == "MATERIAL_OBJECTION" and not any(
            "MATERIAL" in f for f in flags):
        flags.append("ADVERSARIAL_TRADER: MATERIAL_OBJECTION")
    return SwarmAssessment(
        candidate_id=cid, as_of=as_of, status="OK",
        agents_run=tuple(ran), claims=tuple(claims),
        adversarial_flags=tuple(flags),
        disagreements=tuple(disagreements),
        unresolved_questions=tuple(questions),
        latency_seconds=round(time.monotonic() - start, 1),
        provenance={"iface": SWARM_VERSION,
                    "facts_supplied": facts, "agent_ms": agent_ms,
                    "cli": _cli_identity(),
                    "adversary_verdict": verdict,
                    "adversary_axes": adversary_axes_out,
                    "tier_completed": tier_completed,
                    "fast_kill": fast_kill,
                    "deep_allowed_by_routing": allow_deep,
                    "agents_skipped": tuple(skipped),
                    "dormant_agents": tuple(s for s in SPECIALISTS
                                            if s not in V2_ACTIVE_AGENTS)})
