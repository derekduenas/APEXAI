"""OptionExpressionOutcome — F O20: prospective-only resolution.
Every horizon whose timestamp has already passed is resolved TOGETHER,
in horizon order, off caller-supplied realized market facts -- this
module never fetches or invents prices itself, and it never resolves
a hand-picked favorable subset while skipping the rest.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.options_research import OPTIONS_RESEARCH_POWER

LEDGER = Path("results/options_research/outcomes.jsonl")

RESOLUTION_HORIZONS = ("5m", "15m", "30m", "60m", "close", "next_session")


class OutcomeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionExpressionOutcome:
    opportunity_id: str
    subject: str
    horizon: str
    horizon_timestamp: str
    resolved_at: str
    underlying_price_at_horizon: float | None
    structure_net_pnl: dict          # expression_type -> float | None
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.horizon not in RESOLUTION_HORIZONS:
            raise OutcomeError(f"unknown horizon {self.horizon!r}")

    def as_record(self) -> dict:
        return {"kind": "option_expression_outcome", **asdict(self)}


def _chain_write(rec: dict) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, rec)


def resolve_horizon(*, opportunity_id: str, subject: str, horizon: str,
                    horizon_timestamp, now, underlying_price_at_horizon,
                    structure_net_pnl: dict, known_from) -> OptionExpressionOutcome:
    import pandas as pd
    out = OptionExpressionOutcome(
        opportunity_id=opportunity_id, subject=subject, horizon=horizon,
        horizon_timestamp=str(pd.Timestamp(horizon_timestamp)),
        resolved_at=str(pd.Timestamp(now)),
        underlying_price_at_horizon=underlying_price_at_horizon,
        structure_net_pnl=dict(structure_net_pnl),
        known_from=str(pd.Timestamp(known_from)))
    _chain_write(out.as_record())
    return out


def resolve_all_due_horizons(*, opportunity_id: str, subject: str, now, known_from,
                             horizon_timestamps: dict, price_and_pnl_fn) -> tuple:
    """`horizon_timestamps`: {horizon_name: timestamp} for the horizons
    this opportunity actually defines. `price_and_pnl_fn(horizon,
    horizon_timestamp) -> (underlying_price, structure_net_pnl_dict)`
    supplies the realized facts. Only horizons already in the past
    relative to `now` are resolved, and ALL of them are, together."""
    import pandas as pd
    now_ts = pd.Timestamp(now)
    resolved = []
    for h in RESOLUTION_HORIZONS:
        if h not in horizon_timestamps:
            continue
        ts = pd.Timestamp(horizon_timestamps[h])
        if ts > now_ts:
            continue
        price, pnl = price_and_pnl_fn(h, ts)
        resolved.append(resolve_horizon(
            opportunity_id=opportunity_id, subject=subject, horizon=h,
            horizon_timestamp=ts, now=now_ts, underlying_price_at_horizon=price,
            structure_net_pnl=pnl, known_from=known_from))
    return tuple(resolved)
