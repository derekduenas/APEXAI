"""OPTIONS PROSPECTIVE SCOREBOARD.

The Options Predator has architecture and no prospective combat memory.
This is the ledger that accumulates it.

Two disciplines are enforced here rather than remembered:

REFUSALS ARE EVIDENCE. A system that only records the trades it took
learns nothing about the trades it declined. Every pipeline stop is
counted at the stage it occurred, so "we refused 40 and attacked 3" is
visible -- and so is the opposite failure, a funnel that never refuses.

n_raw IS NOT n. Four decision instants inside one session are four
views of one day. The scoreboard reports the effective count next to
the raw one, always, so no summary can quietly inflate its own sample.

decision_power: NONE -- bookkeeping.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

# The funnel, in order. A candidate stops at exactly one stage.
PIPELINE_STAGES = (
    "CANDIDATE",             # something was looked at
    "SERIOUS",               # survived first-pass domain state
    "WAIT_FOR_ENTRY",        # thesis intact, location not yet attackable
    "ATTACK_READY",          # geometry + assassin cleared it
    "PAPER_ATTACKED",        # a simulated fill actually happened
)

STOP_REASONS = (
    "NO_DIRECTIONAL_THESIS",
    "INSUFFICIENT_SURFACE",
    "NO_EXPRESSIONS",
    "GEOMETRY_REFUSED",
    "ASSASSIN_REFUSED",
    "NO_TRADE",              # a legitimate, wanted outcome
    "EXECUTION_IMPOSSIBLE",
    "DATA_QUALITY",
)


@dataclass
class SessionScoreboard:
    session: str
    stages: dict = field(default_factory=dict)
    stops: dict = field(default_factory=dict)
    near_misses: list = field(default_factory=list)
    attacks: list = field(default_factory=list)
    symbol_sessions: set = field(default_factory=set)

    # ---------------------------------------------------------- record
    def stage(self, name: str) -> None:
        if name not in PIPELINE_STAGES:
            raise ValueError(f"unknown pipeline stage {name!r}")
        self.stages[name] = self.stages.get(name, 0) + 1

    def stop(self, reason: str, *, symbol=None, detail=None) -> None:
        if reason not in STOP_REASONS:
            raise ValueError(f"unknown stop reason {reason!r}")
        self.stops[reason] = self.stops.get(reason, 0) + 1

    def near_miss(self, *, symbol: str, T: str, missing: str) -> None:
        """Cleared everything but one gate. The most informative
        population we have: it isolates a single variable."""
        self.near_misses.append({"symbol": symbol, "T": T,
                                 "blocked_by": missing})

    def attack(self, *, symbol: str, T: str, expression: str,
               attribution=None) -> None:
        self.symbol_sessions.add((symbol, self.session))
        self.attacks.append({"symbol": symbol, "T": T,
                             "expression": expression,
                             "attribution": (attribution.as_record()
                                             if attribution else None)})

    # ---------------------------------------------------------- report
    def report(self) -> dict:
        from apex.predators.options.friction_attribution import summarize
        atts = [a["attribution"] for a in self.attacks if a["attribution"]]
        n_raw = len(self.attacks)
        n_eff = len(self.symbol_sessions)

        by_expression = {}
        for a in self.attacks:
            by_expression[a["expression"]] = \
                by_expression.get(a["expression"], 0) + 1

        # THESIS_RIGHT vs PROFITABLE -- the comparison that says whether
        # to work on forecasting or on execution.
        right = sum(1 for a in atts if a and a["primary_class"] in
                    ("THESIS_RIGHT_FRICTION_SURVIVED",
                     "THESIS_RIGHT_FRICTION_KILLED",
                     "THESIS_RIGHT_OPTION_LOST"))
        profitable = sum(1 for a in atts if a and
                         isinstance(a.get("executable_pnl"), (int, float))
                         and a["executable_pnl"] > 0)

        return {
            "kind": "options_session_scoreboard",
            "session": self.session,
            "pipeline": {s: self.stages.get(s, 0) for s in PIPELINE_STAGES},
            "stops": dict(self.stops),
            "refusals_total": sum(self.stops.values()),
            "near_misses": len(self.near_misses),
            "near_miss_detail": self.near_misses[:50],
            "attacks_raw": n_raw,
            "attacks_effective_lower_bound": n_eff,
            "by_expression": by_expression,
            "thesis_right": right,
            "profitable": profitable,
            "right_but_unprofitable": max(0, right - profitable),
            "friction": (summarize(_rehydrate(atts)) if atts else
                         {"n": 0, "headline": "no attacks resolved"}),
            "sample_law": "attacks_raw is NOT the sample size; several "
                          "attacks in one session are views of one day",
            "refusal_law": "refusals are evidence -- a funnel that never "
                           "refuses is not selective, and one that never "
                           "attacks is not a hunter",
            "evidence_class": "PROSPECTIVE_PAPER",
            "decision_power": "NONE",
        }


class _Rehydrated:
    """summarize() reads attributes; scoreboard stores dicts."""

    def __init__(self, d: dict):
        self.__dict__.update(d)


def _rehydrate(records: list) -> list:
    return [_Rehydrated(r) for r in records if r]


def combine(reports: list) -> dict:
    """Roll several sessions into a campaign view."""
    pipeline, stops, by_expr = {}, {}, {}
    raw = eff = right = prof = near = 0
    for r in reports:
        for k, v in r["pipeline"].items():
            pipeline[k] = pipeline.get(k, 0) + v
        for k, v in r["stops"].items():
            stops[k] = stops.get(k, 0) + v
        for k, v in r["by_expression"].items():
            by_expr[k] = by_expr.get(k, 0) + v
        raw += r["attacks_raw"]
        eff += r["attacks_effective_lower_bound"]
        right += r["thesis_right"]
        prof += r["profitable"]
        near += r["near_misses"]
    return {
        "kind": "options_campaign_scoreboard",
        "sessions": len(reports), "pipeline": pipeline, "stops": stops,
        "by_expression": by_expr, "attacks_raw": raw,
        "attacks_effective_lower_bound": eff,
        "near_misses": near,
        "thesis_right": right, "profitable": prof,
        "right_but_unprofitable": max(0, right - prof),
        "evidence_class": "PROSPECTIVE_PAPER",
        "law": "prospective paper evidence accumulates here; it does "
               "not become PAPER_AUTHORIZED by growing, only by being "
               "reviewed against a pre-registered standard",
    }
