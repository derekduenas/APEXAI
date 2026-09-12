"""NULL_COURT_V1_DEPENDENCE_AWARE -- the acceptance court for the
repaired statistic. A NEW court. It does not overwrite NULL_COURT_V0,
whose verdict is FAIL forever.

WHAT IS DIFFERENT FROM V0
  * decision statistic: DEPENDENCE_AWARE_DM_HAC_V0 (inference.py)
  * seeds: WM0E_R1_HOLDOUT_V0 -- 50 fresh seeds derived from a namespace,
    never inspected; the 25 V0 seeds are excluded by construction
  * tolerance: MAX_FP = 5 of 50 (derived from the statistic's nominal
    alpha in error_control(); no independence between controls assumed)
  * a SECONDARY non-overlap diagnostic is persisted per cell; it cannot
    rescue the primary and is never averaged with it

WHAT IS IDENTICAL TO V0 (frozen, on purpose)
  M0 and its configuration; the null comparator; N0-N4 and P0 as
  defined in controls.py V0.1; the S1 world and parameters; the H_15M
  horizon; the feature set; the positive-control rule.

NO RESCUE LOGIC
There is no code path that changes lag, kernel, threshold, seeds, M0,
features, horizon or the primary statistic in response to a result.
A control that fails is sealed as failed. A further methodology change
is a new repair identity with a new fresh seed set.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from apex.world_model import controls as C
from apex.world_model import features as _features
from apex.world_model import inference as I
from apex.world_model import models as _models
from apex.world_model import targets as _targets
from apex.world_model.budget import wm0e_r1_truth
from apex.world_model.canonical import content_hash
from apex.world_model.court import (CONTROL_FAILURE, INVALID, NO_SIGNAL, PASS,
                                    P0_MIN_DETECTION_RATE,
                                    P0_MIN_POSITIVE_DIRECTION, RUN_INVALID,
                                    SIGNAL_DETECTED, S1_PARAMS, S1_SIGMA,
                                    N_STEPS, CourtViolation, _world,
                                    binomial_tail)
from apex.world_model.grader import Z_RULE, null_rule
from apex.world_model.holdout import (HOLDOUT, HOLDOUT_SEEDS,
                                      WM_0E_DEVELOPMENT_NULL_SET_V0)
from apex.world_model.models import M0SyntheticBaseline, NullBaseline
from apex.world_model.teststand import default_dataset, run_pipeline
from apex.world_model.worlds import S1_CAUSAL_TREND

COURT_VERSION_V1 = "NULL_COURT_V1_DEPENDENCE_AWARE"
COURT_AUTHORITY_V1 = ("NONE. Synthetic acceptance court for a statistical "
                      "repair. Confers no trading, order, capital or "
                      "real-market research authority.")
MAX_FALSE_POSITIVES_V1 = 5
SEEDS_PER_CONTROL = len(HOLDOUT_SEEDS)          # 50
CONTROLS = ("N0", "N1", "N2", "N3", "N4")
POSITIVE_CONTROLS = ("P0",)
FAMILY_METHOD = ("union bound across the five negative controls -- no "
                 "independence between controls is assumed")


def _file_sha(mod) -> str:
    return hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()


def error_control_v1(alpha: float = I.NOMINAL_ALPHA_ONE_SIDED,
                     n: int = SEEDS_PER_CONTROL,
                     max_fp: int = MAX_FALSE_POSITIVES_V1) -> dict:
    per_control = binomial_tail(n, alpha, max_fp + 1)
    return {"individual_alpha_one_sided": alpha,
            "alpha_source": "1 - Phi(%.1f), asymptotic N(0,1) reference of "
                            "the DM/HAC statistic" % I.DM_THRESHOLD,
            "trials_per_control": n,
            "expected_false_positives": n * alpha,
            "max_tolerated_false_positives": max_fp,
            "court_false_fail_probability_per_control": per_control,
            "family_false_fail_probability_union_bound":
                min(1.0, len(CONTROLS) * per_control),
            "family_method": FAMILY_METHOD,
            "reference": "Binomial(%d, %.5f); P(FP > %d)" % (n, alpha, max_fp)}


@dataclass(frozen=True)
class CourtDefinitionV1:
    court_id: str
    code_commit: str
    creation_time: float
    model_identity: dict
    model_config_hash: str
    null_identity: dict
    budget_canonical: dict
    seed_set: tuple = HOLDOUT_SEEDS
    controls: tuple = CONTROLS
    positive_controls: tuple = POSITIVE_CONTROLS
    court_version: str = COURT_VERSION_V1
    authority: str = COURT_AUTHORITY_V1

    def canonical(self) -> dict:
        return {"court_version": self.court_version,
                "court_id": self.court_id, "code_commit": self.code_commit,
                "supersedes_without_overwriting": "NULL_COURT_V0 (FAIL)",
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
                "seed_set": HOLDOUT,                 # ordered seeds, derivation, hash
                "development_set_excluded": {
                    "name": "WM_0E_DEVELOPMENT_NULL_SET_V0",
                    "hash": content_hash(list(WM_0E_DEVELOPMENT_NULL_SET_V0)),
                    "overlap_with_acceptance": 0},
                "inference": I.inference_contract(),
                "secondary_diagnostic": {
                    "version": I.NON_OVERLAP_VERSION,
                    "spacing": _targets.TARGET_HORIZON_STEPS,
                    "anchor": I.NON_OVERLAP_ANCHOR, "role": I.NON_OVERLAP_ROLE},
                "error_control": error_control_v1(),
                "positive_control_rule": {
                    "min_detection_rate": P0_MIN_DETECTION_RATE,
                    "min_positive_direction_rate": P0_MIN_POSITIVE_DIRECTION,
                    "rationale": "same frozen rule as V0; >= 40/50 detections "
                                 "and >= 45/50 positive mean gain; predeclared"},
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


def run_control_v1(defn: CourtDefinitionV1, control: str, seed: int) -> dict:
    """One (control, seed) cell: primary DM/HAC verdict, the secondary
    non-overlap diagnostic, and the OLD iid z for reference only.
    Exceptions become RUN_INVALID, never a silent skip."""
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
        primary = I.dm_hac_rule(m["grades"], n["grades"])
        secondary = I.non_overlap_rule(m["grades"], n["grades"])
        legacy = null_rule(m["grades"], n["grades"])          # reference only
        return {"control": control, "seed": seed,
                "verdict": primary["verdict"],                  # PRIMARY decides
                "t_hac": primary["t"], "hac_se": primary["hac_se"],
                "se_inflation_vs_iid": primary["se_inflation_vs_iid"],
                "mean_loglik_gain": primary["mean_loglik_gain"],
                "n_eval": primary["n"],
                "non_overlap": {"verdict": secondary["verdict"],
                                "z": secondary["z"], "n": secondary["n"]},
                "legacy_iid_z_reference_only": legacy["z"],
                "world_hash": world.world_hash}
    except Exception as e:                                   # noqa: BLE001
        return {"control": control, "seed": seed, "verdict": RUN_INVALID,
                "error": "%s: %s" % (type(e).__name__, str(e)[:160]),
                "world_hash": world.world_hash}


def _summary(xs: list) -> dict:
    s = sorted(xs)
    return {"min": s[0], "median": s[len(s) // 2], "max": s[-1],
            "mean": sum(s) / len(s)}


def judge_control_v1(cells: list, control: str) -> dict:
    valid = [c for c in cells if c["verdict"] != RUN_INVALID]
    invalid = len(cells) - len(valid)
    if invalid > 0:
        return {"control": control, "court_verdict": INVALID,
                "run_invalid": invalid, "n": len(cells),
                "errors": [c.get("error") for c in cells
                           if c["verdict"] == RUN_INVALID][:3]}
    detections = sum(1 for c in valid if c["verdict"] == SIGNAL_DETECTED)
    ts = [c["t_hac"] for c in valid]
    no_det = sum(1 for c in valid if c["non_overlap"]["verdict"] == SIGNAL_DETECTED)
    base = {"control": control, "n": len(valid), "detections": detections,
            "detection_rate": detections / len(valid),
            "primary_t_hac": _summary(ts),
            "se_inflation_vs_iid": _summary([c["se_inflation_vs_iid"] for c in valid]),
            "legacy_iid_z_reference_only": _summary(
                [c["legacy_iid_z_reference_only"] for c in valid]),
            "non_overlap_robustness": {
                "detections": no_det, "detection_rate": no_det / len(valid),
                "z": _summary([c["non_overlap"]["z"] for c in valid]),
                "role": "secondary; not binding; not averaged"}}
    if control in POSITIVE_CONTROLS:
        pos = sum(1 for c in valid if c["mean_loglik_gain"] > 0)
        rate = detections / len(valid)
        drate = pos / len(valid)
        ok = rate >= P0_MIN_DETECTION_RATE and drate >= P0_MIN_POSITIVE_DIRECTION
        base.update({"court_verdict": PASS if ok else CONTROL_FAILURE,
                     "positive_direction_rate": drate,
                     "non_overlap_consistent": (no_det / len(valid)) >= P0_MIN_DETECTION_RATE})
        return base
    ok = detections <= MAX_FALSE_POSITIVES_V1
    base.update({"court_verdict": PASS if ok else CONTROL_FAILURE,
                 "false_positives": detections,
                 "expected_false_positives": len(valid) * I.NOMINAL_ALPHA_ONE_SIDED,
                 "max_tolerated": MAX_FALSE_POSITIVES_V1,
                 "non_overlap_consistent": no_det <= MAX_FALSE_POSITIVES_V1})
    return base


def define_v1(code_commit: str, creation_time: float) -> CourtDefinitionV1:
    """Build the sealed definition WITHOUT running anything, so the
    commitment can be inspected, hashed and tested before a sitting."""
    if I.DM_THRESHOLD != Z_RULE:
        raise CourtViolation("threshold drifted from the retained Z_RULE")
    if set(HOLDOUT_SEEDS) & set(WM_0E_DEVELOPMENT_NULL_SET_V0):
        raise CourtViolation("acceptance seeds overlap the development set")
    m0 = M0SyntheticBaseline().model_identity()
    nl = NullBaseline().model_identity()
    budget = wm0e_r1_truth()
    return CourtDefinitionV1(
        court_id="COURT-V1-%s" % content_hash(
            {"seeds": HOLDOUT["seed_set_hash"], "commit": code_commit,
             "controls": C.CONTROLS_VERSION,
             "inference": I.INFERENCE_VERSION})[:12],
        code_commit=code_commit, creation_time=creation_time,
        model_identity={"model_id": m0["model_id"],
                        "model_version": m0["model_version"],
                        "configuration": m0["configuration"]},
        model_config_hash=content_hash(m0["configuration"]),
        null_identity={"model_id": nl["model_id"],
                       "model_version": nl["model_version"],
                       "configuration": nl["configuration"]},
        budget_canonical=budget.canonical())


def convene_v1(code_commit: str, creation_time: float) -> tuple:
    """Seal, THEN run. No parameter of the court may change in between,
    and nothing in this function reads a result before all cells exist."""
    defn = define_v1(code_commit, creation_time)
    sealed_hash = defn.court_hash                 # SEALED BEFORE ANY RUN
    results = {}
    for ctrl in defn.controls + defn.positive_controls:
        cells = [run_control_v1(defn, ctrl, s) for s in defn.seed_set]
        results[ctrl] = {"cells": cells, "judgement": judge_control_v1(cells, ctrl)}
    if defn.court_hash != sealed_hash:
        raise CourtViolation("court definition changed during the sitting")
    verdicts = {c: results[c]["judgement"]["court_verdict"] for c in results}
    return defn, {"court_hash": sealed_hash, "results": results,
                  "verdicts": verdicts,
                  "court_pass": all(v == PASS for v in verdicts.values())}
