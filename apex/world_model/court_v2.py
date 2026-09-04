"""NULL_COURT_V2_BLOCK_BOOTSTRAP -- acceptance court for the dependent
block-bootstrap inference. A NEW court. NULL_COURT_V0 stays FAIL forever;
NULL_COURT_V1 stays defined-and-never-convened forever.

PRIMARY: DEPENDENT_BLOCK_BOOTSTRAP_V0 (bootstrap.py). SECONDARY, non-
binding, never averaged, cannot rescue: DEPENDENCE_AWARE_DM_HAC_V0 (R1)
and NON_OVERLAP_ROBUSTNESS_V0; the legacy iid z is carried for reference.

FROZEN, IDENTICAL TO V0/V1: M0 and its configuration; the null
comparator; N0-N4 and P0 (controls.py V0.1); the S1 world; H_15M; the
feature set; the positive-control rule.

ACCEPTANCE SEEDS: WM0E_R1_HOLDOUT_V0 -- persisted before R1, never
executed (artifact inspection recorded in the R2 seal).

PREREQUISITE ENCODED IN THE IDENTITY: the court cannot be defined without
the sha256 of a calibration-exercise artifact that PASSED the
predeclared envelope. Calibration therefore precedes acceptance by
construction, and the court hash commits to which calibration it was.

NO RESCUE LOGIC. Nothing here changes alpha, B, block rule, seeds, M0,
features, horizon or controls in response to a result.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from apex.world_model import bootstrap as BS
from apex.world_model import controls as C
from apex.world_model import features as _features
from apex.world_model import inference as I
from apex.world_model import models as _models
from apex.world_model import targets as _targets
from apex.world_model.budget import wm0e_r2_truth
from apex.world_model.canonical import content_hash
from apex.world_model.court import (CONTROL_FAILURE, INVALID, PASS,
                                    P0_MIN_DETECTION_RATE,
                                    P0_MIN_POSITIVE_DIRECTION, RUN_INVALID,
                                    SIGNAL_DETECTED, S1_PARAMS, S1_SIGMA,
                                    N_STEPS, CourtViolation, _world,
                                    binomial_tail)
from apex.world_model.grader import null_rule
from apex.world_model.holdout import (HOLDOUT, HOLDOUT_SEEDS,
                                      WM_0E_DEVELOPMENT_NULL_SET_V0)
from apex.world_model.models import M0SyntheticBaseline, NullBaseline
from apex.world_model.teststand import default_dataset, run_pipeline
from apex.world_model.worlds import S1_CAUSAL_TREND

COURT_VERSION_V2 = "NULL_COURT_V2_BLOCK_BOOTSTRAP"
COURT_AUTHORITY_V2 = ("NONE. Synthetic acceptance court for a statistical "
                      "repair. Confers no trading, order, capital or "
                      "real-market research authority.")
MAX_FALSE_POSITIVES_V2 = 5
SEEDS_PER_CONTROL = len(HOLDOUT_SEEDS)
CONTROLS = ("N0", "N1", "N2", "N3", "N4")
POSITIVE_CONTROLS = ("P0",)
FAMILY_METHOD = ("union bound across the five negative controls; no "
                 "independence between controls is assumed")


def _file_sha(mod) -> str:
    return hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()


def error_control_v2(n: int = SEEDS_PER_CONTROL,
                     max_fp: int = MAX_FALSE_POSITIVES_V2) -> dict:
    """Tolerance justified against BOTH the nominal alpha and the
    calibration envelope's upper bound, predeclared."""
    a_nom = BS.ALPHA
    a_env = BS.CALIBRATION_ENVELOPE["null_fixture_type1_max"]
    a_pool = BS.CALIBRATION_ENVELOPE["pooled_dependent_null_type1_max"]
    rows = {}
    for label, a in (("nominal", a_nom), ("envelope_pooled_max", a_pool),
                     ("envelope_fixture_max", a_env)):
        t = binomial_tail(n, a, max_fp + 1)
        rows[label] = {"alpha": a, "expected_false_positives": n * a,
                       "P_FP_exceeds_tolerance": t,
                       "family_union_bound": min(1.0, len(CONTROLS) * t)}
    return {"trials_per_control": n, "max_tolerated_false_positives": max_fp,
            "reference": "Binomial(n, alpha); P(FP > max_fp)",
            "tails": rows, "family_method": FAMILY_METHOD,
            "justification": "max_fp=5 keeps the court's false-fail "
                "probability at 0.15% per control (0.76% family bound) at "
                "nominal alpha and 1.4% at the pooled envelope maximum, "
                "while a control whose realised rate is >= 3x nominal "
                "(E[FP] >= 3.75) is more likely than not to be convicted. "
                "Fixed before any acceptance outcome."}


@dataclass(frozen=True)
class CourtDefinitionV2:
    court_id: str
    code_commit: str
    creation_time: float
    model_identity: dict
    model_config_hash: str
    null_identity: dict
    budget_canonical: dict
    calibration_evidence_sha256: str
    seed_set: tuple = HOLDOUT_SEEDS
    controls: tuple = CONTROLS
    positive_controls: tuple = POSITIVE_CONTROLS
    court_version: str = COURT_VERSION_V2
    authority: str = COURT_AUTHORITY_V2

    def canonical(self) -> dict:
        return {"court_version": self.court_version,
                "court_id": self.court_id, "code_commit": self.code_commit,
                "supersedes_without_overwriting": ["NULL_COURT_V0 (FAIL)",
                                                   "NULL_COURT_V1 (never convened)"],
                "repairs_defect": I.WM_STAT_001["defect_id"],
                "model_identity": self.model_identity,
                "model_config_hash": self.model_config_hash,
                "null_comparator": self.null_identity,
                "controls_version": C.CONTROLS_VERSION,
                "controls": {c: C.CONTROL_CONTRACT[c] for c in self.controls},
                "positive_controls": {c: C.CONTROL_CONTRACT[c]
                                      for c in self.positive_controls},
                "target": {"horizon": _targets.TARGET_HORIZON,
                           "horizon_steps": _targets.TARGET_HORIZON_STEPS,
                           "definition": _targets.TARGET_DEFINITION,
                           "version": _targets.TARGET_VERSION},
                "feature_set_sha256": _file_sha(_features),
                "models_sha256": _file_sha(_models),
                "controls_sha256": _file_sha(C),
                "seed_set": HOLDOUT,
                "development_set_excluded": {
                    "name": "WM_0E_DEVELOPMENT_NULL_SET_V0",
                    "hash": content_hash(list(WM_0E_DEVELOPMENT_NULL_SET_V0)),
                    "overlap_with_acceptance": 0},
                "primary_inference": BS.bootstrap_contract(),
                "calibration_evidence_sha256": self.calibration_evidence_sha256,
                "secondary_diagnostics": {
                    "hac": I.inference_contract(),
                    "non_overlap": {"version": I.NON_OVERLAP_VERSION,
                                    "spacing": _targets.TARGET_HORIZON_STEPS,
                                    "anchor": I.NON_OVERLAP_ANCHOR},
                    "role": "secondary; not binding; not averaged; cannot "
                            "rescue a failed primary"},
                "error_control": error_control_v2(),
                "positive_control_rule": {
                    "min_detection_rate": P0_MIN_DETECTION_RATE,
                    "min_positive_direction_rate": P0_MIN_POSITIVE_DIRECTION,
                    "rationale": "same frozen rule as V0/V1; >= 40/50 "
                                 "detections and >= 45/50 positive mean gain"},
                "base_world": {"type": S1_CAUSAL_TREND, "sigma": S1_SIGMA,
                               "params": S1_PARAMS, "n_steps": N_STEPS,
                               "observe_latent": True},
                "research_budget": self.budget_canonical,
                "number_of_tests": len(self.seed_set) * (
                    len(self.controls) + len(self.positive_controls)),
                "rescue_logic": "NONE",
                "authority": self.authority}

    @property
    def court_hash(self) -> str:
        return content_hash(self.canonical())


def load_calibration(path: str) -> tuple:
    """The calibration artifact must exist and must have PASSED its own
    predeclared envelope. Returns (sha256, parsed)."""
    raw = Path(path).read_bytes()
    doc = json.loads(raw)
    if doc.get("envelope_verdict") != "PASS":
        raise CourtViolation("calibration artifact did not PASS its envelope: %r"
                             % doc.get("envelope_verdict"))
    if doc.get("bootstrap_contract_hash") != BS.content_identity():
        raise CourtViolation("calibration was run under a different bootstrap "
                             "contract than the one about to sit")
    return hashlib.sha256(raw).hexdigest(), doc


def define_v2(code_commit: str, creation_time: float,
              calibration_path: str) -> CourtDefinitionV2:
    if set(HOLDOUT_SEEDS) & set(WM_0E_DEVELOPMENT_NULL_SET_V0):
        raise CourtViolation("acceptance seeds overlap the development set")
    cal_sha, _ = load_calibration(calibration_path)
    m0 = M0SyntheticBaseline().model_identity()
    nl = NullBaseline().model_identity()
    budget = wm0e_r2_truth()
    return CourtDefinitionV2(
        court_id="COURT-V2-%s" % content_hash(
            {"seeds": HOLDOUT["seed_set_hash"], "commit": code_commit,
             "controls": C.CONTROLS_VERSION,
             "inference": BS.content_identity(),
             "calibration": cal_sha})[:12],
        code_commit=code_commit, creation_time=creation_time,
        model_identity={"model_id": m0["model_id"],
                        "model_version": m0["model_version"],
                        "configuration": m0["configuration"]},
        model_config_hash=content_hash(m0["configuration"]),
        null_identity={"model_id": nl["model_id"],
                       "model_version": nl["model_version"],
                       "configuration": nl["configuration"]},
        budget_canonical=budget.canonical(),
        calibration_evidence_sha256=cal_sha)


def run_control_v2(defn: CourtDefinitionV2, control: str, seed: int) -> dict:
    world = _world(seed)
    try:
        if control == "N4":
            model = C.RandomRanker(defn.court_id, seed)
            ds = default_dataset
        else:
            model = M0SyntheticBaseline()
            ds = {"N0": C.n0_dataset, "N1": C.n1_dataset,
                  "N2": C.n2_dataset, "N3": C.n3_dataset,
                  "P0": lambda c, s: default_dataset}[control](defn.court_id, seed)
        if control != "N4" and model.model_identity()["configuration"] != \
                defn.model_identity["configuration"]:
            raise CourtViolation("M0 configuration drifted from the sealed court")
        m = run_pipeline(world, model, dataset=ds, code_commit=defn.code_commit)
        n = run_pipeline(world, NullBaseline(), dataset=ds,
                         code_commit=defn.code_commit)
        primary = BS.bootstrap_rule(m["grades"], n["grades"],
                                    court_id=defn.court_id, control=control,
                                    seed=seed)
        hac = I.dm_hac_rule(m["grades"], n["grades"])
        nov = I.non_overlap_rule(m["grades"], n["grades"])
        legacy = null_rule(m["grades"], n["grades"])
        return {"control": control, "seed": seed,
                "verdict": primary["verdict"],                 # PRIMARY decides
                "p_bootstrap": primary["p_bootstrap"], "t_obs": primary["t_obs"],
                "block_length": primary["block"]["block_length"],
                "block_proposed": primary["block"]["proposed"],
                "block_clamped": primary["block"]["clamped"],
                "selector": primary["block"]["selector_output"],
                "t_star_q": primary["t_star_q"],
                "mean_loglik_gain": primary["mean_loglik_gain"],
                "n_eval": primary["n"],
                "secondary": {"hac_t": hac["t"], "hac_verdict": hac["verdict"],
                              "non_overlap_z": nov["z"],
                              "non_overlap_verdict": nov["verdict"],
                              "legacy_iid_z": legacy["z"]},
                "world_hash": world.world_hash}
    except Exception as e:                                   # noqa: BLE001
        return {"control": control, "seed": seed, "verdict": RUN_INVALID,
                "error": "%s: %s" % (type(e).__name__, str(e)[:160]),
                "world_hash": world.world_hash}


def _summary(xs: list) -> dict:
    s = sorted(xs)
    return {"min": s[0], "median": s[len(s) // 2], "max": s[-1],
            "mean": sum(s) / len(s)}


def judge_control_v2(cells: list, control: str) -> dict:
    valid = [c for c in cells if c["verdict"] != RUN_INVALID]
    invalid = len(cells) - len(valid)
    if invalid > 0:
        return {"control": control, "court_verdict": INVALID,
                "run_invalid": invalid, "n": len(cells),
                "errors": [c.get("error") for c in cells
                           if c["verdict"] == RUN_INVALID][:3]}
    det = sum(1 for c in valid if c["verdict"] == SIGNAL_DETECTED)
    hac_det = sum(1 for c in valid if c["secondary"]["hac_verdict"] == SIGNAL_DETECTED)
    nov_det = sum(1 for c in valid if c["secondary"]["non_overlap_verdict"] == SIGNAL_DETECTED)
    base = {"control": control, "n": len(valid), "detections": det,
            "detection_rate": det / len(valid),
            "p_bootstrap": _summary([c["p_bootstrap"] for c in valid]),
            "t_obs": _summary([c["t_obs"] for c in valid]),
            "block_length": _summary([c["block_length"] for c in valid]),
            "block_clamped_counts": {k: sum(1 for c in valid if c["block_clamped"] == k)
                                     for k in ("lower", "none", "upper")},
            "secondary_diagnostics": {
                "hac_detections": hac_det,
                "hac_t": _summary([c["secondary"]["hac_t"] for c in valid]),
                "non_overlap_detections": nov_det,
                "legacy_iid_z": _summary([c["secondary"]["legacy_iid_z"] for c in valid]),
                "role": "not binding; not averaged; cannot rescue"}}
    if control in POSITIVE_CONTROLS:
        pos = sum(1 for c in valid if c["mean_loglik_gain"] > 0)
        rate, drate = det / len(valid), pos / len(valid)
        ok = rate >= P0_MIN_DETECTION_RATE and drate >= P0_MIN_POSITIVE_DIRECTION
        base.update({"court_verdict": PASS if ok else CONTROL_FAILURE,
                     "positive_direction_rate": drate})
        return base
    ok = det <= MAX_FALSE_POSITIVES_V2
    base.update({"court_verdict": PASS if ok else CONTROL_FAILURE,
                 "false_positives": det,
                 "expected_false_positives_nominal": len(valid) * BS.ALPHA,
                 "max_tolerated": MAX_FALSE_POSITIVES_V2})
    return base


def convene_v2(code_commit: str, creation_time: float,
               calibration_path: str) -> tuple:
    """Seal, THEN run. Frozen for the sitting; a failure is sealed."""
    defn = define_v2(code_commit, creation_time, calibration_path)
    sealed_hash = defn.court_hash
    results = {}
    for ctrl in defn.controls + defn.positive_controls:
        cells = [run_control_v2(defn, ctrl, s) for s in defn.seed_set]
        results[ctrl] = {"cells": cells, "judgement": judge_control_v2(cells, ctrl)}
    if defn.court_hash != sealed_hash:
        raise CourtViolation("court definition changed during the sitting")
    verdicts = {c: results[c]["judgement"]["court_verdict"] for c in results}
    return defn, {"court_hash": sealed_hash, "results": results,
                  "verdicts": verdicts,
                  "court_pass": all(v == PASS for v in verdicts.values())}
