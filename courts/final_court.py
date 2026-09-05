"""FINAL_SYNTHETIC_ACCEPTANCE_COURT_V0 -- WM-0E-R7. ONE SITTING. NO DEVELOPMENT.

Six rows, frozen: N0_SHADOW_TARGET_NULL_V1, N1_TIME_DESTRUCTION_E1860_V1, N2
(noise features), N3_SHADOW_FEATURE_NULL_V1, N4 (random ranker),
P0_CAUSAL_TREND_POWERED_V2. Engine DEPENDENT_BLOCK_BOOTSTRAP_V0.1, E=1860,
boundary 720, alpha 0.025, B 1999. Per-control acceptance ONLY (<= 5/50 for
each null; P0 >= 40/50 detections AND >= 45/50 direction). N0 V1 and N3 V1
are role-reversed twins of one two-world family and are never counted as
independent evidence. Nothing here reads a result to change anything.

SEEDS. Namespace WM0E_R7_FINAL_ACCEPTANCE_V0, 50 indices. Primary world seed
per (namespace, control, role, index): sha256(NS|control|role|index)[:8] mod
2^31-1. Companion worlds (N0's target world B, N3's shadow-feature world B)
are the FROZEN controls' own deterministic namespace functions of the
primary seed -- part of the validated control identity -- and are recorded
per cell with their role labels. Every seed (primary and companion) is
audited against every prior development/acceptance/calibration seed.

ONE-WAY. R7_COURT_OPENED is written once (O_EXCL); from that instant the
whole acceptance set is CONSUMED whatever happens. Cells are written once
each (O_EXCL); a second write for the same cell is refused. An integrity
failure (OOM, geometry, provenance, hash) makes the court RUN_INVALID and
stops it; a scientific failure never stops it -- all 300 cells run.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from apex.world_model import bootstrap as BS
from apex.world_model import controls as C
from apex.world_model import controls_r3 as R3
from apex.world_model import controls_r4 as R4
from apex.world_model import controls_r5 as R5
from apex.world_model import controls_r51 as R51
from apex.world_model import inference as I
from apex.world_model import teststand as TS
from apex.world_model.budget import wm0e_r51_truth
from apex.world_model.canonical import content_hash
from apex.world_model.controls import ControlViolation
from apex.world_model.court import SEED_SET as V0_SEEDS
from apex.world_model.grader import null_rule
from apex.world_model.holdout import HOLDOUT_SEEDS as V21_SEEDS
from apex.world_model.models import M0SyntheticBaseline, NullBaseline

COURT_VERSION = "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"
RUNNER_VERSION = "FINAL_COURT_RUNNER_V0.1"
RUNNER_HISTORY = {
    "V0": "COURT-FINAL-ae42a5e4fda7 (namespace WM0E_R7_FINAL_ACCEPTANCE_V0) opened 2026-09-05T18:35:33Z and "
          "failed on its first cell: WM-IMPL-002 -- the companion world and the bootstrap result were both "
          "bound to the name `b`, so the cell record read `.config` on a dict. 0/300 cells; RUN_INVALID; "
          "the namespace is CONSUMED; one N0 seed pair entered computation in memory.",
    "V0.1": "same scientific court semantics; unambiguous names (companion_world, bootstrap_result); "
            "companion provenance read from the world object before anything is rebound; reload "
            "validation; development-only end-to-end qualification of the exact run_cell path for all six "
            "controls BEFORE any acceptance namespace exists. The qualification itself exposed a second latent "
            "defect (run_cell did not create its cells/ directory; V0's chain did it externally) -- fixed inside "
            "run_cell. IMPLEMENTATION_REPAIR."}
CONSUMED_NAMESPACES = ("WM0E_R1_HOLDOUT_V0", "WM0E_R7_FINAL_ACCEPTANCE_V0")
BURNED_R7_NAMESPACE = "WM0E_R7_FINAL_ACCEPTANCE_V0"
QUALIFICATION_NAMESPACE = "WM0E_R7_1_RUNNER_QUALIFICATION_DEV_V0"     # development-only, never acceptance
# The acceptance namespace is MINTED in a later commit. While None, nothing can
# derive, instantiate or inspect an acceptance seed.
NAMESPACE = None
N_INDEX = 50
SEED_MODULUS = 2 ** 31 - 1
E = 1860
NULL_MAX_DETECTIONS = 5
P0_MIN_DETECTIONS = 40
P0_MIN_DIRECTION = 45
AUTHORITY = "SYNTHETIC_RESEARCH_ONLY"
CONTROLS = ("N0", "N1", "N2", "N3", "N4", "P0")
IDENTITY = {"N0": "N0_SHADOW_TARGET_NULL_V1", "N1": "N1_TIME_DESTRUCTION_E1860_V1",
            "N2": "N2_NOISE_FEATURES (controls.py V0.1)", "N3": "N3_SHADOW_FEATURE_NULL_V1",
            "N4": "N4_RANDOM_RANKER (controls.py V0.1)", "P0": "P0_CAUSAL_TREND_POWERED_V2"}
PRIMARY_ROLE = {"N0": "feature_world", "N1": "world", "N2": "world", "N3": "target_world",
                "N4": "world", "P0": "world"}
COMPANION_ROLE = {"N0": "target_world (frozen R51.target_seed of the feature seed)",
                  "N3": "shadow_feature_world (frozen R3.shadow_seed of the target seed)"}
EXPECTED_GEOMETRY = {"N0": (E, 701), "N1": (E, R51.N1_EXPECTED_TRAIN), "N2": (E, 701),
                     "N3": (E, 701), "N4": (E, 701), "P0": (E, 701)}
TWIN_DISCLOSURE = ("N0_SHADOW_TARGET_NULL_V1 and N3_SHADOW_FEATURE_NULL_V1 are role-reversed "
                   "variants of ONE two-independent-world null family; useful as distinct "
                   "directionality checks; NOT independent evidence streams. Primary acceptance "
                   "is per control; no pooled or independence-based family test promotes the court.")


class CourtIntegrityFailure(Exception):
    """Infrastructure/provenance failure -> RUN_INVALID. Never a science verdict."""


# ---------------------------------------------------------------- §8 budget snapshot
# The ResearchBudget ledger lives in the FROZEN scientific surface (budget.py),
# so the final snapshot is a DOCUMENT: the frozen ledger as it stands plus the
# infrastructure and acceptance history that the ledger's categories do not
# carry, hashed together. Nothing in the surface changes.
ADDITIONAL_HISTORY = {
    "regression_infrastructure": [
        "MONOLITHIC_CONTAINED_REGRESSION: REGRESSION_OOM, killed at ~47% inside 1400M (2026-09-05 03:57Z); resource-invalid",
        "BOUNDED_FULL_REGRESSION_V0 (R6): fresh-process module sharding, 3983 nodeids; FAIL -- test_null_rig.py shard OOM",
        "TEST-NULL-RIG-MEMORY-001: test-support memory repair; peak 698 MiB; exact semantic equivalence",
        "BOUNDED_FULL_REGRESSION_V0.1 (R6.1): 3988/3988 nodeids, 3969 PASS / 19 SKIP, 0 OOM; PASS"],
    "acceptance_sets_consumed": ["WM0E_R1_HOLDOUT_V0: 50 seeds, consumed by COURT-V2-386a408b7417 (NULL_COURT_V2.1, FAIL)"],
    "development_seed_sets_observed": {"WM_0E_DEVELOPMENT_NULL_SET_V0": 25, "WM0E_R3_N3_DEV_V0": 100, "WM0E_R3_P0_DEV_V0": 50,
                                       "WM0E_R4_P0_DEV_V0": 50, "WM0E_R5_NEG_DEV_V0": 100, "WM0E_R51_DEV_V0": 100},
    "failed_court_sittings": ["COURT-a4c366b64b0d", "COURT-0d4063653ce6", "COURT-bad6d1f1cff0", "COURT-V2-386a408b7417"],
    "statistical_methodology_revisions": ["iid z (WM-0D) -> DEPENDENCE_AWARE_DM_HAC_V0 (R1, stopped at calibration) -> "
                                          "DEPENDENT_BLOCK_BOOTSTRAP_V0 (R2, implementation error) -> V0.1 (R2.1, frozen)"],
    "control_redesigns": ["N3 V0 retired -> N3_SHADOW_FEATURE_NULL_V1", "N0 V0 failed E1860 -> N0_SHADOW_TARGET_NULL_V1"],
    "positive_control": ["P0 V0 failed power (31/50)", "magnitude ladder 1.0/1.5/2.0/3.0 failed (R3)",
                         "evaluation-length ladder 465/930/1395/1860 -> 1860 selected (R4)"],
    "one_model_one_test": False}


def r7_budget_snapshot() -> dict:
    ledger = wm0e_r51_truth()
    doc = {"name": "WORLD_MODEL_RESEARCH_BUDGET_V0_FINAL_PRE_R7", "ledger": ledger.canonical(),
           "ledger_hash": ledger.budget_hash, "burden": ledger.burden_statement(),
           "additional_history": ADDITIONAL_HISTORY}
    doc["snapshot_hash"] = content_hash({"ledger": doc["ledger"], "additional_history": ADDITIONAL_HISTORY})
    return doc


# ---------------------------------------------------------------- §4 seeds
def _need(namespace):
    if namespace is None:
        raise CourtIntegrityFailure("acceptance NAMESPACE not minted; pass an explicit development namespace")
    return namespace


def derive_seed(control: str, role: str, index: int, namespace: str = None) -> int:
    namespace = _need(namespace if namespace is not None else NAMESPACE)
    h = hashlib.sha256(("%s|%s|%s|%d" % (namespace, control, role, index)).encode()).digest()
    return int.from_bytes(h[:8], "big") % SEED_MODULUS


def seed_manifest(namespace: str = None) -> dict:
    namespace = _need(namespace if namespace is not None else NAMESPACE)
    rows = []
    for ctl in CONTROLS:
        for i in range(N_INDEX):
            p = derive_seed(ctl, PRIMARY_ROLE[ctl], i, namespace)
            row = {"control": ctl, "index": i, "primary_role": PRIMARY_ROLE[ctl], "primary_seed": p}
            if ctl == "N0":
                row["companion_role"] = COMPANION_ROLE["N0"]; row["companion_seed"] = R51.target_seed(p)
            if ctl == "N3":
                row["companion_role"] = COMPANION_ROLE["N3"]; row["companion_seed"] = R3.shadow_seed(p)
            rows.append(row)
    all_seeds = sorted({r["primary_seed"] for r in rows} | {r["companion_seed"] for r in rows if "companion_seed" in r})
    return {"namespace": namespace, "indices": N_INDEX, "cells": rows,
            "algorithm": "primary = int.from_bytes(sha256(namespace|control|role|index)[:8], big) mod 2^31-1; "
                         "companion = the frozen control's own namespace function of the primary seed "
                         "(R51.target_seed for N0, R3.shadow_seed for N3)",
            "all_seeds_count": len(all_seeds), "manifest_hash": content_hash(rows)}


def _burned_r7_seeds() -> list:
    m = seed_manifest(BURNED_R7_NAMESPACE)
    return sorted({r["primary_seed"] for r in m["cells"]} | {r["companion_seed"] for r in m["cells"] if "companion_seed" in r})


def _qualification_seeds() -> list:
    m = seed_manifest(QUALIFICATION_NAMESPACE)
    return sorted({r["primary_seed"] for r in m["cells"]} | {r["companion_seed"] for r in m["cells"] if "companion_seed" in r})


def prior_seed_universe() -> dict:
    """Every seed any WM-0E research, development, acceptance or calibration
    ever touched, primary AND companion, plus fixture PRNG namespaces."""
    u = {"V0_dev_25": list(V0_SEEDS), "V2_1_consumed_50": list(V21_SEEDS),
         "R3_N3_dev_100": list(R3.N3_DEV_SEEDS),
         "R3_N3_dev_shadow_100": [R3.shadow_seed(s) for s in R3.N3_DEV_SEEDS],
         "R3_P0_dev_50": list(R3.P0_DEV_SEEDS), "R4_P0_dev_50": list(R4.DEV_SEEDS),
         "R5_dev_100": list(R5.R5_DEV_SEEDS),
         "R5_N3V1_shadow_100": [R3.shadow_seed(s) for s in R5.R5_DEV_SEEDS],
         "R51_dev_100": list(R51.DEV_SEEDS), "R51_N0V1_target_100": list(R51.N0_V1_TARGET_SEEDS),
         "R51_N1_dev_100": list(R51.DEV_SEEDS),
         "calibration_fixture_prng": [7_301_000 + k for k in range(1, 40)] + [8_100_000 + k for k in range(1, 40)]
                                     + [9_500_000 + k for k in range(0, 20)] + [9_400_001, 9_400_002],
         "V0_court_probe_seeds": [1000, 1037],
         "R7_consumed_primary_and_companion_400": _burned_r7_seeds(),
         "R7_partially_executed_N0_index0_pair": [derive_seed("N0", "feature_world", 0, BURNED_R7_NAMESPACE),
                                                  R51.target_seed(derive_seed("N0", "feature_world", 0, BURNED_R7_NAMESPACE))],
         "R7_1_runner_qualification_dev": _qualification_seeds()}
    return u


def collision_audit(manifest: dict) -> dict:
    mine = {r["primary_seed"] for r in manifest["cells"]} | {r["companion_seed"] for r in manifest["cells"] if "companion_seed" in r}
    prior = prior_seed_universe()
    hits = {k: sorted(mine & set(v)) for k, v in prior.items() if mine & set(v)}
    return {"prior_sets_checked": {k: len(v) for k, v in prior.items()}, "r7_seeds": len(mine),
            "collisions": hits, "count": sum(len(v) for v in hits.values())}


# ---------------------------------------------------------------- §7 definition
def _file_sha(mod) -> str:
    return hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class FinalCourtDefinition:
    court_id: str
    code_commit: str
    creation_time: float
    scientific_surface_hash: str
    seed_manifest_hash: str
    budget_snapshot_hash: str
    namespace: str
    purpose: str = "ACCEPTANCE"          # or "RUNNER_QUALIFICATION_DEVELOPMENT_ONLY"

    def canonical(self) -> dict:
        m0 = M0SyntheticBaseline().model_identity(); nl = NullBaseline().model_identity()
        return {"court_version": COURT_VERSION, "court_id": self.court_id, "code_commit": self.code_commit,
                "runner": {"version": RUNNER_VERSION, "history": RUNNER_HISTORY, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                "purpose": self.purpose, "authority": AUTHORITY, "creation_time": self.creation_time,
                "scientific_surface_hash": self.scientific_surface_hash,
                "M0": {"identity": {"model_id": m0["model_id"], "model_version": m0["model_version"],
                                    "configuration": m0["configuration"]}, "config_hash": content_hash(m0["configuration"])},
                "null_comparator": {"model_id": nl["model_id"], "model_version": nl["model_version"]},
                "inference": {"contract_hash": BS.content_identity(), "version": BS.BOOTSTRAP_VERSION,
                              "B": BS.B_REPLICATIONS, "alpha": BS.ALPHA, "decision": BS.DECISION_CONVENTION,
                              "block_rule": BS.BLOCK_RULE},
                "secondary_diagnostics_only": {"hac": I.INFERENCE_VERSION, "non_overlap": I.NON_OVERLAP_VERSION},
                "controls": {c: IDENTITY[c] for c in CONTROLS},
                "control_source_sha256": {"controls.py": _file_sha(C), "controls_r3.py": _file_sha(R3),
                                          "controls_r4.py": _file_sha(R4), "controls_r5.py": _file_sha(R5),
                                          "controls_r51.py": _file_sha(R51)},
                "control_contracts": {"N0": R51.N0_V1_CONTRACT, "N1": {**R51.N1_E1860_CONTRACT, "transformation_sha256": hashlib.sha256(__import__("inspect").getsource(C.n1_dataset).encode()).hexdigest()},
                                      "N2": C.CONTROL_CONTRACT["N2"], "N3": R3.N3_V1_CONTRACT, "N4": C.CONTROL_CONTRACT["N4"],
                                      "P0": {"identity": IDENTITY["P0"], "mu_multiplier": R4.P0_MU_MULTIPLIER, "params": dict(R4.S1_PARAMS), "sigma": R4.S1_SIGMA, "E": E}},
                "geometry": {"standard": R4.R4_SPLIT.canonical(), "N1": R51.N1_SPLIT.canonical(),
                             "expected_usable_and_train": EXPECTED_GEOMETRY, "T_standard": R4.T_MAX, "T_N1": R51.T_N1},
                "executed_split_contract": TS.EXECUTED_SPLIT_CONTRACT,
                "seeds": {"namespace": self.namespace, "indices": N_INDEX, "manifest_hash": self.seed_manifest_hash,
                          "derivation": seed_manifest(self.namespace)["algorithm"],
                          "consumed_namespaces_never_reused": list(CONSUMED_NAMESPACES)},
                "acceptance": {"null_controls": "detections <= %d / 50 PASS; >= %d FAIL" % (NULL_MAX_DETECTIONS, NULL_MAX_DETECTIONS + 1),
                               "P0": "detections >= %d / 50 AND direction >= %d / 50" % (P0_MIN_DETECTIONS, P0_MIN_DIRECTION),
                               "detection": "primary bootstrap p <= alpha with mean(d) > 0; secondaries cannot rescue",
                               "family": TWIN_DISCLOSURE},
                "cells_expected": len(CONTROLS) * N_INDEX,
                "resource_contract": {"slice": "wmresearch.slice", "unit_memory_max": "1400M", "wrapper": "wm_contained.sh"},
                "research_budget_snapshot_hash": self.budget_snapshot_hash,
                "precourt_regression": "REQUIRED to PASS on this exact commit before opening; its artifact "
                                       "sha256 is recorded in the R7_COURT_OPENED record (it cannot exist "
                                       "before this definition is committed)",
                "rescue_logic": "NONE", "development_inside_court": "NONE"}

    @property
    def court_hash(self) -> str:
        return content_hash(self.canonical())


def define(code_commit: str, creation_time: float, surface_hash: str, namespace: str = None,
           purpose: str = "ACCEPTANCE") -> FinalCourtDefinition:
    namespace = _need(namespace if namespace is not None else NAMESPACE)
    if purpose == "ACCEPTANCE" and namespace in CONSUMED_NAMESPACES:
        raise CourtIntegrityFailure("namespace %s is CONSUMED and can never be reused" % namespace)
    if purpose == "ACCEPTANCE" and namespace == QUALIFICATION_NAMESPACE:
        raise CourtIntegrityFailure("the development qualification namespace is not acceptance")
    man = seed_manifest(namespace)
    if purpose == "ACCEPTANCE":
        aud = collision_audit(man)
        if aud["count"]:
            raise CourtIntegrityFailure("seed collisions: %s" % aud["collisions"])
    snap = r7_budget_snapshot()
    cid = "COURT-FINAL-%s" % content_hash({"ns": namespace, "commit": code_commit, "manifest": man["manifest_hash"],
                                            "engine": BS.content_identity(), "surface": surface_hash,
                                            "runner": RUNNER_VERSION, "purpose": purpose})[:12]
    return FinalCourtDefinition(court_id=cid, code_commit=code_commit, creation_time=creation_time,
                                scientific_surface_hash=surface_hash, seed_manifest_hash=man["manifest_hash"],
                                budget_snapshot_hash=snap["snapshot_hash"], namespace=namespace, purpose=purpose)


# ---------------------------------------------------------------- §12 cells
def cell_id(court_id: str, control: str, index: int, world_hashes: dict) -> str:
    return content_hash({"court": court_id, "control": control, "index": index, "worlds": world_hashes})


def _write_once(path: str, doc: dict):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)     # refuses overwrite
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f, indent=1, default=str)


def run_cell(defn: FinalCourtDefinition, control: str, index: int, out_dir: str) -> dict:
    if control not in CONTROLS or not (0 <= index < N_INDEX):
        raise CourtIntegrityFailure("unexpected control/index %s/%s" % (control, index))
    os.makedirs(os.path.join(out_dir, "cells"), exist_ok=True)      # found by R7.1 qualification: V0 relied on the caller
    path = os.path.join(out_dir, "cells", "%s_%02d.json" % (control, index))
    if os.path.exists(path):
        raise CourtIntegrityFailure("duplicate cell %s/%d" % (control, index))
    seed = derive_seed(control, PRIMARY_ROLE[control], index, defn.namespace)
    companion_world = None
    if control == "N1":
        world = R51.n1_world(seed); split = R51.N1_SPLIT; ds = R51.n1_e1860_dataset(seed); model = M0SyntheticBaseline(); worlds = {"world": world.world_hash}
    else:
        world = R4.r4_world(seed); split = R4.R4_SPLIT
        if control == "N0":
            companion_world = R51.target_world(world); ds = R51.n0_v1_dataset(seed); model = M0SyntheticBaseline()
            worlds = {"feature_world": world.world_hash, "target_world": companion_world.world_hash}
            if companion_world.world_hash == world.world_hash or companion_world.config.seed == seed:
                raise CourtIntegrityFailure("N0 same-world pairing")
        elif control == "N3":
            companion_world = R3.shadow_world(world); ds = R3.n3_v1_dataset(seed); model = M0SyntheticBaseline()
            worlds = {"target_world": world.world_hash, "shadow_feature_world": companion_world.world_hash}
            if companion_world.world_hash == world.world_hash or companion_world.config.seed == seed:
                raise CourtIntegrityFailure("N3 same-world pairing")
        elif control == "N2":
            ds = C.n2_dataset(defn.court_id, seed); model = M0SyntheticBaseline(); worlds = {"world": world.world_hash}
        elif control == "N4":
            ds = TS.default_dataset; model = C.RandomRanker(defn.court_id, seed); worlds = {"world": world.world_hash}
        else:
            ds = TS.default_dataset; model = M0SyntheticBaseline(); worlds = {"world": world.world_hash}
    if control != "N4" and model.model_identity()["configuration"] != defn.canonical()["M0"]["identity"]["configuration"]:
        raise CourtIntegrityFailure("M0 configuration drifted")
    m = TS.run_pipeline(world, model, dataset=ds, split=split, code_commit=defn.code_commit)
    n = TS.run_pipeline(world, NullBaseline(), dataset=ds, split=split, code_commit=defn.code_commit)
    es = m["executed_split"]
    exp_eval, exp_train = EXPECTED_GEOMETRY[control]
    if m["n_eval"] != exp_eval or m["n_train"] != exp_train or es["boundary"] != 720 or es["usable_evaluation_count"] != exp_eval:
        raise CourtIntegrityFailure("geometry %s: eval %d train %d boundary %d" % (control, m["n_eval"], m["n_train"], es["boundary"]))
    # provenance of the companion world is fixed HERE, from the world object, before any other binding
    companion_seed = companion_world.config.seed if companion_world is not None else None
    d = np.array(I.paired_differentials(m["grades"], n["grades"]))
    bootstrap_result = BS.bootstrap_test(d.tolist(), court_id=defn.court_id, control=control, seed=seed)
    h = I.dm_hac_rule(m["grades"], n["grades"]); nov = I.non_overlap_rule(m["grades"], n["grades"]); z = null_rule(m["grades"], n["grades"])
    c = d - d.mean(); acf1 = float((c[1:] * c[:-1]).sum() / (c * c).sum()) if (c * c).sum() > 0 else 0.0
    cell = {"cell_id": cell_id(defn.court_id, control, index, worlds), "court_id": defn.court_id, "court_hash": defn.court_hash,
            "control": control, "identity": IDENTITY[control], "index": index, "primary_seed": seed, "worlds": worlds,
            "companion_seed": companion_seed, "namespace": defn.namespace, "purpose": defn.purpose,
            "runner": RUNNER_VERSION,
            "verdict": bootstrap_result["verdict"], "p": bootstrap_result["p_bootstrap"], "t_obs": bootstrap_result["t_obs"],
            "block_length": bootstrap_result["block"]["block_length"], "block": bootstrap_result["block"],
            "t_star_q975": bootstrap_result["t_star_q"]["q975"], "mean_d": float(d.mean()), "sd_d": float(d.std(ddof=1)), "acf1_d": acf1,
            "positive": bool(d.mean() > 0), "n_eval": m["n_eval"], "n_train": m["n_train"],
            "executed_split_hash": es["executed_split_hash"],
            "secondary": {"hac_t": h["t"], "hac_verdict": h["verdict"], "non_overlap_z": nov["z"],
                          "non_overlap_verdict": nov["verdict"], "legacy_iid_z": z["z"]}, "utc": time.time()}
    _write_once(path, cell)
    reloaded = load_cell(path, defn)                       # the artifact must validate on reload
    return reloaded


def load_cell(path: str, defn: FinalCourtDefinition) -> dict:
    """Reload a persisted cell and validate it against the court. Refuses a
    wrong court, a seed that does not derive from (namespace, control, role,
    index), a cell_id that does not recompute, or a corrupted artifact."""
    try:
        cell = json.load(open(path))
    except (OSError, ValueError) as e:
        raise CourtIntegrityFailure("corrupted cell artifact %s: %s" % (path, type(e).__name__))
    for k in ("cell_id", "court_id", "court_hash", "control", "index", "primary_seed", "worlds", "verdict", "p", "t_obs", "block", "n_eval", "n_train"):
        if k not in cell:
            raise CourtIntegrityFailure("cell artifact missing %s" % k)
    if cell["court_id"] != defn.court_id or cell["court_hash"] != defn.court_hash:
        raise CourtIntegrityFailure("cell belongs to a different court")
    if cell["control"] not in CONTROLS or not (0 <= cell["index"] < N_INDEX):
        raise CourtIntegrityFailure("cell has unexpected control/index")
    if cell["primary_seed"] != derive_seed(cell["control"], PRIMARY_ROLE[cell["control"]], cell["index"], defn.namespace):
        raise CourtIntegrityFailure("cell seed does not derive from the court namespace")
    if cell["cell_id"] != cell_id(defn.court_id, cell["control"], cell["index"], cell["worlds"]):
        raise CourtIntegrityFailure("cell_id does not recompute")
    if cell["control"] in ("N0", "N3") and (cell["companion_seed"] is None or len(cell["worlds"]) != 2):
        raise CourtIntegrityFailure("two-world cell without companion provenance")
    exp_eval, exp_train = EXPECTED_GEOMETRY[cell["control"]]
    if cell["n_eval"] != exp_eval or cell["n_train"] != exp_train:
        raise CourtIntegrityFailure("cell geometry mismatch on reload")
    return cell


# ---------------------------------------------------------------- §23 verdict
def judge(cells: list) -> dict:
    by = {c: [x for x in cells if x["control"] == c] for c in CONTROLS}
    q = lambda xs, k: float(np.quantile(xs, k)) if xs else None
    rows = {}
    for ctl, cs in by.items():
        det = sum(1 for x in cs if x["verdict"] == "SIGNAL_DETECTED"); pos = sum(1 for x in cs if x["positive"])
        ps = [x["p"] for x in cs]; ts = [x["t_obs"] for x in cs]; bl = [x["block_length"] for x in cs]
        row = {"identity": IDENTITY[ctl], "cells": len(cs), "detections": det, "rate": det / len(cs) if cs else None,
               "p": {"min": min(ps), "q10": q(ps, .1), "med": q(ps, .5), "q90": q(ps, .9), "max": max(ps),
                     "frac_le_025": float(np.mean(np.array(ps) <= .025)), "frac_le_05": float(np.mean(np.array(ps) <= .05)),
                     "frac_le_10": float(np.mean(np.array(ps) <= .10))} if cs else None,
               "t_obs": {"min": min(ts), "q10": q(ts, .1), "med": q(ts, .5), "q90": q(ts, .9), "max": max(ts)} if cs else None,
               "block": {"q25": q(bl, .25), "med": q(bl, .5), "q75": q(bl, .75)} if cs else None,
               "acf1_d_med": q([x["acf1_d"] for x in cs], .5), "t_star_q975_med": q([x["t_star_q975"] for x in cs], .5),
               "hac_detections": sum(1 for x in cs if x["secondary"]["hac_verdict"] == "SIGNAL_DETECTED"),
               "non_overlap_detections": sum(1 for x in cs if x["secondary"]["non_overlap_verdict"] == "SIGNAL_DETECTED"),
               "usable_eval": sorted({x["n_eval"] for x in cs}), "n_train": sorted({x["n_train"] for x in cs})}
        if ctl == "P0":
            row.update({"direction": pos, "direction_rate": pos / len(cs) if cs else None,
                        "verdict": "PASS" if (det >= P0_MIN_DETECTIONS and pos >= P0_MIN_DIRECTION and len(cs) == N_INDEX) else "FAIL"})
        else:
            row.update({"max_allowed": NULL_MAX_DETECTIONS,
                        "verdict": "PASS" if (det <= NULL_MAX_DETECTIONS and len(cs) == N_INDEX) else "FAIL"})
        rows[ctl] = row
    det_idx = {c: {x["index"] for x in by[c] if x["verdict"] == "SIGNAL_DETECTED"} for c in CONTROLS if c != "P0"}
    overlap = {"%s∩%s" % (a, b): sorted(det_idx[a] & det_idx[b]) for i, a in enumerate(det_idx) for b in list(det_idx)[i + 1:]}
    return {"controls": rows, "cross_control": {"overlap_by_index": overlap,
                                                "pooled_negative_detections": "%d/250 (DESCRIPTIVE ONLY)" % sum(len(v) for v in det_idx.values()),
                                                "twin_disclosure": TWIN_DISCLOSURE},
            "all_pass": all(r["verdict"] == "PASS" for r in rows.values())}
