"""WORLD_MODEL_FORECAST_V0 -- P(future path | current causal state).

THIS IS NOT A TRADE RECOMMENDATION. It carries no direction to act on,
no size, and no authority. Something downstream may one day read a
forecast and decide something; that decision will be made THERE, under
its own governance, and this contract will still not have made it.

WHY A DISTRIBUTION AND NOT UP/DOWN
A predator sizes on the shape of the loss distribution, not on a
direction. "Up, 61% confident" cannot be Kelly-sized, cannot be
compared against option-implied state, and cannot be calibrated: it
throws away the tail, which is the only part that decides survival. So
the contract carries quantiles, tail probabilities, MFE/MAE and
intervals, and a directional probability is one derived field among
many rather than the product.

UNAVAILABLE MUST STAY UNAVAILABLE
Every distributional quantity is optional and defaults to None. A model
that cannot separate epistemic from aleatoric uncertainty must say so by
leaving them None -- it may NOT emit 0.0 and let a reader infer
certainty. Fabricating a quantity nobody estimated is worse than
admitting the gap, because the gap is visible and the fabrication is
not.

CONTENT IDENTITY vs INSTANCE IDENTITY
Two forecasts produced from the same input by the same model version
with the same distribution are the SAME SCIENTIFIC OBJECT even though
they were created at different wall-clock instants.

    forecast_hash  CONTENT identity  -- excludes creation_time
    forecast_id    INSTANCE identity -- includes it

Putting creation_time inside the content hash would make scientific
identity depend on when a script happened to run, and two identical
forecasts would look like two different findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field

from apex.world_model.canonical import (NumericContractViolation,
                                        content_hash, strict_float,
                                        strict_probability)

FORECAST_SCHEMA_VERSION = "WORLD_MODEL_FORECAST_V0"

H_5M = "H_5M"
H_15M = "H_15M"
H_30M = "H_30M"
H_60M = "H_60M"
H_SESSION_CLOSE = "H_SESSION_CLOSE"
HORIZONS = (H_5M, H_15M, H_30M, H_60M, H_SESSION_CLOSE)

# Horizon identity is SEMANTIC. H_SESSION_CLOSE deliberately carries no
# duration: the close is a calendar boundary, and its realised instant
# is not knowable when the forecast is made. Encoding it as "+390m"
# would smuggle in an assumption about a session that has not happened.
HORIZON_MINUTES = {H_5M: 5.0, H_15M: 15.0, H_30M: 30.0, H_60M: 60.0,
                   H_SESSION_CLOSE: None}


class ForecastContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class PredictiveDistribution:
    """Everything optional. Absent means NOT ESTIMATED, never zero."""
    expected_return: float | None = None
    median_return: float | None = None
    quantiles: dict | None = None          # {"0.05": x, "0.5": y, ...}
    prob_return_gt_zero: float | None = None
    prob_return_lt_zero: float | None = None
    tail_probabilities: dict | None = None
    expected_mfe: float | None = None
    expected_mae: float | None = None
    mfe_quantiles: dict | None = None
    mae_quantiles: dict | None = None
    predictive_intervals: dict | None = None   # {"0.90": [lo, hi]}
    total_uncertainty: float | None = None
    epistemic_uncertainty: float | None = None
    aleatoric_uncertainty: float | None = None

    def __post_init__(self):
        self.canonical()

    def _q(self, q: dict | None, label: str) -> dict | None:
        if q is None:
            return None
        if not isinstance(q, dict) or not q:
            raise ForecastContractViolation(
                "%s must be a non-empty mapping of quantile -> value"
                % label)
        levels = []
        for k in q:
            lv = strict_probability(_as_level(k, label), field="%s key %r"
                                    % (label, k))
            levels.append((lv, k))
        levels.sort()
        prev_val = None
        out = {}
        for lv, k in levels:
            v = strict_float(q[k], field="%s[%s]" % (label, k))
            if prev_val is not None and v < prev_val:
                raise ForecastContractViolation(
                    "%s is not monotonic: quantile %s gives %r after %r. "
                    "A non-monotonic quantile function is not a "
                    "distribution, and it is NOT sorted into shape here"
                    % (label, k, v, prev_val))
            prev_val = v
            out[str(lv)] = v
        return out

    def canonical(self) -> dict:
        d = {
            "expected_return": strict_float(
                self.expected_return, field="expected_return",
                allow_none=True),
            "median_return": strict_float(
                self.median_return, field="median_return", allow_none=True),
            "quantiles": self._q(self.quantiles, "quantiles"),
            "prob_return_gt_zero": strict_probability(
                self.prob_return_gt_zero, field="prob_return_gt_zero",
                allow_none=True),
            "prob_return_lt_zero": strict_probability(
                self.prob_return_lt_zero, field="prob_return_lt_zero",
                allow_none=True),
            "expected_mfe": strict_float(
                self.expected_mfe, field="expected_mfe", allow_none=True),
            "expected_mae": strict_float(
                self.expected_mae, field="expected_mae", allow_none=True),
            "mfe_quantiles": self._q(self.mfe_quantiles, "mfe_quantiles"),
            "mae_quantiles": self._q(self.mae_quantiles, "mae_quantiles"),
            "total_uncertainty": strict_float(
                self.total_uncertainty, field="total_uncertainty",
                allow_none=True),
            "epistemic_uncertainty": strict_float(
                self.epistemic_uncertainty, field="epistemic_uncertainty",
                allow_none=True),
            "aleatoric_uncertainty": strict_float(
                self.aleatoric_uncertainty, field="aleatoric_uncertainty",
                allow_none=True),
        }
        if self.tail_probabilities is not None:
            if not isinstance(self.tail_probabilities, dict):
                raise ForecastContractViolation(
                    "tail_probabilities must be a mapping")
            d["tail_probabilities"] = {
                str(k): strict_probability(
                    v, field="tail_probabilities[%s]" % k)
                for k, v in self.tail_probabilities.items()}
        else:
            d["tail_probabilities"] = None

        if self.predictive_intervals is not None:
            if not isinstance(self.predictive_intervals, dict):
                raise ForecastContractViolation(
                    "predictive_intervals must be a mapping")
            iv = {}
            for k, pair in self.predictive_intervals.items():
                strict_probability(_as_level(k, "predictive_intervals"),
                                   field="predictive_intervals key %r" % k)
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ForecastContractViolation(
                        "predictive_intervals[%s] must be [lo, hi]" % k)
                lo = strict_float(pair[0], field="interval %s lo" % k)
                hi = strict_float(pair[1], field="interval %s hi" % k)
                if lo > hi:
                    raise ForecastContractViolation(
                        "predictive_intervals[%s] = [%r, %r] is inverted; "
                        "it is NOT reordered here" % (k, lo, hi))
                iv[str(k)] = [lo, hi]
            d["predictive_intervals"] = iv
        else:
            d["predictive_intervals"] = None

        p_up, p_dn = d["prob_return_gt_zero"], d["prob_return_lt_zero"]
        if p_up is not None and p_dn is not None and p_up + p_dn > 1.0 + 1e-9:
            raise ForecastContractViolation(
                "P(r>0)=%r and P(r<0)=%r sum to more than 1" % (p_up, p_dn))
        return d


def _as_level(key, label):
    if isinstance(key, bool):
        raise ForecastContractViolation("%s key is a bool" % label)
    if isinstance(key, (int, float)):
        return float(key)
    try:
        return float(key)
    except (TypeError, ValueError):
        raise ForecastContractViolation(
            "%s key %r is not a quantile level" % (label, key)) from None


@dataclass(frozen=True)
class WorldModelForecast:
    forecast_id: str
    input_id: str
    input_hash: str
    model_id: str
    model_version: str
    model_family: str
    information_tier: str
    creation_time: float
    known_from: float
    forecast_horizon: str
    distribution: PredictiveDistribution
    calibration_metadata: dict = _field(default_factory=dict)
    uncertainty_metadata: dict = _field(default_factory=dict)
    schema_version: str = FORECAST_SCHEMA_VERSION

    def __post_init__(self):
        self._validate()

    def _validate(self) -> None:
        if self.forecast_horizon not in HORIZONS:
            raise ForecastContractViolation(
                "unknown forecast_horizon %r; permitted %s"
                % (self.forecast_horizon, list(HORIZONS)))
        if not self.input_hash:
            raise ForecastContractViolation(
                "forecast does not commit to an input_hash: an unbound "
                "forecast cannot be checked against what it claims to "
                "have seen")
        strict_float(self.creation_time, field="creation_time")
        strict_float(self.known_from, field="known_from")

    def content(self) -> dict:
        """CONTENT identity -- creation_time deliberately excluded."""
        self._validate()
        return {
            "schema_version": self.schema_version,
            "input_id": self.input_id,
            "input_hash": self.input_hash,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_family": self.model_family,
            "information_tier": self.information_tier,
            "known_from": float(self.known_from),
            "forecast_horizon": self.forecast_horizon,
            "horizon_minutes": HORIZON_MINUTES[self.forecast_horizon],
            "distribution": self.distribution.canonical(),
            "calibration_metadata": dict(self.calibration_metadata),
            "uncertainty_metadata": dict(self.uncertainty_metadata),
        }

    @property
    def forecast_hash(self) -> str:
        return content_hash(self.content())

    def instance(self) -> dict:
        body = self.content()
        body["creation_time"] = float(self.creation_time)
        body["forecast_id"] = self.forecast_id
        return body

    def sealed(self) -> dict:
        body = self.instance()
        body["forecast_hash"] = self.forecast_hash
        body["PREDICTION_AUTHORITY"] = "FORECAST_REPRESENTATION_ONLY"
        body["TRADING_AUTHORITY"] = "NONE"
        body["CAPITAL_AUTHORITY"] = "NONE"
        body["ORDER_AUTHORITY"] = "NONE"
        return body

    def binds_to(self, wm_input) -> bool:
        """Does this forecast actually commit to that input?"""
        return (self.input_hash == wm_input.input_hash
                and self.input_id == wm_input.input_id
                and self.information_tier == wm_input.information_tier)


__all__ = ["FORECAST_SCHEMA_VERSION", "HORIZONS", "HORIZON_MINUTES",
           "H_5M", "H_15M", "H_30M", "H_60M", "H_SESSION_CLOSE",
           "PredictiveDistribution", "WorldModelForecast",
           "ForecastContractViolation", "NumericContractViolation"]
