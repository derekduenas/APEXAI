"""OBSERVATORY-DERIVED MARKET FEATURES -- namespaced to prevent drift.

THE LAW THIS MODULE EXISTS TO ENFORCE (operator, Build Addendum A).
Hunter's ChartState computes VWAP, opening range and RVOL, and it sits
behind the `apex.hunter` firewall. The Observatory needs those
quantities and cannot import them. The naive resolution -- "compute our
own" -- is how a system ends up with three realities:

    Hunter VWAP              = definition A
    Pattern Observatory VWAP = definition B
    ParticipantPressure VWAP = definition C   (someday)

and then nobody can say which one a disagreement came from.

So every quantity here is explicitly namespaced `OBS_*`, carries its own
`calculation_version` and a `formula_hash` derived from the actual
formula text, and names the bars it consumed. An OBS_ value may NEVER be
described as canonical or as Hunter-equivalent, and a test enforces that
the prefix is present on every exported quantity.

FUTURE_TARGET: extract these into a SHARED CANONICAL MARKET-FEATURE
LAYER living outside both the Hunter and Frontier firewalls, so Hunter,
Frontier-2 and the Observatory consume one definition. That refactor is
deliberately NOT done here -- doing it tonight would mean editing
Hunter's semantics, which is prohibited. This module is the honest
interim: duplicated arithmetic, loudly labelled as duplicated.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

CALCULATION_VERSION = "obs_features_v1"

# The formula TEXT is hashed, so changing the arithmetic changes the hash
# and every persisted observation remains attributable to the exact
# definition that produced it.
FORMULAS = {
    "OBS_VWAP":
        "sum(((high+low+close)/3) * volume) / sum(volume) over regular-session "
        "bars from session_open to as_of inclusive; None if sum(volume)==0",
    "OBS_OPENING_RANGE":
        "high = max(high), low = min(low) over the FIRST n bars at or after "
        "session_open (n=OPENING_RANGE_BARS); position = (close-low)/(high-low)",
    "OBS_RVOL":
        "cumulative regular-session volume / median cumulative volume at the "
        "SAME minutes_into_session across prior sessions; NOT_ESTIMABLE when "
        "fewer than OBS_RVOL_MIN_SESSIONS prior sessions exist",
    "OBS_RETURN_FROM_OPEN":
        "close(as_of)/open(first regular bar) - 1",
    "OBS_DISPERSION":
        "population stdev of OBS_RETURN_FROM_OPEN across a symbol set",
}

OPENING_RANGE_BARS = 5
OBS_RVOL_MIN_SESSIONS = 10          # below this RVOL is NOT_ESTIMABLE, never 0
NOT_ESTIMABLE = "NOT_ESTIMABLE"


def formula_hash(name: str) -> str:
    if name not in FORMULAS:
        raise KeyError(f"no declared formula for {name!r}")
    payload = f"{CALCULATION_VERSION}|{name}|{FORMULAS[name]}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ObsFeature:
    """One Observatory-derived quantity, fully attributable."""

    name: str
    value: float | None
    status: str                      # OK | NOT_ESTIMABLE | NO_DATA
    calculation_version: str
    formula: str
    formula_hash: str
    source_bars: int
    source_symbol: str
    event_time: str | None
    known_from: str | None

    def __post_init__(self):
        if not self.name.startswith("OBS_"):
            raise ValueError(
                f"{self.name!r}: Observatory-derived features MUST carry the "
                "OBS_ prefix -- an unprefixed name would eventually be "
                "mistaken for the canonical Hunter definition")

    def as_dict(self) -> dict:
        return {"kind": "obs_feature", "name": self.name, "value": self.value,
                "status": self.status,
                "calculation_version": self.calculation_version,
                "formula": self.formula, "formula_hash": self.formula_hash,
                "source_bars": self.source_bars,
                "source_symbol": self.source_symbol,
                "event_time": self.event_time, "known_from": self.known_from,
                "canonical": False,
                "hunter_equivalent": False,
                "note": "Observatory-derived. NOT canonical, NOT "
                        "Hunter-equivalent. See FUTURE_TARGET in "
                        "apex/pattern_observatory/obs_features.py",
                "decision_power": OBSERVATORY_POWER}


def _mk(name, value, status, bars, symbol, event_time, known_from) -> ObsFeature:
    return ObsFeature(name=name, value=value, status=status,
                      calculation_version=CALCULATION_VERSION,
                      formula=FORMULAS[name], formula_hash=formula_hash(name),
                      source_bars=bars, source_symbol=symbol,
                      event_time=(str(event_time) if event_time else None),
                      known_from=(str(known_from) if known_from else None))


def obs_vwap(bars, *, symbol: str, known_from) -> ObsFeature:
    """Volume-weighted average of the typical price over the supplied
    (already session-filtered) bars."""
    if bars is None or not len(bars):
        return _mk("OBS_VWAP", None, "NO_DATA", 0, symbol, None, known_from)
    vol = float(bars["volume"].sum())
    if vol <= 0:
        return _mk("OBS_VWAP", None, NOT_ESTIMABLE, len(bars), symbol,
                   bars["event_time_utc"].max(), known_from)
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    return _mk("OBS_VWAP", float((tp * bars["volume"]).sum() / vol), "OK",
               len(bars), symbol, bars["event_time_utc"].max(), known_from)


def obs_opening_range(bars, *, symbol: str, known_from,
                      n_bars: int = OPENING_RANGE_BARS) -> dict:
    """High/low of the first n regular-session bars, plus where price
    currently sits relative to that range."""
    if bars is None or len(bars) < n_bars:
        f = _mk("OBS_OPENING_RANGE", None, NOT_ESTIMABLE,
                0 if bars is None else len(bars), symbol, None, known_from)
        return {"feature": f.as_dict(), "high": None, "low": None,
                "position": None, "state": "UNKNOWN"}
    head = bars.head(n_bars)
    hi, lo = float(head["high"].max()), float(head["low"].min())
    last = float(bars["close"].iloc[-1])
    pos = None if hi <= lo else (last - lo) / (hi - lo)
    state = ("ABOVE_OR_HIGH" if last > hi else
             "BELOW_OR_LOW" if last < lo else "INSIDE_OR")
    f = _mk("OBS_OPENING_RANGE", pos, "OK", len(bars), symbol,
            bars["event_time_utc"].max(), known_from)
    return {"feature": f.as_dict(), "high": hi, "low": lo, "position": pos,
            "state": state}


def obs_return_from_open(bars, *, symbol: str, known_from) -> ObsFeature:
    if bars is None or len(bars) < 2:
        return _mk("OBS_RETURN_FROM_OPEN", None, NOT_ESTIMABLE,
                   0 if bars is None else len(bars), symbol, None, known_from)
    o = float(bars["open"].iloc[0])
    if o == 0:
        return _mk("OBS_RETURN_FROM_OPEN", None, NOT_ESTIMABLE, len(bars),
                   symbol, bars["event_time_utc"].max(), known_from)
    return _mk("OBS_RETURN_FROM_OPEN",
               float(bars["close"].iloc[-1]) / o - 1.0, "OK", len(bars),
               symbol, bars["event_time_utc"].max(), known_from)


def obs_rvol(bars, *, symbol: str, known_from,
             prior_session_cumvol: list | None = None,
             minutes_into_session: int | None = None) -> ObsFeature:
    """Relative volume against a time-of-day baseline.

    HONEST BY CONSTRUCTION: with no multi-session baseline this returns
    NOT_ESTIMABLE, never 0.0 and never 1.0. On 2026-08-19 RVOL was
    correctly reported UNKNOWN all session for exactly this reason, and
    that must not silently become a number here.
    """
    n = 0 if bars is None else len(bars)
    if not prior_session_cumvol or len(prior_session_cumvol) < OBS_RVOL_MIN_SESSIONS:
        f = _mk("OBS_RVOL", None, NOT_ESTIMABLE, n, symbol,
                (bars["event_time_utc"].max() if n else None), known_from)
        return f
    import statistics
    base = statistics.median(prior_session_cumvol)
    if base <= 0 or not n:
        return _mk("OBS_RVOL", None, NOT_ESTIMABLE, n, symbol, None, known_from)
    return _mk("OBS_RVOL", float(bars["volume"].sum()) / base, "OK", n, symbol,
               bars["event_time_utc"].max(), known_from)


def obs_dispersion(returns: list) -> dict:
    """Cross-sectional dispersion of returns across a symbol set."""
    vals = [r for r in returns if r is not None]
    if len(vals) < 2:
        return {"name": "OBS_DISPERSION", "value": None,
                "status": NOT_ESTIMABLE, "n": len(vals),
                "formula_hash": formula_hash("OBS_DISPERSION"),
                "decision_power": OBSERVATORY_POWER}
    import statistics
    return {"name": "OBS_DISPERSION", "value": float(statistics.pstdev(vals)),
            "status": "OK", "n": len(vals),
            "formula": FORMULAS["OBS_DISPERSION"],
            "formula_hash": formula_hash("OBS_DISPERSION"),
            "calculation_version": CALCULATION_VERSION,
            "canonical": False, "hunter_equivalent": False,
            "decision_power": OBSERVATORY_POWER}
