"""STAGED ENRICHMENT — and the selection bias it would otherwise hide.

Deep tape and option surfaces are expensive, so they are gathered only
where operationally justified. That is a cost decision, not a claim
about returns, and this detector has NO alpha authority.

THE TRAP THIS MODULE EXISTS TO PREVENT. If rich state is collected
only for subjects already doing something interesting, then in the
eventual training corpus:

    "options data present"  correlates with  "something was happening"

and a World Model can learn that the PRESENCE of a field predicts
movement -- which is an artifact of our sampling, not a property of
the market. Worse, "missing because boring" and "missing because the
vendor failed" would look identical.

So missingness is never generic. Three causes stay permanently
distinct:

  NOT_ENRICHED              we chose not to look, and the reason and
                            rule version are recorded
  ENRICHMENT_ATTEMPT_FAILED we looked and the attempt failed
  DATA_NOT_AVAILABLE        we looked, it succeeded, the data does not
                            exist (options before the options open)

A future dataset builder can therefore reconstruct the exact selection
rule that produced its own coverage, and correct for it -- or at
minimum know that it must.

decision_power: NONE_STATE -- this decides where to spend API calls,
never what to trade.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Bumping this version is what makes a coverage change visible in the
# corpus. A dataset built across two rule versions must know it.
ENRICHMENT_RULE_VERSION = "PULSE_ENRICHMENT_V0"

TIER1_CONTINUOUS = "TIER1_CONTINUOUS"
MATERIAL_MOVE = "MATERIAL_MOVE"
MATERIAL_VOLUME = "MATERIAL_VOLUME"
CATALYST_SUBJECT = "CATALYST_SUBJECT"
REFERENCE_SAMPLE = "REFERENCE_SAMPLE"
NOT_ENRICHED = "NOT_ENRICHED"

ATTEMPT_FAILED = "ENRICHMENT_ATTEMPT_FAILED"
BUDGET_EXCEEDED = "ENRICHMENT_BUDGET_EXCEEDED"
DATA_NOT_AVAILABLE = "DATA_NOT_AVAILABLE"
SUCCEEDED = "SUCCEEDED"

# Operational thresholds. These are DELIBERATELY round numbers chosen
# to bound API cost, and they are NOT tuned against any outcome. If
# they are ever changed, the rule version changes with them.
MATERIAL_MOVE_BPS = 200.0
MATERIAL_RELATIVE_VOLUME = 3.0
# A fixed fraction of ordinary subjects is enriched REGARDLESS of
# activity, purely so the corpus contains deep state for boring names
# too. Without it, "deep state exists" is perfectly confounded with
# "something was happening".
REFERENCE_SAMPLE_RATE = 0.02


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def eligibility(subject, *, tier1, move_bps=None, relative_volume=None,
                catalyst_subject=False, as_of=None,
                known_from=None) -> dict:
    """Should this subject receive expensive sensing this cycle?

    Returns the decision AND everything needed to reproduce it later,
    including the moment the evidence became knowable -- an
    eligibility decided on information APEX did not yet have would be
    a leak dressed as an optimisation."""
    reasons = []
    if tier1:
        reasons.append(TIER1_CONTINUOUS)
    if isinstance(move_bps, (int, float)) and \
            abs(move_bps) >= MATERIAL_MOVE_BPS:
        reasons.append(MATERIAL_MOVE)
    if isinstance(relative_volume, (int, float)) and \
            relative_volume >= MATERIAL_RELATIVE_VOLUME:
        reasons.append(MATERIAL_VOLUME)
    if catalyst_subject:
        reasons.append(CATALYST_SUBJECT)
    if not reasons and _sampled(subject):
        reasons.append(REFERENCE_SAMPLE)

    return {
        "eligible": bool(reasons),
        "reason": reasons[0] if reasons else NOT_ENRICHED,
        "all_reasons": reasons,
        "rule_version": ENRICHMENT_RULE_VERSION,
        "eligibility_time": _now(),
        "eligibility_as_of": as_of,
        "eligibility_known_from": known_from or as_of,
        "evidence": {"tier1": tier1, "move_bps": move_bps,
                     "relative_volume": relative_volume,
                     "catalyst_subject": catalyst_subject},
        "thresholds": {"material_move_bps": MATERIAL_MOVE_BPS,
                       "material_relative_volume":
                           MATERIAL_RELATIVE_VOLUME,
                       "reference_sample_rate": REFERENCE_SAMPLE_RATE},
        "law": "operational sensing budget only; this carries no "
               "prediction and no capital authority",
        "decision_power": "NONE_STATE"}


def _sampled(subject: str) -> bool:
    """A deterministic unbiased slice of ordinary subjects.

    Deterministic on the symbol so the sample is reproducible and
    stable rather than a different set every cycle -- a corpus needs
    the SAME boring names followed over time, not a random dusting."""
    import hashlib
    h = int(hashlib.sha256(subject.encode()).hexdigest()[:8], 16)
    return (h % 10_000) < int(REFERENCE_SAMPLE_RATE * 10_000)


class EnrichmentRecord:
    """What was asked for, what came back, and why anything is absent."""

    def __init__(self, elig: dict):
        self.elig = elig
        self.requested, self.outcomes = [], {}
        self.started = _now()

    def request(self, kind: str):
        self.requested.append(kind)

    def succeeded(self, kind: str, *, as_of=None):
        self.outcomes[kind] = {"outcome": SUCCEEDED, "as_of": as_of}

    def failed(self, kind: str, *, why: str):
        self.outcomes[kind] = {"outcome": ATTEMPT_FAILED, "why": why}

    def budget_exceeded(self, kind: str, *, rank, budget):
        """Eligible, but the cycle's API budget was spent first. The
        rank is recorded because the budget is spent in PRIORITY
        order, so this missingness is systematically biased toward
        lower-priority subjects."""
        self.outcomes[kind] = {"outcome": BUDGET_EXCEEDED,
                               "rank": rank, "budget": budget,
                               "why": f"eligible but ranked {rank} "
                                      f"against a per-cycle budget of "
                                      f"{budget}"}

    def unavailable(self, kind: str, *, why: str):
        self.outcomes[kind] = {"outcome": DATA_NOT_AVAILABLE,
                               "why": why}

    def record(self) -> dict:
        return {
            "enriched": bool(self.elig.get("eligible")),
            "reason": self.elig.get("reason"),
            "all_reasons": self.elig.get("all_reasons", []),
            "rule_version": self.elig.get("rule_version"),
            "eligibility_time": self.elig.get("eligibility_time"),
            "eligibility_as_of": self.elig.get("eligibility_as_of"),
            "eligibility_known_from":
                self.elig.get("eligibility_known_from"),
            "evidence": self.elig.get("evidence"),
            "thresholds": self.elig.get("thresholds"),
            "requested": sorted(set(self.requested)),
            "succeeded": sorted(k for k, v in self.outcomes.items()
                                if v["outcome"] == SUCCEEDED),
            "failed": {k: v for k, v in self.outcomes.items()
                       if v["outcome"] == ATTEMPT_FAILED},
            "not_available": {k: v for k, v in self.outcomes.items()
                              if v["outcome"] == DATA_NOT_AVAILABLE},
            "budget_exceeded": {k: v for k, v in self.outcomes.items()
                                if v["outcome"] == BUDGET_EXCEEDED},
            "started": self.started, "completed": _now(),
            "SELECTION_BIAS_LAW":
                "absence of deep state is NOT random. NOT_ENRICHED "
                "means we chose not to look; ENRICHMENT_ATTEMPT_FAILED "
                "means we looked and failed; DATA_NOT_AVAILABLE means "
                "the data does not exist; ENRICHMENT_BUDGET_EXCEEDED "
                "means we were allowed to look and ran out of budget "
                "in priority order. A dataset builder must never "
                "collapse these into one missing value."}
