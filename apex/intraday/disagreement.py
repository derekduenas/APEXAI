"""DataDisagreementState — for a serious candidate, compare every
available price/quote source and record where they disagree. Never
silently choose one source over another; the disagreement itself is a
first-class, persisted fact.

Phase 0.4 (FULL-UNIVERSE SENSORY ARCHITECTURE). Sources in scope for
APEX today: the primary broad realtime feed (currently EODHD trades),
a secondary source when configured, and Robinhood's executable quote/L2
(via the microscope child-session route) as the closest thing APEX has
to "the price you could actually trade at."

decision_power: NONE. This module measures disagreement; it never
resolves it into a single "true" price.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# a price disagreement below this fraction is noise (quote timing jitter
# between two legitimately-synced sources); above it is MATERIAL
MATERIAL_PRICE_DIFF_FRAC = 0.002        # 20bp
MATERIAL_STALENESS_S = 30.0             # matches the SAC1-15 gateway law


@dataclass(frozen=True)
class SourceQuote:
    source: str
    price: float | None
    bid: float | None
    ask: float | None
    event_time: str | None
    known_from: str | None


@dataclass(frozen=True)
class DataDisagreementState:
    symbol: str
    as_of: str
    sources: tuple                       # (SourceQuote, ...)

    price_diff_frac: float | None
    timestamp_diff_s: float | None
    spread_diff_frac: float | None

    staleness_by_source: dict            # source -> age_s or None

    material: bool
    reason: str

    def as_record(self) -> dict:
        return {"kind": "data_disagreement_state", **asdict(self)}


def compare(symbol: str, as_of, sources: tuple, *,
           material_price_diff: float = MATERIAL_PRICE_DIFF_FRAC,
           material_staleness_s: float = MATERIAL_STALENESS_S
           ) -> DataDisagreementState:
    import pandas as pd
    t = pd.Timestamp(as_of)
    priced = [s for s in sources if s.price is not None]

    price_diff = timestamp_diff = spread_diff = None
    reasons = []
    if len(priced) >= 2:
        prices = [s.price for s in priced]
        price_diff = round((max(prices) - min(prices)) / min(prices), 5) \
            if min(prices) > 0 else None
        times = [pd.Timestamp(s.event_time) for s in priced
                if s.event_time is not None]
        if len(times) >= 2:
            timestamp_diff = round(
                (max(times) - min(times)).total_seconds(), 3)
        spreads = [(s.ask - s.bid) / s.price for s in priced
                  if s.bid is not None and s.ask is not None
                  and s.price not in (None, 0)]
        if len(spreads) >= 2:
            spread_diff = round(max(spreads) - min(spreads), 5)

    staleness = {}
    for s in sources:
        if s.known_from is None:
            staleness[s.source] = None
            continue
        staleness[s.source] = round(
            (t - pd.Timestamp(s.known_from)).total_seconds(), 1)

    material = False
    if price_diff is not None and price_diff >= material_price_diff:
        material = True
        reasons.append(f"price_diff {price_diff:.4f} >= "
                       f"{material_price_diff}")
    for src, age in staleness.items():
        if age is not None and age > material_staleness_s:
            material = True
            reasons.append(f"{src} stale {age:.0f}s")
    if not priced:
        material = True
        reasons.append("no source produced a comparable price")

    return DataDisagreementState(
        symbol=symbol, as_of=str(t), sources=tuple(sources),
        price_diff_frac=price_diff, timestamp_diff_s=timestamp_diff,
        spread_diff_frac=spread_diff, staleness_by_source=staleness,
        material=material, reason="; ".join(reasons) or "sources agree")
