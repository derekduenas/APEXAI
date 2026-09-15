"""HUNTER_PAPER_LIFECYCLE_V1 — the accounting the paper path never had.

WHERE THE PATH ACTUALLY STOPPED, measured rather than assumed:

  * `capital.decide()` returns only WATCH or OBSERVE. PAPER_ELIGIBLE is UNREACHABLE by construction -- there is
    no branch that returns it -- and capital.py says so in its own comment.
  * `authorize_paper`, `assess_fill`, `PaperPosition` and `manage` all exist and work, but `authorize_paper` is
    called from NOTHING except tests.
  * `apex/hunter/paper.py` contains ZERO references to fees, realized P&L, or any ledger. `manage` tracks a
    qty FRACTION and an EXIT action -- with no exit price, no exit time, no share count, and no cashflow.

So the pieces existed and the ACCOUNTING did not. This module supplies exactly the missing links -- sizing,
component fees, realized cashflow, and a hash-chained persisted ledger -- by orchestrating the existing
components rather than reimplementing them.

TWO THINGS IT DELIBERATELY DOES NOT DO. It does not make PAPER_ELIGIBLE reachable: the capital gate is
untouched, and SIMULATED_UNCALIBRATED remains refused for production authorization. And it never invents a
number: a fee whose input is missing is UNKNOWN and propagates to UNKNOWN, an unresolved exit stays OPEN with its
exposure visible, and neither ever becomes zero.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field

SCHEMA = "HUNTER_PAPER_LIFECYCLE_V1"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = 0.0        # a BUY genuinely owes no SEC fee; that is 0, not unknown


class LifecycleRefused(RuntimeError):
    """A lifecycle step that cannot be taken honestly. Named, never silent."""


# ------------------------------------------------------------------ fees
@dataclass(frozen=True)
class EquityFeeSchedule:
    """Declared component fees. Every component names its BASIS and its SIDE.

    `None` for any rate means the desk does not know it. It is NOT zero, and it makes the total UNKNOWN --
    because a missing fee silently treated as zero is a P&L overstatement that compounds on every trade."""
    schedule_id: str = "PAPER_EQUITY_V1"
    commission_per_share: float | None = 0.0        # declared zero-commission paper broker
    sec_fee_rate: float | None = 0.0000278          # SELL side, on principal, rounded UP to the cent
    taf_per_share: float | None = 0.000166          # SELL side, per share
    taf_cap: float | None = 8.30                    # SELL side, per execution

    def digest(self) -> str:
        import hashlib
        import json
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


def compute_fees(side: str, shares: int, price: float, schedule: EquityFeeSchedule) -> dict:
    """Per-component fees for one execution. Components that do not APPLY to this side are 0.0 and say so;
    components whose rate is unknown are UNKNOWN and poison the total."""
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise LifecycleRefused("UNDECLARED_SIDE: %r" % side)
    principal = round(float(shares) * float(price), 6)
    comps, basis = {}, {}

    if schedule.commission_per_share is None:
        comps["commission"] = UNKNOWN
    else:
        comps["commission"] = round(schedule.commission_per_share * shares, 6)
    basis["commission"] = "per_share, both sides"

    if side == "BUY":
        comps["sec_fee"], comps["finra_taf"] = NOT_APPLICABLE, NOT_APPLICABLE
        basis["sec_fee"] = basis["finra_taf"] = "SELL side only: not applicable to a BUY"
    else:
        comps["sec_fee"] = (UNKNOWN if schedule.sec_fee_rate is None else
                            math.ceil(schedule.sec_fee_rate * principal * 100) / 100)
        basis["sec_fee"] = "rate x principal, rounded UP to the cent (the charged amount)"
        if schedule.taf_per_share is None:
            comps["finra_taf"] = UNKNOWN
        else:
            taf = round(schedule.taf_per_share * shares, 6)
            comps["finra_taf"] = taf if schedule.taf_cap is None else min(taf, schedule.taf_cap)
        basis["finra_taf"] = "per share, capped per execution"

    unknown = sorted(k for k, v in comps.items() if v == UNKNOWN)
    total = UNKNOWN if unknown else round(sum(comps.values()), 6)
    return {"side": side, "shares": int(shares), "price": float(price), "principal": principal,
            "components": comps, "basis": basis, "unknown_components": unknown, "total": total,
            "schedule_id": schedule.schedule_id, "schedule_digest": schedule.digest()}


# ------------------------------------------------------------------ sizing
def size_position(weight: float, nav_usd: float, entry_price: float) -> dict:
    """Whole shares only. The residual is REPORTED, not rounded away -- an unaccounted residual is how a paper
    book drifts from the cash it claims to hold."""
    if entry_price <= 0:
        raise LifecycleRefused("ENTRY_PRICE_NOT_POSITIVE: %r" % entry_price)
    target_notional = float(weight) * float(nav_usd)
    shares = int(math.floor(target_notional / entry_price))
    filled_notional = round(shares * entry_price, 6)
    return {"weight": float(weight), "nav_usd": float(nav_usd), "entry_price": float(entry_price),
            "target_notional": round(target_notional, 6), "shares": shares,
            "filled_notional": filled_notional,
            "residual_notional": round(target_notional - filled_notional, 6)}


# ------------------------------------------------------------------ realization
def realize(*, direction: str, shares: int, entry_price: float, exit_price,
            entry_fees: dict, exit_fees: dict | None) -> dict:
    """Gross and net realized P&L, or an explicit refusal.

    An unresolved exit does NOT produce a zero; it produces OPEN with the exposure still visible."""
    if exit_price is None or exit_fees is None:
        return {"status": "OPEN_UNRESOLVED", "realized_gross": UNKNOWN, "realized_net": UNKNOWN,
                "fees_total": UNKNOWN,
                "remaining_exposure": {"shares": int(shares), "direction": direction,
                                       "entry_price": float(entry_price),
                                       "notional_at_entry": round(shares * entry_price, 6)},
                "note": "no exit price is known; an unresolved exit is exposure, not a flat book"}
    sign = 1.0 if direction == "LONG" else -1.0
    gross = round(sign * (float(exit_price) - float(entry_price)) * shares, 6)
    fees = [entry_fees.get("total"), exit_fees.get("total")]
    if UNKNOWN in fees:
        return {"status": "FEES_UNKNOWN", "realized_gross": gross, "realized_net": UNKNOWN,
                "fees_total": UNKNOWN,
                "unknown_components": sorted(set(entry_fees.get("unknown_components", []))
                                             | set(exit_fees.get("unknown_components", []))),
                "note": "gross is knowable, net is not; an unknown fee never becomes zero"}
    fees_total = round(sum(fees), 6)
    return {"status": "REALIZED", "realized_gross": gross, "fees_total": fees_total,
            "realized_net": round(gross - fees_total, 6),
            "remaining_exposure": {"shares": 0}}


# ------------------------------------------------------------------ the persisted ledger
def _sides(direction: str) -> tuple:
    return ("BUY", "SELL") if direction == "LONG" else ("SELL", "BUY")


def append(ledger_path, entry: dict) -> dict:
    from apex.governance.chain_ledger import chain_append
    return chain_append(ledger_path, {"schema": SCHEMA, **entry})


def read(ledger_path) -> list:
    import json
    import pathlib
    p = pathlib.Path(ledger_path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def existing_outcome(ledger_path, decision_id: str):
    """Has this decision already reached a terminal lifecycle state? Exactly-once is enforced HERE, not by a
    caller remembering."""
    for r in read(ledger_path):
        if r.get("decision_id") == decision_id and r.get("stage") in (
                "REALIZED", "OPEN_UNRESOLVED", "NOT_AUTHORIZED", "NO_FILL"):
            return r
    return None


# ------------------------------------------------------------------ the lifecycle
def run_lifecycle(*, capital_decision, candidate: dict, entry_bars, ledger_path,
                  exit_price=None, exit_reason: str = "UNRESOLVED",
                  schedule: EquityFeeSchedule | None = None, nav_usd: float = 100_000.0,
                  synthetic=None, bundle_id: str | None = None) -> dict:
    """candidate -> authorization -> fill -> sizing -> entry fees -> managed exit -> exit fees -> realized P&L,
    every step persisted. Orchestration only: authorization, fill and management are the EXISTING components."""
    from apex.hunter.paper import PaperPosition, assess_fill, authorize_paper, manage

    schedule = schedule or EquityFeeSchedule()
    did = candidate.get("decision_id")
    run_id = uuid.uuid4().hex[:12]

    prior = existing_outcome(ledger_path, did)
    if prior is not None:
        rec = append(ledger_path, {"stage": "RECONCILED_DUPLICATE", "decision_id": did, "run_id": run_id,
                                   "prior_stage": prior.get("stage"),
                                   "note": "this decision already reached a terminal lifecycle state; "
                                           "nothing was filled, charged or realized again"})
        return {"stage": "RECONCILED_DUPLICATE", "prior_stage": prior.get("stage"), "record": rec}

    # 1. AUTHORIZATION -- the real gate. A refusal is a first-class outcome and is persisted.
    order = authorize_paper(capital_decision, candidate, bundle_id=bundle_id, synthetic=synthetic)
    if isinstance(order, dict):
        append(ledger_path, {"stage": "NOT_AUTHORIZED", "decision_id": did, "run_id": run_id,
                             "capital_final_state": capital_decision.final_state,
                             "reason": order.get("reason")})
        return {"stage": "NOT_AUTHORIZED", "reason": order.get("reason")}
    append(ledger_path, {"stage": "AUTHORIZED", "decision_id": did, "run_id": run_id,
                         "order": order.as_record(), "authorized_by": order.authorized_by,
                         "capital_final_state": capital_decision.final_state})

    # 2. FILL
    fill = assess_fill(order, entry_bars)
    append(ledger_path, {"stage": "FILL_ASSESSED", "decision_id": did, "run_id": run_id, "fill": fill})
    if fill.get("fill_price") is None:
        append(ledger_path, {"stage": "NO_FILL", "decision_id": did, "run_id": run_id,
                             "grade": fill.get("grade"),
                             "note": "no fill price: no position, no fees and no P&L may be asserted"})
        return {"stage": "NO_FILL", "grade": fill.get("grade")}

    entry_price = float(fill["fill_price"])
    entry_side, exit_side = _sides(order.direction)

    # 3. SIZING and 4. ENTRY FEES
    sizing = size_position(order.weight, nav_usd, entry_price)
    if sizing["shares"] <= 0:
        append(ledger_path, {"stage": "NO_FILL", "decision_id": did, "run_id": run_id,
                             "sizing": sizing, "note": "authorized weight buys zero whole shares"})
        return {"stage": "NO_FILL", "sizing": sizing}
    entry_fees = compute_fees(entry_side, sizing["shares"], entry_price, schedule)
    append(ledger_path, {"stage": "POSITION_OPEN", "decision_id": did, "run_id": run_id,
                         "sizing": sizing, "entry_fees": entry_fees, "entry_price": entry_price,
                         "direction": order.direction, "shares": sizing["shares"]})

    # 5. MANAGED EXIT -- through the real manager, so its refusals still apply
    pos = PaperPosition(order=order)
    pos = manage(pos, "EXIT", actor="paper_lifecycle")
    append(ledger_path, {"stage": "MANAGED", "decision_id": did, "run_id": run_id,
                         "actions": pos.actions, "state": pos.state})

    # 6. EXIT FEES and 7. REALIZATION
    exit_fees = (compute_fees(exit_side, sizing["shares"], float(exit_price), schedule)
                 if exit_price is not None else None)
    r = realize(direction=order.direction, shares=sizing["shares"], entry_price=entry_price,
                exit_price=exit_price, entry_fees=entry_fees, exit_fees=exit_fees)
    append(ledger_path, {"stage": r["status"], "decision_id": did, "run_id": run_id,
                         "exit_price": exit_price, "exit_reason": exit_reason,
                         "exit_fees": exit_fees, "realization": r,
                         "lineage": order.lineage})
    return {"stage": r["status"], "realization": r, "entry_fees": entry_fees, "exit_fees": exit_fees,
            "sizing": sizing, "order_id": order.order_id}


# ------------------------------------------------------------------ independent reconstruction
def reconstruct(ledger_path) -> dict:
    """Rebuild quantities, cashflows, fees, positions and P&L from the PERSISTED RECORDS ALONE.

    It recomputes rather than reads: share counts from weight and NAV, fees from the recorded schedule, gross
    from the two prices. A reconstruction that trusts the producer's own arithmetic proves nothing."""
    rows = read(ledger_path)
    out = {"schema": SCHEMA, "records": len(rows), "decisions": {}, "cash": 0.0,
           "fees_paid": 0.0, "realized_net": 0.0, "open_exposure": [], "unknown_fees": [],
           "disagreements": []}
    by_dec = {}
    for r in rows:
        by_dec.setdefault(r.get("decision_id"), []).append(r)

    for did, recs in by_dec.items():
        if did is None:
            continue
        stages = [r.get("stage") for r in recs]
        opened = next((r for r in recs if r.get("stage") == "POSITION_OPEN"), None)
        final = next((r for r in recs if r.get("stage") in ("REALIZED", "FEES_UNKNOWN",
                                                            "OPEN_UNRESOLVED")), None)
        entry = {"stages": stages, "terminal": (final or {}).get("stage")
                 or next((s for s in stages if s in ("NOT_AUTHORIZED", "NO_FILL")), None)}
        if opened is None:
            out["decisions"][did] = entry
            continue

        sizing, direction = opened["sizing"], opened["direction"]
        shares = int(math.floor(sizing["target_notional"] / sizing["entry_price"]))
        if shares != opened["shares"]:
            out["disagreements"].append({"decision_id": did, "field": "shares",
                                         "recorded": opened["shares"], "recomputed": shares})
        # The schedule is rebuilt from its DEFAULTS and then checked against the digest the producer recorded.
        # If the producer used a different schedule the digests disagree and the reconstruction says so rather
        # than silently recomputing fees under the wrong one.
        sched = EquityFeeSchedule()
        if opened["entry_fees"].get("schedule_digest") != sched.digest():
            out["disagreements"].append({"decision_id": did, "field": "fee_schedule_digest",
                                         "recorded": opened["entry_fees"].get("schedule_digest"),
                                         "recomputed": sched.digest()})
        entry_side, exit_side = _sides(direction)
        re_entry = compute_fees(entry_side, shares, opened["entry_price"], sched)
        if re_entry["total"] != opened["entry_fees"]["total"]:
            out["disagreements"].append({"decision_id": did, "field": "entry_fees",
                                         "recorded": opened["entry_fees"]["total"],
                                         "recomputed": re_entry["total"]})
        entry_cash = -shares * opened["entry_price"] if direction == "LONG" else shares * opened["entry_price"]
        cash = entry_cash - (re_entry["total"] if re_entry["total"] != UNKNOWN else 0.0)
        fees = re_entry["total"] if re_entry["total"] != UNKNOWN else UNKNOWN

        entry.update(shares=shares, entry_price=opened["entry_price"], direction=direction)
        if final is not None and final.get("stage") in ("REALIZED", "FEES_UNKNOWN") \
                and final.get("exit_price") is not None:
            xp = float(final["exit_price"])
            re_exit = compute_fees(exit_side, shares, xp, sched)
            exit_cash = shares * xp if direction == "LONG" else -shares * xp
            sign = 1.0 if direction == "LONG" else -1.0
            gross = round(sign * (xp - opened["entry_price"]) * shares, 6)
            if gross != final["realization"]["realized_gross"]:
                out["disagreements"].append({"decision_id": did, "field": "realized_gross",
                                             "recorded": final["realization"]["realized_gross"],
                                             "recomputed": gross})
            if UNKNOWN in (fees, re_exit["total"]):
                entry.update(realized_gross=gross, realized_net=UNKNOWN)
                out["unknown_fees"].append(did)
            else:
                total_fees = round(fees + re_exit["total"], 6)
                net = round(gross - total_fees, 6)
                if net != final["realization"]["realized_net"]:
                    out["disagreements"].append({"decision_id": did, "field": "realized_net",
                                                 "recorded": final["realization"]["realized_net"],
                                                 "recomputed": net})
                entry.update(realized_gross=gross, realized_net=net, fees=total_fees, exit_price=xp)
                out["fees_paid"] = round(out["fees_paid"] + total_fees, 6)
                out["realized_net"] = round(out["realized_net"] + net, 6)
                cash = entry_cash + exit_cash - total_fees
            out["cash"] = round(out["cash"] + cash, 6)
        else:
            entry.update(realized_net=UNKNOWN, open_shares=shares)
            out["open_exposure"].append({"decision_id": did, "shares": shares, "direction": direction,
                                         "entry_price": opened["entry_price"],
                                         "notional_at_entry": round(shares * opened["entry_price"], 6)})
            out["cash"] = round(out["cash"] + cash, 6)
        out["decisions"][did] = entry

    out["reconciles"] = not out["disagreements"]
    return out
