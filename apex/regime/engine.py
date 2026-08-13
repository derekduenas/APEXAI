"""Deterministic, PIT-safe regime assignment from a DECLARED definition.

The regime engine EVALUATES a regime definition stated in advance. It does not
discover the regime in which a factor looks best -- there is no method here that
searches thresholds or splits and returns the strongest. "The factor differs by
regime" is evidence this can produce; "therefore trade only in regime X" is a
NEW strategy hypothesis that must be registered and consume a credit, and this
module cannot take that step.

PIT safety reuses the existing discipline: a regime label at date T is a
function only of data with known_from <= T. A definition that would need future
data to assign T is refused, not silently forward-filled.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class RegimeError(ValueError):
    """A regime definition was malformed or would require future data."""


@dataclass(frozen=True)
class RegimeDefinition:
    """A pre-declared regime rule. Canonical, versioned, source-tracked."""

    name: str
    version: str
    state_variable: str          # e.g. 'trailing_vol', 'trend', 'breadth'
    thresholds: tuple            # DECLARED cut points, ascending
    labels: tuple                # len(thresholds)+1 labels
    min_sample: int              # a regime with fewer dates is 'insufficient'
    lineage: str

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.thresholds) + 1:
            raise RegimeError(
                f"{self.name}: {len(self.labels)} labels needs "
                f"{len(self.labels) - 1} thresholds, got {len(self.thresholds)}"
            )
        if list(self.thresholds) != sorted(self.thresholds):
            raise RegimeError(f"{self.name}: thresholds must be ascending")


@dataclass(frozen=True)
class RegimeAssignment:
    definition_name: str
    definition_version: str
    labels_by_date: pd.Series    # date -> regime label
    counts: dict
    insufficient: tuple          # labels below min_sample

    def as_dict(self) -> dict:
        return {
            "definition": f"{self.definition_name}@{self.definition_version}",
            "counts": self.counts,
            "insufficient_regimes": list(self.insufficient),
        }


def assign_regime(
    state_series: pd.Series,
    definition: RegimeDefinition,
    *,
    knowable_asof: pd.Series | None = None,
) -> RegimeAssignment:
    """Assign a regime label per date from a DECLARED definition.

    `state_series` is the pre-declared state variable (e.g. trailing realised
    vol), already PIT-computed. `knowable_asof`, if given, must be <= each date;
    a state value knowable only later is a leak and is refused.
    """
    s = state_series.dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        raise RegimeError("regime assignment needs a DatetimeIndex")
    if knowable_asof is not None:
        asof = knowable_asof.reindex(s.index)
        late = asof[asof > s.index]
        if len(late):
            raise RegimeError(
                f"{definition.name}: state variable for {late.index[0].date()} is "
                f"knowable only at {late.iloc[0]} -- a future leak; refused"
            )

    edges = [-np.inf, *definition.thresholds, np.inf]
    idx = np.digitize(s.to_numpy(), edges[1:-1], right=False)
    labels = pd.Series([definition.labels[i] for i in idx], index=s.index)

    counts = {lab: int((labels == lab).sum()) for lab in definition.labels}
    insufficient = tuple(lab for lab, n in counts.items() if n < definition.min_sample)
    return RegimeAssignment(
        definition_name=definition.name,
        definition_version=definition.version,
        labels_by_date=labels,
        counts=counts,
        insufficient=insufficient,
    )
