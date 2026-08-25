"""HISTORICAL ALTERNATE APEXES — the market evolution tournament.

For every sealed test period, several policies live through the SAME
causal history with the SAME execution assumptions:

  APEX_INCUMBENT     what V1's frozen rules would have decided
  APEX_CHALLENGER    what EdgeForge's frozen challenger would have
  SIMPLE_MOMENTUM    a baseline anyone could have written in 1995
  RANDOM_ELIGIBLE    random choice among causally eligible actions
  NO_TRADE           flat is a position

COMMON HISTORY LAW (the Attack Lab's common-world law, applied to
time): every policy sees the identical decision moments keyed by
timestamp. A policy that skips a moment fails the tournament -- it
does not get a flattering subset of history.

RANDOM_ELIGIBLE is the quiet star. A challenger that beats momentum
but not random selection among eligible actions has discovered
eligibility, not skill -- the filter did the work, the picker added
nothing.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import statistics

from apex.chronos import EVIDENCE_LABEL
from apex.chronos.clock import ChronosViolation

NOT_ESTIMABLE = "NOT_ESTIMABLE"

POLICIES = ("APEX_INCUMBENT", "APEX_CHALLENGER", "SIMPLE_MOMENTUM",
            "RANDOM_ELIGIBLE", "NO_TRADE")


def run_tournament(*, decisions_by_policy: dict, period: str) -> dict:
    """decisions_by_policy: {policy: {timestamp: r_multiple|None}}.

    None means the policy chose not to act at that moment -- which is
    itself a decision and scores 0.0, exactly like NO_TRADE. A missing
    TIMESTAMP, by contrast, means the policy never faced the moment,
    and that breaks the comparison."""
    unknown = [p for p in decisions_by_policy if p not in POLICIES]
    if unknown:
        raise ChronosViolation(
            f"undeclared policies {unknown}; the tournament roster is "
            f"fixed so nobody enters a flattering late arrival")
    if "NO_TRADE" not in decisions_by_policy:
        raise ChronosViolation(
            "NO_TRADE must run; it is the baseline everything must "
            "beat and the cheapest thing to forget")

    keysets = {p: set(d) for p, d in decisions_by_policy.items()}
    ref = keysets["NO_TRADE"]
    for p, ks in keysets.items():
        if ks != ref:
            raise ChronosViolation(
                f"{p} faced {len(ks)} moments but the common history "
                f"has {len(ref)}: a policy that skips moments gets a "
                f"flattering subset of history, and that is not a "
                f"comparison")

    rows = {}
    for p, d in decisions_by_policy.items():
        vals = [(v if isinstance(v, (int, float)) else 0.0)
                for v in d.values()]
        acted = sum(1 for v in d.values()
                    if isinstance(v, (int, float)))
        rows[p] = {"n_moments": len(vals), "n_acted": acted,
                   "total_R": round(sum(vals), 4),
                   "median_R": (round(statistics.median(vals), 4)
                                if vals else NOT_ESTIMABLE),
                   "favorable_fraction": (
                       round(sum(1 for v in vals if v > 0) / len(vals),
                             4) if vals else NOT_ESTIMABLE)}

    ch = rows.get("APEX_CHALLENGER")
    findings = []
    if ch:
        for rival, meaning in (
                ("NO_TRADE", "doing nothing"),
                ("RANDOM_ELIGIBLE", "random selection among eligible "
                                    "actions -- eligibility did the "
                                    "work, the picker added nothing"),
                ("SIMPLE_MOMENTUM", "a 1995 baseline")):
            r = rows.get(rival)
            if r and ch["total_R"] <= r["total_R"]:
                findings.append(
                    f"challenger did not beat {rival} ({meaning})")
    return {"kind": "chronos_tournament", "period": period,
            "evidence_label": EVIDENCE_LABEL,
            "standings": rows,
            "challenger_findings": findings,
            "verdict": ("CHALLENGER_DOMINATED" if ch and not findings
                        else "CHALLENGER_NOT_SUPERIOR" if ch
                        else "NO_CHALLENGER_ENTERED"),
            "law": "identical moments, identical execution "
                   "assumptions, identical causal information; "
                   "beating momentum but not random-eligible is "
                   "discovering eligibility, not skill",
            "decision_power": "NONE_RESEARCH"}
