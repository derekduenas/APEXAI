"""OptionExecutionModel — F O13: canonical economics never use midpoint
fantasy. CONSERVATIVE_TAKER (buy ask, sell bid) is the one real,
canonical fill mode tonight; DIAGNOSTIC_MIDPOINT is always reported
ALONGSIDE it for transparency, never in place of it.
EMPIRICALLY_CALIBRATED and STRESS are declared, unreachable until a
real fill-history dataset exists to calibrate from.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

FILL_MODES = ("CONSERVATIVE_TAKER", "DIAGNOSTIC_MIDPOINT",
             "EMPIRICALLY_CALIBRATED", "STRESS")
CANONICAL_FILL_MODE = "CONSERVATIVE_TAKER"
UNREACHABLE_FILL_MODES = {
    "EMPIRICALLY_CALIBRATED": "NO_FILL_HISTORY_DATASET_YET",
    "STRESS": "NO_CALIBRATED_BASELINE_TO_STRESS_YET",
}

LEG_FILL_TYPES = ("COMBO_FILL", "LEGGED_FILL")


class ExecutionModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class FillEstimate:
    fill_mode: str
    leg_fill_type: str
    entry_price: float | None
    exit_price: float | None
    spread_cost: float | None
    fees: float
    slippage: float
    is_canonical: bool
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.fill_mode not in FILL_MODES:
            raise ExecutionModelError(f"unknown fill_mode {self.fill_mode!r}")
        if self.fill_mode in UNREACHABLE_FILL_MODES:
            raise ExecutionModelError(
                f"{self.fill_mode} is declared unreachable tonight: "
                f"{UNREACHABLE_FILL_MODES[self.fill_mode]}")
        if self.leg_fill_type not in LEG_FILL_TYPES:
            raise ExecutionModelError(f"unknown leg_fill_type {self.leg_fill_type!r}")

    def as_record(self) -> dict:
        return asdict(self)


def conservative_taker_single_leg(*, bid: float | None, ask: float | None,
                                  side: str, fee_per_contract: float,
                                  known_from) -> FillEstimate:
    """side: 'BUY' (pays ask) or 'SELL' (receives bid). Returns a fill
    with price=None (UNKNOWN, not fabricated) if the required side of
    the quote is missing."""
    price = ask if side == "BUY" else bid
    spread_cost = (ask - bid) if (bid is not None and ask is not None) else None
    return FillEstimate(
        fill_mode=CANONICAL_FILL_MODE, leg_fill_type="COMBO_FILL",
        entry_price=price, exit_price=None, spread_cost=spread_cost,
        fees=fee_per_contract, slippage=0.0, is_canonical=True,
        known_from=str(known_from))


def diagnostic_midpoint_single_leg(*, bid: float | None, ask: float | None,
                                   fee_per_contract: float, known_from) -> FillEstimate:
    """Always accompanies, never replaces, the conservative estimate --
    explicitly labeled non-canonical."""
    mid = (bid + ask) / 2 if (bid is not None and ask is not None) else None
    return FillEstimate(
        fill_mode="DIAGNOSTIC_MIDPOINT", leg_fill_type="COMBO_FILL",
        entry_price=mid, exit_price=None, spread_cost=0.0,
        fees=fee_per_contract, slippage=0.0, is_canonical=False,
        known_from=str(known_from))


def vertical_conservative_fill(*, long_bid, long_ask, short_bid, short_ask,
                               fee_per_contract: float, known_from,
                               legged: bool = False) -> FillEstimate:
    """A debit vertical bought conservatively: pay ask on the long leg,
    receive bid on the short leg. `legged=True` marks this as two
    separate, non-simultaneous fills (legging risk), never assumed
    away."""
    if long_ask is None or short_bid is None:
        net_debit = None
    else:
        net_debit = long_ask - short_bid
    return FillEstimate(
        fill_mode=CANONICAL_FILL_MODE,
        leg_fill_type="LEGGED_FILL" if legged else "COMBO_FILL",
        entry_price=net_debit, exit_price=None,
        spread_cost=((long_ask - long_bid) + (short_ask - short_bid))
        if None not in (long_ask, long_bid, short_ask, short_bid) else None,
        fees=fee_per_contract * 2, slippage=0.0, is_canonical=True,
        known_from=str(known_from))
