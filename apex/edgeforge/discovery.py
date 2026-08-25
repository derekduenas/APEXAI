"""FRONTIER DISCOVERY + RESIDUAL EDGE SEARCH.

Phase 2. Exploration may be aggressive; confirmation may not. The
asymmetry is the whole design: generating candidates is cheap and
should be prolific, while believing one is expensive and should be
grudging.

RESIDUAL EDGE SEARCH is the flagship. It conditions ON the incumbent's
own view and asks the question that ordinary backtesting cannot:

    Among states APEX considers approximately EQUIVALENT, what
    remaining information separates favorable from unfavorable futures?

That question only has interesting answers when the incumbent is
already competent. If GOOD states and WAIT states differ wildly, the
incumbent is doing the work. If they are indistinguishable in outcome
while APEX treats them differently, the representation is the problem
-- and the residual is where the missing variable lives.

Its output is a MissingVariableHypothesis. Never a feature. Never a
rule. A hypothesis that has not yet been allowed to be wrong.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import itertools
import statistics
from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

SEARCH_FAMILIES = (
    "STATE_TRANSITIONS", "SEQUENCES", "NONLINEAR_INTERACTIONS",
    "CROSS_PREDATOR_DISAGREEMENT", "LEAD_LAG", "PARTICIPANT_TRANSITIONS",
    "VOLATILITY_TRANSITIONS", "LIQUIDITY_TRANSITIONS",
    "FAILED_BREAKOUT_PRECURSORS", "FORCED_FLOW_PRECURSORS",
    "TAIL_PRECURSORS", "EXECUTION_ANOMALIES",
    "GATE_FAILURE_PRECURSORS", "NEAR_MISS_STRUCTURE",
)

CANDIDATE_STATUS = ("DISCOVERY_ONLY",)     # nothing else exists here

MIN_GROUP = 8          # REPORTING_PRIOR: below this, no split is read


class DiscoveryViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchAccounting:
    """The denominator. Without it, any 'finding' is a lottery ticket
    presented without the losing tickets."""
    hypotheses_searched: int
    interactions_tested: int
    transformations_considered: int
    family_wise_search_count: int
    variants_generated: int

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MissingVariableHypothesis:
    """Structure the incumbent cannot see, proposed -- not adopted."""
    hypothesis_id: str
    conditioned_on: dict          # what the incumbent considered equal
    candidate_variable: str
    interaction_form: str
    separation_observed: dict
    mechanism_hypothesis: str
    competing_explanations: tuple
    falsifiers: tuple
    search_accounting: dict
    n_raw: int
    n_effective_lower_bound: int
    status: str = "DISCOVERY_ONLY"
    calibration: str = "NONE_FITTED"
    law: str = ("a hypothesis, never a feature: this has not yet been "
                "allowed to be wrong")
    decision_power: str = "NONE_RESEARCH"

    def __post_init__(self):
        if not self.falsifiers:
            raise DiscoveryViolation(
                f"{self.hypothesis_id}: no falsifier, so nothing could "
                f"ever retire it")
        if not self.competing_explanations:
            raise DiscoveryViolation(
                f"{self.hypothesis_id}: no competing explanation -- "
                f"the first story found is not the only one available")

    def as_record(self) -> dict:
        return {"kind": "missing_variable_hypothesis", **asdict(self)}


def residual_search(*, observations: list, incumbent_equivalence: tuple,
                    candidate_variables: tuple, outcome_key: str,
                    family: str, min_group: int = MIN_GROUP) -> dict:
    """Condition on the incumbent's view; look for residual structure.

    `observations` are dicts carrying the incumbent's fields, the
    candidate variables, and a realized outcome. Groups too small to
    read return INSUFFICIENT rather than a split through noise."""
    if family not in SEARCH_FAMILIES:
        raise DiscoveryViolation(f"undeclared search family {family!r}")

    strata = {}
    for o in observations:
        if outcome_key not in o:
            continue
        key = tuple(str(o.get(f, "UNKNOWN"))
                    for f in incumbent_equivalence)
        strata.setdefault(key, []).append(o)

    n_tested, findings = 0, []
    for key, group in strata.items():
        if len(group) < min_group * 2:
            continue
        for var in candidate_variables:
            vals = [(o[var], o[outcome_key]) for o in group
                    if isinstance(o.get(var), (int, float))
                    and isinstance(o.get(outcome_key), (int, float))]
            n_tested += 1
            if len(vals) < min_group * 2:
                continue
            vals.sort(key=lambda x: x[0])
            half = len(vals) // 2
            lo = [y for _x, y in vals[:half]]
            hi = [y for _x, y in vals[half:]]
            if len(lo) < min_group or len(hi) < min_group:
                continue
            sep = statistics.median(hi) - statistics.median(lo)
            pooled = (statistics.pstdev([y for _x, y in vals]) or 1e-9)
            findings.append({
                "incumbent_stratum": dict(zip(incumbent_equivalence,
                                              key)),
                "candidate_variable": var,
                "n_in_stratum": len(vals),
                "median_low_half": round(statistics.median(lo), 6),
                "median_high_half": round(statistics.median(hi), 6),
                "separation": round(sep, 6),
                "separation_over_sd": round(sep / pooled, 4),
                "sessions_in_stratum": len(
                    {o.get("session") for o in group})})

    findings.sort(key=lambda f: -abs(f["separation_over_sd"]))
    acct = SearchAccounting(
        hypotheses_searched=n_tested,
        interactions_tested=n_tested,
        transformations_considered=len(candidate_variables),
        family_wise_search_count=n_tested,
        variants_generated=len(findings)).as_record()

    return {"kind": "residual_search",
            "family": family,
            "conditioned_on": list(incumbent_equivalence),
            "candidate_variables": list(candidate_variables),
            "n_strata": len(strata),
            "n_strata_usable": sum(1 for g in strata.values()
                                   if len(g) >= min_group * 2),
            "search_accounting": acct,
            "findings": findings[:20],
            "verdict": ("INSUFFICIENT_DATA" if not findings
                        else "CANDIDATES_GENERATED"),
            "min_group": min_group,
            "min_group_classification": "REPORTING_PRIOR",
            "law": "every one of these comparisons is in the same "
                   "multiple-testing family; the top finding must be "
                   "read against all "
                   f"{n_tested} tested",
            "decision_power": "NONE_RESEARCH"}


def propose_missing_variable(*, search: dict, finding: dict,
                             hypothesis_id: str, mechanism: str,
                             competing: tuple, falsifiers: tuple,
                             n_effective: int) -> MissingVariableHypothesis:
    return MissingVariableHypothesis(
        hypothesis_id=hypothesis_id,
        conditioned_on=finding["incumbent_stratum"],
        candidate_variable=finding["candidate_variable"],
        interaction_form="median split within incumbent stratum",
        separation_observed={
            "separation": finding["separation"],
            "separation_over_sd": finding["separation_over_sd"],
            "n": finding["n_in_stratum"]},
        mechanism_hypothesis=mechanism,
        competing_explanations=competing,
        falsifiers=falsifiers,
        search_accounting=search["search_accounting"],
        n_raw=finding["n_in_stratum"],
        n_effective_lower_bound=n_effective)


def frontier_scan(*, observations: list, families: tuple,
                  incumbent_equivalence: tuple,
                  candidate_variables: tuple, outcome_key: str) -> dict:
    """Run several search families and report the whole denominator."""
    runs, total = {}, 0
    for fam in families:
        r = residual_search(
            observations=observations,
            incumbent_equivalence=incumbent_equivalence,
            candidate_variables=candidate_variables,
            outcome_key=outcome_key, family=fam)
        runs[fam] = r
        total += r["search_accounting"]["family_wise_search_count"]
    return {"kind": "frontier_scan", "families": list(families),
            "runs": runs,
            "total_comparisons_across_families": total,
            "law": "exploration may be aggressive; confirmation may "
                   "not. Every candidate here is DISCOVERY_ONLY and "
                   "must be read against the total comparison count",
            "decision_power": "NONE_RESEARCH"}
