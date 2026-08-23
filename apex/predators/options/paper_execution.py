"""OPTIONS PAPER EXECUTION + OUTCOME RESOLVER.

Deterministic simulated execution and honest resolution. Two laws
govern everything here:

FILL LAW  every option leg crosses ITS OWN contract's quoted side --
          long pays ASK, short receives BID. Stock crosses the
          executable side of the underlying. No midpoint, no
          theoretical/model price, no future-best strike or DTE.
          Every fill carries its pedigree so a later reader can see
          exactly which quote produced it.

SEQUENCE  the BEFORE card is sealed FIRST. Only then may the future be
LAW       revealed and the outcome resolved. `resolve()` refuses
          without a sealed card hash, so the ordering is structural
          rather than a matter of discipline.

COUNTERFACTUALS are MEASUREMENT ONLY: we resolve what stock / call /
vertical would each have done so the Predator can learn which weapon
suited the thesis -- never to retroactively "correct" the decision it
actually sealed.

decision_power: NONE_PAPER -- simulation. Authority OBSERVE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"
CONTRACT_MULTIPLIER = 100


class ExecutionRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class PaperFill:
    expression: str
    direction: str
    legs: tuple              # ((action, right, strike, price, side),)
    net_debit: float         # positive = we paid
    contracts: int
    capital_committed: float
    spread_paid: float | None
    fill_pedigree: tuple
    T: str
    expiration: str | None = None      # CONTRACT IDENTITY, see below
    # ---- RISK LAW: R is DECLARED BEFORE the trade, never inferred
    capital_deployed: float | str = NOT_ESTIMABLE
    maximum_theoretical_loss: float | str = NOT_ESTIMABLE
    planned_invalidation_loss: float | str = NOT_ESTIMABLE
    declared_1R_dollars: float | str = NOT_ESTIMABLE
    risk_basis: str = "NOT_DECLARED"
    execution_pedigree: str = "OBSERVED_QUOTE"
    risk_law: str = ("capital deployed, maximum theoretical loss and 1R "
                     "are three different numbers; R comes from the "
                     "sealed plan, never from the instrument default")
    law: str = ("each leg crossed its own contract's quoted side; no "
                "midpoint, no model price, no future-best selection")
    decision_power: str = "NONE_PAPER"

    def as_record(self) -> dict:
        return {"kind": "options_paper_fill", **asdict(self)}


def simulate_entry(candidate, *, T: str, contracts: int = 1,
                   sealed_card_hash: str | None = None,
                   risk_basis: str = "NOT_DECLARED",
                   planned_invalidation_loss: float | None = None
                   ) -> PaperFill:
    """Execute an ExpressionCandidate at quoted sides.

    RISK LAW: the caller declares how the sealed plan defines 1R. We
    refuse to guess. A long call held to expiry risks its premium; the
    same call abandoned when the underlying invalidates risks far less,
    and silently equating the two would corrupt every R-multiple this
    system ever reports."""
    if not sealed_card_hash or len(sealed_card_hash) < 32:
        raise ExecutionRefused(
            "paper execution requires a sealed BEFORE card -- the "
            "decision is sealed before it is filled, never after")
    legs, pedigree = [], []
    if candidate.expression == "STOCK":
        px = candidate.legs[0][3]
        side = "ASK_SIDE" if candidate.direction == "LONG" else "BID_SIDE"
        legs.append(("BUY" if candidate.direction == "LONG" else "SELL",
                     "STOCK", px, px, side))
        pedigree.append(f"STOCK crossed {side} at {px}")
        net = px * contracts * 1.0
        risk = _declare_risk(candidate, risk_basis,
                             planned_invalidation_loss, abs(net))
        return PaperFill(expression="STOCK",
                         direction=candidate.direction,
                         legs=tuple(legs), net_debit=round(net, 2),
                         contracts=contracts,
                         capital_committed=round(net, 2),
                         spread_paid=None, fill_pedigree=tuple(pedigree),
                         T=T, execution_pedigree=getattr(
                             candidate, "execution_pedigree",
                             "MODELLED_EXECUTION"), **risk)
    if not getattr(candidate, "expiration", None):
        raise ExecutionRefused(
            "option execution requires the contract's expiration -- a "
            "strike alone does not identify a contract, and resolving "
            "on strike only can price a different expiry")
    net = 0.0
    for action, right, strike, price in candidate.legs:
        side = "ASK" if action == "BUY" else "BID"
        legs.append((action, right, strike, price, side))
        pedigree.append(
            f"{action} {getattr(candidate, 'expiration', '?')} "
            f"{right}{strike} filled at that contract's {side} = {price}")
        net += price if action == "BUY" else -price
    net_total = net * CONTRACT_MULTIPLIER * contracts
    risk = _declare_risk(candidate, risk_basis, planned_invalidation_loss,
                         abs(net_total))
    return PaperFill(
        expression=candidate.expression, direction=candidate.direction,
        legs=tuple(legs), net_debit=round(net_total, 2),
        contracts=contracts, capital_committed=round(abs(net_total), 2),
        spread_paid=candidate.quoted_spread_cost,
        fill_pedigree=tuple(pedigree), T=T,
        expiration=getattr(candidate, "expiration", None),
        execution_pedigree=getattr(candidate, "execution_pedigree",
                                   "OBSERVED_QUOTE"), **risk)


def _declare_risk(candidate, risk_basis: str,
                  planned_invalidation_loss: float | None,
                  capital: float) -> dict:
    """Persist the three distinct risk numbers plus the declared 1R."""
    from apex.predators.options.expression import RISK_BASES
    mtl = getattr(candidate, "max_theoretical_loss", None)
    out = {"capital_deployed": round(capital, 2),
           "maximum_theoretical_loss": (round(mtl, 2) if mtl
                                        else NOT_ESTIMABLE),
           "planned_invalidation_loss": (planned_invalidation_loss
                                         if planned_invalidation_loss
                                         is not None else NOT_ESTIMABLE),
           "risk_basis": risk_basis}
    if risk_basis == "NOT_DECLARED":
        out["declared_1R_dollars"] = NOT_ESTIMABLE
        return out
    if risk_basis not in RISK_BASES:
        raise ExecutionRefused(f"unknown risk_basis {risk_basis!r}")
    if risk_basis == "PLANNED_INVALIDATION":
        r = planned_invalidation_loss
    elif risk_basis in ("MAX_LOSS", "FULL_PREMIUM"):
        r = mtl if mtl else capital
    else:
        r = planned_invalidation_loss
    out["declared_1R_dollars"] = (round(r, 2) if r else NOT_ESTIMABLE)
    return out


@dataclass(frozen=True)
class Outcome:
    sealed_card_hash: str
    expression: str
    entry: dict
    exit: dict
    pnl: float | str
    r_multiple: float | str
    mfe: float | str
    mae: float | str
    time_to_mfe_min: float | str
    time_to_mae_min: float | str
    time_to_invalidation_min: float | str
    time_to_target_min: float | str
    underlying_return_pct: float | str
    execution_cost: float | None
    risk_basis: str = "NOT_DECLARED"
    declared_1R_dollars: float | str = NOT_ESTIMABLE
    capital_deployed: float | str = NOT_ESTIMABLE
    maximum_theoretical_loss: float | str = NOT_ESTIMABLE
    iv_change: float | str = NOT_ESTIMABLE
    theta_impact: float | str = NOT_ESTIMABLE
    spread_impact: float | str = NOT_ESTIMABLE
    counterfactuals: dict = field(default_factory=dict)
    evidence_class: str = "HISTORICAL_DEVELOPMENT_REPLAY"
    law: str = ("counterfactuals are MEASUREMENT ONLY -- they may never "
                "retroactively alter the decision that was sealed")
    decision_power: str = "NONE_PAPER"

    def as_record(self) -> dict:
        return {"kind": "options_outcome", **asdict(self)}


def _exit_value(legs, expiration, expiration_lookup) -> float | None:
    """Mark the position out at quoted sides: we SELL longs at BID and
    BUY BACK shorts at ASK -- the honest round trip.

    The lookup is keyed on FULL contract identity (expiration, strike,
    right). Keying on strike alone would let a July quote close a June
    position."""
    total = 0.0
    for action, right, strike, _entry_px, _side in legs:
        if right == "STOCK":
            return None
        q = expiration_lookup(expiration, strike, right)
        if q is None:
            return None
        bid, ask = q
        if action == "BUY":
            total += bid          # closing a long: hit the BID
        else:
            total -= ask          # closing a short: pay the ASK
    return total


def resolve(*, fill: PaperFill, sealed_card_hash: str,
            future_underlying: list, future_quote_lookup,
            invalidation: float | None = None,
            target: float | None = None,
            entry_underlying: float | None = None,
            entry_options_state=None, exit_options_state=None) -> Outcome:
    """Resolve one sealed paper decision. Refuses without the card."""
    if not sealed_card_hash or len(sealed_card_hash) < 32:
        raise ExecutionRefused(
            "resolution requires the sealed BEFORE card hash")
    import pandas as pd

    # ---- underlying path
    ur, mfe_u, mae_u = NOT_ESTIMABLE, NOT_ESTIMABLE, NOT_ESTIMABLE
    t_mfe = t_mae = t_inval = t_target = NOT_ESTIMABLE
    if future_underlying and entry_underlying:
        closes = [(pd.Timestamp(b["t"]), b["c"]) for b in
                  future_underlying]
        t0 = closes[0][0]
        sign = 1.0 if fill.direction == "LONG" else -1.0
        excursions = [(t, sign * (c / entry_underlying - 1.0) * 100)
                      for t, c in closes]
        ur = round((closes[-1][1] / entry_underlying - 1.0) * 100, 4)
        best = max(excursions, key=lambda x: x[1])
        worst = min(excursions, key=lambda x: x[1])
        mfe_u, mae_u = round(best[1], 4), round(worst[1], 4)
        t_mfe = round((best[0] - t0).total_seconds() / 60, 1)
        t_mae = round((worst[0] - t0).total_seconds() / 60, 1)
        if invalidation is not None:
            hit = [t for t, c in closes
                   if (c <= invalidation if fill.direction == "LONG"
                       else c >= invalidation)]
            t_inval = (round((hit[0] - t0).total_seconds() / 60, 1)
                       if hit else NOT_ESTIMABLE)
        if target is not None:
            hit = [t for t, c in closes
                   if (c >= target if fill.direction == "LONG"
                       else c <= target)]
            t_target = (round((hit[0] - t0).total_seconds() / 60, 1)
                        if hit else NOT_ESTIMABLE)

    # ---- position exit at quoted sides
    pnl, r_mult = NOT_ESTIMABLE, NOT_ESTIMABLE
    exit_rec = {"method": "quoted-side round trip: sell longs at BID, "
                          "buy back shorts at ASK"}
    if fill.expression == "STOCK":
        if future_underlying and entry_underlying:
            last = future_underlying[-1]["c"]
            sign = 1.0 if fill.direction == "LONG" else -1.0
            pnl = round(sign * (last - entry_underlying) *
                        fill.contracts, 2)
            exit_rec["price"] = last
    else:
        ev = _exit_value(fill.legs, fill.expiration, future_quote_lookup)
        if ev is not None:
            gross = ev * CONTRACT_MULTIPLIER * fill.contracts
            pnl = round(gross - fill.net_debit, 2)
            exit_rec["net_credit_received"] = round(gross, 2)
    # R LAW: divide by the DECLARED 1R only. Capital deployed is not R.
    r_basis = fill.risk_basis
    if isinstance(pnl, float) and \
            isinstance(fill.declared_1R_dollars, (int, float)) and \
            fill.declared_1R_dollars > 0:
        r_mult = round(pnl / fill.declared_1R_dollars, 4)
    elif isinstance(pnl, float):
        r_mult = NOT_ESTIMABLE
        r_basis = "NOT_DECLARED -- R withheld rather than assumed"

    iv_ch = NOT_ESTIMABLE
    if entry_options_state is not None and exit_options_state is not None:
        a = getattr(entry_options_state, "atm_iv", None)
        b = getattr(exit_options_state, "atm_iv", None)
        if a and b:
            iv_ch = round(b - a, 5)

    return Outcome(
        sealed_card_hash=sealed_card_hash, expression=fill.expression,
        entry={"net_debit": fill.net_debit,
               "capital": fill.capital_committed,
               "pedigree": list(fill.fill_pedigree)},
        exit=exit_rec, pnl=pnl, r_multiple=r_mult,
        risk_basis=r_basis,
        declared_1R_dollars=fill.declared_1R_dollars,
        capital_deployed=fill.capital_deployed,
        maximum_theoretical_loss=fill.maximum_theoretical_loss,
        mfe=mfe_u, mae=mae_u, time_to_mfe_min=t_mfe,
        time_to_mae_min=t_mae, time_to_invalidation_min=t_inval,
        time_to_target_min=t_target, underlying_return_pct=ur,
        execution_cost=fill.spread_paid, iv_change=iv_ch)


def counterfactual_expressions(*, candidates: list, T: str,
                               sealed_card_hash: str,
                               future_underlying: list,
                               future_quote_lookup,
                               entry_underlying: float,
                               option_contracts: int = 1,
                               risk_basis: str = "NOT_DECLARED",
                               planned_losses: dict | None = None
                               ) -> dict:
    """Resolve EVERY expression that was available, so the Predator can
    learn which weapon suited the thesis. MEASUREMENT ONLY.

    COMPARABILITY LAW: one option contract controls
    CONTRACT_MULTIPLIER shares, so the stock counterfactual is sized to
    the SAME underlying exposure. Comparing one share against one
    contract would flatter the option's capital efficiency by 100x --
    a fake result, not an insight."""
    planned_losses = planned_losses or {}
    out = {}
    for c in candidates:
        qty = (option_contracts * CONTRACT_MULTIPLIER
               if c.expression == "STOCK" else option_contracts)
        try:
            f = simulate_entry(
                c, T=T, contracts=qty,
                sealed_card_hash=sealed_card_hash,
                risk_basis=risk_basis,
                planned_invalidation_loss=planned_losses.get(c.expression))
            o = resolve(fill=f, sealed_card_hash=sealed_card_hash,
                        future_underlying=future_underlying,
                        future_quote_lookup=future_quote_lookup,
                        entry_underlying=entry_underlying)
            out[c.expression] = {"pnl": o.pnl, "r": o.r_multiple,
                                 "round_trip_friction": getattr(
                                     c, "round_trip_friction", None),
                                 "max_loss_basis": getattr(
                                     c, "max_loss_basis", None),
                                 "risk_basis": o.risk_basis,
                                 "declared_1R_dollars":
                                 o.declared_1R_dollars,
                                 "capital": f.capital_committed,
                                 "execution_pedigree":
                                 f.execution_pedigree,
                                 "quantity": qty,
                                 "exposure_basis":
                                 f"{option_contracts} contract(s) "
                                 f"= {option_contracts * CONTRACT_MULTIPLIER}"
                                 f" shares of underlying exposure"}
        except ExecutionRefused:
            raise
        except Exception as e:                             # noqa: BLE001
            out[c.expression] = {"error": type(e).__name__}
    out["_law"] = ("measurement only -- the sealed decision is never "
                   "retroactively optimized against these results")
    out["_comparison_law"] = (
        "no expression winner may be declared from a single number. "
        "Delta-equivalent share exposure, equal declared risk and equal "
        "capital are DIFFERENT questions with different answers; report "
        "the basis or report nothing.")
    out["_winner"] = ("WITHHELD -- requires an explicit comparison "
                      "basis; see expression.normalize()")
    return out
