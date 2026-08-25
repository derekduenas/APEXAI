"""THE ADVERSARY — an engine whose job is to KILL apparent edge.

Phase 5. Every other component in EdgeForge is, structurally, looking
for something. This one is looking for reasons the thing found is not
real. Without a component whose success condition is destruction, a
research system's incentives all point one way, and it will eventually
find what it is looking for whether or not it exists.

FRAGILITY LAW. An edge that exists only under perfect fill, perfect
entry, perfect timing, one exact regime, or one exact model assumption
is FRAGILE -- regardless of how impressive its historical P&L looks.
"Survived when nothing went wrong" is not a result.

NO MAGIC SCORE. Breakpoints are reported separately (execution,
mechanism, path, tail), because an edge that dies at 2 cents of
slippage and one that dies only in a correlation shock have nothing in
common and averaging them into a single "robustness" figure would hide
exactly the distinction that matters.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

STRESS_FAMILIES = {
    "EXECUTION": ("ENTRY_SLIPPAGE", "SPREAD_EXPANSION", "PARTIAL_FILL",
                  "MISSED_FILL", "PROVIDER_LATENCY", "DELAYED_ENTRY"),
    "PATH": ("FALSE_BREAKOUT", "GAP_THROUGH_INVALIDATION",
             "WORSE_SEQUENCING", "SIGNAL_DECAY"),
    "MECHANISM": ("MECHANISM_FAILURE", "FAILED_CASCADE",
                  "REGIME_SHIFT"),
    "MARKET": ("IV_SHOCK", "THETA_PASSAGE", "LIQUIDITY_WITHDRAWAL",
               "CORRELATION_SHOCK", "SECTOR_REVERSAL",
               "TEMPORARY_MISSING_DATA"),
}
ALL_STRESSES = tuple(s for fam in STRESS_FAMILIES.values() for s in fam)


class AdversaryViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class StressResult:
    stress: str
    family: str
    magnitude: float
    favorable_world_fraction: float | str
    median_pnl: float | str
    survived: bool | str
    note: str = ""

    def as_record(self) -> dict:
        return asdict(self)


def _summarize(outs: dict) -> tuple:
    pnls = [o["pnl"] for o in outs.values()
            if isinstance(o.get("pnl"), (int, float))]
    if not pnls:
        return NOT_ESTIMABLE, NOT_ESTIMABLE
    return (round(sum(1 for p in pnls if p > 0) / len(pnls), 4),
            round(statistics.median(pnls), 2))


def attack_candidate(*, attack, worlds: list, evaluate_common,
                     stress_grid: dict, survival_floor: float = 0.40
                     ) -> dict:
    """Run the full stress battery and locate the breakpoints.

    `stress_grid` maps stress name -> [(magnitude, attack_or_world
    transform)], where a transform returns either a modified attack or
    a modified world list. Both are supported because some degradations
    live in the instrument and some in the market."""
    base_run = evaluate_common(attacks=[attack], worlds=worlds)
    base_frac, base_med = _summarize(base_run["outcomes"][attack.attack_id])

    results, breakpoints = [], {}
    for stress, rungs in stress_grid.items():
        if stress not in ALL_STRESSES:
            raise AdversaryViolation(f"undeclared stress {stress!r}")
        family = next(f for f, ss in STRESS_FAMILIES.items()
                      if stress in ss)
        broke_at = None
        for magnitude, transform in sorted(rungs, key=lambda r: r[0]):
            stressed_attack, stressed_worlds = transform(attack, worlds)
            run = evaluate_common(attacks=[stressed_attack],
                                  worlds=stressed_worlds)
            frac, med = _summarize(
                run["outcomes"][stressed_attack.attack_id])
            survived = (isinstance(frac, float)
                        and frac >= survival_floor)
            results.append(StressResult(
                stress=stress, family=family, magnitude=magnitude,
                favorable_world_fraction=frac, median_pnl=med,
                survived=survived))
            if not survived and broke_at is None:
                broke_at = magnitude
        breakpoints[stress] = (broke_at if broke_at is not None
                               else "SURVIVED_ALL_TESTED")

    fam_break = {}
    for fam, stresses in STRESS_FAMILIES.items():
        pts = {s: breakpoints[s] for s in stresses if s in breakpoints}
        if pts:
            fam_break[fam] = pts

    # fragility: dies at the gentlest rung of anything
    fragile_at = [s for s, b in breakpoints.items()
                  if isinstance(b, (int, float))
                  and b <= min(m for m, _t in stress_grid[s])]
    verdict = ("FRAGILE" if fragile_at else
               "SURVIVED_TESTED_STRESSES"
               if all(b == "SURVIVED_ALL_TESTED"
                      for b in breakpoints.values())
               else "CONDITIONALLY_ROBUST")

    return {"kind": "adversary_report",
            "attack_id": attack.attack_id,
            "base_favorable_world_fraction": base_frac,
            "base_median_pnl": base_med,
            "stress_results": [r.as_record() for r in results],
            "breakpoints_by_family": fam_break,
            "execution_breakpoint": fam_break.get("EXECUTION"),
            "mechanism_breakpoint": fam_break.get("MECHANISM"),
            "path_breakpoint": fam_break.get("PATH"),
            "fragile_under": fragile_at,
            "verdict": verdict,
            "survival_floor": survival_floor,
            "survival_floor_classification": "REPORTING_PRIOR",
            "law": "an edge that needs everything to go right is not an "
                   "edge; breakpoints are reported separately because "
                   "dying at 2c of slippage and dying in a correlation "
                   "shock are different diseases",
            "decision_power": "NONE_RESEARCH"}


# ---------------------------------------------------- transforms

def entry_slippage(cents: float):
    def t(attack, worlds):
        p = dict(attack.params)
        if "entry" in p:
            sign = 1.0 if p.get("direction") == "LONG" else -1.0
            p["entry"] = p["entry"] + sign * cents
        elif "entry_premium" in p:
            p["entry_premium"] = p["entry_premium"] + cents
        return _respec(attack, p), worlds
    return t


def iv_shock(shift: float):
    def t(attack, worlds):
        p = dict(attack.params)
        p["iv_shift"] = p.get("iv_shift", 0.0) + shift
        return _respec(attack, p), worlds
    return t


def exit_friction(extra: float):
    def t(attack, worlds):
        p = dict(attack.params)
        k = ("exit_friction_per_contract"
             if "entry_premium" in p else "round_trip_friction")
        p[k] = p.get(k, 0.0) + extra
        return _respec(attack, p), worlds
    return t


def delayed_entry(bars: int):
    def t(attack, worlds):
        from apex.edgeforge.multiverse import WorldBranch
        out = []
        for w in worlds:
            path = w.path[bars:] if len(w.path) > bars + 2 else w.path
            out.append(WorldBranch(
                branch_id=w.branch_id, parent_state_hash=w.parent_state_hash,
                hypothesis_condition=w.hypothesis_condition,
                generation_method="ADVERSARIAL_STRESS",
                generation_pedigree=f"[ADVERSARIAL_STRESS] DELAYED_ENTRY "
                                    f"{bars} bars on {w.branch_id}",
                path=path, source_session=w.source_session))
        return attack, out
    return t


def _respec(attack, params):
    from apex.edgeforge.attack_lab import CandidateAttack
    d = asdict(attack)
    d["params"] = params
    d["attack_id"] = f"{attack.attack_id}__stressed"
    d.pop("kind_", None)
    return CandidateAttack(**d)
