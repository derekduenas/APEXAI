"""OptionSurfaceState — F O6: per (expiry, strike) surface features,
each carrying {value, status, support, freshness, known_from}, the same
honesty discipline as apex.frontier2.curve.DimensionCurvature. No
single scalar "IV Rank" stands in for the whole surface.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

SUPPORTED, NO_SUPPORT = "SUPPORTED", "NO_SUPPORT"

SURFACE_FEATURES = ("atm_iv", "skew", "smile_curvature", "term_structure",
                   "call_put_relative_richness", "spread_dollars", "spread_pct",
                   "depth", "volume", "open_interest",
                   "surface_change_1m", "surface_change_5m", "surface_change_15m",
                   "surface_change_30m", "surface_change_60m")


class SurfaceStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class SurfaceFeature:
    name: str
    value: float | None
    status: str
    support: int
    freshness_s: float | None
    known_from: str

    def __post_init__(self):
        if self.name not in SURFACE_FEATURES:
            raise SurfaceStateError(f"unknown surface feature {self.name!r}")
        if self.status not in (SUPPORTED, NO_SUPPORT):
            raise SurfaceStateError(f"unknown status {self.status!r}")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OptionSurfaceState:
    symbol: str
    expiration: str
    standardized_moneyness: float | None
    delta_bucket: str | None
    features: dict
    known_from: str
    as_of: str
    schema_version: str = "OPTION_SURFACE_SCHEMA_V1"
    decision_power: str = OPTIONS_RESEARCH_POWER

    def as_record(self) -> dict:
        return {"kind": "option_surface_state", **asdict(self)}

    def feature(self, name: str) -> dict | None:
        return self.features.get(name)


def build_feature(name: str, value: float | None, *, known_from,
                  reason_unsupported: str | None = None, freshness_s=None) -> SurfaceFeature:
    if value is None:
        return SurfaceFeature(name=name, value=None, status=NO_SUPPORT, support=0,
                              freshness_s=None, known_from=str(known_from))
    return SurfaceFeature(name=name, value=value, status=SUPPORTED, support=1,
                          freshness_s=freshness_s, known_from=str(known_from))


def build_surface(symbol: str, expiration: str, *, known_from, now,
                  standardized_moneyness=None, delta_bucket=None,
                  values: dict | None = None) -> OptionSurfaceState:
    """`values`: {feature_name: value_or_None}. Any SURFACE_FEATURES name
    not in `values` is built as NO_SUPPORT automatically -- callers
    never have to remember to declare absence."""
    import pandas as pd
    values = values or {}
    features = {}
    for name in SURFACE_FEATURES:
        features[name] = build_feature(
            name, values.get(name), known_from=known_from,
            reason_unsupported=None if name in values else "NOT_SUPPLIED"
        ).as_record()
    return OptionSurfaceState(
        symbol=symbol, expiration=expiration,
        standardized_moneyness=standardized_moneyness, delta_bucket=delta_bucket,
        features=features, known_from=str(pd.Timestamp(known_from)),
        as_of=str(pd.Timestamp(now)))
