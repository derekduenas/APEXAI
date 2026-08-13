"""PIT validation for factory features. MEASURED, not asserted.

Every factory feature is emitted with a `known_from` frame recording the filing
date that made each cell knowable. This module compares that against the
formation date, exactly as the APEX-002 dry run does for NSI. A feature is not
PIT-valid because its raw field exists; it is PIT-valid because no populated
cell was knowable only after its formation date.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PITResult:
    feature_id: str
    populated: int
    violations: int
    missing_knowability: int

    @property
    def compliant(self) -> bool:
        return self.violations == 0 and self.missing_knowability == 0

    @property
    def pct(self) -> float:
        if not self.populated:
            return float("nan")
        return (self.populated - self.violations) / self.populated * 100.0

    def as_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "populated": self.populated,
            "violations": self.violations,
            "missing_knowability": self.missing_knowability,
            "pct": self.pct,
            "compliant": self.compliant,
        }


def validate_feature(
    feature_id: str,
    values: pd.DataFrame,
    known_from: pd.DataFrame,
    eligible: pd.DataFrame,
) -> PITResult:
    present = (eligible & values.notna()).to_numpy()
    if not present.any():
        return PITResult(feature_id, 0, 0, 0)

    kf = known_from.to_numpy()
    formation = np.repeat(known_from.index.to_numpy()[:, None],
                          known_from.shape[1], axis=1)

    missing = int(pd.isna(kf[present]).sum())
    violations = int((kf[present] > formation[present]).sum())
    return PITResult(feature_id, int(present.sum()), violations, missing)


def validate_all(
    values: dict[str, pd.DataFrame],
    known: dict[str, pd.DataFrame],
    eligible: pd.DataFrame,
) -> dict[str, PITResult]:
    return {
        fid: validate_feature(fid, values[fid], known[fid], eligible)
        for fid in sorted(values)
    }
