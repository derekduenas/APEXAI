"""THE CLAUDE CIO — judgment, never authority.

    Math has authority. Claude has judgment.

The CIO receives the desk's STRUCTURED state (kernel directive +
conviction + the specialists' recorded views) and returns synthesis:
what coheres, what contradicts, what is missing, and what research
question is worth asking next. It is advisory in the strictest sense —
`advisory_only: True` on every record, and `apply_to_kernel()` proves by
construction that no CIO field can alter a kernel directive.

FORBIDDEN to the CIO (same list as the Swarm, plus the Captain's own):
no prices, no stops, no sizes, no authorizations, no state transitions,
no overriding a veto, no changing an intelligence-spend directive into
a larger one. Its ceiling is a sentence and a question.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CIO_VERSION = "apex_claude_cio_v1"
DEADLINE_S = 90

_PROMPT = """You are the CIO of a systematic trading desk, reviewing ONE
opportunity. The deterministic kernel has already ruled on process; you
cannot change it. You do not set prices, stops, sizes, or
authorizations. Your job is judgment: coherence, contradiction, and the
next useful question.

DESK STATE (the only facts you have):
{state}

Respond with ONLY a JSON object, no other text:
{{"synthesis": "<one sentence: what this opportunity actually is>",
  "contradictions": ["<unresolved conflict between desk views>", ...],
  "missing_information": ["<what would most change the assessment>", ...],
  "next_research_question": "<the single most valuable question>",
  "deep_research_worthwhile": true or false,
  "concerns": ["<risk the numbers may not capture>", ...]}}
Empty lists are acceptable and often correct."""


@dataclass(frozen=True)
class CIOAdvice:
    decision_id: str
    status: str                      # OK | BLOCKED_EXTERNAL_AUTH | FAILED
    synthesis: str = ""
    contradictions: tuple = ()
    missing_information: tuple = ()
    next_research_question: str = ""
    deep_research_worthwhile: bool | None = None
    concerns: tuple = ()
    latency_s: float | None = None
    advisory_only: bool = True
    can_authorize: bool = False
    can_size: bool = False
    can_move_stops: bool = False
    version: str = field(default=CIO_VERSION)

    def __post_init__(self):
        if not self.advisory_only or self.can_authorize or self.can_size \
                or self.can_move_stops:
            raise ValueError("CONSTITUTIONAL: the CIO is advisory only")
        if self.status != "OK" and (self.synthesis or self.contradictions):
            raise ValueError("a non-OK CIO status carries no content")

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "captain_cio_advice"
        return d


def apply_to_kernel(kernel_state, advice: CIOAdvice):
    """THE FIREWALL, as a function: the CIO's output can never change a
    kernel directive. Returns the kernel state UNMODIFIED, with the
    advice attached as commentary. Any future code that wants CIO input
    to matter must go through a versioned governance change, not here."""
    rec = kernel_state.as_record()
    rec["cio_advice"] = advice.as_record()
    rec["cio_changed_directive"] = False
    return rec


def review(kernel_state, candidate: dict, bundle: dict | None,
           runner=None, deadline_s: float = DEADLINE_S) -> CIOAdvice:
    """Ask the CIO. Structured facts only; strict JSON; defensive parse;
    hermetic-test firewall (no live LLM inside pytest)."""
    import os
    import subprocess
    import time
    from pathlib import Path

    did = kernel_state.decision_id
    marker = Path("ops/swarm_auth_ok")
    if not marker.exists():
        return CIOAdvice(decision_id=did, status="BLOCKED_EXTERNAL_AUTH")
    if runner is None and "PYTEST_CURRENT_TEST" in os.environ:
        return CIOAdvice(decision_id=did, status="FAILED")
    state = json.dumps({
        "kernel_directive": {
            "opportunity_quality": kernel_state.opportunity_quality,
            "directional_thesis": kernel_state.directional_thesis,
            "entry_thesis": kernel_state.entry_thesis,
            "primary_unresolved": kernel_state.primary_unresolved,
            "next_action": kernel_state.next_action,
            "intelligence_spend": kernel_state.recommended_intelligence_spend},
        "conviction": kernel_state.conviction,
        "candidate": {k: candidate.get(k) for k in
                      ("symbol", "product", "playbook_id", "direction",
                       "matched", "risk_frac")},
        "specialist_views": {
            "analog": (bundle or {}).get("analog_view"),
            "ml": (bundle or {}).get("ml_view"),
            "swarm": (bundle or {}).get("swarm_view", {}).get("status"),
            "disagreement": (bundle or {}).get("disagreement")}},
        default=str)
    t0 = time.monotonic()
    try:
        if runner is None:
            def runner(p):
                r = subprocess.run(
                    [str(Path.home() / ".local/bin/claude"), "-p", p],
                    capture_output=True, text=True, cwd="/tmp",
                    timeout=deadline_s)
                if r.returncode != 0:
                    raise RuntimeError(f"claude exit {r.returncode}")
                return r.stdout
        raw = runner(_PROMPT.format(state=state)).strip()
        if raw.startswith("```"):
            raw = raw.strip("`\n")
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        return CIOAdvice(
            decision_id=did, status="OK",
            synthesis=str(obj.get("synthesis", ""))[:400],
            contradictions=tuple(str(x)[:300] for x in
                                 obj.get("contradictions", [])[:6]),
            missing_information=tuple(str(x)[:300] for x in
                                      obj.get("missing_information", [])[:6]),
            next_research_question=str(
                obj.get("next_research_question", ""))[:300],
            deep_research_worthwhile=bool(
                obj.get("deep_research_worthwhile")),
            concerns=tuple(str(x)[:300] for x in obj.get("concerns", [])[:6]),
            latency_s=round(time.monotonic() - t0, 1))
    except Exception:                                       # noqa: BLE001
        return CIOAdvice(decision_id=did, status="FAILED",
                         latency_s=round(time.monotonic() - t0, 1))
