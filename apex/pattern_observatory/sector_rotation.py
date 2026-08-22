"""SECTOR ROTATION STATE -- the blind spot 2026-08-19 exposed.

WHAT HAPPENED. On the first natural-acceptance session the market told a
clear cross-sectional story: XLV +1.98% and XLP +1.31% against XLK -1.37%
and XLI -1.23%, with breadth collapsing from 9/11 advancing at the open
to 4/11 by midday. A textbook defensive rotation broadening into index
weakness.

APEX captured all eleven sector SPDRs, anchored every one of them live at
09:30:00, and then never looked at them again. A repository grep for
`sector_rotation | rotation_state | breadth_state` returned nothing:
the organ did not exist. Meanwhile `apex/frontier2/curve.py` DECLARES
`sector_leadership` and `breadth` as first-class dimensions and reported
them `NOT_AVAILABLE` on 0/16,829 records -- a hungry consumer with no
producer.

This module is the producer. It does not feed Curve (the Observatory has
no authority over the official path); it feeds the Observatory's own
world state, and it demonstrates that the data was always sufficient.

WHAT THIS IS NOT: a trading rule. `DEFENSIVE_ROTATION` is a description
of a cross-section, not a reason to buy staples. Classification carries
no directional claim and no probability.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER
from apex.pattern_observatory.obs_features import (
    obs_dispersion, obs_opening_range, obs_return_from_open, obs_vwap,
)

# The eleven SPDR sector ETFs. This is PUBLIC MARKET TAXONOMY, not Hunter
# IP -- Hunter keeps its own copy at apex/hunter/context_builder.py behind
# the firewall, and duplicating a list of eleven public tickers is the
# honest cost of that boundary. See FUTURE_TARGET in obs_features.py.
SECTOR_ETFS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE",
               "XLU", "XLV", "XLY")

SECTOR_NAMES = {
    "XLB": "Materials", "XLC": "Communication Services", "XLE": "Energy",
    "XLF": "Financials", "XLI": "Industrials", "XLK": "Technology",
    "XLP": "Consumer Staples", "XLRE": "Real Estate", "XLU": "Utilities",
    "XLV": "Health Care", "XLY": "Consumer Discretionary",
}

# Which sectors behave defensively vs cyclically. DECLARED taxonomy,
# pre-registered before any pattern was observed, never fitted.
DEFENSIVE = ("XLP", "XLU", "XLV", "XLRE")
CYCLICAL = ("XLY", "XLI", "XLF", "XLB", "XLE")

# TECH IS TWO DIFFERENT THINGS AND THE GROUP MEAN HIDES IT.
# Measured on the first real cross-section this module ever saw
# (2026-08-19 15:00 ET): XLK -0.242% while XLC +1.182%. The mean reads
# "tech leads the market by 0.63pp" -- the exact opposite of what the
# semiconductor/software complex was doing. XLC is Meta/Alphabet/media
# and routinely decouples from XLK.
#
# The taxonomy is PRE-REGISTERED and is NOT being retuned to fit that
# observation -- retuning a grouping because of one session is precisely
# the behaviour this system forbids. Instead the internal split is
# carried on every state, and a divergence beyond the declared spread is
# stated in the reasoning, so an averaged label can never silently
# conceal a disagreeing pair.
TECH = ("XLK", "XLC")
TECH_CORE = "XLK"
TECH_COMMS = "XLC"

MARKET_PROXY = "SPY"

STATES = ("BROAD_RISK_ON", "BROAD_RISK_OFF", "DEFENSIVE_ROTATION",
          "CYCLICAL_ROTATION", "TECH_LEADERSHIP", "TECH_UNWIND",
          "ENERGY_LEADERSHIP", "FINANCIAL_LEADERSHIP", "NARROW_LEADERSHIP",
          "BREADTH_DIVERGENCE", "MIXED", "UNKNOWN")

# DECLARED thresholds. Written from the 2026-08-19 cross-section before
# any outcome was measured; they describe "how different is different",
# not "what makes money". Never tune these against returns.
BROAD_FRACTION = 0.80           # >=80% of sectors one way == broad
LEADERSHIP_SPREAD = 0.0050      # 50bp group-vs-market to call leadership
NARROW_MAX_ADVANCERS = 3        # index up on <=3 sectors == narrow
MIN_SECTORS_FOR_STATE = 8       # below this the cross-section is UNKNOWN


@dataclass(frozen=True)
class SectorObservation:
    symbol: str
    name: str
    return_from_open: float | None
    return_vs_market: float | None
    vwap_state: str
    opening_range_state: str
    rank: int | None
    quality: str
    bars: int


@dataclass(frozen=True)
class SectorRotationState:
    as_of: str
    known_from: str
    state: str
    sectors: tuple
    leaders: tuple
    laggards: tuple
    advancers: int
    decliners: int
    sectors_observed: int
    dispersion: dict
    defensive_minus_cyclical: float | None
    tech_vs_market: float | None
    tech_internal_split: dict
    market_return: float | None
    rank_changes: dict = field(default_factory=dict)
    leadership_persistence: dict = field(default_factory=dict)
    reasoning: tuple = ()
    quality: str = "UNKNOWN"

    def as_dict(self) -> dict:
        return {
            "kind": "sector_rotation_state", "as_of": self.as_of,
            "known_from": self.known_from, "state": self.state,
            "sectors": [s.__dict__ for s in self.sectors],
            "leaders": list(self.leaders), "laggards": list(self.laggards),
            "advancers": self.advancers, "decliners": self.decliners,
            "sectors_observed": self.sectors_observed,
            "dispersion": self.dispersion,
            "defensive_minus_cyclical": self.defensive_minus_cyclical,
            "tech_vs_market": self.tech_vs_market,
            "tech_internal_split": dict(self.tech_internal_split),
            "market_return": self.market_return,
            "rank_changes": dict(self.rank_changes),
            "leadership_persistence": dict(self.leadership_persistence),
            "reasoning": list(self.reasoning), "quality": self.quality,
            "is_trading_rule": False,
            "decision_power": OBSERVATORY_POWER,
        }


def _group_mean(obs_by_sym: dict, group: tuple) -> float | None:
    vals = [obs_by_sym[s].return_from_open for s in group
            if s in obs_by_sym and obs_by_sym[s].return_from_open is not None]
    return sum(vals) / len(vals) if vals else None


def observe_sector(symbol: str, bars, *, market_return: float | None,
                   known_from, quality: str) -> SectorObservation:
    ret = obs_return_from_open(bars, symbol=symbol, known_from=known_from)
    vwap = obs_vwap(bars, symbol=symbol, known_from=known_from)
    orng = obs_opening_range(bars, symbol=symbol, known_from=known_from)

    vwap_state = "UNKNOWN"
    if vwap.value is not None and bars is not None and len(bars):
        last = float(bars["close"].iloc[-1])
        vwap_state = "ABOVE_VWAP" if last > vwap.value else "BELOW_VWAP"

    vs_mkt = (None if (ret.value is None or market_return is None)
              else ret.value - market_return)
    return SectorObservation(
        symbol=symbol, name=SECTOR_NAMES.get(symbol, symbol),
        return_from_open=ret.value, return_vs_market=vs_mkt,
        vwap_state=vwap_state, opening_range_state=orng["state"],
        rank=None, quality=quality, bars=(0 if bars is None else len(bars)))


def classify(observations: list, *, market_return: float | None,
             prior_ranks: dict | None = None,
             leadership_history: dict | None = None,
             as_of, known_from, quality: str = "UNKNOWN") -> SectorRotationState:
    """Classify the cross-section. Descriptive only."""
    usable = [o for o in observations if o.return_from_open is not None]
    reasoning = []

    if len(usable) < MIN_SECTORS_FOR_STATE:
        return SectorRotationState(
            as_of=str(as_of), known_from=str(known_from), state="UNKNOWN",
            sectors=tuple(observations), leaders=(), laggards=(),
            advancers=0, decliners=0, sectors_observed=len(usable),
            dispersion={"status": "NOT_ESTIMABLE"},
            defensive_minus_cyclical=None, tech_vs_market=None,
            tech_internal_split={"status": "NOT_ESTIMABLE"},
            market_return=market_return,
            reasoning=(f"only {len(usable)} of {len(SECTOR_ETFS)} sectors "
                       f"observable; minimum is {MIN_SECTORS_FOR_STATE}",),
            quality=quality)

    ranked = sorted(usable, key=lambda o: -(o.return_from_open or 0.0))
    ranked = [SectorObservation(**{**o.__dict__, "rank": i + 1})
              for i, o in enumerate(ranked)]
    by_sym = {o.symbol: o for o in ranked}

    advancers = sum(1 for o in ranked if (o.return_from_open or 0) > 0)
    decliners = len(ranked) - advancers
    disp = obs_dispersion([o.return_from_open for o in ranked])

    defen = _group_mean(by_sym, DEFENSIVE)
    cycl = _group_mean(by_sym, CYCLICAL)
    tech = _group_mean(by_sym, TECH)
    dmc = (None if (defen is None or cycl is None) else defen - cycl)
    tvm = (None if (tech is None or market_return is None)
           else tech - market_return)

    core = by_sym.get(TECH_CORE)
    comms = by_sym.get(TECH_COMMS)
    split = {"XLK": core.return_from_open if core else None,
             "XLC": comms.return_from_open if comms else None}
    if split["XLK"] is not None and split["XLC"] is not None:
        split["spread"] = split["XLC"] - split["XLK"]
        split["diverging"] = abs(split["spread"]) >= LEADERSHIP_SPREAD
        split["note"] = ("XLK and XLC disagree; the TECH group mean is not "
                         "representative of either"
                         if split["diverging"] else "tech complex coherent")
    else:
        split["spread"] = None
        split["diverging"] = None
        split["note"] = "insufficient tech observations"

    rank_changes = {}
    if prior_ranks:
        for s, o in by_sym.items():
            if s in prior_ranks and o.rank is not None:
                rank_changes[s] = prior_ranks[s] - o.rank   # +ve == improving

    frac_up = advancers / len(ranked)
    state = "MIXED"

    if frac_up >= BROAD_FRACTION:
        state = "BROAD_RISK_ON"
        reasoning.append(f"{advancers}/{len(ranked)} sectors advancing")
    elif (1 - frac_up) >= BROAD_FRACTION:
        state = "BROAD_RISK_OFF"
        reasoning.append(f"{decliners}/{len(ranked)} sectors declining")
    elif dmc is not None and dmc >= LEADERSHIP_SPREAD:
        state = "DEFENSIVE_ROTATION"
        reasoning.append(f"defensives lead cyclicals by {dmc*100:.2f}pp")
    elif dmc is not None and dmc <= -LEADERSHIP_SPREAD:
        state = "CYCLICAL_ROTATION"
        reasoning.append(f"cyclicals lead defensives by {-dmc*100:.2f}pp")

    # Tech is called separately because it can lead or unwind INSIDE a
    # defensive or cyclical rotation -- 2026-08-19 was exactly that.
    if split.get("diverging"):
        reasoning.append(
            f"TECH INTERNALLY DIVERGENT: XLK {split['XLK']*100:+.2f}% vs "
            f"XLC {split['XLC']*100:+.2f}% ({split['spread']*100:+.2f}pp) -- "
            f"the tech group mean is not representative")

    if tvm is not None and tvm <= -LEADERSHIP_SPREAD:
        reasoning.append(f"tech trails the market by {-tvm*100:.2f}pp")
        if state in ("MIXED", "BROAD_RISK_OFF") and not split.get("diverging"):
            state = "TECH_UNWIND"
    elif tvm is not None and tvm >= LEADERSHIP_SPREAD:
        reasoning.append(f"tech leads the market by {tvm*100:.2f}pp")
        if state in ("MIXED", "BROAD_RISK_ON") and not split.get("diverging"):
            state = "TECH_LEADERSHIP"

    if market_return is not None and market_return > 0 \
            and advancers <= NARROW_MAX_ADVANCERS:
        state = "NARROW_LEADERSHIP"
        reasoning.append(f"market up on only {advancers} advancing sectors")

    if market_return is not None:
        # index and cross-section disagreeing is itself the observation
        if market_return > 0 and frac_up < 0.4:
            state = "BREADTH_DIVERGENCE"
            reasoning.append("index up while most sectors decline")
        elif market_return < 0 and frac_up > 0.6:
            state = "BREADTH_DIVERGENCE"
            reasoning.append("index down while most sectors advance")

    if state == "MIXED" and not reasoning:
        reasoning.append("no group separation exceeded the declared spread")

    leaders = tuple(o.symbol for o in ranked[:3])
    laggards = tuple(o.symbol for o in ranked[-3:])

    persistence = {}
    if leadership_history:
        for s in leaders:
            persistence[s] = leadership_history.get(s, 0) + 1

    return SectorRotationState(
        as_of=str(as_of), known_from=str(known_from), state=state,
        sectors=tuple(ranked), leaders=leaders, laggards=laggards,
        advancers=advancers, decliners=decliners, sectors_observed=len(ranked),
        dispersion=disp, defensive_minus_cyclical=dmc, tech_vs_market=tvm,
        tech_internal_split=split,
        market_return=market_return, rank_changes=rank_changes,
        leadership_persistence=persistence, reasoning=tuple(reasoning),
        quality=quality)
