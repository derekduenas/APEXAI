"""Abnormality scanner v1 — detects what DESERVES ATTENTION, not what will
make money.

The scanner's question is "what is unusual right now?"; whether an
abnormality has a plausible tradable mechanism is the playbooks' question.
That separation is what prevents the scanner from becoming a hidden alpha
optimizer: its thresholds are ATTENTION thresholds, frozen from what
"abnormal" means statistically (roughly the top few percent of ordinary
variation), never tuned on outcomes. If forward data later shows these
thresholds fire on 500 names a day or five, that is a FINDING about the
thresholds, recorded — not silently retuned.

Funnel discipline: every stage records its full denominator. Zero
candidates is legal and expected to be common.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

import numpy as np

from apex.hunter.chartstate import ChartState
from apex.hunter.relstrength import RelativeStrengthState

SCANNER_VERSION = "hunter_scanner_v1"

# ---- frozen attention thresholds (justifications in HUNTER-SCANNER doc) ----
RVOL_EXTREME = 2.0            # 2x time-of-day median participation
DISPLACEMENT_Z = 2.5          # 30m return vs ATR-implied 30m scale
RANGE_EXPANSION_X = 1.5       # session range so far vs full-day ATR
RS_MARKET_60M = 0.0075        # +75bp excess vs market over 60m
RS_SECTOR_60M = 0.0050        # +50bp excess vs sector over 60m
GAP_MATERIAL = 0.02           # 2% overnight gap
GAP_FAIL_RETRACE = 0.75
# structural (OR/VWAP) events are ordinary drift unless participated and
# material: a marginal poke on below-normal volume describes half the tape
# on any trending day (measured on real data pre-freeze, 2026-08-14 smoke)
STRUCTURE_RVOL_FLOOR = 1.2
OR_BREAK_MATERIAL = 0.25      # beyond the range by >= 25% of its width
MIN_PRICE = 5.0               # frozen liquidity gates (protocol §4)
MIN_MEDIAN_DOLLAR_VOL = 50e6
MIN_MINUTES_IN = 30           # RVOL/displacement unstable before 10:00 ET
WATCHLIST_CAP = 20


class Signal(Enum):
    EXTREME_RVOL = "EXTREME_RVOL"
    PRICE_DISPLACEMENT = "PRICE_DISPLACEMENT"
    RANGE_EXPANSION = "RANGE_EXPANSION"
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"
    RELATIVE_WEAKNESS = "RELATIVE_WEAKNESS"
    OPENING_RANGE_BREAK_UP = "OPENING_RANGE_BREAK_UP"
    OPENING_RANGE_BREAK_DOWN = "OPENING_RANGE_BREAK_DOWN"
    VWAP_RECLAIM = "VWAP_RECLAIM"
    VWAP_LOSS = "VWAP_LOSS"
    GAP_AND_GO = "GAP_AND_GO"
    GAP_FAILURE = "GAP_FAILURE"


# declared in the design, not computable from v1 data; listed so their
# absence is visible rather than forgotten
DORMANT_SIGNALS = ("VOLATILITY_EXPANSION_MULTIDAY", "COMPRESSION_RELEASE",
                   "SECTOR_DIVERGENCE", "PEER_DIVERGENCE")


def displacement_z(cs: ChartState) -> float | None:
    """30m return in units of the ATR-implied 30m move: atr_frac/sqrt(13)
    (13 half-hours per session). Scale from PRIOR days only."""
    if cs.r_30m is None or not cs.atr_frac:
        return None
    return float(cs.r_30m / (cs.atr_frac / np.sqrt(13)))


def detect_signals(cs: ChartState, rs: RelativeStrengthState) -> tuple:
    s: list = []
    if cs.minutes_into_session < MIN_MINUTES_IN:
        return ()
    if cs.rvol_tod is not None and cs.rvol_tod >= RVOL_EXTREME:
        s.append(Signal.EXTREME_RVOL)
    z = displacement_z(cs)
    if z is not None and abs(z) >= DISPLACEMENT_Z:
        s.append(Signal.PRICE_DISPLACEMENT)
    if cs.range_vs_atr is not None and cs.range_vs_atr >= RANGE_EXPANSION_X:
        s.append(Signal.RANGE_EXPANSION)
    if (rs.excess_market_60m is not None and rs.excess_sector_60m is not None):
        if (rs.excess_market_60m >= RS_MARKET_60M
                and rs.excess_sector_60m >= RS_SECTOR_60M):
            s.append(Signal.RELATIVE_STRENGTH)
        if (rs.excess_market_60m <= -RS_MARKET_60M
                and rs.excess_sector_60m <= -RS_SECTOR_60M):
            s.append(Signal.RELATIVE_WEAKNESS)
    # attention is on the CURRENT state (price outside the OR now, not a
    # round-tripped poke), and structural events must be participated AND
    # material — otherwise they describe half the tape on a trending day
    participated = cs.rvol_tod is not None and cs.rvol_tod >= STRUCTURE_RVOL_FLOOR
    if (participated and cs.position_in_or is not None
            and cs.position_in_or > 1.0 + OR_BREAK_MATERIAL):
        s.append(Signal.OPENING_RANGE_BREAK_UP)
    if (participated and cs.position_in_or is not None
            and cs.position_in_or < -OR_BREAK_MATERIAL):
        s.append(Signal.OPENING_RANGE_BREAK_DOWN)
    if participated and cs.vwap_reclaim:
        s.append(Signal.VWAP_RECLAIM)
    if participated and cs.vwap_rejection:
        s.append(Signal.VWAP_LOSS)
    if cs.gap_frac is not None and abs(cs.gap_frac) >= GAP_MATERIAL:
        cont = (cs.day_return is not None
                and np.sign(cs.day_return) == np.sign(cs.gap_frac)
                and abs(cs.day_return) > 0)
        if cont:
            s.append(Signal.GAP_AND_GO)
        if (cs.gap_fill_frac is not None
                and cs.gap_fill_frac >= GAP_FAIL_RETRACE):
            s.append(Signal.GAP_FAILURE)
    return tuple(s)


def liquidity_data_ok(cs: ChartState) -> tuple:
    """(ok, reasons). Fail closed: unknown liquidity is a refusal."""
    reasons = []
    if cs.price < MIN_PRICE:
        reasons.append("PRICE_BELOW_MIN")
    if cs.median_dollar_volume is None:
        reasons.append("MEDIAN_DOLLAR_VOLUME_UNKNOWN")
    elif cs.median_dollar_volume < MIN_MEDIAN_DOLLAR_VOL:
        reasons.append("MEDIAN_DOLLAR_VOLUME_BELOW_MIN")
    hard = {"STALE_BARS", "SPARSE_BARS", "NO_RVOL_BASELINE", "NO_ATR_CONTEXT"}
    bad = hard.intersection(cs.data_quality)
    if bad:
        reasons.extend(sorted(bad))
    return (len(reasons) == 0, tuple(reasons))


@dataclass(frozen=True)
class ScanResult:
    t_utc: str
    scanner_version: str
    universe_count: int
    states_computed: int
    liquidity_data_ok: int
    abnormal: int
    watchlist: tuple                # ((symbol, signals, sort_key), ...)
    rejected_examples: tuple        # sample of refusals with reasons
    dormant_signals: tuple = DORMANT_SIGNALS

    def as_record(self) -> dict:
        d = asdict(self)
        d["watchlist"] = [{"symbol": s, "signals": [x.value for x in sig],
                           "rvol": k} for s, sig, k in self.watchlist]
        return d


def scan(t_utc: str, universe_count: int,
         pairs: list) -> ScanResult:
    """pairs: [(ChartState, RelativeStrengthState), ...] for every name a
    state could be computed for. Returns the funnel with denominators."""
    ok_pairs, rejected = [], []
    for cs, rs in pairs:
        ok, why = liquidity_data_ok(cs)
        if ok:
            ok_pairs.append((cs, rs))
        elif len(rejected) < 10:
            rejected.append((cs.symbol, why))
    hits = []
    for cs, rs in ok_pairs:
        sigs = detect_signals(cs, rs)
        if sigs:
            hits.append((cs.symbol, sigs,
                         float(cs.rvol_tod or 0.0), cs, rs))
    hits.sort(key=lambda h: (-len(h[1]), -h[2]))
    watch = tuple((s, sig, rv) for s, sig, rv, _, _ in hits[:WATCHLIST_CAP])
    return ScanResult(
        t_utc=t_utc, scanner_version=SCANNER_VERSION,
        universe_count=universe_count, states_computed=len(pairs),
        liquidity_data_ok=len(ok_pairs), abnormal=len(hits),
        watchlist=watch, rejected_examples=tuple(rejected))
