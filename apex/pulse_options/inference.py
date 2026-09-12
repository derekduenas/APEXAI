"""FROZEN-ARTIFACT INFERENCE ADAPTER (M2).

Artifact: EXP-002 `fit.params`, copied verbatim from the sealed result record
(`exp002_artifact.json`, source sha256 0c397d70…). Its `params_hash`
(ca04fc6e713e1a5c) is RECOMPUTED with the experiment's own recipe at load
time; a disagreement refuses the artifact.

Provenance carried on every forecast: EXP-002 DEVELOPMENT result
INVALID_NULL_CONTROL; no validated-edge claim; engineering continuity only.
The heuristic direction label is NOT part of the distribution and is not
substituted into it.

Conventions (identical to apex.world_model.exp002.models):
    location = beta0 + sum_j beta_j * (x_j - mean_j) / sd_j,  x = [ret_1, ret_5]
    scale    = rv_30 * s          (Student-t SCALE, not a standard deviation)
    family   = STUDENT_T, nu      (sd = scale * sqrt(nu / (nu - 2)))
    target   = log(close[t+15m] / close[t]);  horizon 15 minutes; input cutoff = bar_complete of the
               bar at t; forecast reference_time = t (the bar's event_time)"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from apex.options_pilot.clock import to_utc_string
from apex.options_pilot.records import FORECAST_TARGET, FORECAST_UNITS, canonical_hash

from .features import FEATURE_ORDER, FEATURE_SET, feature_vector

ARTIFACT_PATH = Path(__file__).with_name("exp002_artifact.json")
EXPECTED_PARAMS_HASH = "ca04fc6e713e1a5c"
HORIZON_MINUTES = 15


class ArtifactRefused(RuntimeError):
    pass


def params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in params.items() if k != "params_hash"},
                                     sort_keys=True, default=float).encode()).hexdigest()[:16]


class FrozenArtifact:
    def __init__(self, doc: dict, *, arm: str = "L"):
        params = doc["params"]
        h = params_hash(params)
        if h != params.get("params_hash") or h != EXPECTED_PARAMS_HASH:
            raise ArtifactRefused("PARAMS_HASH_DISAGREES: recomputed %s, stored %s, expected %s"
                                  % (h, params.get("params_hash"), EXPECTED_PARAMS_HASH))
        if arm != "L":
            raise ArtifactRefused("ARM_NOT_SUPPORTED_BY_PILOT: %s (the pilot uses the registered L arm)" % arm)
        spec = params[arm]
        if spec.get("quadratic") is not False or len(spec["beta"]) != 3 or len(spec["mean"]) != 2 or len(spec["sd"]) != 2:
            raise ArtifactRefused("ARM_SHAPE_UNEXPECTED")
        self.doc, self.params, self.arm, self.spec = doc, params, arm, spec
        self.s, self.nu = float(params["t"]["s"]), float(params["t"]["nu"])
        if not (self.nu > 2.0 and self.s > 0):
            raise ArtifactRefused("T_PARAMETERS_INVALID")
        self.params_hash = h
        self.model_id = "EXP002_%s" % arm
        self.model_hash = canonical_hash({"module": "apex.pulse_options.inference", "convention": "exp002.models._mean_of + rv_30*s",
                                          "feature_set": FEATURE_SET, "arm": arm})
        self.artifact_digest = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()

    @classmethod
    def load(cls, path: Path = ARTIFACT_PATH, *, arm: str = "L") -> "FrozenArtifact":
        return cls(json.loads(Path(path).read_text()), arm=arm)

    def describe(self) -> dict:
        return {"model_id": self.model_id, "arm": self.arm, "params_hash": self.params_hash, "model_hash": self.model_hash,
                "artifact_digest": self.artifact_digest, "feature_order": list(FEATURE_ORDER), "feature_set": FEATURE_SET,
                "normalization": {"mean": self.spec["mean"], "sd": self.spec["sd"], "basis": "[ret_1, ret_5] z-scored with fit-split mean/sd, intercept"},
                "beta": self.spec["beta"], "family": "STUDENT_T", "nu": self.nu, "scale_convention": "scale = rv_30 * s; Student-t scale, not sd",
                "s": self.s, "target": FORECAST_TARGET, "units": FORECAST_UNITS, "horizon_minutes": HORIZON_MINUTES,
                "provenance": {"experiment": "EXP-002", "development_status": self.doc.get("experiment_status"),
                               "source_record_sha256": self.doc.get("source_record_sha256"), "source_commit": self.doc.get("source_commit"),
                               "validated_edge_claim": False}}

    def location(self, f: dict) -> float:
        x = [f["ret_1"], f["ret_5"]]
        z = [(x[j] - self.spec["mean"][j]) / self.spec["sd"][j] for j in range(2)]
        b = self.spec["beta"]
        return float(b[0] + b[1] * z[0] + b[2] * z[1])

    def scale(self, f: dict) -> float:
        return float(f["rv_30"] * self.s)

    def forecast(self, snapshot: dict, *, created_epoch: float, direction_signal: str | None = None) -> dict:
        """A forecast record in the boundary's contract, from a snapshot. The reference time is the
        last completed bar's start; input cutoff its availability; the target ends 15 minutes later."""
        f = feature_vector(snapshot)
        loc, sc = self.location(f), self.scale(f)
        if not (math.isfinite(loc) and math.isfinite(sc) and sc > 0):
            raise ArtifactRefused("NONFINITE_FORECAST")
        ref = snapshot["last_bar_event_time"]
        cut_f = snapshot["fields"]["ret_1"]
        from apex.options_pilot.clock import parse_utc
        available = parse_utc(cut_f["known_from"], field="known_from")
        if created_epoch < available:
            raise ArtifactRefused("CREATED_BEFORE_INPUT_AVAILABLE")
        return {"symbol": snapshot["symbol"], "target": FORECAST_TARGET, "units": FORECAST_UNITS, "horizon_minutes": HORIZON_MINUTES,
                "family": "STUDENT_T", "location": loc, "scale": sc, "nu": self.nu,
                "model_id": self.model_id, "model_hash": self.model_hash, "params_hash": self.params_hash,
                "artifact_digest": self.artifact_digest,
                "reference_time_utc": to_utc_string(ref), "target_end_utc": to_utc_string(ref + HORIZON_MINUTES * 60),
                "input_event_time_utc": to_utc_string(ref), "input_available_utc": to_utc_string(available),
                "input_cutoff_utc": to_utc_string(available), "created_utc": to_utc_string(created_epoch),
                "direction_signal": direction_signal, "inputs": {**f, "state_hash": snapshot["state_hash"]},
                "validation_status": ("NOT_VALIDATED: EXP-002 development result INVALID_NULL_CONTROL; parameters retained for "
                                      "engineering continuity only; no edge claim"),
                "implied_sd": sc * math.sqrt(self.nu / (self.nu - 2.0))}


_DEFAULT = None


def default_artifact() -> FrozenArtifact:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FrozenArtifact.load()
    return _DEFAULT
