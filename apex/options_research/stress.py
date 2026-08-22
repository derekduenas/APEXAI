"""Latency / cost stress matrix — F O21. Canonical economics
(CONSERVATIVE_TAKER, zero delay) are never reported alone; every
candidate's economics are also shown under wider spreads and slower
entries so a thesis that only "works" at fantasy costs is visible as
such. A cell with no `decay_per_minute` input leaves its delayed
net_expectancy as None (UNKNOWN), never fabricated from thin air.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

COST_MULTIPLIERS = (("BASE", 1.0), ("1.5X", 1.5), ("2.0X", 2.0))
ENTRY_DELAY_MINUTES = (0, 1, 5, 15)


class StressError(RuntimeError):
    pass


@dataclass(frozen=True)
class StressCell:
    cost_label: str
    cost_multiplier: float
    entry_delay_minutes: int
    adjusted_spread_cost: float | None
    adjusted_fees: float | None
    adjusted_net_expectancy: float | None
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StressMatrix:
    subject: str
    expression_type: str
    cells: tuple
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if len(self.cells) != len(COST_MULTIPLIERS) * len(ENTRY_DELAY_MINUTES):
            raise StressError(
                f"expected {len(COST_MULTIPLIERS) * len(ENTRY_DELAY_MINUTES)} "
                f"cells, got {len(self.cells)}")

    def as_record(self) -> dict:
        return {"kind": "option_stress_matrix", "subject": self.subject,
                "expression_type": self.expression_type,
                "known_from": self.known_from, "decision_power": self.decision_power,
                "cells": [c.as_record() for c in self.cells]}

    def worst_case_net_expectancy(self) -> float | None:
        known = [c.adjusted_net_expectancy for c in self.cells
                if c.adjusted_net_expectancy is not None]
        return min(known) if known else None


def build_stress_matrix(*, subject: str, expression_type: str,
                        base_spread_cost: float | None, base_fees: float | None,
                        base_net_expectancy: float | None,
                        decay_per_minute: float | None, known_from) -> StressMatrix:
    import pandas as pd
    kf = str(pd.Timestamp(known_from))
    cells = []
    for label, mult in COST_MULTIPLIERS:
        for delay in ENTRY_DELAY_MINUTES:
            spread = (base_spread_cost * mult) if base_spread_cost is not None else None
            fees = (base_fees * mult) if base_fees is not None else None
            if base_net_expectancy is None:
                net = None
            elif delay == 0:
                net = base_net_expectancy - (
                    (spread or 0.0) - (base_spread_cost or 0.0)) - (
                    (fees or 0.0) - (base_fees or 0.0))
            elif decay_per_minute is None:
                net = None
            else:
                decayed = base_net_expectancy - decay_per_minute * delay
                extra_cost = ((spread or 0.0) - (base_spread_cost or 0.0)) + \
                            ((fees or 0.0) - (base_fees or 0.0))
                net = decayed - extra_cost
            cells.append(StressCell(
                cost_label=label, cost_multiplier=mult, entry_delay_minutes=delay,
                adjusted_spread_cost=spread, adjusted_fees=fees,
                adjusted_net_expectancy=net, known_from=kf))
    return StressMatrix(subject=subject, expression_type=expression_type,
                        cells=tuple(cells), known_from=kf)
