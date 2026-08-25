"""OUTCOME INTELLIGENCE — archaeology, taxonomy, and refusal value.

Phases 12-14.

OPPORTUNITY ARCHAEOLOGY (12) looks backward from an extreme outcome
through causally available pre-state fields only, then -- and this is
the part that separates research from storytelling -- finds the many
SIMILAR states that did nothing. A tail winner is only interesting
relative to its near-twins that went nowhere. Without that control
group, archaeology is just a flattering anecdote with timestamps.

FAILED-TRADE INTELLIGENCE (13) refuses to equate outcome with decision
quality in either direction. GOOD_DECISION_BAD_OUTCOME is a real and
common category, and so is BAD_DECISION_GOOD_OUTCOME -- which is the
more dangerous one, because nobody investigates a winner.

REFUSAL INTELLIGENCE (14) resolves what APEX declined at the same
horizons as what it took. Gates that cost more than they save should be
visible; gates that quietly earn their keep should get the credit.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

DECISION_OUTCOME_CLASSES = (
    "GOOD_DECISION_BAD_OUTCOME", "BAD_DECISION_GOOD_OUTCOME",
    "BAD_THESIS", "BAD_MECHANISM", "BAD_TIMING", "BAD_LOCATION",
    "BAD_EXPRESSION", "BAD_EXECUTION", "BAD_SIZE", "REGIME_MISMATCH",
    "THESIS_INVALIDATED_PROTOCOL_HELD", "SOUND_DECISION_GOOD_OUTCOME",
    "UNKNOWN",
)


class OutcomeIntelViolation(RuntimeError):
    pass


# ==================================================== PHASE 13

def classify_decision(*, pnl, mid_change, thesis_path_state,
                      adversary_verdict: str | None,
                      boundary_proximity: str | None,
                      friction_share, expression_alternatives_better:
                      bool | None = None,
                      regime_matched: bool | None = None) -> dict:
    """Separate decision quality from outcome. Both directions."""
    reasons, contributing = [], []
    num = lambda x: isinstance(x, (int, float))          # noqa: E731

    won = num(pnl) and pnl > 0
    thesis_broke = thesis_path_state in (
        "THESIS_INVALIDATED_PROTOCOL_HELD",
        "THESIS_REVALIDATED_AFTER_INVALIDATION")

    # process quality, judged WITHOUT the outcome
    process_flaws = []
    if adversary_verdict == "FRAGILE":
        process_flaws.append("the attack was fragile under stress")
    if boundary_proximity == "KNIFE_EDGE":
        process_flaws.append("the decision sat on its threshold")
    if regime_matched is False:
        process_flaws.append("regime did not match the mechanism")
    if expression_alternatives_better:
        process_flaws.append("a causally available expression dominated")

    if won and process_flaws:
        primary = "BAD_DECISION_GOOD_OUTCOME"
        reasons.append(
            "profitable, but the process was flawed: " +
            "; ".join(process_flaws) +
            ". Nobody investigates a winner, which is exactly why this "
            "category exists")
    elif won:
        primary = "SOUND_DECISION_GOOD_OUTCOME"
        reasons.append("profitable with no recorded process flaw")
    elif thesis_broke and not process_flaws:
        primary = "THESIS_INVALIDATED_PROTOCOL_HELD"
        reasons.append("the thesis broke and the protocol held through "
                       "it by design")
    elif num(friction_share) and friction_share >= 1.0 and \
            num(mid_change) and mid_change > 0:
        primary = "BAD_EXECUTION"
        reasons.append("gained on mid and lost to the round trip")
    elif num(mid_change) and mid_change <= 0 and not process_flaws:
        primary = "GOOD_DECISION_BAD_OUTCOME"
        reasons.append(
            "the move did not come and no process flaw is on record; "
            "a loss is not evidence of a bad decision")
    elif process_flaws:
        primary = ("BAD_EXPRESSION" if expression_alternatives_better
                   else "BAD_LOCATION" if boundary_proximity ==
                   "KNIFE_EDGE" else "BAD_MECHANISM")
        contributing = process_flaws
    else:
        primary = "UNKNOWN"
        reasons.append("insufficient recorded state to classify")

    return {"kind": "decision_outcome_classification",
            "primary_class": primary,
            "process_flaws": process_flaws,
            "contributing": contributing,
            "reasoning": reasons,
            "law": "profitable trades are not automatically good "
                   "decisions; losing trades are not automatically bad "
                   "ones",
            "decision_power": "NONE_RESEARCH"}


# ==================================================== PHASE 12

def opportunity_archaeology(*, target: dict, population: list,
                            prestate_fields: tuple,
                            outcome_key: str,
                            tail_quantile: float = 0.9) -> dict:
    """What distinguished the few tail outcomes from the many similar
    states that did nothing?

    Only causally available pre-state fields are inspected. The control
    group is the point: without the near-twins that went nowhere, this
    is jackpot storytelling."""
    outs = [o[outcome_key] for o in population
            if isinstance(o.get(outcome_key), (int, float))]
    if len(outs) < 10:
        return {"kind": "opportunity_archaeology",
                "verdict": "INSUFFICIENT_POPULATION",
                "n": len(outs)}
    srt = sorted(outs)
    hi_cut = srt[min(len(srt) - 1, int(tail_quantile * len(srt)))]

    tails = [o for o in population
             if isinstance(o.get(outcome_key), (int, float))
             and o[outcome_key] >= hi_cut]

    # DEGENERATE CUT. When the quantile lands on a mass point, every
    # observation qualifies as a "tail" and the control group silently
    # disappears -- leaving an archaeology with nothing to contrast
    # against, which would read as "no discriminators found" when the
    # truth is "no comparison was possible".
    rest = [o for o in population if o not in tails]
    if len(rest) < 3 or len(tails) < 3:
        return {"kind": "opportunity_archaeology",
                "verdict": "DEGENERATE_TAIL_CUT",
                "n_population": len(population),
                "n_tails": len(tails), "n_rest": len(rest),
                "tail_cut": round(hi_cut, 6),
                "why": (f"the {tail_quantile:.0%} cut at {hi_cut} does "
                        f"not separate this population (outcomes are "
                        f"concentrated at a mass point); there is no "
                        f"control group to contrast against"),
                "law": "no comparison was possible -- that is different "
                       "from finding no discriminators",
                "decision_power": "NONE_RESEARCH"}

    # NEAR-TWINS: states that looked like the target beforehand
    def dist(a, b):
        d, n = 0.0, 0
        for f in prestate_fields:
            x, y = a.get(f), b.get(f)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                d += (x - y) ** 2
                n += 1
        return (d / n) ** 0.5 if n else float("inf")

    ranked = sorted(
        (o for o in population if o is not target),
        key=lambda o: dist(target, o))
    twins = ranked[:max(10, len(population) // 10)]
    twin_outs = [o[outcome_key] for o in twins
                 if isinstance(o.get(outcome_key), (int, float))]
    twin_tails = [o for o in twins if o in tails]

    # which pre-state fields actually differ between tails and the rest
    discriminators = []
    for f in prestate_fields:
        tv = [o[f] for o in tails if isinstance(o.get(f), (int, float))]
        rv = [o[f] for o in rest
              if isinstance(o.get(f), (int, float))]
        if len(tv) < 3 or len(rv) < 3:
            continue
        sd = statistics.pstdev(rv) or 1e-9
        gap = (statistics.median(tv) - statistics.median(rv)) / sd
        discriminators.append({"field": f, "tail_median":
                               round(statistics.median(tv), 6),
                               "rest_median":
                               round(statistics.median(rv), 6),
                               "gap_in_sd": round(gap, 4),
                               "n_tail": len(tv)})
    discriminators.sort(key=lambda d: -abs(d["gap_in_sd"]))

    twin_tail_rate = (len(twin_tails) / len(twins)) if twins else \
        NOT_ESTIMABLE
    base_rate = len(tails) / len(population)
    return {"kind": "opportunity_archaeology",
            "verdict": "CONTRASTED",
            "n_population": len(population), "n_tails": len(tails),
            "tail_cut": round(hi_cut, 6),
            "base_tail_rate": round(base_rate, 4),
            "n_near_twins": len(twins),
            "near_twin_tail_rate": (round(twin_tail_rate, 4)
                                    if isinstance(twin_tail_rate, float)
                                    else twin_tail_rate),
            "near_twin_median_outcome": (
                round(statistics.median(twin_outs), 6)
                if twin_outs else NOT_ESTIMABLE),
            "discriminators": discriminators[:10],
            "key_question": "what distinguished the few tail outcomes "
                            "from the MANY SIMILAR states that did "
                            "nothing?",
            "law": "the near-twins that went nowhere are the control "
                   "group; without them this is jackpot storytelling",
            "decision_power": "NONE_RESEARCH"}


# ==================================================== PHASE 14

def gate_value(*, cohorts: dict, horizon_note: str) -> dict:
    """Resolve refusals against attacks at consistent horizons."""
    rows = {}
    for cohort, outcomes in cohorts.items():
        vals = [v for v in outcomes if isinstance(v, (int, float))]
        if not vals:
            rows[cohort] = {"n": len(outcomes),
                            "verdict": NOT_ESTIMABLE}
            continue
        rows[cohort] = {
            "n_raw": len(vals),
            "median": round(statistics.median(vals), 6),
            "mean": round(sum(vals) / len(vals), 6),
            "favorable_fraction": round(
                sum(1 for v in vals if v > 0) / len(vals), 4)}

    attacked = rows.get("PAPER_ATTACKED", {})
    waited = rows.get("WAIT_FOR_ENTRY", {})
    signal = None
    if isinstance(attacked.get("median"), float) and \
            isinstance(waited.get("median"), float):
        if waited["median"] > attacked["median"]:
            signal = ("REFUSED_STATES_OUTPERFORMED_ATTACKS: the gate "
                      "may be filtering backward. This is descriptive "
                      "and must not move a gate on its own")
        else:
            signal = "ATTACKS_OUTPERFORMED_REFUSALS on this sample"
    return {"kind": "gate_value", "cohorts": rows, "signal": signal,
            "horizon": horizon_note,
            "law": "independent sessions, not observations, are the "
                   "sample; gates are never optimized automatically",
            "decision_power": "NONE_RESEARCH"}
