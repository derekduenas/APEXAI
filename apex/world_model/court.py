"""NULL_COURT_V0 -- does the research court manufacture discoveries?

WM-0D showed the engine can say NO_SIGNAL once, on one null world, under
one seed. That is a single data point about a statistical procedure.
The court asks the question that actually matters: challenged
repeatedly, across five distinct ways of destroying a real relationship,
does the court's false-discovery behaviour match what its own rule
predicts?

EVERYTHING IS SEALED BEFORE ANYTHING RUNS
Seed set, controls, decision rule, tolerance, model identity -- the
court hash commits to all of them. Then the runs happen. A court whose
tolerance was chosen after seeing the results is not a court.

THE SEED SET  (25, predeclared, justified)
    seeds = [1000 + 37*i for i in range(25)]
Why 25: at the per-test nominal alpha of 0.023, twenty-five independent
trials give Binomial(25, 0.023) false positives -- expected 0.58 -- and
a tolerance of 3 gives a court-level false-fail probability of about
0.0022 per control (~1.1% across five). Fewer seeds could not tell a
2% rate from a 10% one; more buys little and each control_experiment
costs ~1 s, so 25 x 6 runs is ~3 minutes. The number is chosen for
what it can DETECT, not for what it will show.

INDEPENDENCE, STATED HONESTLY
Seeds generate INDEPENDENT worlds (per-stream PRNG, disjoint keys), so
per-seed verdicts under a null are independent draws and the binomial
model applies ACROSS seeds. It says nothing about the calibration of
the per-seed test WITHIN a world -- that is exactly what the court is
measuring. If the observed false-positive rate materially exceeds the
nominal 0.023, the per-seed rule is miscalibrated and the court FAILS;
the rule is NOT adjusted here.

VERDICT TAXONOMY  (four words, not one PASS/FAIL)
    per seed :  NO_SIGNAL | SIGNAL_DETECTED | RUN_INVALID
    per control: PASS | CONTROL_FAILURE | INVALID
NO_SIGNAL is a successful research execution that found nothing. It is
not an exception, a warning, or a failed model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field as _field

from apex.world_model.canonical import content_hash
from apex.world_model.grader import NULL_RULE, Z_RULE, null_rule
from apex.world_model.models import M0SyntheticBaseline, NullBaseline
from apex.world_model.teststand import default_dataset, run_pipeline
from apex.world_model.worlds import S1_CAUSAL_TREND, WorldConfig, generate_world
from apex.world_model import controls as C

COURT_VERSION = "NULL_COURT_V0"
COURT_AUTHORITY = "SYNTHETIC_RESEARCH_ONLY"
SEED_SET = tuple(1000 + 37 * i for i in range(25))
NOMINAL_ALPHA = 0.023                   # one-sided z > 2.0 under a true null
MAX_FALSE_POSITIVES = 3                 # predeclared tolerance per control
P0_MIN_DETECTION_RATE = 0.80            # predeclared
P0_MIN_POSITIVE_DIRECTION = 0.90        # predeclared

NO_SIGNAL, SIGNAL_DETECTED, RUN_INVALID = "NO_SIGNAL", "SIGNAL_DETECTED", "RUN_INVALID"
PASS, CONTROL_FAILURE, INVALID = "PASS", "CONTROL_FAILURE", "INVALID"

# the S1 world the court uses -- the SAME parameters WM-0D's positive
# control used, so nothing about the world was chosen for this brick
S1_PARAMS = {"mu": 0.0015, "flip_prob": 0.02}
S1_SIGMA = 0.002
N_STEPS = 1200


class CourtViolation(Exception):
    pass


def binomial_tail(n: int, p: float, k: int) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i)
               for i in range(k, n + 1))


@dataclass(frozen=True)
class CourtDefinition:
    court_id: str
    code_commit: str
    model_identity: dict
    model_config_hash: str
    creation_time: float
    seed_set: tuple = SEED_SET
    controls: tuple = ("N0", "N1", "N2", "N3", "N4")
    positive_controls: tuple = ("P0",)
    court_version: str = COURT_VERSION
    authority: str = COURT_AUTHORITY

    def error_control(self) -> dict:
        n = len(self.seed_set)
        return {"individual_nominal_alpha": NOMINAL_ALPHA,
                "trials_per_control": n,
                "expected_false_positives": n * NOMINAL_ALPHA,
                "max_tolerated_false_positives": MAX_FALSE_POSITIVES,
                "court_false_fail_probability_per_control":
                    binomial_tail(n, NOMINAL_ALPHA, MAX_FALSE_POSITIVES + 1),
                "court_false_fail_probability_across_controls":
                    1 - (1 - binomial_tail(n, NOMINAL_ALPHA,
                                           MAX_FALSE_POSITIVES + 1))
                    ** len(self.controls),
                "independence_assumption": "ACROSS seeds only (disjoint "
                    "PRNG streams -> independent worlds). Says nothing "
                    "about WITHIN-world calibration, which is what the "
                    "court measures."}

    def canonical(self) -> dict:
        return {"court_version": self.court_version,
                "court_id": self.court_id, "code_commit": self.code_commit,
                # a control's IMPLEMENTATION is part of the court's identity:
                # change one, and this is a different court (WM-0E §16)
                "controls_version": C.CONTROLS_VERSION,
                "model_identity": self.model_identity,
                "model_config_hash": self.model_config_hash,
                "seed_set": list(self.seed_set),
                "seed_set_hash": content_hash(list(self.seed_set)),
                "controls": {c: C.CONTROL_CONTRACT[c] for c in self.controls},
                "positive_controls": {c: C.CONTROL_CONTRACT[c]
                                      for c in self.positive_controls},
                "decision_rule": NULL_RULE, "z_rule": Z_RULE,
                "decision_rule_hash": content_hash({"rule": NULL_RULE,
                                                    "z": Z_RULE}),
                "error_control": self.error_control(),
                "positive_control_rule": {
                    "min_detection_rate": P0_MIN_DETECTION_RATE,
                    "min_positive_direction_rate": P0_MIN_POSITIVE_DIRECTION},
                "base_world": {"type": S1_CAUSAL_TREND, "sigma": S1_SIGMA,
                               "params": S1_PARAMS, "n_steps": N_STEPS,
                               "observe_latent": True},
                "number_of_tests": len(self.seed_set) * (
                    len(self.controls) + len(self.positive_controls)),
                "authority": self.authority}

    @property
    def court_hash(self) -> str:
        return content_hash(self.canonical())


def _world(seed: int):
    return generate_world(WorldConfig(world_type=S1_CAUSAL_TREND, seed=seed,
                                      n_subjects=1, n_steps=N_STEPS,
                                      sigma=S1_SIGMA, params=S1_PARAMS,
                                      observe_latent=True))


def run_control(defn: CourtDefinition, control: str, seed: int) -> dict:
    """One (control, seed) cell. Returns the per-seed verdict and the
    statistics behind it. Exceptions become RUN_INVALID, never a
    silent skip."""
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
        if C.CONTROL_CONTRACT and model.model_identity()["configuration"] != \
                defn.model_identity["configuration"] and control != "N4":
            raise CourtViolation("M0 configuration drifted from the sealed court")
        m = run_pipeline(world, model, dataset=ds, code_commit=defn.code_commit)
        n = run_pipeline(world, NullBaseline(), dataset=ds,
                         code_commit=defn.code_commit)
        v = null_rule(m["grades"], n["grades"])
        return {"control": control, "seed": seed, "verdict": v["verdict"],
                "z": v["z"], "mean_loglik_gain": v["mean_loglik_gain"],
                "n_eval": v["n"], "world_hash": world.world_hash}
    except Exception as e:                                   # noqa: BLE001
        return {"control": control, "seed": seed, "verdict": RUN_INVALID,
                "error": "%s: %s" % (type(e).__name__, str(e)[:160]),
                "world_hash": world.world_hash}


def judge_control(cells: list, control: str) -> dict:
    valid = [c for c in cells if c["verdict"] != RUN_INVALID]
    invalid = len(cells) - len(valid)
    if invalid > 0:
        return {"control": control, "court_verdict": INVALID,
                "run_invalid": invalid, "n": len(cells),
                "errors": [c.get("error") for c in cells
                           if c["verdict"] == RUN_INVALID][:3]}
    detections = sum(1 for c in valid if c["verdict"] == SIGNAL_DETECTED)
    zs = [c["z"] for c in valid]
    if control == "P0":
        pos = sum(1 for c in valid if c["mean_loglik_gain"] > 0)
        rate = detections / len(valid)
        drate = pos / len(valid)
        ok = rate >= P0_MIN_DETECTION_RATE and drate >= P0_MIN_POSITIVE_DIRECTION
        return {"control": control, "court_verdict": PASS if ok else CONTROL_FAILURE,
                "n": len(valid), "detections": detections,
                "detection_rate": rate, "positive_direction_rate": drate,
                "z_min": min(zs), "z_median": sorted(zs)[len(zs) // 2],
                "z_max": max(zs)}
    ok = detections <= MAX_FALSE_POSITIVES
    return {"control": control, "court_verdict": PASS if ok else CONTROL_FAILURE,
            "n": len(valid), "false_positives": detections,
            "false_positive_rate": detections / len(valid),
            "expected_under_nominal_alpha": len(valid) * NOMINAL_ALPHA,
            "max_tolerated": MAX_FALSE_POSITIVES,
            "z_min": min(zs), "z_median": sorted(zs)[len(zs) // 2],
            "z_max": max(zs),
            "z_over_2_fraction": sum(1 for z in zs if z > Z_RULE) / len(zs)}


def convene(code_commit: str, creation_time: float) -> tuple:
    """Seal the court, THEN run it. Returns (definition, results)."""
    m0 = M0SyntheticBaseline()
    ident = m0.model_identity()
    defn = CourtDefinition(
        court_id="COURT-%s" % content_hash({"seeds": list(SEED_SET),
                                             "commit": code_commit,
                                             "controls": C.CONTROLS_VERSION})[:12],
        code_commit=code_commit,
        model_identity={"model_id": ident["model_id"],
                        "model_version": ident["model_version"],
                        "configuration": ident["configuration"]},
        model_config_hash=content_hash(ident["configuration"]),
        creation_time=creation_time)
    sealed_hash = defn.court_hash                 # SEALED BEFORE ANY RUN
    results = {}
    for ctrl in defn.controls + defn.positive_controls:
        cells = [run_control(defn, ctrl, s) for s in defn.seed_set]
        results[ctrl] = {"cells": cells, "judgement": judge_control(cells, ctrl)}
    if defn.court_hash != sealed_hash:
        raise CourtViolation("court definition changed during the sitting")
    verdicts = {c: results[c]["judgement"]["court_verdict"] for c in results}
    return defn, {"court_hash": sealed_hash, "results": results,
                  "verdicts": verdicts,
                  "court_pass": all(v == PASS for v in verdicts.values())}
