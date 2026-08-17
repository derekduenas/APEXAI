"""EQUITY SHADOW PAPER — a zero-authority execution simulator.

The question it answers: "had APEX been AUTHORIZED to trade this exact
opportunity at this exact moment, what would actually have happened?"
The counterfactual is authorization and nothing else — the thesis, the
entry/stop/target, the quote, and the clock are all real.

THE FROZEN ELIGIBILITY RULE (SHADOW_ELIGIBILITY_V2, corrected pre-freeze
per operator review — "not REFUSED" accidentally admitted NO_TRADE):

  TWO COHORTS, never mixed:
    DECISION_FAITHFUL_SHADOW      Capital == PAPER_ELIGIBLE — what APEX
                                  would ACTUALLY have traded were the
                                  external paper lock removed. Zero of
                                  these on Monday is TRUTHFUL (the state
                                  is unreachable until calibration earns
                                  it).
    EXECUTION_RESEARCH_COUNTERFACTUAL
                                  Capital in (OBSERVE, WATCH) — what
                                  execution would have looked like on
                                  interesting-but-unauthorized names.
                                  NOT a paper trade; never enters the
                                  faithful cohort's statistics.
  NO_TRADE and REFUSED can NEVER become SHADOW_OPEN — a refusal is not
  simulated away; those cohorts stay available separately for
  selectivity analysis as REJECTED_COUNTERFACTUAL eligibility records.

  Plus: an OFFICIAL Epoch-1 decision (non-baseline, FORWARD_ELIGIBLE,
  entry/stop/target attached by the frozen playbook); the sealed BEFORE
  card hash; and a REAL quote passing THE ONE CANONICAL FRESHNESS LAW —
  the SAC1-15-repaired ExecutionGateway bound, imported, not redefined.
  A second freshness standard is how SAC1-15 happened.

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

ELIGIBILITY_RULE = "SHADOW_ELIGIBILITY_V2"
# ONE freshness law: the canonical, SAC1-15-repaired gateway bound.
# Deliberately imported, never redefined — mutate the gateway's constant
# and shadow eligibility changes with it (tested).
from apex.execution.gateway import MAX_QUOTE_AGE_S as QUOTE_MAX_AGE_S

COHORT_FAITHFUL = "DECISION_FAITHFUL_SHADOW"
COHORT_RESEARCH = "EXECUTION_RESEARCH_COUNTERFACTUAL"
COHORT_REJECTED = "REJECTED_COUNTERFACTUAL"
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
    cohort: str = "UNKNOWN"
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
    """(ok, cohort, reason). The FROZEN rule, mechanically."""
    if str(decision.get("playbook_id", "")).startswith("BASELINE-"):
        return False, None, "baselines are measurement, never trades"
    if decision.get("forward_eligibility") != "FORWARD_ELIGIBLE":
        return False, None, "not forward-eligible (birth law)"
    if capital is None:
        return False, None, "no capital decision exists"
    state = capital.get("final_state")
    if state in ("REFUSED", "NO_TRADE"):
        return False, COHORT_REJECTED, (
            f"capital {state} — a refusal is never simulated away; "
            f"recorded for selectivity analysis only")
    if not card_hash:
        return False, None, "no sealed BEFORE decision card"
    for k in ("entry", "stop", "target", "direction"):
        if decision.get(k) is None:
            return False, None, f"decision lacks {k}: nothing to follow"
    if state == "PAPER_ELIGIBLE":
        return True, COHORT_FAITHFUL, "would ACTUALLY have traded"
    if state in ("OBSERVE", "WATCH"):
        return True, COHORT_RESEARCH, (
            "execution research on an unauthorized candidate — NOT a "
            "paper trade")
    return False, None, f"unrecognized capital state {state!r}"


def open_position(decision: dict, capital: dict | None, *,
                  card_hash: str | None, quote: dict | None,
                  now=None) -> ShadowPosition:
    """Simulate the fill from a REAL quote, or refuse. The executor
    follows the decision's own geometry — it invents nothing."""
    import pandas as pd
    now = pd.Timestamp(now) if now is not None else \
        pd.Timestamp.now(tz="UTC")
    ok, cohort, reason = eligible(decision, capital, card_hash)
    did, sym = decision.get("decision_id", "?"), decision.get("symbol", "?")
    side = "LONG" if decision.get("direction") == "LONG" else "SHORT"

    def refuse(why):
        p = ShadowPosition(decision_id=did, symbol=sym, side=side,
                           state="SHADOW_REFUSED",
                           cohort=cohort or "UNKNOWN",
                           card_hash=card_hash or "", exit_reason=why)
        _append(p.as_record())
        return p

    if not ok:
        return refuse(reason)

    # SESSION-END ENTRY LAW: the executor's OWN geometry (TIME_STOP_
    # MINUTES) must fit inside the regular session before DAILY_FLAT. A
    # 35-second "trade" at 15:57 pollutes every statistic the horizon
    # defines; the cutoff derives from the frozen time stop, it is not a
    # discretionary number.
    et = now.tz_convert("America/New_York")
    flat_at = et.normalize() + pd.Timedelta(hours=FLAT_BY_ET[0],
                                            minutes=FLAT_BY_ET[1])
    if et + pd.Timedelta(minutes=TIME_STOP_MINUTES) > flat_at:
        return refuse("SHADOW_REFUSED_SESSION_END: insufficient regular-"
                      "session lifetime to express the frozen "
                      f"{TIME_STOP_MINUTES}m horizon before DAILY_FLAT")
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
        cohort=cohort,
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
