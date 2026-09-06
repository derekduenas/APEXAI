"""RESULT_VALIDATOR_V1 -- result integrity for FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1 cells.

WHY THIS EXISTS (WM-0E RESULT-INTEGRITY CLOSURE V1)
The frozen reader `courts.final_court.load_cell` establishes IDENTITY: the
court, the primary seed derivation, the cell_id (which binds court, control,
index and world hashes) and the train/evaluation geometry. It does NOT
establish RESULT integrity: a persisted cell whose `verdict`, `p` or
`positive` field has been altered still reloads. That gap was demonstrated
by independent review (Astra) and is reproduced through the real reader in
tests/test_result_validator.py. This module closes it for future artifacts
WITHOUT editing the frozen court implementation or its sealed definition.

TWO DIFFERENT THINGS, KEPT SEPARATE
  1. CONSISTENCY VALIDATION (validate_cell / audit_court): every field must
     be present, of the right type, inside the domain the frozen producer
     can actually emit, and the decision fields must be mutually consistent
     under the sealed decision rule. Detection and direction counts are
     RECOMPUTED from validated numeric fields; stored verdict strings and
     summary counts are checked against the recount, never trusted.
  2. PAYLOAD COMMITMENT (cell_digest / court_commitment / verify_commitment):
     a strict deterministic digest over every adjudication-relevant field,
     verified against a TRUSTED root supplied separately by the caller.
     Consistency validation cannot detect a coherent alteration (e.g. p
     0.61 -> 0.62 on a NO_SIGNAL cell); only a commitment held outside the
     payload can.

TRUST BOUNDARY (read this before believing a PASS)
  - verify_commitment compares a recomputed root against a root the CALLER
    obtained from somewhere the payload could not have written: a sealed
    predeclaration commit, a separately committed manifest, a record made
    before outcomes. Recomputing a root and comparing it to a root stored
    NEXT TO the payload proves nothing, because whoever altered the payload
    could rewrite that root too. This module therefore refuses a None root.
  - Replacing BOTH the payload and its trusted commitment is outside what
    this check alone can detect. Detecting that needs the commitment to be
    anchored somewhere the adversary cannot write (a commit hash published
    before outcomes, an external witness). That anchoring is a process
    property, not a property of this module.
  - For the historical court COURT-FINAL-f6ba5c856014 no pre-outcome
    commitment of result payloads exists. Any commitment computed now over
    those cells is a POST-HOC AUDIT SNAPSHOT: it can bind the artifacts
    from this moment forward, it cannot establish that they were not
    altered between 2026-09-05T20:16Z and now, and it does not strengthen
    the original seal.

DOMAINS ARE DERIVED FROM THE FROZEN PRODUCER, NOT FROM THE WINNING RESULT
  p          = (1 + #{t* >= t_obs}) / (B + 1), B = 1999  -> p on the lattice
               {k / 2000 : k = 1..2000}, so 0 < p <= 1 and p * 2000 is an integer
  verdict    = SIGNAL_DETECTED iff mean_d > 0 and p <= ALPHA (0.025)
  positive   = mean_d > 0
  block      = clamp(round(b_PPW), H=15, floor(n/6)); block_length equals the
               nested block.block_length; clamped in {lower, none, upper}
               consistent with proposed; selector n equals n_eval
  t_obs      = mean_d / HAC_se, identical formula to secondary.hac_t
               (Bartlett, L = 14, 1/n autocovariances) -> equal up to fp
  hac_verdict = SIGNAL_DETECTED iff hac_t > 2.0 (mean > 0 is implied when
               the HAC se is positive, which a finite t_obs guarantees)
  non_overlap_verdict = SIGNAL_DETECTED iff non_overlap_z > 2.0
  t_star_q975 = numpy linear 0.975 quantile of 1999 t*; therefore
               t_obs > q975 -> at most 50 t* >= t_obs -> p <= 51/2000, and
               t_obs < q975 -> at least 50 t* >= t_obs -> p >= 51/2000
  acf1_d     = lag-1 sample autocorrelation of d -> |acf1_d| <= 1
  seeds      = derive_seed(control, PRIMARY_ROLE, index, namespace);
               companions = R51.target_seed (N0), R3.shadow_seed (N3)
  worlds     = role labels exactly as run_cell writes them; two-world
               controls carry two DISTINCT world hashes
  split      = executed_split_record(R4_SPLIT | N1_SPLIT, E)["executed_split_hash"]
  geometry   = EXPECTED_GEOMETRY[control]

Diagnostic secondaries (`non_overlap_z`, `legacy_iid_z`) may be +/-inf by
construction of the frozen producer (zero-variance subset); NaN is never
admitted anywhere. Every ADJUDICATION field must be finite.

Nothing here reads a result to change anything. decision_power: NONE.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field as _field

from apex.world_model import bootstrap as BS
from apex.world_model import controls_r3 as R3
from apex.world_model import controls_r4 as R4
from apex.world_model import controls_r51 as R51
from apex.world_model import inference as I
from apex.world_model import teststand as TS
from apex.world_model.canonical import content_hash
from courts import final_court as F

VALIDATOR_VERSION = "RESULT_VALIDATOR_V1"
COMMITMENT_VERSION = "RESULT_COMMITMENT_V1"
VERDICTS = ("SIGNAL_DETECTED", "NO_SIGNAL")
COURT_STATUSES = ("PASS", "FAIL", "RUN_INVALID")
P_LATTICE = BS.B_REPLICATIONS + 1                       # 2000
Q975_P_BOUNDARY = 51.0 / P_LATTICE                     # 0.0255, derived above
T_EQUALITY_TOL = 1e-6                                  # hac_t vs t_obs, same formula
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CELL_NAME = re.compile(r"^(N0|N1|N2|N3|N4|P0)_(\d{2})\.json$")

# The exact key set run_cell persists (FINAL_COURT_RUNNER_V0.1). A cell with
# any other key set is not a cell this runner wrote.
CELL_KEYS = ("cell_id", "court_id", "court_hash", "control", "identity", "index", "primary_seed",
             "worlds", "companion_seed", "namespace", "purpose", "runner", "verdict", "p", "t_obs",
             "block_length", "block", "t_star_q975", "mean_d", "sd_d", "acf1_d", "positive",
             "n_eval", "n_train", "executed_split_hash", "secondary", "utc")
SECONDARY_KEYS = ("hac_t", "hac_verdict", "non_overlap_z", "non_overlap_verdict", "legacy_iid_z")
BLOCK_KEYS = ("rule", "lower", "upper", "selector_output", "proposed", "block_length", "clamped")
SELECTOR_KEYS = ("selector", "variant", "n", "K_N", "m_max", "band", "autocov_lags_available",
                 "max_lag_read", "m_hat", "M", "G_hat", "D_hat", "b_opt")
# Everything except the wall-clock instant. `utc` is instance identity, not
# scientific content (the same convention as forecast_hash vs forecast_id).
ADJUDICATION_FIELDS = tuple(k for k in CELL_KEYS if k != "utc")
WORLD_ROLES = {"N0": ("feature_world", "target_world"), "N3": ("target_world", "shadow_feature_world"),
               "N1": ("world",), "N2": ("world",), "N4": ("world",), "P0": ("world",)}
AGGREGATE_KEYS = ("court_id", "court_hash", "code_commit", "precourt_tree_commit", "surface_hash",
                  "precourt_regression_artifact_sha256", "cells_expected", "cells_executed", "duplicate_cells",
                  "missing_cells", "integrity_failure", "judgement", "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1",
                  "runner", "oom_kill_before", "oom_kill_after", "elapsed_s", "resource", "cells")


class ResultValidationFailure(Exception):
    """A result artifact is not what the frozen producer can have written,
    or is internally contradictory. Never a science verdict."""

    def __init__(self, failures):
        self.failures = list(failures)
        super().__init__("; ".join(self.failures))


class CommitmentFailure(Exception):
    """The payload does not match its separately trusted commitment."""


# ---------------------------------------------------------------- strict primitives
def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_real(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _finite(v) -> bool:
    return _is_real(v) and math.isfinite(float(v))


def _not_nan(v) -> bool:
    return _is_real(v) and not math.isnan(float(v))


def expected_split_hash(control: str) -> str:
    """Independently derived from the FROZEN split objects, without
    generating a world or running a forecast."""
    split = R51.N1_SPLIT if control == "N1" else R4.R4_SPLIT
    return TS.executed_split_record(split, F.E)["executed_split_hash"]


def expected_companion_seed(control: str, primary_seed: int):
    if control == "N0":
        return R51.target_seed(primary_seed)
    if control == "N3":
        return R3.shadow_seed(primary_seed)
    return None


def decision(mean_d: float, p: float) -> str:
    """THE SEALED DECISION RULE, restated once: SIGNAL_DETECTED iff mean(d) > 0 and p <= alpha."""
    return "SIGNAL_DETECTED" if (mean_d > 0 and p <= BS.ALPHA) else "NO_SIGNAL"


# ---------------------------------------------------------------- cell validation
def cell_failures(cell, defn: F.FinalCourtDefinition, *, expected_index_range=range(F.N_INDEX)) -> list:
    """Every reason this cell is not a valid FINAL_COURT_RUNNER_V0.1 result for
    `defn`. Empty list == valid. Collects ALL failures so an audit reports
    the whole shape of a bad artifact, not the first symptom."""
    f = []
    if not isinstance(cell, dict):
        return ["cell is %s, not an object" % type(cell).__name__]
    keys = set(cell)
    missing = [k for k in CELL_KEYS if k not in keys]
    extra = sorted(keys - set(CELL_KEYS))
    if missing:
        f.append("missing fields: %s" % missing)
    if extra:
        f.append("unexpected fields: %s" % extra)
    if missing:
        return f                                                    # nothing below is meaningful

    # ---- identity
    ctl = cell["control"]
    if ctl not in F.CONTROLS:
        f.append("unknown control %r" % (ctl,))
        return f
    if cell["identity"] != F.IDENTITY[ctl]:
        f.append("control identity %r != %r" % (cell["identity"], F.IDENTITY[ctl]))
    idx = cell["index"]
    if not _is_int(idx) or idx not in expected_index_range:
        f.append("invalid index %r" % (idx,))
    if not (isinstance(cell["cell_id"], str) and _HEX64.match(cell["cell_id"])):
        f.append("cell_id is not a sha256 hex")
    if cell["court_id"] != defn.court_id:
        f.append("court_id %r != %r" % (cell["court_id"], defn.court_id))
    if cell["court_hash"] != defn.court_hash:
        f.append("court_hash does not match the definition")
    if cell["namespace"] != defn.namespace:
        f.append("namespace %r != %r" % (cell["namespace"], defn.namespace))
    if cell["purpose"] != defn.purpose:
        f.append("purpose %r != %r" % (cell["purpose"], defn.purpose))
    if cell["runner"] != F.RUNNER_VERSION:
        f.append("runner %r != %r" % (cell["runner"], F.RUNNER_VERSION))

    # ---- seeds and worlds (provenance)
    seed = cell["primary_seed"]
    if not _is_int(seed) or not (0 <= seed < F.SEED_MODULUS):
        f.append("primary_seed %r is not an integer in [0, 2^31-1)" % (seed,))
    elif _is_int(idx) and idx in expected_index_range:
        if seed != F.derive_seed(ctl, F.PRIMARY_ROLE[ctl], idx, defn.namespace):
            f.append("primary_seed does not derive from (namespace, %s, %s, %s)" % (ctl, F.PRIMARY_ROLE[ctl], idx))
        exp_comp = expected_companion_seed(ctl, seed)
        if cell["companion_seed"] != exp_comp:
            f.append("companion_seed %r != frozen derivation %r" % (cell["companion_seed"], exp_comp))
    worlds = cell["worlds"]
    roles = WORLD_ROLES[ctl]
    if not isinstance(worlds, dict) or tuple(worlds) != roles:
        f.append("world roles %s != expected %s" % (list(worlds) if isinstance(worlds, dict) else type(worlds).__name__, list(roles)))
    else:
        for r, h in worlds.items():
            if not (isinstance(h, str) and _HEX64.match(h)):
                f.append("world hash for role %s is not a sha256 hex" % r)
        if len(roles) == 2 and len(set(worlds.values())) != 2:
            f.append("two-world control with identical world hashes")
        if _is_int(idx) and cell["cell_id"] != F.cell_id(defn.court_id, ctl, idx, worlds):
            f.append("cell_id does not recompute from (court, control, index, worlds)")

    # ---- geometry and split provenance
    exp_eval, exp_train = F.EXPECTED_GEOMETRY[ctl]
    if not _is_int(cell["n_eval"]) or cell["n_eval"] != exp_eval:
        f.append("n_eval %r != %d" % (cell["n_eval"], exp_eval))
    if not _is_int(cell["n_train"]) or cell["n_train"] != exp_train:
        f.append("n_train %r != %d" % (cell["n_train"], exp_train))
    if cell["executed_split_hash"] != expected_split_hash(ctl):
        f.append("executed_split_hash does not match the frozen %s split at E=%d" % ("N1" if ctl == "N1" else "standard", F.E))

    # ---- adjudication numerics
    p, t, m, sd, acf, q975 = cell["p"], cell["t_obs"], cell["mean_d"], cell["sd_d"], cell["acf1_d"], cell["t_star_q975"]
    for name, v in (("p", p), ("t_obs", t), ("mean_d", m), ("sd_d", sd), ("acf1_d", acf), ("t_star_q975", q975)):
        if not _finite(v):
            f.append("%s is not a finite real number: %r" % (name, v))
    if _finite(p):
        if not (0.0 < p <= 1.0):
            f.append("p = %r outside (0, 1]" % (p,))
        elif abs(p * P_LATTICE - round(p * P_LATTICE)) > 1e-9:
            f.append("p = %r is not on the producer lattice k/%d" % (p, P_LATTICE))
    if _finite(sd) and sd <= 0:
        f.append("sd_d = %r; a finite t_obs requires positive dispersion" % (sd,))
    if _finite(acf) and abs(acf) > 1.0 + 1e-12:
        f.append("acf1_d = %r outside [-1, 1]" % (acf,))
    if not _finite(cell["utc"]) or cell["utc"] <= 0:
        f.append("utc is not a positive finite timestamp")

    # ---- decision consistency (the sealed rule, recomputed)
    if cell["verdict"] not in VERDICTS:
        f.append("unknown verdict %r" % (cell["verdict"],))
    if not isinstance(cell["positive"], bool):
        f.append("positive is %s, not bool" % type(cell["positive"]).__name__)
    if _finite(m) and _finite(p):
        if cell["verdict"] in VERDICTS and cell["verdict"] != decision(m, p):
            f.append("verdict %r contradicts mean_d=%r, p=%r under the sealed rule (%r)" % (cell["verdict"], m, p, decision(m, p)))
        if isinstance(cell["positive"], bool) and cell["positive"] != (m > 0):
            f.append("positive=%r contradicts mean_d=%r" % (cell["positive"], m))
    if _finite(t) and _finite(m) and (t > 0) != (m > 0) and m != 0:
        f.append("sign of t_obs (%r) contradicts sign of mean_d (%r)" % (t, m))
    if _finite(t) and _finite(q975) and _finite(p):
        if t > q975 and p > Q975_P_BOUNDARY + 1e-12:
            f.append("t_obs %r exceeds t_star_q975 %r but p=%r > %.4f" % (t, q975, p, Q975_P_BOUNDARY))
        if t < q975 and p < Q975_P_BOUNDARY - 1e-12:
            f.append("t_obs %r below t_star_q975 %r but p=%r < %.4f" % (t, q975, p, Q975_P_BOUNDARY))

    # ---- block: nested structure and the duplicated representation
    blk = cell["block"]
    if not isinstance(blk, dict) or tuple(sorted(blk)) != tuple(sorted(BLOCK_KEYS)):
        f.append("block structure invalid: %s" % (sorted(blk) if isinstance(blk, dict) else type(blk).__name__))
    else:
        bl = cell["block_length"]
        if not _is_int(bl):
            f.append("block_length %r is not an integer" % (bl,))
        if bl != blk["block_length"]:
            f.append("block_length %r != block.block_length %r" % (bl, blk["block_length"]))
        if blk["rule"] != BS.BLOCK_RULE:
            f.append("block.rule is not the frozen BLOCK_RULE")
        if blk["lower"] != BS.BLOCK_LOWER:
            f.append("block.lower %r != %d" % (blk["lower"], BS.BLOCK_LOWER))
        if _is_int(cell["n_eval"]) and blk["upper"] != cell["n_eval"] // BS.MIN_BLOCKS:
            f.append("block.upper %r != floor(n_eval/%d)" % (blk["upper"], BS.MIN_BLOCKS))
        prop = blk["proposed"]
        if not _is_int(prop) or not _is_int(blk["block_length"]) or not _is_int(blk["upper"]):
            f.append("block proposed/block_length/upper must be integers")
        else:
            chosen = min(max(BS.BLOCK_LOWER, prop), blk["upper"])
            if blk["block_length"] != chosen:
                f.append("block.block_length %r != clamp(proposed=%r)" % (blk["block_length"], prop))
            clamp = "lower" if prop < BS.BLOCK_LOWER else ("upper" if prop > blk["upper"] else "none")
            if blk["clamped"] != clamp:
                f.append("block.clamped %r inconsistent with proposed %r" % (blk["clamped"], prop))
        so = blk["selector_output"]
        if not isinstance(so, dict) or tuple(sorted(so)) != tuple(sorted(SELECTOR_KEYS)):
            f.append("block.selector_output structure invalid")
        else:
            if so["n"] != cell["n_eval"]:
                f.append("selector n %r != n_eval %r" % (so["n"], cell["n_eval"]))
            if not _finite(so["b_opt"]):
                f.append("selector b_opt not finite: %r" % (so["b_opt"],))
            elif _is_int(prop) and prop != int(round(so["b_opt"])):
                f.append("block.proposed %r != round(b_opt=%r)" % (prop, so["b_opt"]))
            if so["variant"] != "circular":
                f.append("selector variant %r is not the frozen circular variant" % (so["variant"],))

    # ---- secondaries: structure, NaN-free, and their own stated rules
    sec = cell["secondary"]
    if not isinstance(sec, dict) or tuple(sorted(sec)) != tuple(sorted(SECONDARY_KEYS)):
        f.append("secondary structure invalid: %s" % (sorted(sec) if isinstance(sec, dict) else type(sec).__name__))
    else:
        if not _finite(sec["hac_t"]):
            f.append("secondary.hac_t not finite: %r" % (sec["hac_t"],))
        elif _finite(t) and abs(sec["hac_t"] - t) > T_EQUALITY_TOL * max(1.0, abs(t)):
            f.append("secondary.hac_t %r != t_obs %r (same HAC studentiser)" % (sec["hac_t"], t))
        for zname in ("non_overlap_z", "legacy_iid_z"):
            if not _not_nan(sec[zname]):
                f.append("secondary.%s is NaN or not a number: %r" % (zname, sec[zname]))
        for vname in ("hac_verdict", "non_overlap_verdict"):
            if sec[vname] not in VERDICTS:
                f.append("secondary.%s unknown verdict %r" % (vname, sec[vname]))
        if _finite(sec["hac_t"]) and sec["hac_verdict"] in VERDICTS:
            exp = "SIGNAL_DETECTED" if sec["hac_t"] > I.DM_THRESHOLD else "NO_SIGNAL"
            if sec["hac_verdict"] != exp:
                f.append("secondary.hac_verdict %r contradicts hac_t %r" % (sec["hac_verdict"], sec["hac_t"]))
        if _not_nan(sec["non_overlap_z"]) and sec["non_overlap_verdict"] in VERDICTS:
            exp = "SIGNAL_DETECTED" if sec["non_overlap_z"] > I.DM_THRESHOLD else "NO_SIGNAL"
            if sec["non_overlap_verdict"] != exp:
                f.append("secondary.non_overlap_verdict %r contradicts non_overlap_z %r" % (sec["non_overlap_verdict"], sec["non_overlap_z"]))
    return f


def validate_cell(cell, defn: F.FinalCourtDefinition, **kw) -> dict:
    """Fail closed. Returns the cell only when NO failure exists."""
    fails = cell_failures(cell, defn, **kw)
    if fails:
        raise ResultValidationFailure(fails)
    return cell


def load_and_validate_cell(path: str, defn: F.FinalCourtDefinition, **kw) -> dict:
    """The frozen reader FIRST (identity, geometry), then result integrity."""
    cell = F.load_cell(path, defn)
    return validate_cell(cell, defn, **kw)


# ---------------------------------------------------------------- recount
def recount(cells: list, *, n_index: int = F.N_INDEX) -> dict:
    """Detections and directions RECOMPUTED from validated numeric fields
    with the sealed rule; acceptance verdicts from the sealed thresholds.
    Stored verdict strings and stored summary counts are NOT used."""
    out = {}
    for ctl in F.CONTROLS:
        cs = [c for c in cells if c["control"] == ctl]
        det = sum(1 for c in cs if decision(c["mean_d"], c["p"]) == "SIGNAL_DETECTED")
        pos = sum(1 for c in cs if c["mean_d"] > 0)
        det_idx = sorted(c["index"] for c in cs if decision(c["mean_d"], c["p"]) == "SIGNAL_DETECTED")
        stored_det = sum(1 for c in cs if c["verdict"] == "SIGNAL_DETECTED")
        stored_pos = sum(1 for c in cs if c["positive"] is True)
        # The thresholds are sealed for exactly N_INDEX cells per control. Any
        # other cell count is NOT adjudicable -- a 1-cell "court" must never
        # read as PASS because 0 <= 5.
        if n_index != F.N_INDEX:
            verdict = "NOT_ADJUDICABLE"
            rule = "thresholds are sealed for %d cells per control; %d requested" % (F.N_INDEX, n_index)
        elif ctl == "P0":
            verdict = "PASS" if (len(cs) == n_index and det >= F.P0_MIN_DETECTIONS and pos >= F.P0_MIN_DIRECTION) else "FAIL"
            rule = "detections >= %d AND direction >= %d of %d" % (F.P0_MIN_DETECTIONS, F.P0_MIN_DIRECTION, n_index)
        else:
            verdict = "PASS" if (len(cs) == n_index and det <= F.NULL_MAX_DETECTIONS) else "FAIL"
            rule = "detections <= %d of %d" % (F.NULL_MAX_DETECTIONS, n_index)
        out[ctl] = {"cells": len(cs), "detections": det, "direction": pos, "detected_indices": det_idx,
                    "stored_verdict_detections": stored_det, "stored_positive_count": stored_pos,
                    "stored_matches_recount": (stored_det == det and stored_pos == pos),
                    "rule": rule, "verdict": verdict}
    return {"controls": out, "all_pass": all(r["verdict"] == "PASS" for r in out.values()),
            "rule_source": "mean_d > 0 and p <= %.3f (bootstrap.ALPHA); thresholds from courts.final_court" % BS.ALPHA}


# ---------------------------------------------------------------- court audit
def _sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def audit_court(out_dir: str, defn: F.FinalCourtDefinition, *, expected_indices=None,
                aggregate_name: str = "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json",
                manifest_name: str = "seed_manifest.json") -> dict:
    """READ-ONLY audit of a court directory: inventory, per-cell validation,
    manifest agreement, individual-vs-aggregate agreement, recount. Returns a
    structured report; `ok` is True only when every check passed. Never
    writes, never executes a cell."""
    expected_indices = list(range(F.N_INDEX)) if expected_indices is None else list(expected_indices)
    idx_range = range(min(expected_indices), max(expected_indices) + 1) if expected_indices else range(0)
    rep = {"validator": VALIDATOR_VERSION, "court_id": defn.court_id, "court_hash": defn.court_hash,
           "namespace": defn.namespace, "purpose": defn.purpose, "failures": [], "cell_failures": {},
           "file_sha256": {}}
    cells_dir = os.path.join(out_dir, "cells")
    expected = {"%s_%02d.json" % (c, i) for c in F.CONTROLS for i in expected_indices}
    found = sorted(os.listdir(cells_dir)) if os.path.isdir(cells_dir) else []
    misnamed = [n for n in found if not _CELL_NAME.match(n)]
    named = [n for n in found if _CELL_NAME.match(n)]
    rep["inventory"] = {"expected": len(expected), "found_files": len(found), "misnamed": misnamed,
                        "missing": sorted(expected - set(named)), "unexpected": sorted(set(named) - expected)}
    if misnamed:
        rep["failures"].append("misnamed cell files: %s" % misnamed)
    if rep["inventory"]["missing"]:
        rep["failures"].append("missing cells: %d" % len(rep["inventory"]["missing"]))
    if rep["inventory"]["unexpected"]:
        rep["failures"].append("unexpected cells: %s" % rep["inventory"]["unexpected"])

    # per-file: frozen reader, then result validation, then filename agreement
    cells, ids, keys_seen = {}, {}, {}
    for name in sorted(set(named) & expected):
        path = os.path.join(cells_dir, name)
        rep["file_sha256"][name] = _sha256_file(path)
        try:
            cell = F.load_cell(path, defn)
        except F.CourtIntegrityFailure as e:
            rep["cell_failures"][name] = ["frozen reader refused: %s" % e]; continue
        fails = cell_failures(cell, defn, expected_index_range=idx_range)
        m = _CELL_NAME.match(name)
        if cell.get("control") != m.group(1) or cell.get("index") != int(m.group(2)):
            fails.append("file name %s disagrees with content (%s, %s)" % (name, cell.get("control"), cell.get("index")))
        if fails:
            rep["cell_failures"][name] = fails
        cells[name] = cell
        ids.setdefault(cell.get("cell_id"), []).append(name)
        keys_seen.setdefault((cell.get("control"), cell.get("index")), []).append(name)
    dup_ids = {k: v for k, v in ids.items() if len(v) > 1}
    dup_keys = {"%s/%s" % k: v for k, v in keys_seen.items() if len(v) > 1}
    rep["inventory"].update({"unique_cell_ids": len(ids), "duplicate_cell_ids": dup_ids, "duplicate_control_index": dup_keys})
    if dup_ids or dup_keys:
        rep["failures"].append("duplicate cells: ids %s keys %s" % (dup_ids, dup_keys))
    if rep["cell_failures"]:
        rep["failures"].append("%d cell(s) failed validation" % len(rep["cell_failures"]))

    # manifest agreement
    man_path = os.path.join(out_dir, manifest_name)
    if os.path.exists(man_path):
        rep["file_sha256"][manifest_name] = _sha256_file(man_path)
        man = json.load(open(man_path))
        rows = {(r["control"], r["index"]): r for r in man.get("cells", [])}
        mf = []
        if man.get("namespace") != defn.namespace:
            mf.append("manifest namespace %r != %r" % (man.get("namespace"), defn.namespace))
        if content_hash(man.get("cells", [])) != man.get("manifest_hash"):
            mf.append("manifest_hash does not recompute from its rows")
        if man.get("manifest_hash") != defn.seed_manifest_hash:
            mf.append("manifest_hash != definition.seed_manifest_hash")
        for name, c in cells.items():
            r = rows.get((c["control"], c["index"]))
            if r is None:
                mf.append("%s has no manifest row" % name); continue
            if r["primary_seed"] != c["primary_seed"] or r.get("companion_seed") != c["companion_seed"]:
                mf.append("%s seeds disagree with the manifest row" % name)
        rep["manifest"] = {"rows": len(rows), "failures": mf}
        rep["failures"].extend(mf)
    else:
        rep["manifest"] = {"status": "ABSENT"}
        rep["failures"].append("seed manifest absent")

    # aggregate agreement
    agg_path = os.path.join(out_dir, aggregate_name)
    if os.path.exists(agg_path):
        rep["file_sha256"][aggregate_name] = _sha256_file(agg_path)
        agg = json.load(open(agg_path))
        af = aggregate_failures(agg, defn, cells, expected_count=len(expected))
        rep["aggregate"] = {"failures": af, "status": agg.get("FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1")}
        rep["failures"].extend(af)
    else:
        rep["aggregate"] = {"status": "ABSENT"}
        rep["failures"].append("aggregate artifact absent")

    # recount over VALID cells only (an invalid cell has no adjudicable numbers)
    valid = [c for n, c in cells.items() if n not in rep["cell_failures"]]
    rep["recount"] = recount(valid, n_index=len(expected_indices))
    rep["ok"] = not rep["failures"]
    return rep


def aggregate_failures(agg: dict, defn: F.FinalCourtDefinition, cells_by_file: dict, *, expected_count: int) -> list:
    af = []
    if not isinstance(agg, dict):
        return ["aggregate is not an object"]
    miss = [k for k in AGGREGATE_KEYS if k not in agg]
    extra = sorted(set(agg) - set(AGGREGATE_KEYS))
    if miss:
        af.append("aggregate missing keys %s" % miss)
    if extra:
        af.append("aggregate unexpected keys %s" % extra)
    if miss:
        return af
    if agg["court_id"] != defn.court_id or agg["court_hash"] != defn.court_hash:
        af.append("aggregate court identity differs from the definition")
    if agg["code_commit"] != defn.code_commit:
        af.append("aggregate code_commit %r != %r" % (agg["code_commit"], defn.code_commit))
    if agg["surface_hash"] != defn.scientific_surface_hash:
        af.append("aggregate surface_hash differs from the definition")
    if agg["runner"] != F.RUNNER_VERSION:
        af.append("aggregate runner %r" % (agg["runner"],))
    if not (isinstance(agg["precourt_regression_artifact_sha256"], str) and _HEX64.match(agg["precourt_regression_artifact_sha256"])):
        af.append("precourt_regression_artifact_sha256 is not a sha256 hex")
    if agg["FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"] not in COURT_STATUSES:
        af.append("unknown court status %r" % (agg["FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"],))
    for k in ("cells_expected", "cells_executed", "duplicate_cells", "missing_cells", "oom_kill_before", "oom_kill_after"):
        if not _is_int(agg[k]) or agg[k] < 0:
            af.append("aggregate %s %r is not a non-negative integer" % (k, agg[k]))
    if not _finite(agg["elapsed_s"]) or agg["elapsed_s"] < 0:
        af.append("aggregate elapsed_s invalid")
    acells = agg["cells"]
    if not isinstance(acells, list):
        return af + ["aggregate.cells is not a list"]
    if agg["cells_expected"] != expected_count:
        af.append("aggregate cells_expected %r != %d" % (agg["cells_expected"], expected_count))
    if agg["cells_executed"] != len(acells):
        af.append("aggregate cells_executed %r != len(cells) %d" % (agg["cells_executed"], len(acells)))
    aids = [c.get("cell_id") if isinstance(c, dict) else None for c in acells]
    if len(set(aids)) != len(aids):
        af.append("aggregate contains duplicate cell_ids")
    if agg["duplicate_cells"] != len(aids) - len(set(aids)):
        af.append("aggregate duplicate_cells %r != %d" % (agg["duplicate_cells"], len(aids) - len(set(aids))))
    if agg["missing_cells"] != expected_count - len(acells):
        af.append("aggregate missing_cells %r != %d" % (agg["missing_cells"], expected_count - len(acells)))
    by_key = {}
    for c in acells:
        if not isinstance(c, dict):
            af.append("aggregate cell entry is not an object"); continue
        by_key.setdefault((c.get("control"), c.get("index")), []).append(c)
    for name, fc in cells_by_file.items():
        k = (fc["control"], fc["index"])
        if k not in by_key:
            af.append("%s has no aggregate counterpart" % name); continue
        if len(by_key[k]) != 1:
            af.append("%s has %d aggregate counterparts" % (name, len(by_key[k]))); continue
        if by_key[k][0] != fc:                                  # SEMANTIC equality (JSON-decoded objects)
            diff = sorted(x for x in set(fc) | set(by_key[k][0]) if fc.get(x) != by_key[k][0].get(x))
            af.append("%s differs from its aggregate counterpart in %s" % (name, diff))
    for k in by_key:
        if not any((fc["control"], fc["index"]) == k for fc in cells_by_file.values()):
            af.append("aggregate cell %s/%s has no file counterpart" % k)
    # the stored judgement and status against a recount of the AGGREGATE's own cells
    valid_agg = [c for c in acells if isinstance(c, dict) and not cell_failures(c, defn, expected_index_range=range(F.N_INDEX))]
    rc = recount(valid_agg, n_index=F.N_INDEX) if expected_count == len(F.CONTROLS) * F.N_INDEX else None
    if rc is not None:
        j = agg["judgement"] if isinstance(agg["judgement"], dict) else {}
        jc = j.get("controls", {}) if isinstance(j.get("controls"), dict) else {}
        for ctl, r in rc["controls"].items():
            s = jc.get(ctl, {})
            if s.get("detections") != r["detections"] or s.get("verdict") != r["verdict"] or (ctl == "P0" and s.get("direction") != r["direction"]):
                af.append("stored judgement for %s (det %r, dir %r, %r) != recount (det %d, dir %d, %s)" % (
                    ctl, s.get("detections"), s.get("direction"), s.get("verdict"), r["detections"], r["direction"], r["verdict"]))
        if len(valid_agg) == expected_count and agg["integrity_failure"] is None:
            exp_status = "PASS" if rc["all_pass"] else "FAIL"
            if agg["FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"] != exp_status:
                af.append("stored status %r != recount %r" % (agg["FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"], exp_status))
        elif agg["FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"] == "PASS":
            af.append("status PASS with %d/%d valid cells and integrity_failure=%r" % (len(valid_agg), expected_count, agg["integrity_failure"]))
    return af


def validate_court(out_dir: str, defn: F.FinalCourtDefinition, **kw) -> dict:
    rep = audit_court(out_dir, defn, **kw)
    if not rep["ok"]:
        raise ResultValidationFailure(rep["failures"])
    return rep


# ---------------------------------------------------------------- payload commitment
def _strict(obj, path="$"):
    """Admit only JSON-representable, NaN/inf-free content with string keys.
    bool is kept distinct from int/float by json.dumps ('true' vs '1' vs '1.0')."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise CommitmentFailure("%s is non-finite (%r); a commitment over NaN is meaningless" % (path, obj))
        return obj
    if isinstance(obj, (list, tuple)):
        return [_strict(v, "%s[%d]" % (path, i)) for i, v in enumerate(obj)]
    if isinstance(obj, dict):
        out = {}
        for k in sorted(obj):
            if not isinstance(k, str):
                raise CommitmentFailure("%s has a non-string key %r" % (path, k))
            out[k] = _strict(obj[k], "%s.%s" % (path, k))
        return out
    raise CommitmentFailure("%s has unserialisable type %s" % (path, type(obj).__name__))


def strict_canonical_bytes(obj) -> bytes:
    """Deterministic, strict serialisation: sorted keys, no whitespace, ASCII
    escapes, no NaN/inf, floats in Python's shortest round-trip repr."""
    return json.dumps(_strict(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def cell_digest(cell: dict) -> str:
    """sha256 over ALL adjudication-relevant fields (everything the runner
    persists except the wall-clock `utc`). A missing field is a refusal,
    not an empty contribution."""
    missing = [k for k in ADJUDICATION_FIELDS if k not in cell]
    if missing:
        raise CommitmentFailure("cannot commit a cell missing %s" % missing)
    body = {k: cell[k] for k in ADJUDICATION_FIELDS}
    return hashlib.sha256(("%s|cell|" % COMMITMENT_VERSION).encode() + strict_canonical_bytes(body)).hexdigest()


def court_commitment(cells: list) -> dict:
    """Deterministic manifest: one entry per cell, ordered by (control, index),
    and a root over the ordered entry lines. Duplicate (control, index) is a
    refusal -- a commitment over an ambiguous set commits to nothing."""
    entries = []
    seen = set()
    for c in cells:
        key = (c["control"], c["index"])
        if key in seen:
            raise CommitmentFailure("duplicate cell %s/%s in commitment set" % key)
        seen.add(key)
        entries.append({"control": c["control"], "index": c["index"], "cell_id": c["cell_id"], "digest": cell_digest(c)})
    entries.sort(key=lambda e: (F.CONTROLS.index(e["control"]) if e["control"] in F.CONTROLS else 99, e["index"]))
    lines = "\n".join("%s|%d|%s|%s" % (e["control"], e["index"], e["cell_id"], e["digest"]) for e in entries)
    root = hashlib.sha256(("%s|root|%d|" % (COMMITMENT_VERSION, len(entries))).encode() + lines.encode()).hexdigest()
    return {"version": COMMITMENT_VERSION, "fields": list(ADJUDICATION_FIELDS), "cells": len(entries),
            "entries": entries, "root": root}


def verify_commitment(cells: list, trusted_root: str, *, trusted_entries: list | None = None) -> dict:
    """Recompute the commitment over `cells` and compare with a root the
    caller obtained INDEPENDENTLY of the payload. Refuses a None/empty root:
    'compare against whatever is stored next to the payload' is the exact
    non-check this function exists to replace. With `trusted_entries`, the
    first cell whose digest differs is named."""
    if not isinstance(trusted_root, str) or not _HEX64.match(trusted_root):
        raise CommitmentFailure("a trusted root must be supplied separately from the payload (got %r)" % (trusted_root,))
    com = court_commitment(cells)
    if trusted_entries is not None:
        by = {(e["control"], e["index"]): e for e in trusted_entries}
        for e in com["entries"]:
            t = by.get((e["control"], e["index"]))
            if t is None:
                raise CommitmentFailure("cell %s/%d has no trusted entry" % (e["control"], e["index"]))
            if t["digest"] != e["digest"] or t["cell_id"] != e["cell_id"]:
                raise CommitmentFailure("cell %s/%d payload does not match its trusted digest" % (e["control"], e["index"]))
        if len(by) != len(com["entries"]):
            raise CommitmentFailure("trusted manifest has %d entries, payload has %d" % (len(by), len(com["entries"])))
    if com["root"] != trusted_root:
        raise CommitmentFailure("commitment root mismatch: payload %s… != trusted %s…" % (com["root"][:16], trusted_root[:16]))
    return {"version": COMMITMENT_VERSION, "root": com["root"], "cells": com["cells"], "verified": True,
            "trust_boundary": "the root was supplied by the caller; this proves the payload matches THAT root, "
                              "not that the root itself is authentic"}
