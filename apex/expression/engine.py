"""The expression engine: distribution + chain -> ranked structures.

INPUT CONTRACT (v4.0 section 1.2): a discretized pmf over horizon returns
that integrates to 1, a chain snapshot, and a MANDATORY distribution_source
that propagates to every output. An expression selected from an
UNCALIBRATED_MODEL or SYNTHETIC distribution can never be presented as a
recommendation -- `as_recommendation()` refuses.

ECONOMICS, stated plainly:
  * entries pay the ASK for what they buy and receive the BID for what they
    sell -- the spread is a real cost, never mid-priced away;
  * structures held past the horizon are RE-PRICED at the horizon with
    remaining life (Black-Scholes, flat IV persistence -- a declared
    ASSUMPTION), so theta is integrated over the holding period rather than
    quoted at spot;
  * defined-risk only: no naked short options exist in the structure set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

EVIDENCE_CLASS = "engineering_measurement"


class DistributionSource(Enum):
    SYNTHETIC = "SYNTHETIC"
    CALIBRATED = "CALIBRATED"
    UNCALIBRATED_MODEL = "UNCALIBRATED_MODEL"


class ExpressionError(ValueError):
    """An expression-engine contract was violated."""


class NotARecommendation(RuntimeError):
    """Only a CALIBRATED distribution can back a recommendation."""


@dataclass(frozen=True)
class OptionQuote:
    kind: str            # "call" | "put"
    strike: float
    expiry_days: int
    bid: float
    ask: float
    iv: float
    open_interest: int = 0
    volume: int = 0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def relative_spread(self) -> float:
        return (self.ask - self.bid) / self.mid if self.mid > 0 else float("inf")


@dataclass(frozen=True)
class ExpressionInput:
    horizon_days: int
    returns: np.ndarray          # discretized return grid
    probs: np.ndarray            # pmf over the grid; must sum to 1
    distribution_source: DistributionSource
    chain: tuple                 # OptionQuote, all expiries >= horizon
    spot: float
    borrow_ok: bool = True
    earnings_in_window: bool = False
    evidence_class: str = field(default=EVIDENCE_CLASS)

    def __post_init__(self):
        p = np.asarray(self.probs, dtype=float)
        if abs(float(p.sum()) - 1.0) > 1e-9:
            raise ExpressionError(f"pmf must integrate to 1; sums to {p.sum()}")
        if (p < 0).any():
            raise ExpressionError("pmf has negative mass")
        if len(p) != len(self.returns):
            raise ExpressionError("returns grid and pmf lengths differ")
        if not isinstance(self.distribution_source, DistributionSource):
            raise ExpressionError("distribution_source is mandatory and typed")
        for q in self.chain:
            if q.expiry_days < self.horizon_days:
                raise ExpressionError(
                    f"chain quote expiring in {q.expiry_days}d is inside the "
                    f"{self.horizon_days}d horizon; the engine re-prices at the "
                    f"horizon and cannot hold an expired contract")


# --- Black-Scholes for horizon re-pricing (flat IV persistence: ASSUMPTION) --

def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(kind: str, s: float, k: float, t_years: float, iv: float) -> float:
    """Zero-rate Black-Scholes. At t=0 returns intrinsic."""
    if t_years <= 0 or iv <= 0:
        intrinsic = max(s - k, 0.0) if kind == "call" else max(k - s, 0.0)
        return intrinsic
    d1 = (math.log(s / k) + 0.5 * iv * iv * t_years) / (iv * math.sqrt(t_years))
    d2 = d1 - iv * math.sqrt(t_years)
    if kind == "call":
        return s * _ncdf(d1) - k * _ncdf(d2)
    return k * _ncdf(-d2) - s * _ncdf(-d1)


def value_at_horizon(q: OptionQuote, spot_at_h: float, horizon_days: int) -> float:
    remaining = (q.expiry_days - horizon_days) / 365.0
    return bs_price(q.kind, spot_at_h, q.strike, remaining, q.iv)


# --- structures (defined-risk ONLY; every leg named) -------------------------

@dataclass(frozen=True)
class Structure:
    name: str
    buys: tuple = ()             # quotes bought at ASK
    sells: tuple = ()            # quotes sold at BID (always covered)
    stock_shares: float = 0.0    # underlying held

    def entry_cost(self, spot: float) -> float:
        cost = self.stock_shares * spot
        cost += sum(q.ask for q in self.buys)
        cost -= sum(q.bid for q in self.sells)
        return cost

    def pnl_at_horizon(self, spot: float, spot_at_h: float, horizon: int) -> float:
        value = self.stock_shares * spot_at_h
        value += sum(value_at_horizon(q, spot_at_h, horizon) for q in self.buys)
        value -= sum(value_at_horizon(q, spot_at_h, horizon) for q in self.sells)
        return value - self.entry_cost(spot)


def _nearest(chain, kind, target_strike):
    cands = [q for q in chain if q.kind == kind]
    if not cands:
        return None
    return min(cands, key=lambda q: abs(q.strike - target_strike))


def build_structures(inp: ExpressionInput) -> list[Structure]:
    """The fixed candidate set. Defined-risk only; a missing leg drops the
    structure rather than improvising one."""
    s = inp.spot
    atm_c = _nearest(inp.chain, "call", s)
    atm_p = _nearest(inp.chain, "put", s)
    otm_c = _nearest(inp.chain, "call", s * 1.05)
    otm_p = _nearest(inp.chain, "put", s * 0.95)

    out = [Structure("common_stock", stock_shares=1.0)]
    if atm_c:
        out.append(Structure("long_call", buys=(atm_c,)))
    if atm_p:
        out.append(Structure("long_put", buys=(atm_p,)))
    if atm_c and otm_c and atm_c.strike < otm_c.strike:
        out.append(Structure("call_debit_spread", buys=(atm_c,), sells=(otm_c,)))
        out.append(Structure("call_credit_spread", buys=(otm_c,), sells=(atm_c,)))
    if atm_p and otm_p and otm_p.strike < atm_p.strike:
        out.append(Structure("put_debit_spread", buys=(atm_p,), sells=(otm_p,)))
        out.append(Structure("put_credit_spread", buys=(otm_p,), sells=(atm_p,)))
    if otm_p:
        out.append(Structure("protective_put", buys=(otm_p,), stock_shares=1.0))
    if otm_p and otm_c:
        out.append(Structure("collar", buys=(otm_p,), sells=(otm_c,),
                             stock_shares=1.0))
    return out


# --- evaluation --------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    name: str
    expected_pnl: float
    utility: float
    pnl_p5: float
    pnl_p95: float
    max_loss: float
    entry_cost: float
    spread_cost: float           # what crossing the quotes cost vs mid
    liquidity_score: float       # min leg OI-and-spread score in [0,1]
    distribution_source: str
    evidence_class: str = field(default=EVIDENCE_CLASS)


@dataclass(frozen=True)
class ExpressionReport:
    selection: str
    candidates: tuple
    distribution_source: str
    objective: str
    risk_aversion: float
    evidence_class: str = field(default=EVIDENCE_CLASS)

    def as_recommendation(self) -> dict:
        """Only a CALIBRATED distribution may back a recommendation."""
        if self.distribution_source != DistributionSource.CALIBRATED.value:
            raise NotARecommendation(
                f"distribution_source={self.distribution_source}: this output "
                f"is infrastructure, not a recommendation. Calibration is "
                f"Group B evidence and accrues only in apex/reality/.")
        return {"selection": self.selection,
                "distribution_source": self.distribution_source,
                "evidence_class": self.evidence_class}


def _liquidity(structure: Structure) -> float:
    legs = list(structure.buys) + list(structure.sells)
    if not legs:
        return 1.0
    scores = []
    for q in legs:
        oi = min(q.open_interest / 500.0, 1.0)
        tight = max(0.0, 1.0 - q.relative_spread / 0.5)
        scores.append(0.5 * oi + 0.5 * tight)
    return float(min(scores))


def evaluate(inp: ExpressionInput, config) -> ExpressionReport:
    lam = float(config.get("expression.risk_aversion"))
    objective = str(config.get("expression.objective"))
    if objective != "exponential_utility":
        raise ExpressionError(f"undeclared objective {objective!r}")

    returns = np.asarray(inp.returns, dtype=float)
    probs = np.asarray(inp.probs, dtype=float)
    spots_h = inp.spot * (1 + returns)

    candidates = []
    for st in build_structures(inp):
        pnl = np.array([st.pnl_at_horizon(inp.spot, sh, inp.horizon_days)
                        for sh in spots_h])
        # utility on P&L per share of underlying notional (comparable basis)
        scaled = pnl / inp.spot
        utility = float(-(probs * np.exp(-lam * scaled)).sum())
        mid_cost = (st.stock_shares * inp.spot
                    + sum(q.mid for q in st.buys) - sum(q.mid for q in st.sells))
        order = np.argsort(pnl)
        cdf = np.cumsum(probs[order])
        p5 = float(pnl[order][np.searchsorted(cdf, 0.05)])
        p95 = float(pnl[order][min(np.searchsorted(cdf, 0.95), len(pnl) - 1)])
        candidates.append(Candidate(
            name=st.name,
            expected_pnl=round(float((probs * pnl).sum()), 6),
            utility=round(utility, 8),
            pnl_p5=round(p5, 4), pnl_p95=round(p95, 4),
            max_loss=round(float(pnl.min()), 4),
            entry_cost=round(st.entry_cost(inp.spot), 4),
            spread_cost=round(st.entry_cost(inp.spot) - mid_cost, 4),
            liquidity_score=round(_liquidity(st), 3),
            distribution_source=inp.distribution_source.value,
        ))

    best = max(candidates, key=lambda c: c.utility)
    return ExpressionReport(
        selection=best.name, candidates=tuple(candidates),
        distribution_source=inp.distribution_source.value,
        objective=objective, risk_aversion=lam,
    )
