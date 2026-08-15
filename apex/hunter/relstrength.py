"""RelativeStrengthState — a central Hunter primitive.

The question is never "is AMD up?" but "is AMD behaving abnormally strongly
relative to the market, its sector, and its peers, right now?" AMD +1.1%
while QQQ is -0.3% and SOXX -0.1% (excess +1.4% / +1.2%, RVOL 3.4x, above
VWAP, above OR) is information; RSI=67 is not.

Everything derives from ChartStates computed at the SAME as-of T, so the
no-leakage property is inherited — this module never touches raw bars.
Missing benchmark state yields None fields, never a fabricated zero excess.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from apex.hunter.chartstate import ChartState

HORIZON_FIELDS = ("r_15m", "r_30m", "r_60m", "day_return")


def _excess(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else float(a - b)


@dataclass(frozen=True)
class RelativeStrengthState:
    symbol: str
    t_utc: str
    market_symbol: str
    sector_symbol: str | None
    n_peers: int
    # excess returns per horizon (None propagates missing data)
    excess_market_15m: float | None
    excess_market_30m: float | None
    excess_market_60m: float | None
    excess_market_day: float | None
    excess_sector_15m: float | None
    excess_sector_30m: float | None
    excess_sector_60m: float | None
    excess_sector_day: float | None
    excess_peers_day: float | None          # vs median peer day return
    # cross-sectional standing among the scanned universe (day excess vs mkt)
    cross_sectional_pct: float | None
    # dynamics
    acceleration: float | None              # 15m excess - (60m excess)/4
    persistence: float | None               # frac of 15/30/60 windows positive
    multi_horizon_agreement: bool | None    # 15m, 30m, 60m excess same sign

    def as_record(self) -> dict:
        return asdict(self)


def compute_relative_strength(
        target: ChartState, market: ChartState,
        sector: ChartState | None = None,
        peers: tuple = (),
        universe_day_excess: tuple = ()) -> RelativeStrengthState:
    """`peers`: ChartStates of same-sector scanned names (excluding target).
    `universe_day_excess`: day excess-vs-market of every scanned name
    (target included), for the cross-sectional percentile."""
    em = {h: _excess(getattr(target, h), getattr(market, h))
          for h in HORIZON_FIELDS}
    es = {h: _excess(getattr(target, h), getattr(sector, h))
          if sector is not None else None for h in HORIZON_FIELDS}

    peer_days = [p.day_return for p in peers if p.day_return is not None]
    ep_day = (_excess(target.day_return, float(np.median(peer_days)))
              if peer_days and target.day_return is not None else None)

    pct = None
    tgt_x = em["day_return"]
    if tgt_x is not None and len(universe_day_excess) >= 5:
        xs = [x for x in universe_day_excess if x is not None]
        if xs:
            pct = float(np.mean([x <= tgt_x for x in xs]))

    accel = (float(em["r_15m"] - em["r_60m"] / 4)
             if em["r_15m"] is not None and em["r_60m"] is not None else None)
    windows = [em[h] for h in ("r_15m", "r_30m", "r_60m")]
    known = [w for w in windows if w is not None]
    persistence = float(np.mean([w > 0 for w in known])) if known else None
    agreement = (bool(all(w > 0 for w in known) or all(w < 0 for w in known))
                 if len(known) == 3 else None)

    return RelativeStrengthState(
        symbol=target.symbol, t_utc=target.t_utc,
        market_symbol=market.symbol,
        sector_symbol=sector.symbol if sector is not None else None,
        n_peers=len(peers),
        excess_market_15m=em["r_15m"], excess_market_30m=em["r_30m"],
        excess_market_60m=em["r_60m"], excess_market_day=em["day_return"],
        excess_sector_15m=es["r_15m"], excess_sector_30m=es["r_30m"],
        excess_sector_60m=es["r_60m"], excess_sector_day=es["day_return"],
        excess_peers_day=ep_day, cross_sectional_pct=pct,
        acceleration=accel, persistence=persistence,
        multi_horizon_agreement=agreement)
