"""Ruling 5 -- preprocessing must be strictly cross-sectional per date.

    "Assert that winsorization, z-scoring, and ranking are strictly
     cross-sectional per date. No global fit (no using future distribution
     moments). If violated -> hard fail."

WHY THE STAGE 3 AUDITOR DOES NOT ALREADY COVER THIS

`apex/audit/lookahead.py` destroys everything AFTER T and checks that nothing
known at T moved. That catches a preprocessing step fitted on future data. It
cannot catch a step fitted on an EXPANDING WINDOW OF PAST DATA -- a percentile
taken over "all history through T", say. That is not lookahead; it is still
forbidden. Protocol section 5 specifies a per-date cross-section at every step:
winsorise at the 1st/99th percentiles OF THAT DATE, z-score against THAT DATE's
moments, rank within THAT DATE.

A global or expanding fit changes what a score means from one date to the next
and couples every security's score to the sample it was computed over.

THE MEASUREMENT

Strict per-date cross-sectionality is exactly the statement that row T is
independent of every other row. So: destroy every row EXCEPT T -- past and
future alike -- recompute, and require row T to be bit-identical. That is a
direct measurement of the property rather than a proxy for it, and it needs no
knowledge of how the composite is implemented.

The two audits are complementary and both are needed:

    lookahead.py        perturbs the FUTURE      catches future leakage
    cross_sectional.py  perturbs EVERY OTHER ROW catches any non-per-date fit
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import FeaturePanel
from apex.features.composite import build_scores

# Recomputation on an identical row is deterministic, so a clean audit is exact.
# The tolerance absorbs floating-point reassociation only.
TOLERANCE = 1e-12


class CrossSectionalAuditError(ValueError):
    """The audit was asked for something it cannot meaningfully answer."""


@dataclass(frozen=True)
class CrossSectionalViolation:
    date: pd.Timestamp
    component: str
    n_securities: int
    max_abs_delta: float

    def describe(self) -> str:
        return (
            f"  {self.date.date()}  {self.component}: {self.n_securities} securities "
            f"changed when OTHER dates were perturbed, max |delta| = "
            f"{self.max_abs_delta:.6g}"
        )


@dataclass(frozen=True)
class CrossSectionalReport:
    probe_dates: tuple
    components: tuple
    violations: tuple
    n_comparisons: int

    @property
    def clean(self) -> bool:
        return not self.violations

    def explain(self) -> str:
        head = (
            f"cross-sectional audit: {self.n_comparisons} comparisons over "
            f"{len(self.probe_dates)} probe dates x {len(self.components)} components"
        )
        if self.clean:
            return (
                head + "\n  CLEAN -- every scored value at T is independent of every "
                "other date, so winsorisation, z-scoring and ranking are strictly "
                "cross-sectional (ruling 5)"
            )
        lines = [
            head,
            f"  {len(self.violations)} VIOLATION(S) of ruling 5 -- preprocessing is "
            f"NOT strictly cross-sectional; a global or expanding fit is present:",
        ]
        lines.extend(v.describe() for v in self.violations)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "clean": self.clean,
            "probe_dates": [str(d.date()) for d in self.probe_dates],
            "components": list(self.components),
            "n_comparisons": self.n_comparisons,
            "violations": [
                {
                    "date": str(v.date.date()),
                    "component": v.component,
                    "n_securities": v.n_securities,
                    "max_abs_delta": v.max_abs_delta,
                }
                for v in self.violations
            ],
        }


def perturb_all_rows_except(
    frame: pd.DataFrame, keep: pd.Timestamp, seed: int = 0
) -> pd.DataFrame:
    """Randomise every row but `keep`, preserving the missing-data pattern.

    NaNs stay NaN: a cross-sectional operation legitimately depends on WHICH
    securities are present on other dates only through nothing at all, but
    changing the missingness pattern would also change the eligible set and
    muddy what the audit is measuring.
    """
    rng = np.random.default_rng(seed)
    out = frame.copy()
    other = frame.index != keep
    block = out.loc[other]
    noise = rng.standard_normal(block.shape) * 10.0 + 5.0
    out.loc[other] = np.where(block.notna().to_numpy(), noise, np.nan)
    return out


def _default_score_fn(features: FeaturePanel, eligible: pd.DataFrame, config: Config):
    return build_scores(features, eligible, config)


def _targets(scores) -> dict:
    return {**scores.category_scores, "apex_score": scores.apex_score, "decile": scores.decile}


def _row(frame: pd.DataFrame, date: pd.Timestamp) -> np.ndarray:
    if date not in frame.index:
        return np.array([])
    return frame.loc[date].to_numpy(dtype="float64")


def _differences(clean: np.ndarray, other: np.ndarray) -> tuple[int, float]:
    if clean.size == 0 or clean.size != other.size:
        return max(clean.size, other.size), float("inf")

    a_nan, b_nan = np.isnan(clean), np.isnan(other)
    both = ~a_nan & ~b_nan
    scale = np.maximum(1.0, np.maximum(np.abs(clean), np.abs(other)))
    with np.errstate(invalid="ignore"):
        differs = (a_nan != b_nan) | (both & (np.abs(clean - other) > TOLERANCE * scale))

    if not differs.any():
        return 0, 0.0
    deltas = np.abs(clean - other)[both & differs]
    return int(differs.sum()), float(deltas.max()) if deltas.size else float("inf")


def audit_cross_sectional(
    features: FeaturePanel,
    eligible: pd.DataFrame,
    config: Config,
    probe_dates,
    score_fn=_default_score_fn,
    seed: int = 20260809,
) -> CrossSectionalReport:
    """Measure ruling 5 at each date in `probe_dates`. Hard fail on violation.

    Raises rather than reporting clean when the audit could not have detected
    anything -- an unauditable date is not a passing date.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(list(probe_dates)))
    if len(dates) == 0:
        raise CrossSectionalAuditError("no probe dates supplied")

    unknown = [d for d in dates if d not in features.dates]
    if unknown:
        raise CrossSectionalAuditError(f"probe dates absent from the panel: {unknown[:5]}")

    baseline = _targets(score_fn(features, eligible, config))
    components = tuple(sorted(baseline))

    for date in dates:
        if not np.isfinite(_row(baseline["apex_score"], date)).any():
            raise CrossSectionalAuditError(
                f"nothing is scored at {date.date()}; auditing it would compare NaN "
                f"against NaN and pass vacuously. Probe dates must sit at or after "
                f"the section 9 anchor."
            )

    violations: list[CrossSectionalViolation] = []
    n_comparisons = 0

    for date in dates:
        perturbed = dataclasses.replace(
            features,
            components={
                name: perturb_all_rows_except(frame, date, seed=seed)
                for name, frame in features.components.items()
            },
        )
        recomputed = _targets(score_fn(perturbed, eligible, config))

        for component in components:
            n_comparisons += 1
            n_differ, max_delta = _differences(
                _row(baseline[component], date),
                _row(recomputed.get(component, pd.DataFrame()), date),
            )
            if n_differ:
                violations.append(
                    CrossSectionalViolation(
                        date=date,
                        component=component,
                        n_securities=n_differ,
                        max_abs_delta=max_delta,
                    )
                )

    return CrossSectionalReport(
        probe_dates=tuple(dates),
        components=components,
        violations=tuple(violations),
        n_comparisons=n_comparisons,
    )
