"""EQUITY SHADOW PAPER — a zero-authority execution simulator.

The question it answers: "had APEX been AUTHORIZED to trade this exact
opportunity at this exact moment, what would actually have happened?"
The counterfactual is authorization and nothing else — the thesis, the
entry/stop/target, the quote, and the clock are all real.

THE FROZEN ELIGIBILITY RULE (SHADOW_ELIGIBILITY_V1, declared before the
first session and never tuned intraday):

  1. an OFFICIAL Epoch-1 decision record exists (non-baseline playbook
     match, FORWARD_ELIGIBLE) — the frozen playbook already attached
     entry/stop/target, so the shadow executor FOLLOWS, never invents;
  2. its capital_decision exists and is not REFUSED;
  3. a REAL microscope quote for the symbol exists within
     QUOTE_MAX_AGE_S of eligibility — no quote, no fill: SHADOW_REFUSED,
     because a simulator that invents its execution inputs is a
     backtester wearing a paper jacket.

"This looks interesting, let's pretend we bought it" is unrepresentable:
open() takes a decision_id, not a thesis.

decision_power = NONE_RESEARCH_SHADOW. Never PAPER_ELIGIBLE, never a
broker call, never overnight (DAILY_FLAT applies: forced flat by 15:58
ET). Unknown execution inputs stay UNKNOWN — never zero.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

RESEARCH_SHADOW = "NONE_RESEARCH_SHADOW"
LEDGER = Path("results/frontier/shadow_paper_ledger.jsonl")

ELIGIBILITY_RULE = "SHADOW_ELIGIBILITY_V1"
QUOTE_MAX_AGE_S = 180
RISK_UNIT_USD = 100.0            # fixed research unit; sizing is not alpha
TIME_STOP_MINUTES = 90           # the frozen outcome-horizon maximum
FLAT_BY_ET = (15, 58)            # DAILY_FLAT: forced flat before close
SLIPPAGE_MODEL = "CROSS_SPREAD_ONLY_V1"   # stated limitation: crossing
# the recorded spread is the ONLY cost modeled; queueing/impact are NOT.

STATES = ("SHADOW_ELIGIBLE", "SHADOW_ENTRY_PENDING", "SHADOW_OPEN",
          "SHADOW_EXIT_PENDING", "SHADOW_FLAT", "SHADOW_REFUSED")


class ShadowViolation(RuntimeError):
    pass


def _append(rec: dict) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, {**rec,
                                  "decision_power": RESEARCH_SHADOW,
                                  "eligibility_rule": ELIGIBILITY_RULE,
                                  "slippage_model": SLIPPAGE_MODEL})


@dataclass(frozen=True)
class ShadowPosition:
    decision_id: str
    symbol: str
    side: str                      # LONG | SHORT
    state: str
    card_hash: str                 # the sealed BEFORE card this references
    entry_price: float | None = None
    entry_time: str | None = None
    spread_paid_frac: float | None = None
    stop: float | None = None
    target: float | None = None
    quantity: float | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    exit_reason: str | None = None

    def as_record(self) -> dict:
        return {"kind": "shadow_paper_position", **asdict(self)}


def eligible(decision: dict, capital: dict | None,
             card_hash: str | None) -> tuple:
    """(ok, reason). The FROZEN rule, mechanically."""
    if str(decision.get("playbook_id", "")).startswith("BASELINE-"):
        return False, "baselines are measurement, never trades"
    if decision.get("forward_eligibility") != "FORWARD_ELIGIBLE":
        return False, "not forward-eligible (birth law)"
    if capital is None:
        return False, "no capital decision exists"
    if capital.get("final_state") == "REFUSED":
        return False, "capital REFUSED — a refusal is not simulated away"
    if not card_hash:
        return False, "no sealed BEFORE decision card"
    for k in ("entry", "stop", "target", "direction"):
        if decision.get(k) is None:
            return False, f"decision lacks {k}: nothing to follow"
    return True, "eligible under " + ELIGIBILITY_RULE


def open_position(decision: dict, capital: dict | None, *,
                  card_hash: str | None, quote: dict | None,
                  now=None) -> ShadowPosition:
    """Simulate the fill from a REAL quote, or refuse. The executor
    follows the decision's own geometry — it invents nothing."""
    import pandas as pd
    now = pd.Timestamp(now) if now is not None else \
        pd.Timestamp.now(tz="UTC")
    ok, reason = eligible(decision, capital, card_hash)
    did, sym = decision.get("decision_id", "?"), decision.get("symbol", "?")
    side = "LONG" if decision.get("direction") == "LONG" else "SHORT"

    def refuse(why):
        p = ShadowPosition(decision_id=did, symbol=sym, side=side,
                           state="SHADOW_REFUSED", card_hash=card_hash or "",
                           exit_reason=why)
        _append(p.as_record())
        return p

    if not ok:
        return refuse(reason)
    bid = quote.get("bid") if quote else None
    ask = quote.get("ask") if quote else None
    qt = quote.get("quote_time") if quote else None
    if bid is None or ask is None or qt is None:
        return refuse("no usable bid/ask — unknown execution inputs stay "
                      "UNKNOWN, never zero; SHADOW_REFUSED")
    age = (now - pd.Timestamp(qt)).total_seconds()
    if age < 0:
        raise ShadowViolation("quote from the future offered for entry")
    if age > QUOTE_MAX_AGE_S:
        return refuse(f"quote {age:.0f}s old > {QUOTE_MAX_AGE_S}s")
    if float(ask) <= float(bid) or float(bid) <= 0:
        return refuse("crossed/absurd market")

    fill = float(ask) if side == "LONG" else float(bid)
    mid = (float(ask) + float(bid)) / 2
    stop, target = float(decision["stop"]), float(decision["target"])
    per_share_risk = abs(fill - stop)
    if per_share_risk <= 0:
        return refuse("fill already through the stop")
    qty = round(RISK_UNIT_USD / per_share_risk, 4)
    p = ShadowPosition(
        decision_id=did, symbol=sym, side=side, state="SHADOW_OPEN",
        card_hash=card_hash, entry_price=fill, entry_time=str(now),
        spread_paid_frac=round(abs(fill - mid) / mid, 6),
        stop=stop, target=target, quantity=qty)
    _append(p.as_record())
    return p


def manage(pos: ShadowPosition, bar: dict, now=None) -> ShadowPosition:
    """One deterministic management step on a COMPLETED 1m bar.
    Same-bar stop+target ambiguity resolves CONSERVATIVELY (stop first).
    The stop never widens because nothing here can write a stop at all.
    """
    import pandas as pd
    now = pd.Timestamp(now) if now is not None else \
        pd.Timestamp.now(tz="UTC")
    if pos.state != "SHADOW_OPEN":
        return pos
    hi, lo = float(bar["high"]), float(bar["low"])
    long_ = pos.side == "LONG"
    hit_stop = lo <= pos.stop if long_ else hi >= pos.stop
    hit_tgt = hi >= pos.target if long_ else lo <= pos.target
    et = now.tz_convert("America/New_York")
    flat_by = et.normalize() + pd.Timedelta(hours=FLAT_BY_ET[0],
                                            minutes=FLAT_BY_ET[1])
    age_min = (now - pd.Timestamp(pos.entry_time)).total_seconds() / 60
    if hit_stop:                       # conservative: stop before target
        exit_px, why = pos.stop, "STOP"
    elif hit_tgt:
        exit_px, why = pos.target, "TARGET"
    elif age_min >= TIME_STOP_MINUTES:
        exit_px, why = float(bar["close"]), "TIME_STOP_90M"
    elif et >= flat_by:
        exit_px, why = float(bar["close"]), "DAILY_FLAT_MANDATE"
    else:
        return pos
    closed = ShadowPosition(**{**asdict(pos), "state": "SHADOW_FLAT",
                               "exit_price": exit_px,
                               "exit_time": str(now), "exit_reason": why})
    sign = 1 if long_ else -1
    gross = sign * (exit_px - pos.entry_price) / pos.entry_price
    # exit cost: the entry's measured half-spread, reapplied as an
    # ESTIMATE (labeled — the exit quote was not observed)
    est_exit_cost = pos.spread_paid_frac
    rec = closed.as_record()
    rec.update({
        "gross_return_frac": round(gross, 6),
        "entry_cost_frac_measured": pos.spread_paid_frac,
        "exit_cost_frac_ESTIMATED": est_exit_cost,
        "net_return_frac": round(gross - pos.spread_paid_frac
                                 - est_exit_cost, 6),
        "r_multiple": round(sign * (exit_px - pos.entry_price)
                            / abs(pos.entry_price - pos.stop), 3),
        "hold_minutes": round(age_min, 1),
        "daily_flat_confirmed": True,
    })
    _append(rec)
    return closed
