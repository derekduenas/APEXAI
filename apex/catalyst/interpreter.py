"""THE INTERPRETER CLIENT — the brain, running on the operator's own
Claude subscription via the headless CLI.

No API key is stored, printed or read anywhere in APEX. The client
shells out to `claude -p`, which authenticates against the operator's
existing subscription on whatever host it runs on. That is a deliberate
consequence: a host where nobody has logged in has no brain, and says
so, rather than silently degrading.

BATCHED ON PURPOSE. A first fetch of the Federal Reserve press feed
yields dozens of documents. One model call per document would cost real
money to learn nothing extra, so a cycle sends its new events together
in a single call. This is the same economy as the intraday watch:
detection is cheap and constant, interpretation is expensive and rare.

FAILURE IS ISOLATED AND VISIBLE. A missing CLI, a timeout, malformed
JSON, or an interpretation that reaches past the fence all produce the
same outcome: the events keep their DETERMINISTIC_NO_LLM stamp, the
cycle records why, and nothing downstream is told a story. The brain is
an enrichment. It is never load-bearing.

decision_power: SHADOW_CONTEXT_ONLY.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from apex.catalyst.brain import (PROMPT_CONTRACT, PROMPT_CONTRACT_SHA,
                                 validate_interpretation)
from apex.catalyst.events import CatalystViolation

DEFAULT_MODEL = os.environ.get("APEX_CATALYST_MODEL", "haiku")
DEFAULT_TIMEOUT_S = int(os.environ.get("APEX_CATALYST_LLM_TIMEOUT", "180"))
MAX_EVENTS_PER_CALL = 25

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class InterpreterUnavailable(RuntimeError):
    """No brain on this host. A normal, reportable state."""


def _strip_fence(text: str) -> str:
    """The CLI commonly wraps JSON in a markdown fence. Unwrap it
    rather than failing on presentation."""
    t = text.strip()
    if t.startswith("```"):
        t = _FENCE.sub("", t)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


class ClaudeCliInterpreter:
    """Runs the brain contract through the operator's subscription."""

    def __init__(self, *, model: str = DEFAULT_MODEL,
                 timeout_s: int = DEFAULT_TIMEOUT_S,
                 binary: str = "claude", cwd: str | None = None):
        self.model = model
        self.timeout_s = timeout_s
        self.binary = binary
        self.cwd = cwd or "/tmp"
        self.calls = 0
        self.last_error: str | None = None

    # ------------------------------------------------------ capability

    def available(self) -> dict:
        path = shutil.which(self.binary)
        return {"kind": "interpreter_capability",
                "available": bool(path),
                "binary": path or self.binary,
                "model": self.model,
                "auth": "OPERATOR_CLAUDE_SUBSCRIPTION",
                "why": ("headless CLI present" if path else
                        "claude CLI not installed or not on PATH -- "
                        "this host has no brain and events will stay "
                        "DETERMINISTIC_NO_LLM")}

    # ---------------------------------------------------------- prompt

    def _prompt(self, events: list) -> str:
        blocks = []
        for ev in events:
            obs = "\n".join(
                f"  - source={o.source} authority={o.source_authority} "
                f"published={o.published_time}\n"
                f"    ref={o.source_ref}\n"
                f"    headline={o.headline}\n"
                f"    excerpt={(o.body_excerpt or '')[:400]}"
                for o in ev.observations)
            blocks.append(f"EVENT {ev.event_id}\n{obs}")
        listing = "\n\n".join(blocks)
        ids = ", ".join(e.event_id for e in events)
        return (
            f"{PROMPT_CONTRACT}\n"
            f"Interpret each event below.\n\n{listing}\n\n"
            f"Return ONLY a JSON object mapping each event id to its "
            f"interpretation object. Event ids: {ids}\n"
            f"Each interpretation may contain ONLY these keys: "
            f"event_type, factual_summary, affected_symbols, "
            f"affected_sectors, affected_assets, "
            f"directional_expectation, mechanism_hypotheses, "
            f"uncertainty, importance, is_scheduled, contradicts, "
            f"cited_source_refs.\n"
            f"cited_source_refs MUST be refs shown above, copied "
            f"exactly. No other keys. No prose outside the JSON.")

    # ----------------------------------------------------------- call

    def _invoke(self, prompt: str) -> dict:
        if not shutil.which(self.binary):
            raise InterpreterUnavailable(
                f"{self.binary} not on PATH: this host has no brain")
        self.calls += 1
        try:
            p = subprocess.run(
                [self.binary, "-p", prompt, "--model", self.model,
                 "--output-format", "json"],
                capture_output=True, text=True,
                timeout=self.timeout_s, cwd=self.cwd)
        except subprocess.TimeoutExpired as e:
            raise InterpreterUnavailable(
                f"interpreter timed out after {self.timeout_s}s") from e
        if p.returncode != 0:
            raise InterpreterUnavailable(
                f"claude exited {p.returncode}: {p.stderr[:200]}")
        try:
            envelope = json.loads(p.stdout)
        except json.JSONDecodeError as e:
            raise InterpreterUnavailable(
                f"CLI envelope was not JSON: {e}") from e
        if envelope.get("is_error"):
            raise InterpreterUnavailable(
                f"CLI reported error: "
                f"{str(envelope.get('result'))[:200]}")
        try:
            return json.loads(_strip_fence(envelope.get("result", "")))
        except json.JSONDecodeError as e:
            raise InterpreterUnavailable(
                f"brain did not return JSON: {e}") from e

    # -------------------------------------------------------- applying

    def interpret_many(self, events: list) -> dict:
        """One call for a cycle's new events. Returns a summary; the
        events are enriched in place. Never raises."""
        events = [e for e in events if e.observations][:MAX_EVENTS_PER_CALL]
        if not events:
            return {"calls": 0, "interpreted": 0, "refused": 0,
                    "error": None, "skipped": 0}
        try:
            payload = self._invoke(self._prompt(events))
        except InterpreterUnavailable as e:
            self.last_error = str(e)[:200]
            return {"calls": self.calls, "interpreted": 0, "refused": 0,
                    "error": self.last_error, "skipped": len(events)}

        by_id = {e.event_id: e for e in events}
        done, refused, notes = 0, 0, []
        for eid, interp in (payload or {}).items():
            ev = by_id.get(eid)
            if ev is None or not isinstance(interp, dict):
                continue
            refs = tuple(o.source_ref for o in ev.observations)
            try:
                validated = validate_interpretation(
                    interp, available_source_refs=refs)
            except CatalystViolation as e:
                # a brain reaching past the fence is a finding, not a
                # crash -- the event simply stays uninterpreted
                refused += 1
                notes.append(f"{eid}: {str(e)[:120]}")
                continue
            self._apply(ev, validated["interpretation"])
            done += 1

        if refused:
            self.last_error = f"{refused} refused: {'; '.join(notes[:3])}"
        return {"calls": self.calls, "interpreted": done,
                "refused": refused, "error": self.last_error,
                "skipped": len(events) - done - refused,
                "prompt_contract_sha": PROMPT_CONTRACT_SHA}

    def _apply(self, ev, interp: dict) -> None:
        """Copy validated interpretation onto the event. The source
        headline is never overwritten -- it is what we actually read."""
        def tup(key):
            v = interp.get(key) or ()
            return tuple(v) if isinstance(v, (list, tuple)) else (v,)

        if interp.get("event_type"):
            ev.event_type = interp["event_type"]
        if interp.get("factual_summary"):
            ev.factual_summary = interp["factual_summary"]
        if interp.get("affected_symbols"):
            ev.affected_symbols = tup("affected_symbols")
        if interp.get("affected_sectors"):
            ev.affected_sectors = tup("affected_sectors")
        if interp.get("affected_assets"):
            ev.affected_assets = tup("affected_assets")
        if interp.get("mechanism_hypotheses"):
            ev.mechanism_hypotheses = tup("mechanism_hypotheses")
        if interp.get("uncertainty"):
            ev.uncertainty = tup("uncertainty")
        if interp.get("importance"):
            ev.importance = interp["importance"]
        # the field the whole reaction comparison depends on. It was
        # requested, permitted and validated -- and then dropped here,
        # because the event had nowhere to put it.
        de = interp.get("directional_expectation")
        if de and de != "UNKNOWN":
            ev.directional_expectation = de
            ev.expectation_source = "LLM_DERIVED_INTERPRETATION"
            ev.expectation_contract_sha = PROMPT_CONTRACT_SHA
            # sealed at interpretation time, which is strictly before
            # any reaction horizon can have matured
            ev.expectation_known_from = ev.known_from
        ev.interpreter = (f"CLAUDE_CLI:{self.model}"
                          f"@{PROMPT_CONTRACT_SHA}")
