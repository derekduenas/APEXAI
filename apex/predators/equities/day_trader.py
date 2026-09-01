"""EQUITY DAY TRADER — a SHADOW predator. Zero capital authority.

It exists to answer one question the Options sleeve cannot answer about
itself:

    IF THE UNDERLYING THESIS WAS RIGHT, WOULD DIRECTLY TRADING THE
    STOCK HAVE MONETIZED IT BETTER THAN THE OPTION STRUCTURE?

and, independently, whether direct equity can find high-quality
intraday locations at all.

IT IS NOT AN OPTIONS MIRROR. Converting "Options says LONG" into "buy
stock" would measure nothing: the two sleeves would share every error
and the comparison would be circular. This sleeve forms its own setup
from shared market state, and is allowed to disagree, to refuse, and to
find nothing.

REUSES THE COMMISSIONED GEOMETRY. EquityAttackGeometry already answers
location, chase and invalidation; this module adds only what did not
exist: setup classification, a structural risk model, and a marketable
execution model. Rebuilding geometry here would have created a second
opinion about the same question.

decision_power: SHADOW_ONLY -- no order surface, no capital, no
authority over Options, no path to promote itself.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from apex.predators.equities.attack_geometry import (
    EquityAttackGeometry, atr, session_vwap)

# PROMOTED 2026-08-28 by operator directive (Evolution Engine V2 §2)
# after commissioning verified: causal decisions, two-sided setups,
# realistic crossed-spread fills, structural stops, durable prospective
# cards, paper accounting, failure isolation. This is an authority
# label, not proof of edge: it may COMPETE for paper capital, nothing
# more. Real capital remains locked.
AUTHORITY = "PAPER_ACTIVE_EXPLORATORY"
SLEEVE = "EQUITY_DAY_TRADER"
THRESHOLD_SET = "EQUITY_SHADOW_V1"

# Predeclared, conservative, and NOT fitted to any observed outcome.
MIN_MEDIAN_VOLUME_PER_MIN = 20_000      # no thin names
MIN_BARS = 30
SHADOW_RISK_BUDGET = 300.0              # one fixed budget, never sized
MAX_STALENESS_S = 300.0

# Execution is MODELLED, and says so. The fabric stores OHLCV bars, not
# quotes, so a fill cannot be read from an observed spread. A declared
# conservative model is honest; a midpoint fill would be fantasy.
EXECUTION_MODEL = "NEXT_BAR_OPEN_PLUS_MODELLED_SPREAD"
MODELLED_SPREAD_BPS = 2.0               # crossed on entry AND exit

SETUP_TYPES = ("LONG_BREAKOUT", "SHORT_BREAKDOWN",
               "LONG_FAILED_BREAKDOWN", "SHORT_FAILED_BREAKOUT")

DECISIONS = ("ATTACK_READY_SHADOW", "WAIT", "NO_THESIS",
             "GEOMETRY_REFUSED", "CHASE_REFUSED", "NO_VALID_STOP",
             "NO_TRADE", "DATA_STALE", "INSUFFICIENT_DATA")

# Location gate. Deliberately the incumbent shared vocabulary -- these
# are market-geometry facts, not Options-specific rules.
ATTACKABLE_ENTRY_QUALITY = ("GOOD", "ACCEPTABLE")
REFUSED_CHASE = ("HIGH", "EXTREME")


class EquityShadowViolation(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------ setups

def classify_setup(bars: list, *, direction: str,
                   lookback: int = 20) -> dict:
    """Name the structure, or refuse to name one.

    Four families only. A setup we cannot name is NOT a setup, and
    inventing a fifth label to cover an ambiguous tape is how a
    classifier stops meaning anything.
    """
    if len(bars) < lookback + 5:
        return {"setup_type": None, "why": "insufficient structure"}

    window = bars[-(lookback + 5):-1]
    hi = max(b["high"] for b in window)
    lo = min(b["low"] for b in window)
    last = bars[-1]
    c = last["close"]

    broke_up = c > hi
    broke_dn = c < lo
    # a FAILED break: price traded through the level and closed back
    poked_up = last["high"] > hi and c <= hi
    poked_dn = last["low"] < lo and c >= lo

    if direction == "LONG":
        if broke_up:
            return {"setup_type": "LONG_BREAKOUT", "level": hi,
                    "why": f"close {c:.4f} above {lookback}-bar high "
                           f"{hi:.4f}"}
        if poked_dn:
            return {"setup_type": "LONG_FAILED_BREAKDOWN", "level": lo,
                    "why": f"traded below {lo:.4f} and closed back "
                           f"above -- sellers could not hold it"}
    else:
        if broke_dn:
            return {"setup_type": "SHORT_BREAKDOWN", "level": lo,
                    "why": f"close {c:.4f} below {lookback}-bar low "
                           f"{lo:.4f}"}
        if poked_up:
            return {"setup_type": "SHORT_FAILED_BREAKOUT", "level": hi,
                    "why": f"traded above {hi:.4f} and closed back "
                           f"below -- buyers could not hold it"}
    return {"setup_type": None,
            "why": "no nameable structure at this location"}


# -------------------------------------------------------------- risk

# Repair EQUITY-FRICTION-BLIND-SIZING (P1, operator-authorized
# 2026-08-28). The prior model sized qty = budget // price_distance,
# so a 9.46-cent stop on NVDA produced 3,170 shares whose round-trip
# friction alone was ~0.95R -- a position DECLARED as 1R that the
# execution model itself knew would lose ~1.95R at its ordinary stop.
# A known execution cost is part of risk. declared_1R now means
# ECONOMIC risk, never pre-friction chart risk.
STOP_LOSS_TOLERANCE = 0.02      # numerical/model tolerance on 1R


SIZING_SEMANTICS = "CANONICAL_V1"


def size_shadow(*, entry: float, stop: float, direction: str,
                budget: float = SHADOW_RISK_BUDGET,
                spread_bps: float | None = None) -> dict:
    """Size from the EXECUTABLE loss at the stop, not price distance.

        executable_stop_loss_per_share =
            adverse price move to the stop
          + entry execution cost
          + stop-exit execution cost

    quantity = floor(budget / executable_stop_loss_per_share), and the
    hard invariant follows by construction:
    modelled_total_loss_at_stop <= budget (+ tolerance).

    Costs use the incumbent modelled spread, priced CONSERVATIVELY at
    the worse of entry/stop so the invariant holds in both directions.
    A missing cost model REFUSES -- no silent fallback to
    price-distance-only sizing, ever again.

    This deliberately does NOT move the stop, judge the setup, or set a
    minimum stop distance: whether ultra-tight invalidations are
    economically viable is the FRICTION_DOMINANT_GEOMETRY research
    question, not a threshold to invent from one trade.
    """
    if entry is None or stop is None:
        return {"valid": False, "why": "entry or stop unavailable"}
    bps = MODELLED_SPREAD_BPS if spread_bps is None else spread_bps
    if bps is None or bps < 0:
        return {"valid": False,
                "why": "execution-cost estimate unavailable: sizing "
                       "REFUSES rather than falling back to "
                       "price-distance-only risk",
                "declared_1R": "NOT_ESTIMABLE"}
    risk_per_share = (entry - stop) if direction == "LONG" \
        else (stop - entry)
    if risk_per_share <= 0:
        return {"valid": False,
                "why": f"stop {stop:.4f} is not on the losing side of "
                       f"entry {entry:.4f} for a {direction}: there is "
                       f"no structural invalidation here"}
    worse = max(abs(entry), abs(stop))
    cost_side = worse * (bps / 10_000.0)      # per share, per crossing
    # RISK-005 (2026-09-01), SIZING_SEMANTICS CANONICAL_V1. This was
    # `+ 2.0 * cost_side`, which counted the ENTRY crossing twice:
    # `entry` here is the EXECUTABLE fill from marketable_fill(), which
    # has already crossed the spread, so `risk_per_share` = entry-stop
    # ALREADY contains one crossing. Only the EXIT crossing may be
    # added. Measured on the real book the double count overstated
    # planned risk by +33.1% (IWM) and +36.0% (XLE), which under the
    # capital-growth doctrine is a GROWTH defect -- systematic
    # under-sizing -- not merely a cosmetic one.
    eslps = risk_per_share + 1.0 * cost_side
    qty = int(budget // eslps)
    if qty < 1:
        return {"valid": False,
                "why": f"executable stop loss/share {eslps:.4f} "
                       f"exceeds the whole budget {budget}"}
    modelled_loss = round(qty * eslps, 2)
    assert modelled_loss <= budget * (1 + STOP_LOSS_TOLERANCE), \
        "sizing invariant violated -- refuse rather than mis-declare"
    return {"valid": True,
            "risk_per_share": round(risk_per_share, 6),
            "entry_cost_per_share": round(cost_side, 6),
            "stop_exit_cost_per_share": round(cost_side, 6),
            "executable_stop_loss_per_share": round(eslps, 6),
            "quantity": qty,
            "declared_1R": modelled_loss,
            "sizing_semantics": SIZING_SEMANTICS,
            "entry_slippage_embedded_in_entry": round(
                cost_side * qty, 2),
            "modelled_total_loss_at_stop": modelled_loss,
            "friction_fraction_of_1R": round(
                (2.0 * cost_side * qty) / modelled_loss, 4),
            "law": "declared_1R is ECONOMIC risk: the modelled loss at "
                   "the structural stop, execution costs included "
                   "ONCE -- the entry crossing is already embedded in "
                   "the executable fill and is never added again"}


def marketable_fill(reference: float, direction: str) -> dict:
    """Cross the spread, both ways. LONG lifts the offer, SHORT hits the
    bid. No midpoint."""
    half = reference * (MODELLED_SPREAD_BPS / 10_000.0)
    fill = reference + half if direction == "LONG" else reference - half
    return {"fill": round(fill, 6), "reference": reference,
            "friction_per_share": round(half, 6),
            "model": EXECUTION_MODEL,
            "spread_bps": MODELLED_SPREAD_BPS,
            "law": "modelled, not observed: the fabric stores OHLCV "
                   "bars and not quotes, so this is a declared "
                   "conservative model rather than a read spread"}


# ---------------------------------------------------------- decision

@dataclass
class EquityShadowDecision:
    decision_id: str
    symbol: str
    session: str
    decision: str
    event_time: str
    known_from: str
    direction: str | None = None
    setup_type: str | None = None
    entry_reference: float | None = None
    entry_fill: float | None = None
    stop: float | None = None
    risk_per_share: float | None = None
    quantity: int | None = None
    declared_1R: float | None = None
    friction_per_share: float | None = None
    entry_quality: str = "UNKNOWN"
    chase_risk: str = "UNKNOWN"
    invalidation_distance_atr: float | None = None
    extension_atr: float | None = None
    # risk anatomy (FRICTION_DOMINANT_GEOMETRY observation fields)
    stop_distance_price: float | None = None
    spread_to_stop_ratio: float | None = None
    modeled_entry_cost: float | None = None
    modeled_stop_exit_cost: float | None = None
    modeled_round_trip_friction: float | None = None
    friction_fraction_of_1R: float | None = None
    modeled_total_loss_at_stop: float | None = None
    market_state: dict = field(default_factory=dict)
    catalyst_alignment: str = "CATALYST_UNKNOWN"
    reasons: tuple = ()
    threshold_set: str = THRESHOLD_SET
    execution_model: str = EXECUTION_MODEL
    release_sha: str = "UNKNOWN"
    prospective: bool = True
    sleeve: str = SLEEVE
    authority: str = AUTHORITY

    def __post_init__(self):
        if self.decision not in DECISIONS:
            raise EquityShadowViolation(
                f"unknown decision {self.decision!r}")
        if self.setup_type is not None and self.setup_type not in SETUP_TYPES:
            raise EquityShadowViolation(
                f"unknown setup_type {self.setup_type!r}")
        if self.decision == "ATTACK_READY_SHADOW":
            if not (self.stop and self.declared_1R and self.setup_type):
                raise EquityShadowViolation(
                    "a shadow attack without a structural stop, a "
                    "declared 1R and a named setup is not a decision")

    def as_record(self) -> dict:
        return {"kind": "equity_shadow_decision", **asdict(self),
                "decision_power": "SHADOW_ONLY"}


def decide(*, symbol: str, session: str, bars: list, now,
           known_from: str, release_sha: str = "UNKNOWN",
           catalyst_alignment: str = "CATALYST_UNKNOWN",
           median_volume: float | None = None) -> EquityShadowDecision:
    """One prospective shadow decision. Refusals are first-class."""
    def mk(decision, **kw):
        raw = f"{symbol}|{session}|{known_from}"
        return EquityShadowDecision(
            decision_id="EQS_" + hashlib.sha256(raw.encode()).hexdigest()[:16],
            symbol=symbol, session=session, decision=decision,
            event_time=str(now), known_from=known_from,
            release_sha=release_sha,
            catalyst_alignment=catalyst_alignment, **kw)

    if median_volume is not None and median_volume < MIN_MEDIAN_VOLUME_PER_MIN:
        return mk("NO_TRADE", reasons=(
            f"median volume {median_volume:.0f}/min is below the "
            f"predeclared floor {MIN_MEDIAN_VOLUME_PER_MIN}",))
    if len(bars) < MIN_BARS:
        return mk("INSUFFICIENT_DATA",
                  reasons=(f"{len(bars)} bars < {MIN_BARS}",))

    probe = EquityAttackGeometry().compute(
        subject=symbol, direction="LONG", bars=bars, now=now,
        known_from=known_from, liquidity_quality="HEALTHY")
    a = atr(bars)
    vwap = session_vwap(bars)
    c = bars[-1]["close"]
    if a is None or not a or vwap is None:
        return mk("INSUFFICIENT_DATA", reasons=("ATR or VWAP "
                                                "NOT_ESTIMABLE",))

    # this sleeve's OWN directional read: where price sits against the
    # session's volume-weighted anchor. Deliberately not the Options
    # trend model -- two sleeves sharing one thesis measure nothing.
    dist_atr = (c - vwap) / a
    if abs(dist_atr) < 0.15:
        return mk("NO_THESIS", market_state={"vwap_distance_atr":
                                             round(dist_atr, 4)},
                  reasons=("price is at the session anchor: no "
                           "directional read",))
    direction = "LONG" if dist_atr > 0 else "SHORT"

    geo = EquityAttackGeometry().compute(
        subject=symbol, direction=direction, bars=bars, now=now,
        known_from=known_from, liquidity_quality="HEALTHY")
    state = {"vwap_distance_atr": round(dist_atr, 4),
             "atr": round(a, 6), "vwap": round(vwap, 4),
             "close": c, "geometry_data_quality": geo.data_quality}
    common = {"direction": direction, "market_state": state,
              "entry_quality": geo.entry_quality,
              "chase_risk": geo.chase_risk,
              "invalidation_distance_atr": geo.invalidation_distance_atr,
              "extension_atr": round(abs(dist_atr), 4)}

    setup = classify_setup(bars, direction=direction)
    if not setup["setup_type"]:
        return mk("NO_THESIS", reasons=(setup["why"],), **common)

    common["setup_type"] = setup["setup_type"]

    if geo.chase_risk in REFUSED_CHASE:
        return mk("CHASE_REFUSED", reasons=(
            f"chase {geo.chase_risk}: already extended "
            f"{abs(dist_atr):.2f} ATR from the anchor",), **common)
    if geo.entry_quality not in ATTACKABLE_ENTRY_QUALITY:
        return mk("GEOMETRY_REFUSED", reasons=(
            f"entry_quality {geo.entry_quality}",), **common)
    if geo.invalidation is None:
        return mk("NO_VALID_STOP", reasons=(
            "geometry produced no structural invalidation",), **common)

    fill = marketable_fill(c, direction)
    sized = size_shadow(entry=fill["fill"], stop=geo.invalidation,
                        direction=direction)
    if not sized["valid"]:
        return mk("NO_VALID_STOP", reasons=(sized["why"],), **common)

    rt = (sized["entry_cost_per_share"]
          + sized["stop_exit_cost_per_share"]) * sized["quantity"]
    return mk("ATTACK_READY_SHADOW",
              entry_reference=c, entry_fill=fill["fill"],
              stop=geo.invalidation,
              risk_per_share=sized["risk_per_share"],
              quantity=sized["quantity"],
              declared_1R=sized["declared_1R"],
              friction_per_share=fill["friction_per_share"],
              stop_distance_price=sized["risk_per_share"],
              spread_to_stop_ratio=round(
                  (2 * sized["entry_cost_per_share"])
                  / sized["risk_per_share"], 4),
              modeled_entry_cost=round(
                  sized["entry_cost_per_share"] * sized["quantity"], 2),
              modeled_stop_exit_cost=round(
                  sized["stop_exit_cost_per_share"]
                  * sized["quantity"], 2),
              modeled_round_trip_friction=round(rt, 2),
              friction_fraction_of_1R=sized["friction_fraction_of_1R"],
              modeled_total_loss_at_stop=sized[
                  "modelled_total_loss_at_stop"],
              reasons=(setup["why"],
                       f"{geo.entry_quality} location, chase "
                       f"{geo.chase_risk}"),
              **common)
