"""THE ARENA — candidates compete with each other AND with cash.

Every decision here is decomposed. There is deliberately no single
number, because the moment one exists somebody optimises it and the
reasoning becomes decoration.

    distribution · edge pedigree · redundancy · tail dependence
    risk concentration · execution burden · capital lockup
    catalyst exposure · opportunity cost · uncertainty

An action comes out. The reasoning stays componentwise, and every
refusal names which component refused.

decision_power: SHADOW_COUNTERFACTUAL_ONLY.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

NOT_ESTIMABLE = "NOT_ESTIMABLE"

ACTIONS = ("FUND", "PARTIALLY_FUND", "REFUSE_REDUNDANT",
           "REFUSE_RISK_CONCENTRATION", "DEFER_FOR_SUPERIOR_OPPORTUNITY",
           "CAPITAL_RESERVED", "NO_CAPITAL", "CASH_PREFERRED")

REDUNDANCY = ("INDEPENDENT", "PARTIALLY_REDUNDANT", "HIGHLY_REDUNDANT",
              "UNKNOWN")

EDGE_PEDIGREE = ("UNPROVEN", "REPLAY_ONLY", "PROSPECTIVE_THIN",
                 "PROSPECTIVE_ESTABLISHED")

# Index/sector membership sufficient to notice the obvious case. Not a
# correlation model -- a deliberately crude structural map, because a
# fitted correlation on 4 trades would be false precision.
INDEX_FAMILY = {
    "SPY": "US_LARGE_BETA", "QQQ": "US_LARGE_BETA",
    "IWM": "US_SMALL_BETA",
    "AAPL": "US_LARGE_BETA", "MSFT": "US_LARGE_BETA",
    "NVDA": "US_LARGE_BETA",
}
SECTOR = {"AAPL": "TECH", "MSFT": "TECH", "NVDA": "SEMIS",
          "SPY": "BROAD", "QQQ": "BROAD_TECH", "IWM": "BROAD_SMALL"}


class CapitalViolation(RuntimeError):
    pass


@dataclass
class Candidate:
    """One ATTACK_READY opportunity, as the arena sees it."""
    candidate_id: str
    symbol: str
    direction: str
    expression: str
    declared_risk: float
    max_gain: float | str = NOT_ESTIMABLE
    edge_pedigree: str = "UNPROVEN"
    signal_half_life_min: float | str = NOT_ESTIMABLE
    capital_lockup_min: float | str = NOT_ESTIMABLE
    execution_burden: float | str = NOT_ESTIMABLE
    catalyst_exposure: str = "UNKNOWN"
    why_small_wins: str = "UNKNOWN"
    entry_quality: str = "UNKNOWN"

    def __post_init__(self):
        if self.edge_pedigree not in EDGE_PEDIGREE:
            raise CapitalViolation(
                f"unknown edge_pedigree {self.edge_pedigree!r}")
        if not isinstance(self.declared_risk, (int, float)) \
                or self.declared_risk <= 0:
            raise CapitalViolation(
                "declared_risk must be positive: it is the 1R "
                "denominator and the only thing bounding this position")

    @property
    def beta_family(self) -> str:
        return INDEX_FAMILY.get(self.symbol, "UNKNOWN")

    @property
    def sector(self) -> str:
        return SECTOR.get(self.symbol, "UNKNOWN")

    def as_record(self) -> dict:
        return {"kind": "capital_candidate", **asdict(self),
                "beta_family": self.beta_family, "sector": self.sector}


@dataclass
class PortfolioState:
    available_capital: float
    open_positions: list = field(default_factory=list)

    @property
    def capital_at_risk(self) -> float:
        return round(sum(p.get("declared_risk", 0.0)
                         for p in self.open_positions), 2)

    def exposure(self, key: str) -> dict:
        out = {}
        for p in self.open_positions:
            k = p.get(key, "UNKNOWN")
            sign = 1 if p.get("direction") == "LONG" else -1
            out[k] = round(out.get(k, 0.0)
                           + sign * p.get("declared_risk", 0.0), 2)
        return out

    def as_record(self) -> dict:
        return {"kind": "portfolio_state",
                "available_capital": self.available_capital,
                "capital_at_risk": self.capital_at_risk,
                "n_positions": len(self.open_positions),
                "beta_family_exposure": self.exposure("beta_family"),
                "sector_exposure": self.exposure("sector"),
                "symbol_exposure": self.exposure("symbol")}


def redundancy(cand: Candidate, portfolio: PortfolioState,
               peers: list) -> dict:
    """Three tickers can be one bet. Say so out loud."""
    same_symbol, same_beta, same_sector = [], [], []
    for other in list(portfolio.open_positions) + [
            p.as_record() if hasattr(p, "as_record") else p
            for p in peers]:
        if other.get("candidate_id") == cand.candidate_id:
            continue
        if other.get("direction") != cand.direction:
            continue
        if other.get("symbol") == cand.symbol:
            same_symbol.append(other.get("symbol"))
        elif other.get("beta_family") == cand.beta_family \
                and cand.beta_family != "UNKNOWN":
            same_beta.append(other.get("symbol"))
        if other.get("sector") == cand.sector and cand.sector != "UNKNOWN":
            same_sector.append(other.get("symbol"))

    if same_symbol:
        cls, why = "HIGHLY_REDUNDANT", (
            f"same underlying and direction as {same_symbol}")
    elif len(same_beta) >= 2:
        cls, why = "HIGHLY_REDUNDANT", (
            f"{cand.symbol} plus {same_beta} in the same direction is "
            f"one {cand.beta_family} bet wearing "
            f"{len(same_beta) + 1} tickers")
    elif same_beta:
        cls, why = "PARTIALLY_REDUNDANT", (
            f"shares beta family {cand.beta_family} with {same_beta}")
    elif cand.beta_family == "UNKNOWN":
        cls, why = "UNKNOWN", "beta family not mapped for this symbol"
    else:
        cls, why = "INDEPENDENT", "no shared direction/beta/underlying"
    return {"kind": "redundancy_assessment", "classification": cls,
            "why": why, "same_symbol": same_symbol,
            "same_beta_family": same_beta, "same_sector": same_sector,
            "law": "correlation is not collapsed into a score; the "
                   "shared factor is named"}


def tail_dependence(cand: Candidate, portfolio: PortfolioState) -> dict:
    """Normal-times independence is not stress independence. Positions
    that merely rhyme in calm markets become one position in a
    liquidation, and that is exactly when it matters."""
    shared_beta = [p for p in portfolio.open_positions
                   if p.get("beta_family") == cand.beta_family]
    if cand.beta_family == "UNKNOWN":
        stress = "UNKNOWN"
        why = "beta family unmapped -- stress behaviour unknowable here"
    elif shared_beta:
        stress = "CONVERGES_UNDER_STRESS"
        why = (f"{len(shared_beta)} open position(s) share "
               f"{cand.beta_family}; in a shock these stop being "
               f"separate bets")
    else:
        stress = "NO_KNOWN_SHARED_STRESS_FACTOR"
        why = "no mapped shared factor -- absence of evidence only"
    return {"kind": "tail_dependence", "stress_behaviour": stress,
            "why": why, "shared_positions": len(shared_beta),
            "law": "historical correlation alone is insufficient"}


def opportunity_cost(cand: Candidate, *, session_minutes_left) -> dict:
    """Capital committed here cannot fund what appears later. Future
    opportunities are UNKNOWN and are not pretended otherwise."""
    lock = cand.capital_lockup_min
    if not isinstance(lock, (int, float)) or \
            not isinstance(session_minutes_left, (int, float)):
        return {"kind": "opportunity_cost", "assessment": NOT_ESTIMABLE,
                "why": "lockup or remaining session unknown"}
    frac = lock / session_minutes_left if session_minutes_left else 1.0
    return {"kind": "opportunity_cost",
            "lockup_minutes": lock,
            "session_minutes_left": session_minutes_left,
            "fraction_of_remaining_session": round(min(frac, 1.0), 3),
            "assessment": ("DOMINATES_REMAINING_SESSION" if frac >= 0.75
                           else "MATERIAL" if frac >= 0.4 else "MODEST"),
            "law": "future opportunities are UNKNOWN; this measures "
                   "what is given up, not what is missed"}


def compete(*, candidates: list, portfolio: PortfolioState,
            session_minutes_left=None,
            catalyst_environment: str = "UNKNOWN") -> dict:
    """Run the arena. Every candidate competes with the others and with
    cash; every action names the component that produced it."""
    decisions, funded = [], []
    remaining = portfolio.available_capital

    # unproven edges do not get to argue from size; ranking is by risk
    # ascending so the cheapest way to learn something goes first
    order = sorted(candidates, key=lambda c: c.declared_risk)

    for cand in order:
        red = redundancy(cand, portfolio, funded)
        tail = tail_dependence(cand, portfolio)
        oc = opportunity_cost(
            cand, session_minutes_left=session_minutes_left)
        reasons = []

        if cand.declared_risk > remaining:
            action = "NO_CAPITAL"
            reasons.append(
                f"declared risk {cand.declared_risk} exceeds remaining "
                f"{round(remaining, 2)}")
        elif red["classification"] == "HIGHLY_REDUNDANT":
            action = "REFUSE_REDUNDANT"
            reasons.append(red["why"])
        elif tail["stress_behaviour"] == "CONVERGES_UNDER_STRESS" \
                and len(portfolio.open_positions) >= 2:
            action = "REFUSE_RISK_CONCENTRATION"
            reasons.append(tail["why"])
        elif catalyst_environment in ("EVENT_HEAVY", "SHOCK") \
                and red["classification"] == "PARTIALLY_REDUNDANT":
            action = "CAPITAL_RESERVED"
            reasons.append(
                f"{catalyst_environment} environment with a partially "
                f"redundant book: reserve rather than stack")
        elif oc.get("assessment") == "DOMINATES_REMAINING_SESSION" \
                and cand.edge_pedigree == "UNPROVEN":
            action = "DEFER_FOR_SUPERIOR_OPPORTUNITY"
            reasons.append(
                "an unproven edge locking most of the remaining "
                "session is a poor claim on scarce capital")
        else:
            action = "FUND"
            reasons.append(
                f"{red['classification']}, risk {cand.declared_risk} "
                f"within remaining {round(remaining, 2)}")

        if action == "FUND":
            remaining -= cand.declared_risk
            rec = cand.as_record()
            rec["candidate_id"] = cand.candidate_id
            funded.append(rec)

        decisions.append({
            "candidate_id": cand.candidate_id, "symbol": cand.symbol,
            "direction": cand.direction, "action": action,
            "reasons": reasons, "redundancy": red,
            "tail_dependence": tail, "opportunity_cost": oc,
            "edge_pedigree": cand.edge_pedigree})

    if not decisions:
        return {"kind": "capital_arena", "verdict": "NO_CANDIDATES",
                "cash_preferred": True,
                "law": "zero candidates is not a failure",
                "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}

    n_funded = sum(1 for d in decisions if d["action"] == "FUND")
    return {"kind": "capital_arena",
            "evaluated_utc": datetime.now(timezone.utc).isoformat(),
            "n_candidates": len(decisions), "n_funded": n_funded,
            "capital_committed": round(
                portfolio.available_capital - remaining, 2),
            "capital_remaining": round(remaining, 2),
            "cash_preferred": n_funded == 0,
            "catalyst_environment": catalyst_environment,
            "decisions": decisions,
            "no_magic_score": True,
            "law": "a trade must be better than doing nothing; cash "
                   "has zero loss, zero friction and full optionality",
            "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}
