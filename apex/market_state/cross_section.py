"""Cross-sectional series builders -- sector leadership + breadth.

Two canonical minute-resolution scalar series per session, computed from
the persisted bar streams and NOTHING else:

  SECTOR_LEADERSHIP_DISPERSION
      cross-sectional std of the 11 sector ETFs' returns-from-open at
      each minute. Rising dispersion = leadership is differentiating
      (rotation); falling = the tape is moving as one block. This is a
      LEVEL series -- Curve's derivative stack decides whether it is
      bending, this module never does.

  BREADTH_ADVANCING_FRACTION
      fraction of the 11 sector ETFs above their own session open at
      each minute, in [0, 1]. A signed/bounded level series (diff mode
      downstream).

SUFFICIENCY IS PER-MINUTE HONEST: a minute where fewer than
MIN_MEMBERS_PER_MINUTE sectors have a bar yet contributes NO point --
never a point computed from 3 sectors pretending to be the cross
section. Overall series quality reflects the worst material gap.

The open reference is each symbol's own 09:30 ET bar (the session
anchor convention). A symbol with no 09:30 bar is excluded from every
minute rather than silently rebased.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.market_state import BARS_ROOT, MARKET_PROXY, SECTOR_ETFS
from apex.market_state.schemas import (
    DEGRADED, INVALID, LIMITED, NOT_ESTIMABLE, VALID, CrossSectionalSeries,
)

FORMULA_VERSION = "market_state_cross_section_v1"
MIN_MEMBERS_PER_MINUTE = 8          # of 11 -- fewer is not a cross-section
SESSION_OPEN_ET = "09:30"


def _load_closes(symbol: str, day: str) -> dict:
    """{minute_timestamp(ET-floored, tz-aware UTC): close} from the
    canonical session stream. Missing file -> empty dict, honestly."""
    import pandas as pd
    p = Path(BARS_ROOT) / f"{symbol}_{day}.json"
    if not p.exists():
        return {}
    try:
        rows = json.loads(p.read_text()).get("bars", [])
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    for b in rows:
        try:
            t = pd.Timestamp(b["event_time_utc"]).floor("min")
            out[t] = float(b["close"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _session_minutes(day: str, now):
    import pandas as pd
    open_t = pd.Timestamp(f"{day} {SESSION_OPEN_ET}:00",
                          tz="America/New_York").tz_convert("UTC")
    end = min(pd.Timestamp(now).tz_convert("UTC"),
              pd.Timestamp(f"{day} 16:00:00",
                           tz="America/New_York").tz_convert("UTC"))
    if end <= open_t:
        return open_t, []
    return open_t, list(pd.date_range(open_t, end, freq="min",
                                      inclusive="left"))


def build(day: str, *, now) -> dict:
    """Both canonical series for `day`, computed as of `now`.

    Returns {"sector_leadership": CrossSectionalSeries,
             "breadth": CrossSectionalSeries} -- always both keys, each
    honestly NOT_ESTIMABLE/insufficient when the tape cannot support it.
    """
    import statistics

    import pandas as pd

    closes = {s: _load_closes(s, day) for s in SECTOR_ETFS}
    open_t, minutes = _session_minutes(day, now)

    opens = {}
    for s in SECTOR_ETFS:
        o = closes[s].get(open_t)
        if o is not None and o > 0:
            opens[s] = o
    usable = sorted(opens)

    def _series(name: str, fn) -> CrossSectionalSeries:
        pts, newest = [], None
        skipped_thin = 0
        for m in minutes:
            vals = []
            for s in usable:
                c = closes[s].get(m)
                if c is not None:
                    vals.append(c / opens[s] - 1.0)
                    newest = m if (newest is None or m > newest) else newest
            if len(vals) >= MIN_MEMBERS_PER_MINUTE:
                pts.append((m, fn(vals)))
            else:
                skipped_thin += 1
        n_exp = len(minutes)
        reasoning = []
        if skipped_thin:
            reasoning.append(f"{skipped_thin}/{n_exp} minutes below "
                             f"{MIN_MEMBERS_PER_MINUTE}-member floor, "
                             f"emitted NO point (never a thin fake)")
        if len(usable) < len(SECTOR_ETFS):
            missing = sorted(set(SECTOR_ETFS) - set(usable))
            reasoning.append(f"no 09:30 open anchor for {missing}; "
                             f"excluded from every minute")
        cov = len(pts) / n_exp if n_exp else 0.0
        if not pts:
            quality, sufficient = NOT_ESTIMABLE, False
        elif len(usable) < MIN_MEMBERS_PER_MINUTE:
            quality, sufficient = INVALID, False
        elif cov >= 0.97 and len(usable) == len(SECTOR_ETFS):
            quality, sufficient = VALID, True
        elif cov >= 0.90:
            quality, sufficient = LIMITED, True
        else:
            quality, sufficient = DEGRADED, False
        return CrossSectionalSeries(
            name=name, points=tuple(pts), sufficient=sufficient,
            quality=quality, members_observed=len(usable),
            members_expected=len(SECTOR_ETFS),
            source=f"{BARS_ROOT} (canonical session streams)",
            source_time=(str(newest) if newest is not None else None),
            known_from=str(pd.Timestamp(now)),
            formula_version=FORMULA_VERSION, reasoning=tuple(reasoning))

    def _dispersion(vals):
        return statistics.pstdev(vals)

    def _advancing(vals):
        return sum(1 for v in vals if v > 0) / len(vals)

    return {"sector_leadership": _series("SECTOR_LEADERSHIP_DISPERSION",
                                         _dispersion),
            "breadth": _series("BREADTH_ADVANCING_FRACTION", _advancing)}


def curve_points(series: CrossSectionalSeries, *, window: int) -> list:
    """The exact [(t, value)] shape curve.compute expects, trailing
    `window` points, ONLY if the series declared itself sufficient --
    an insufficient series yields [] so the dimension lands NO_SUPPORT,
    never a fabricated feed."""
    if not series.sufficient:
        return []
    return [(t, v) for t, v in series.points[-window:]]
