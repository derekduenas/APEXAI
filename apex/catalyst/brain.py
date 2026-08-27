"""THE CATALYST BRAIN CONTRACT — what the interpreter may say.

An LLM reading the world is genuinely valuable and genuinely dangerous.
Valuable because "good earnings but the stock cannot rally" is a
semantic judgement no price model reaches. Dangerous because a language
model is equally fluent when it is wrong, and a fabricated consensus
figure reads exactly like a measured one.

So the brain is fenced by contract rather than by hope:

    IT MAY RETURN      event_type, affected symbols/sectors, a factual
                       summary drawn from cited sources, directional
                       EXPECTATION, mechanism hypotheses, uncertainties,
                       importance, contradiction flags

    IT MAY NOT RETURN  any surprise number, any price, any authority,
                       any trading verdict, any claim without a cited
                       source observation, any certainty it was not
                       given

`validate_interpretation` enforces this. An interpretation that reaches
past the fence is REFUSED rather than trimmed, because silently
dropping a forbidden field teaches nothing and hides a brain that is
drifting.

THE PROMPT CONTRACT below is the actual instruction the brain runs
under. It lives in code, versioned with the release, so an
interpretation can always be traced to the exact instruction that
produced it.

decision_power: SHADOW_CONTEXT_ONLY.
"""
from __future__ import annotations

import hashlib

from apex.catalyst.events import (EVENT_TYPES, IMPORTANCE,
                                  CatalystViolation)
from apex.catalyst.reaction import DIRECTIONAL_EXPECTATION

# Fields the brain is permitted to produce. Anything else is refused.
ALLOWED_FIELDS = frozenset({
    "event_type", "factual_summary", "affected_symbols",
    "affected_sectors", "affected_assets", "directional_expectation",
    "mechanism_hypotheses", "uncertainty", "importance",
    "is_scheduled", "contradicts", "cited_source_refs"})

# Fields that would let interpretation masquerade as measurement or
# authority. Named explicitly so the refusal message can say why.
FORBIDDEN_FIELDS = {
    "surprise": "surprise is DETERMINISTIC arithmetic over actual and "
                "consensus; an interpreted surprise is a fabricated "
                "number wearing a measurement's clothes",
    "actual_value": "numeric releases come from the source, not the "
                    "reader",
    "consensus": "an invented consensus is worse than no surprise",
    "expected_value": "same as consensus",
    "price": "the brain does not observe prices",
    "return_pct": "reaction is measured, never asserted",
    "authority": "authority is granted by governance, never claimed",
    "decision_power": "same as authority",
    "verdict": "the brain does not decide anything",
    "trade": "the brain does not trade",
    "direction": "a TRADE direction is a decision; the brain may only "
                 "state a directional EXPECTATION about the world",
    "attackable": "attackability belongs to the Predator",
    "confidence_score": "a scalar confidence invites a threshold; "
                        "state uncertainties in words instead",
}

# The permitted vocabulary is INTERPOLATED from the same tuples the
# validator enforces, so the instruction and the fence can never drift
# apart. Live traffic proved why this matters: the first real call
# returned "Regulatory enforcement action - individuals" and was
# refused, because the contract had named the allowed FIELDS but never
# the allowed VALUES. A model cannot satisfy a constraint it was never
# shown, and refusing it for that would be blaming the reader for an
# unwritten rule. Changing this text changes PROMPT_CONTRACT_SHA, so
# every interpretation stays traceable to the exact wording behind it.
PROMPT_CONTRACT = f"""\
You are APEX's catalyst analyst. You read the world; you never trade.

You will be given SOURCE OBSERVATIONS: headlines and excerpts, each
with a source, an authority tier and a publication time.

Return ONLY an interpretation of what those sources say:
  event_type, factual_summary (drawn strictly from the cited text),
  affected_symbols / sectors / assets, directional_expectation,
  mechanism_hypotheses, uncertainty, importance, is_scheduled,
  contradicts, cited_source_refs.

CLOSED VOCABULARIES -- use these EXACT strings, nothing else:
  event_type must be one of:
    {", ".join(EVENT_TYPES)}
  importance must be one of:
    {", ".join(IMPORTANCE)}
  directional_expectation must be one of:
    {", ".join(DIRECTIONAL_EXPECTATION)}
  If nothing fits, use OTHER / UNKNOWN. Inventing a more descriptive
  label is not more informative -- it is refused, and the event ends
  up with no interpretation at all.

  affected_symbols must be ticker symbols. mechanism_hypotheses and
  uncertainty must be arrays of strings. cited_source_refs must be
  refs copied EXACTLY from the observations you were given.

HARD RULES
1. Never state a fact that is not in a cited source. If the sources do
   not say it, it is not known.
2. Never produce a number that was not in a source. You do not compute
   surprises, prices or returns.
3. directional_expectation describes what the NEWS implies about the
   world, not what anyone should do. POSITIVE / NEGATIVE / AMBIGUOUS /
   UNKNOWN. AMBIGUOUS and UNKNOWN are good answers when true.
4. If credible sources disagree, say so. Do not pick a side.
5. Mechanism hypotheses are HYPOTHESES. Give the causal chain you think
   connects the event to the affected entities, and say what would show
   you were wrong.
6. You have no authority. You cannot approve, block, size or direct any
   trade, and nothing you write will be allowed to.
7. An empty or low-importance answer is often correct. Most headlines
   are not catalysts.
"""

PROMPT_CONTRACT_SHA = hashlib.sha256(
    PROMPT_CONTRACT.encode()).hexdigest()[:16]


def validate_interpretation(interp: dict, *,
                            available_source_refs: tuple) -> dict:
    """Accept or REFUSE a brain interpretation. Never silently trim."""
    if not isinstance(interp, dict):
        raise CatalystViolation("interpretation must be a mapping")

    reached = sorted(set(interp) & set(FORBIDDEN_FIELDS))
    if reached:
        why = "; ".join(f"{f}: {FORBIDDEN_FIELDS[f]}" for f in reached)
        raise CatalystViolation(
            f"interpretation reached past the fence -- {why}")

    unknown = sorted(set(interp) - ALLOWED_FIELDS)
    if unknown:
        raise CatalystViolation(
            f"undeclared interpretation fields {unknown}: the contract "
            f"is a whitelist, so a new field must be authorized rather "
            f"than merely unforbidden")

    et = interp.get("event_type", "UNKNOWN")
    if et not in EVENT_TYPES:
        raise CatalystViolation(f"unknown event_type {et!r}")
    de = interp.get("directional_expectation", "UNKNOWN")
    if de not in DIRECTIONAL_EXPECTATION:
        raise CatalystViolation(
            f"unknown directional_expectation {de!r}")
    imp = interp.get("importance", "UNKNOWN")
    if imp not in IMPORTANCE:
        raise CatalystViolation(f"unknown importance {imp!r}")

    cited = tuple(interp.get("cited_source_refs") or ())
    if interp.get("factual_summary") and not cited:
        raise CatalystViolation(
            "a factual summary with no cited source is exactly the "
            "'news says' failure this contract exists to prevent")
    uncited = [c for c in cited if c not in available_source_refs]
    if uncited:
        raise CatalystViolation(
            f"cited sources {uncited} were never retrieved: the brain "
            f"is citing documents it was not given")

    return {"kind": "validated_interpretation",
            "interpretation": dict(interp),
            "prompt_contract_sha": PROMPT_CONTRACT_SHA,
            "cited_source_refs": list(cited),
            "law": "interpretation only -- no facts, no numbers, no "
                   "authority",
            "decision_power": "SHADOW_CONTEXT_ONLY"}


def hypothesis_is_falsifiable(h: dict) -> bool:
    """A mechanism hypothesis without a falsifier is a story. Same law
    the Governor applies to its own diagnoses."""
    return bool(h.get("mechanism")) and bool(h.get("would_be_wrong_if"))
