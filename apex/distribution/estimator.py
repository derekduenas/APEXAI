"""Distribution estimator v1: deterministic, provenance-preserving, honest.

The v1 methodology is the humblest defensible one: the HISTORICAL EMPIRICAL
conditional distribution -- the in-sample forward-return distribution of
names in the same signal bucket (optionally conditioned on world state),
discretized to the expression engine's pmf contract. It is NOT calibrated
and says so; the pipe runs end-to-end today, and the reality loop's forward
record is the only path to the CALIBRATED stamp.

MINTING CALIBRATED IS GATED: `mint_calibrated` demands a reality-loop
calibration report on disk whose producer shows at least
MIN_CALIBRATION_DATES effective dates and reliability at or under the
declared bound. There is no keyword argument that skips this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

from apex.expression.engine import DistributionSource

EVIDENCE_CLASS = "engineering_measurement"

MIN_CALIBRATION_DATES = 10
MAX_CALIBRATION_RELIABILITY = 0.01


class CalibrationStatus(Enum):
    CALIBRATED = "CALIBRATED"
    UNCALIBRATED_MODEL = "UNCALIBRATED_MODEL"
    HISTORICAL_EMPIRICAL = "HISTORICAL_EMPIRICAL"
    SYNTHETIC = "SYNTHETIC"


# The TOTAL, explicit mapping into the expression engine's source enum.
# Nothing maps to CALIBRATED except CALIBRATED. There is no default branch
# that could upgrade a status by omission.
_TO_EXPRESSION_SOURCE = {
    CalibrationStatus.CALIBRATED: DistributionSource.CALIBRATED,
    CalibrationStatus.UNCALIBRATED_MODEL: DistributionSource.UNCALIBRATED_MODEL,
    CalibrationStatus.HISTORICAL_EMPIRICAL: DistributionSource.UNCALIBRATED_MODEL,
    CalibrationStatus.SYNTHETIC: DistributionSource.SYNTHETIC,
}


class EstimatorError(ValueError):
    """A distribution-estimator invariant was violated."""


@dataclass(frozen=True)
class DistributionEstimate:
    returns: np.ndarray
    probs: np.ndarray
    horizon_days: int
    calibration_status: CalibrationStatus
    provenance: dict            # signal, conditioning, window, methodology
    calibration_evidence: str | None
    evidence_class: str = field(default=EVIDENCE_CLASS)

    def expression_source(self) -> DistributionSource:
        return _TO_EXPRESSION_SOURCE[self.calibration_status]

    def expected_return(self) -> float:
        return float((self.returns * self.probs).sum())


def empirical_conditional(bucket_returns, horizon_days: int, *,
                          signal: str, conditioning: dict,
                          estimation_window: str, n_bins: int = 41
                          ) -> DistributionEstimate:
    """The v1: discretize the historical same-bucket forward returns."""
    r = np.asarray(bucket_returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 100:
        raise EstimatorError(
            f"{len(r)} conditional observations is too few to call a "
            f"distribution; refuse rather than smooth")
    # TYPE-CONFUSION GUARD: the inputs must be RETURNS (fractions). A rank,
    # score, or percentile fed here would silently become a 'distribution'
    # -- the exact identity slippage the calibration audit forbids.
    if np.abs(r).max() > 3.0:
        raise EstimatorError(
            f"input values reach {np.abs(r).max():.1f}: these are not "
            f"fractional returns. A rank or score must never become a "
            f"probability distribution by passing through this function.")
    lo, hi = np.quantile(r, 0.005), np.quantile(r, 0.995)
    edges = np.linspace(lo, hi, n_bins + 1)
    counts, _ = np.histogram(np.clip(r, lo, hi), bins=edges)
    probs = counts / counts.sum()
    centers = (edges[:-1] + edges[1:]) / 2
    return DistributionEstimate(
        returns=centers, probs=probs, horizon_days=int(horizon_days),
        calibration_status=CalibrationStatus.HISTORICAL_EMPIRICAL,
        provenance={"signal": signal, "conditioning": dict(conditioning),
                    "estimation_window": estimation_window,
                    "methodology": f"empirical histogram, {n_bins} bins, "
                                   f"n={len(r)}, tails clipped at 0.5%"},
        calibration_evidence=None)


def mint_calibrated(estimate: DistributionEstimate,
                    reality_report: Path, producer: str) -> DistributionEstimate:
    """The ONLY door to CALIBRATED. Demands a reality-loop report whose
    named producer has accrued enough forward evidence."""
    report = json.loads(Path(reality_report).read_text())

    # SAC1-01: WHERE the evidence came from, checked BEFORE how much of it
    # there is. `calibration_certification` is one of the six uses the
    # evidence law forbids to EODHD_HISTORICAL_EXPLORATORY, and until this
    # audit require_permitted() had ZERO production callers -- the law
    # existed, the only door that could violate it never consulted it.
    # CALIBRATED is the sole status permitted to authorize, so minting one
    # from laboratory tape is the shortest path to fabricated confidence.
    from apex.hunter.evidence import (EvidenceClass, EvidenceViolation,
                                      require_permitted)
    raw_class = report.get("evidence_class")
    if raw_class is None:
        raise EvidenceViolation(
            f"{reality_report} carries no evidence_class: calibration "
            f"cannot be certified against evidence of unverifiable "
            f"provenance. Unlabelled is refused exactly as loudly as "
            f"forbidden.")
    try:
        cls = EvidenceClass(raw_class)
    except ValueError:
        raise EvidenceViolation(
            f"unknown evidence_class {raw_class!r} in {reality_report}")
    require_permitted(cls, "calibration_certification")

    stats = report.get("producers", {}).get(producer)
    if stats is None:
        raise EstimatorError(f"{producer!r} has no record in {reality_report}")
    if stats["n_effective_dates"] < MIN_CALIBRATION_DATES:
        raise EstimatorError(
            f"{producer!r} has {stats['n_effective_dates']} effective dates "
            f"< {MIN_CALIBRATION_DATES}: calibration is forward evidence and "
            f"cannot be hurried")
    if stats["reliability"] > MAX_CALIBRATION_RELIABILITY:
        raise EstimatorError(
            f"{producer!r} reliability {stats['reliability']} exceeds the "
            f"{MAX_CALIBRATION_RELIABILITY} bound: its probabilities are not "
            f"yet honest enough to stamp")
    return DistributionEstimate(
        returns=estimate.returns, probs=estimate.probs,
        horizon_days=estimate.horizon_days,
        calibration_status=CalibrationStatus.CALIBRATED,
        provenance={**estimate.provenance,
                    "calibrated_against": producer},
        calibration_evidence=str(reality_report))


def pit_diagnostic(estimates_and_outcomes) -> dict:
    """Probability-integral-transform uniformity check: for each (estimate,
    realized return), where did reality land in the stated cdf? Calibrated
    distributions put reality uniformly across [0,1]; an overconfident model
    piles mass in the tails. Diagnostic for the eventual live path."""
    pits = []
    for est, realized in estimates_and_outcomes:
        cdf = np.cumsum(est.probs)
        pits.append(float(np.interp(realized, est.returns, cdf)))
    pits = np.array(pits)
    counts, _ = np.histogram(pits, bins=10, range=(0, 1))
    return {"n": len(pits),
            "tail_mass_frac": round(float(((pits < 0.1) | (pits > 0.9)).mean()), 3),
            "uniform_expectation": 0.2,
            "decile_counts": counts.tolist()}
