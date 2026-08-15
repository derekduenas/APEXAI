"""APEX CAPITAL gate for Hunter candidates — Phase 4 of the integration
spine. One pipeline; this module is a SEAM, not a system.

It ADAPTS the existing economic machinery (portfolio.risk.assess_risk,
portfolio.capacity participation law, the opportunity engine's
uncertainty-raises-the-bar rule) to intraday candidates through explicit
typed interfaces. It rebuilds nothing and it executes nothing: no broker
import exists here, no order method is reachable, and LIVE_ELIGIBLE is not
a member of the state set.

THE FORECAST SLOT: Phase 3 (ML -> distributions -> calibration) is dark
until forward data earns it. Its place in the spine is typed NOW:
ForecastSlot(status=NOT_YET_AVAILABLE). A missing forecast prevents
capital authorization (PAPER_ELIGIBLE requires a commissioned forecast
path) but never kills the observational program — structurally sound
candidates proceed as OBSERVE and their outcomes keep accruing for
learning. Probabilities are never synthesized because the capital engine
would like to have them; in v1 even a PRESENT estimate is REFUSED
(GOVERNANCE_FAILURE: forecast path not commissioned), so no half-wired
edge numbers can leak in before Phase 3 is formally lit.

Final states (frozen): OBSERVE / WATCH / PAPER_ELIGIBLE / NO_TRADE /
REFUSED. Regime uncertainty is conservative-only: it can halve the risk
budget and cap the state at WATCH; it can never relax anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from apex.portfolio.capacity import MAX_PARTICIPATION
from apex.portfolio.risk import (MAX_POSITION_WEIGHT, PortfolioState,
                                 assess_risk)

CAPITAL_VERSION = "hunter_capital_v1"

# declared paper-research sizing template (within the TradeThesis <=0.5%
# risk law); the weight cap DEFERS to the existing risk engine's position
# limit — one law, one source of truth, the adapter never competes with it
PAPER_NAV_USD = 100_000.0
PAPER_RISK_BUDGET_FRAC = 0.0025          # NAV at the structural stop
INTRADAY_BUILD_DAYS = 1                  # capacity law: same-day in/out


class FinalState(Enum):
    OBSERVE = "OBSERVE"
    WATCH = "WATCH"
    PAPER_ELIGIBLE = "PAPER_ELIGIBLE"
    NO_TRADE = "NO_TRADE"
    REFUSED = "REFUSED"
    # LIVE_ELIGIBLE deliberately does not exist.


class Reason(Enum):
    NO_CALIBRATED_FORECAST = "NO_CALIBRATED_FORECAST"
    INSUFFICIENT_EDGE_EVIDENCE = "INSUFFICIENT_EDGE_EVIDENCE"
    REGIME_UNCERTAIN = "REGIME_UNCERTAIN"
    RISK_LIMIT = "RISK_LIMIT"
    CAPACITY_LIMIT = "CAPACITY_LIMIT"
    COST_UNKNOWN = "COST_UNKNOWN"
    PORTFOLIO_CONFLICT = "PORTFOLIO_CONFLICT"
    DATA_QUALITY = "DATA_QUALITY"
    GOVERNANCE_FAILURE = "GOVERNANCE_FAILURE"


FORECAST_NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"


@dataclass(frozen=True)
class ForecastSlot:
    """Phase 3's socket. status is the ONLY source of truth; nothing
    downstream may infer an expected return when it says NOT_YET_AVAILABLE."""
    status: str = FORECAST_NOT_YET_AVAILABLE
    estimate: object = None              # DistributionEstimate, Phase 3+


@dataclass(frozen=True)
class CapitalDecision:
    decision_id: str
    symbol: str
    playbook_id: str
    final_state: str
    reason_codes: tuple
    reasons_detail: tuple
    forecast_status: str
    weight: float | None
    target_notional_usd: float | None
    gates: dict
    capital_version: str = field(default=CAPITAL_VERSION)

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "capital_decision"
        return d


# declared CRUDE intraday uncertainty proxy (labeled as such): it may only
# raise caution, never lower it. The daily world-state classifier joins the
# intraday loop in a later wiring pass; until then unknown = uncertain.
MARKET_MOVE_UNCERTAIN = 0.015


def intraday_market_uncertain(market_cs) -> bool:
    if market_cs is None or market_cs.day_return is None:
        return True                                   # fail closed
    if market_cs.data_quality:
        return True
    return abs(market_cs.day_return) >= MARKET_MOVE_UNCERTAIN


def _hard_quality(cs_record: dict) -> tuple:
    hard = {"STALE_BARS", "SPARSE_BARS", "NO_RVOL_BASELINE", "NO_ATR_CONTEXT"}
    return tuple(sorted(hard.intersection(cs_record.get("data_quality", ()))))


def evaluate_candidate(candidate: dict, *, sector: str | None,
                       median_dollar_volume: float | None,
                       ann_vol: float | None,
                       market_uncertain: bool,
                       forecast: ForecastSlot,
                       portfolio: PortfolioState,
                       relative_spread: float | None = None,
                       nav_usd: float = PAPER_NAV_USD) -> CapitalDecision:
    """candidate: a playbook DECISION record from the forward ledger.
    Deterministic; every stage's numbers land in `gates`."""
    codes: list = []
    detail: list = []
    gates: dict = {"regime_uncertain": market_uncertain}

    def out(state: FinalState, weight=None, notional=None) -> CapitalDecision:
        return CapitalDecision(
            decision_id=candidate.get("decision_id", "?"),
            symbol=candidate.get("symbol", "?"),
            playbook_id=candidate.get("playbook_id", "?"),
            final_state=state.value,
            reason_codes=tuple(dict.fromkeys(c.value for c in codes)),
            reasons_detail=tuple(detail), forecast_status=forecast.status,
            weight=weight, target_notional_usd=notional, gates=gates)

    # 1. governance — fail closed before any economics
    risk_frac = candidate.get("risk_frac")
    missing = [k for k in ("decision_id", "playbook_id", "entry", "stop",
                           "target", "risk_frac") if candidate.get(k) is None]
    if missing or candidate.get("playbook_id", "").startswith("BASELINE-"):
        codes.append(Reason.GOVERNANCE_FAILURE)
        detail.append(f"not a capital candidate: missing {missing or 'n/a'}"
                      f" / baselines are measurement, not candidates")
        return out(FinalState.REFUSED)
    if candidate.get("forward_eligibility") != "FORWARD_ELIGIBLE":
        codes.append(Reason.GOVERNANCE_FAILURE)
        detail.append("capital never authorizes a non-evidence-grade "
                      "forecast (birth law)")
        return out(FinalState.REFUSED)

    # 2. data quality — unknown never becomes safe
    bad = _hard_quality(candidate.get("chart_state", {}))
    if bad:
        codes.append(Reason.DATA_QUALITY)
        detail.append(f"hard data-quality flags: {bad}")
        gates["data_quality"] = bad
        return out(FinalState.REFUSED)

    # 3. the forecast slot — typed, never synthesized
    if forecast.status == FORECAST_NOT_YET_AVAILABLE:
        codes.append(Reason.NO_CALIBRATED_FORECAST)
        codes.append(Reason.INSUFFICIENT_EDGE_EVIDENCE)
        detail.append("Phase 3 dark: candidate may be OBSERVED, never "
                      "capital-authorized; no expected return exists")
        gates["forecast"] = FORECAST_NOT_YET_AVAILABLE
    else:
        codes.append(Reason.GOVERNANCE_FAILURE)
        detail.append(f"forecast path not commissioned in {CAPITAL_VERSION}: "
                      f"status {forecast.status!r} refused until Phase 3 is "
                      f"formally lit (no half-wired edge numbers)")
        return out(FinalState.REFUSED)

    # 4. sizing from the declared template; regime uncertainty halves BOTH
    #    the risk budget and the position cap (conservative in every
    #    dimension, so caution survives whichever constraint binds)
    scale = 0.5 if market_uncertain else 1.0
    if market_uncertain:
        codes.append(Reason.REGIME_UNCERTAIN)
        detail.append("uncertain world state: risk budget and position cap "
                      "halved, final state capped at WATCH "
                      "(conservative-only rule)")
    weight = min(PAPER_RISK_BUDGET_FRAC * scale / risk_frac,
                 MAX_POSITION_WEIGHT * scale)
    notional = weight * nav_usd
    gates["sizing"] = {"risk_budget_frac": PAPER_RISK_BUDGET_FRAC * scale,
                       "weight": round(weight, 5),
                       "target_notional_usd": round(notional, 2)}

    # 5. risk — existing engine, constraints never selectors
    if ann_vol is None or sector is None:
        codes.append(Reason.DATA_QUALITY)
        detail.append("risk inputs unavailable (ann_vol/sector)")
        return out(FinalState.REFUSED)
    risk = assess_risk(weight=weight, ann_vol=ann_vol, sector=sector,
                       worst_case_loss_frac=risk_frac, is_defined_risk=True,
                       portfolio=portfolio)
    gates["risk"] = {"accepted": risk.accepted, "reasons": list(risk.reasons),
                     "consumption": risk.risk_consumption}
    if not risk.accepted:
        for r in risk.reasons:
            codes.append(Reason.PORTFOLIO_CONFLICT if "sector" in r
                         else Reason.RISK_LIMIT)
            detail.append(f"risk: {r}")
        return out(FinalState.NO_TRADE, weight, notional)

    # 6. capacity — participation law from the existing module
    if median_dollar_volume is None:
        codes.append(Reason.CAPACITY_LIMIT)
        detail.append("ADDV unknown: capacity cannot be assessed")
        return out(FinalState.NO_TRADE, weight, notional)
    cap_usd = MAX_PARTICIPATION * median_dollar_volume * INTRADAY_BUILD_DAYS
    gates["capacity"] = {"capacity_usd": round(cap_usd, 2),
                         "participation": MAX_PARTICIPATION}
    if notional > cap_usd:
        codes.append(Reason.CAPACITY_LIMIT)
        detail.append(f"notional {notional:,.0f} exceeds intraday capacity "
                      f"{cap_usd:,.0f}")
        return out(FinalState.NO_TRADE, weight, notional)

    # 7. cost — measured or UNKNOWN; a guess is not a measurement
    if relative_spread is None:
        codes.append(Reason.COST_UNKNOWN)
        detail.append("no measured spread: cost unknown blocks capital "
                      "authorization, not observation")
        gates["cost"] = "UNKNOWN"
    else:
        gates["cost"] = {"relative_spread": relative_spread}

    # 8. final state. PAPER_ELIGIBLE requires a commissioned forecast path,
    #    which v1 refuses above — so it is UNREACHABLE here by construction
    #    until Phase 3 lights the slot. That is the design, not a gap.
    if market_uncertain:
        return out(FinalState.WATCH, weight, notional)
    return out(FinalState.OBSERVE, weight, notional)
