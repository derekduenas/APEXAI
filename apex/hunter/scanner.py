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
from apex.hunter.watchlist import make_entry

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
from apex.hunter.contracts import (LIQUIDITY_MIN_MEDIAN_DOLLAR_VOL,  # noqa: E402
                                   LIQUIDITY_MIN_PRICE)
MIN_PRICE = LIQUIDITY_MIN_PRICE               # sovereign source (F-07)
MIN_MEDIAN_DOLLAR_VOL = LIQUIDITY_MIN_MEDIAN_DOLLAR_VOL
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
    watchlist: tuple                # (WatchlistEntry, ...) -- the canonical
                                    # contract, apex/hunter/watchlist.py
    rejected_examples: tuple        # sample of refusals with reasons
    dormant_signals: tuple = DORMANT_SIGNALS

    def as_record(self) -> dict:
        d = asdict(self)
        d["watchlist"] = [e.as_record() for e in self.watchlist]
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
    # RVOL HONESTY: cs.rvol_tod is None on an invalid session anchor
    # (SESSION INTEGRITY GATE, chartstate.py v1.2) -- it is never
    # laundered into 0.0 here. A missing rvol is its own sort tier
    # (WatchlistEntry.sort_key), never confused with a real near-zero
    # reading, and is persisted as rvol=None + rvol_status, never as a
    # fabricated number a downstream consumer could mistake for data.
    hits = []
    for cs, rs in ok_pairs:
        sigs = detect_signals(cs, rs)
        if sigs:
            rvol = cs.rvol_tod           # already None when invalid
            rvol_status = (cs.feature_validity.get("rvol_tod", {})
                          .get("status", "UNKNOWN")
                          if cs.feature_validity else
                          ("VALID" if rvol is not None else "UNKNOWN"))
            entry = make_entry(cs.symbol, [s.value for s in sigs], rvol,
                               rvol_status=rvol_status, as_of=cs.t_utc)
            hits.append(entry)
    hits.sort(key=lambda e: e.sort_key())
    watch = tuple(hits[:WATCHLIST_CAP])
    return ScanResult(
        t_utc=t_utc, scanner_version=SCANNER_VERSION,
        universe_count=universe_count, states_computed=len(pairs),
        liquidity_data_ok=len(ok_pairs), abnormal=len(hits),
        watchlist=watch, rejected_examples=tuple(rejected))
