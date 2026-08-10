"""Analytic null reference for the IC t-statistic.

WHY THIS EXISTS
---------------
Protocol section 7 pre-registers a Newey-West HAC t-statistic at lag 25 on a
DAILY cross-sectional IC series. Because the forward window is 20 trading days,
consecutive IC observations share 19 of their 20 days, and the IC series under
the null is a moving average of order 19. Its autocorrelation decays linearly
from ~0.92 at lag 1 to ~0 at lag 19 -- which is exactly what the pipeline
produces, confirming the overlap structure is correct.

A Bartlett kernel weights the autocovariance at lag j by (1 - j/(lag+1)). At
lag 25 the weight on lag 19 is 0.27, so the estimator discards roughly three
quarters of the autocovariance that actually matters. The long-run variance is
therefore under-estimated, standard errors are too small, and the t-statistic is
over-dispersed. Measured: sd(t) ~ 1.21 and a nominal 5% test rejects ~10.5% at
holdout sample length.

This is a property of the pre-registered ESTIMATOR, not a defect in APEX.

WHAT WAS DONE ABOUT IT
----------------------
User ruling, 2026-08-09: disclose, do not amend. Protocol section 7 keeps lag 25
and section 10 keeps t >= 2.5. The measured true size is stamped on every result
instead of being corrected away, and the amendment log stays empty.

What IS corrected is the Stage 2 gate, which previously compared the pipeline
against a ~5% expectation that was never right for this estimator. It now
compares the pipeline's t-distribution against a reference simulated from an
independent model of the null process at the same (n_obs, overlap, lag, kernel).

Three properties keep that from being a constant quietly widened until green:

  1. The reference is generated from the null MODEL. It never sees pipeline
     output, so it cannot be tuned to match whatever APEX happens to produce.
  2. The resulting gate is TWO-SIDED. A pipeline whose t-statistics are too
     TIGHT now fails as well -- a failure mode the old ceiling could not see.
  3. `describes_autocorrelation_of` verifies the model actually applies to the
     series being judged. If APEX's IC autocorrelation is not MA(overlap), the
     reference is void and the comparison refuses to certify anything.

The grand-mean-IC assertion in the null rig is untouched. That is the test which
detects lookahead and survivorship contamination, and it was always correct.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np

BARTLETT = "bartlett"
TRUNCATED = "truncated"

# Replications are generated in chunks so a long series at high replication
# count does not materialise a single multi-hundred-megabyte array.
_CHUNK = 2000


class ReferenceError(ValueError):
    """The reference could not be constructed, or was asked for nonsense."""


# ---------------------------------------------------------------------------
# the estimator
# ---------------------------------------------------------------------------


def _kernel_weight(j: int, lag: int, kernel: str) -> float:
    if kernel == BARTLETT:
        return 1.0 - j / (lag + 1.0)
    if kernel == TRUNCATED:
        return 1.0
    raise ReferenceError(f"unknown kernel '{kernel}'")


def _hac_tstat_batch(y: np.ndarray, lag: int, kernel: str) -> np.ndarray:
    """t-statistic of the mean of each row, under a HAC long-run variance.

    Vectorised across rows. Regressing on a constant makes the HAC covariance of
    the intercept the HAC variance of the mean, which is what protocol section 7
    asks for -- the same quantity `apex.evaluate.ic.newey_west_tstat` computes
    through statsmodels.
    """
    n_obs = y.shape[1]
    means = y.mean(axis=1)
    e = y - means[:, None]

    s = np.einsum("rt,rt->r", e, e) / n_obs  # gamma_0
    for j in range(1, min(lag, n_obs - 1) + 1):
        gamma = np.einsum("rt,rt->r", e[:, j:], e[:, :-j]) / n_obs
        s += 2.0 * _kernel_weight(j, lag, kernel) * gamma

    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(s > 0, means / np.sqrt(s / n_obs), np.nan)
    return out


def hac_tstat(x: np.ndarray, lag: int, kernel: str = BARTLETT) -> float:
    """Scalar convenience wrapper over `_hac_tstat_batch`."""
    values = np.asarray(x, dtype="float64").ravel()
    if values.size < 2:
        return float("nan")
    return float(_hac_tstat_batch(values[None, :], lag, kernel)[0])


def autocorrelation(x: np.ndarray, max_lag: int) -> np.ndarray:
    """Sample autocorrelation of `x` at lags 0..max_lag."""
    values = np.asarray(x, dtype="float64").ravel()
    e = values - values.mean()
    denominator = float(e @ e)
    if denominator <= 0:
        raise ReferenceError("series has zero variance; autocorrelation undefined")
    return np.array(
        [float(e[j:] @ e[: e.size - j]) / denominator for j in range(max_lag + 1)]
    )


# ---------------------------------------------------------------------------
# the reference distribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NullReference:
    """Simulated distribution of the IC t-statistic under the null.

    The null model: forward returns carry no cross-sectional information, so each
    day's IC is pure noise, and an IC measured over a `overlap`-day forward window
    is the moving average of `overlap` such daily shocks. That produces exactly
    the triangular autocorrelation the pipeline exhibits.
    """

    t_stats: np.ndarray
    n_obs: int
    overlap: int
    lag: int
    kernel: str
    seed: int
    n_replications: int
    autocorrelation_tolerance: float = 0.20
    _finite: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        finite = self.t_stats[np.isfinite(self.t_stats)]
        if finite.size < 2:
            raise ReferenceError("reference simulation produced no usable t-statistics")
        object.__setattr__(self, "_finite", finite)
        object.__setattr__(self, "t_stats", np.asarray(self.t_stats, dtype="float64"))

    # -- summary statistics --------------------------------------------------

    @property
    def mean(self) -> float:
        return float(self._finite.mean())

    @property
    def sd(self) -> float:
        return float(self._finite.std(ddof=1))

    def quantile(self, q: float) -> float:
        return float(np.quantile(self._finite, q))

    def rejection_rate(self, threshold: float = 1.96) -> float:
        """Two-sided rejection rate of a nominal test at `threshold`."""
        return float((np.abs(self._finite) > threshold).mean())

    def one_sided_size(self, threshold: float) -> float:
        """P(t >= threshold | H0). The number disclosed with every result."""
        return float((self._finite >= threshold).mean())

    def family_wise_size(self, threshold: float, n_tests: int) -> float:
        """Uncorrected family-wise error over `n_tests` independent looks.

        This is what makes the ledger's Holm correction necessary; it is reported
        rather than used as a threshold.
        """
        if n_tests < 1:
            raise ReferenceError("n_tests must be at least 1")
        return 1.0 - (1.0 - self.one_sided_size(threshold)) ** n_tests

    @property
    def nominal_one_sided_size(self) -> float:
        """What a correctly-sized normal test would give at t >= 2.5."""
        return 0.5 * math.erfc(2.5 / math.sqrt(2.0))

    @property
    def digest(self) -> str:
        """Stable hash of the simulated distribution, for the results header."""
        h = hashlib.sha256()
        h.update(
            f"{self.n_obs}|{self.overlap}|{self.lag}|{self.kernel}|"
            f"{self.seed}|{self.n_replications}".encode()
        )
        h.update(np.asarray(self.t_stats, dtype="float64").tobytes())
        return h.hexdigest()

    # -- validity of the model itself ----------------------------------------

    def describes_autocorrelation_of(self, series: np.ndarray) -> bool:
        """Does the MA(`overlap`) null model actually describe this IC series?

        Checked rather than assumed. If APEX's IC autocorrelation has not decayed
        by the overlap horizon, the reference is not the right yardstick and the
        comparison must not be allowed to certify anything.
        """
        values = np.asarray(series, dtype="float64").ravel()
        values = values[np.isfinite(values)]
        if values.size < 4 * self.overlap:
            raise ReferenceError(
                f"need at least {4 * self.overlap} observations to judge "
                f"autocorrelation structure; got {values.size}"
            )
        acf = autocorrelation(values, min(2 * self.overlap, values.size - 2))
        tail = np.abs(acf[self.overlap :])
        return bool(tail.mean() < self.autocorrelation_tolerance)

    def disclosure(self) -> dict:
        """The block stamped onto every RunResult header."""
        return {
            "estimator": f"newey-west {self.kernel} lag {self.lag}",
            "overlap_trading_days": self.overlap,
            "n_obs": self.n_obs,
            "reference_replications": self.n_replications,
            "reference_digest": self.digest[:16],
            "sd_of_t_under_null": round(self.sd, 4),
            "nominal_5pct_test_actual_size": round(self.rejection_rate(1.96), 4),
            "threshold_2p5_nominal_one_sided_size": round(self.nominal_one_sided_size, 5),
            "threshold_2p5_measured_one_sided_size": round(self.one_sided_size(2.5), 5),
            "note": (
                "Bartlett HAC under-weights the MA(overlap-1) autocovariance of "
                "overlapping forward windows, so the pre-registered t >= 2.5 "
                "hurdle is less stringent than its nominal size implies. "
                "Pre-registration NOT amended (ruling 2026-08-09); disclosed here."
            ),
        }


def simulate_null_tstats(
    n_obs: int,
    overlap: int,
    lag: int,
    kernel: str = BARTLETT,
    n_replications: int = 20_000,
    seed: int = 0,
    autocorrelation_tolerance: float = 0.20,
) -> NullReference:
    """Simulate the null distribution of the HAC t-statistic.

    Each replication builds an IC series as the `overlap`-day moving average of
    iid standard-normal daily shocks, then applies the same HAC estimator the
    pipeline reports. The shocks' scale is irrelevant: the t-statistic is scale
    invariant, so no assumption about the size of a daily IC is being smuggled in.
    """
    if n_obs < 4:
        raise ReferenceError(f"n_obs must be at least 4; got {n_obs}")
    if overlap < 1:
        raise ReferenceError(f"overlap must be at least 1; got {overlap}")
    if lag < 0:
        raise ReferenceError(f"lag must be non-negative; got {lag}")

    rng = np.random.default_rng(seed)
    chunks: list[np.ndarray] = []
    remaining = int(n_replications)

    while remaining > 0:
        size = min(_CHUNK, remaining)
        shocks = rng.standard_normal((size, n_obs + overlap - 1))
        # Moving average of `overlap` shocks, via cumulative sums.
        cumulative = np.concatenate(
            [np.zeros((size, 1)), np.cumsum(shocks, axis=1)], axis=1
        )
        series = (cumulative[:, overlap:] - cumulative[:, :-overlap]) / overlap
        chunks.append(_hac_tstat_batch(series, lag, kernel))
        remaining -= size

    return NullReference(
        t_stats=np.concatenate(chunks),
        n_obs=int(n_obs),
        overlap=int(overlap),
        lag=int(lag),
        kernel=kernel,
        seed=int(seed),
        n_replications=int(n_replications),
        autocorrelation_tolerance=float(autocorrelation_tolerance),
    )


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsistencyVerdict:
    """Is an observed sample of t-statistics consistent with the null reference?"""

    consistent: bool
    n_observed: int
    observed_mean: float
    observed_sd: float
    reference_mean: float
    reference_sd: float
    location_z: float
    dispersion_z: float
    z_threshold: float
    power_to_detect_unit_shift: float
    underpowered: bool
    failures: tuple[str, ...]

    def explain(self) -> str:
        lines = [
            f"observed {self.n_observed} null worlds: "
            f"mean t = {self.observed_mean:+.3f}, sd t = {self.observed_sd:.3f}",
            f"reference (same estimator, same n_obs): "
            f"mean t = {self.reference_mean:+.3f}, sd t = {self.reference_sd:.3f}",
            f"location z = {self.location_z:+.2f}, dispersion z = "
            f"{self.dispersion_z:+.2f}, threshold |z| = {self.z_threshold:.1f}",
            f"power to detect a +1.0 shift at this sample size: "
            f"{self.power_to_detect_unit_shift:.0%}"
            + ("  [UNDERPOWERED]" if self.underpowered else ""),
        ]
        if self.failures:
            lines.append("FAILED: " + "; ".join(self.failures))
        return "\n".join(lines)


def _dispersion_null(
    reference: NullReference, n: int, rng: np.random.Generator, n_boot: int = 2000
) -> tuple[float, float]:
    """Sampling mean and sd of sd(t) for a sample of size `n` drawn from the reference."""
    draws = rng.choice(reference.t_stats[np.isfinite(reference.t_stats)], size=(n_boot, n))
    sds = draws.std(axis=1, ddof=1)
    return float(sds.mean()), float(sds.std(ddof=1))


def consistency(
    observed: np.ndarray,
    reference: NullReference,
    z_threshold: float = 3.0,
    min_power: float = 0.50,
    seed: int = 20260809,
) -> ConsistencyVerdict:
    """Two-sided comparison of observed null t-statistics against the reference.

    LOCATION catches a pipeline that produces systematically inflated (or
    deflated) t-statistics -- the signature of lookahead or survivorship leakage.

    DISPERSION catches a pipeline whose t-statistics are too wide or too tight,
    which is how a broken standard error or a collapsing cross-section shows up.

    The verdict also reports its own power, so a green result on a small sweep
    cannot be mistaken for evidence of correctness.
    """
    values = np.asarray(observed, dtype="float64").ravel()
    values = values[np.isfinite(values)]
    n = values.size
    if n < 2:
        raise ReferenceError(f"need at least 2 observed t-statistics; got {n}")

    rng = np.random.default_rng(seed)

    location_se = reference.sd / math.sqrt(n)
    location_z = (float(values.mean()) - reference.mean) / location_se

    boot_mean, boot_sd = _dispersion_null(reference, n, rng)
    dispersion_z = (float(values.std(ddof=1)) - boot_mean) / boot_sd if boot_sd > 0 else 0.0

    failures: list[str] = []
    if abs(location_z) > z_threshold:
        failures.append(
            f"location shifted {location_z:+.1f} standard errors from the null "
            f"reference -- the signature of lookahead or survivorship leakage"
        )
    if abs(dispersion_z) > z_threshold:
        direction = "wider" if dispersion_z > 0 else "tighter"
        failures.append(
            f"dispersion is {direction} than the reference by {abs(dispersion_z):.1f} "
            f"standard errors -- the standard errors or the cross-section are wrong"
        )

    shifted = rng.choice(reference.t_stats[np.isfinite(reference.t_stats)], size=(400, n)) + 1.0
    detected = np.abs((shifted.mean(axis=1) - reference.mean) / location_se) > z_threshold
    power = float(detected.mean())

    return ConsistencyVerdict(
        consistent=not failures,
        n_observed=n,
        observed_mean=float(values.mean()),
        observed_sd=float(values.std(ddof=1)),
        reference_mean=reference.mean,
        reference_sd=reference.sd,
        location_z=location_z,
        dispersion_z=dispersion_z,
        z_threshold=z_threshold,
        power_to_detect_unit_shift=power,
        underpowered=power < min_power,
        failures=tuple(failures),
    )
