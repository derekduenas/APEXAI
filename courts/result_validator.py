"""RESULT_VALIDATOR_V1.1 -- result integrity for FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1 cells.

WHY THIS EXISTS (WM-0E RESULT-INTEGRITY CLOSURE V1 -> V1.1)
The frozen reader `courts.final_court.load_cell` establishes IDENTITY: the
court, the primary seed derivation, the cell_id (which binds court, control,
index and world hashes) and the train/evaluation geometry. It does NOT
establish RESULT integrity: a persisted cell whose `verdict`, `p` or
`positive` field has been altered still reloads. Independent review (Astra)
demonstrated that gap; V1 of this module closed it for the top-level result
fields. Astra's second review found V1 incomplete: nested selector numerics
(`G_hat = NaN`, `K_N = True`) and a float-valued companion seed passed, and
the validator and the commitment disagreed on producer-legitimate
infinities. V1.1 repairs those without editing the frozen court
implementation or its sealed definition.

TWO DIFFERENT THINGS, KEPT SEPARATE
  1. CONSISTENCY VALIDATION (validate_cell / audit_court): every field --
     top-level AND nested -- must be present, of the right Python type
     (bool is never a number; an integer field must be an int, not a float
     equal to an int), inside the domain the frozen producer can emit, and
     mutually consistent under the sealed decision rule. Detection and
     direction counts are RECOMPUTED from validated numeric fields; stored
     verdict strings and summary counts are checked against the recount,
     never trusted.
  2. PAYLOAD COMMITMENT (RESULT_COMMITMENT_V1 preserved; RESULT_COMMITMENT_V1.1
     added): a strict deterministic digest over every adjudication-relevant
     field, verified against a TRUSTED root supplied separately by the
     caller. Consistency validation cannot detect a coherent alteration
     (p 0.61 -> 0.6105 on a NO_SIGNAL cell); only a commitment held outside
     the payload can.

TRUST MODEL (corrected wording, Astra V1 review)
  - SEAL THE PROTOCOL BEFORE OUTCOMES (the court definition, seeds, rule).
  - ANCHOR RESULT COMMITMENTS WHEN RESULTS ARE PRODUCED. A result hash cannot
    exist before its result is computed; the absence of a "pre-outcome
    result hash" is not a defect. What matters is that the commitment is
    anchored somewhere the payload cannot rewrite (a commit made when the
    results were produced, an external witness) and is supplied to the
    verifier INDEPENDENTLY of the payload.
  - VERIFY LATER READS against that separately trusted commitment.
    verify_commitment* therefore refuses a None root. Recomputing a root
    stored next to the payload proves nothing.
  - Replacing BOTH the payload and its trusted commitment is outside what
    this check alone detects; that is a property of where the root is
    anchored, not of this module.
  - For the historical court COURT-FINAL-f6ba5c856014 the first result
    commitment was computed on 2026-09-06 (RESULT_COMMITMENT_V1 root in
    POST_HOC_AUDIT_SNAPSHOT_V1.json, commit 9d1fca897), after the court
    sealed on 2026-09-05T20:16Z. It anchors the artifacts from that moment;
    the interval before it is unanchored and nothing here changes that.

DOMAINS ARE DERIVED FROM THE FROZEN PRODUCER, NOT FROM THE WINNING RESULT
  p          = (1 + #{t* >= t_obs}) / (B + 1), B = 1999  -> p on the lattice
               {k / 2000 : k = 1..2000}, so 0 < p <= 1 and p * 2000 is an integer
  verdict    = SIGNAL_DETECTED iff mean_d > 0 and p <= ALPHA (0.025)
  positive   = mean_d > 0
  block      = clamp(round(b_PPW), H=15, floor(n/6)); block_length equals the
               nested block.block_length; clamped in {lower, none, upper}
               consistent with proposed
  selector   = Politis-White/PPW on the centred differential, n = n_eval:
               K_N = max(5, ceil(sqrt(log10 n))); m_max = ceil(sqrt n) + K_N;
               band = 2 sqrt(log10 n / n); autocov_lags_available =
               max(2 m_max, m_max + K_N); 0 <= m_hat <= m_max; M = max(1, 2 m_hat);
               max_lag_read = max(M, m_hat + K_N); G_hat finite; D_hat finite >= 0;
               b_opt = (2 G^2 / D)^(1/3) n^(1/3) if D > 0 else 0; proposed = round(b_opt)
  t_obs      = mean_d / HAC_se, identical formula to secondary.hac_t
               (Bartlett, L = 14, 1/n autocovariances) -> equal up to fp
  hac_verdict = SIGNAL_DETECTED iff hac_t > 2.0
  non_overlap_verdict = SIGNAL_DETECTED iff non_overlap_z > 2.0
  t_star_q975 = numpy linear 0.975 quantile of 1999 t*; therefore
               t_obs > q975 -> p <= 51/2000 and t_obs < q975 -> p >= 51/2000
  acf1_d     = lag-1 sample autocorrelation of d -> |acf1_d| <= 1
  seeds      = derive_seed(control, PRIMARY_ROLE, index, namespace), int;
               companions = R51.target_seed (N0), R3.shadow_seed (N3), int
  worlds     = role labels exactly as run_cell writes them; two-world
               controls carry two DISTINCT world hashes
  split      = executed_split_record(R4_SPLIT | N1_SPLIT, E)["executed_split_hash"]
  geometry   = EXPECTED_GEOMETRY[control]

INFINITY POLICY. NaN is refused everywhere. Infinity is refused in every
field the producer contract requires finite. Exactly two DIAGNOSTIC fields
may legitimately be +/-inf because the frozen producer emits them when a
subset has zero variance: `secondary.non_overlap_z` and
`secondary.legacy_iid_z` (INFINITY_PERMITTED_PATHS). RESULT_COMMITMENT_V1
cannot serialise those; RESULT_COMMITMENT_V1.1 can (see below).

Nothing here reads a result to change anything. decision_power: NONE.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re

from apex.world_model import bootstrap as BS
from apex.world_model import controls_r3 as R3
from apex.world_model import controls_r4 as R4
from apex.world_model import controls_r51 as R51
from apex.world_model import inference as I
from apex.world_model import teststand as TS
from apex.world_model.canonical import content_hash
from courts import final_court as F

VALIDATOR_VERSION = "RESULT_VALIDATOR_V1.1"
VALIDATOR_HISTORY = {
    "V1": "top-level result fields validated; nested selector numerics, integer typing of companion_seed and "
          "block integers not fully validated (Astra review 2026-09-06)",
    "V1.1": "every nested numeric/identity field typed and domain-checked from the frozen producer; "
            "infinity policy made explicit and shared with RESULT_COMMITMENT_V1.1"}
COMMITMENT_VERSION = "RESULT_COMMITMENT_V1"          # preserved; historical snapshot identity
COMMITMENT_VERSION_V11 = "RESULT_COMMITMENT_V1.1"    # tagged-leaf canonical form, permits declared diagnostic infinities
VERDICTS = ("SIGNAL_DETECTED", "NO_SIGNAL")
COURT_STATUSES = ("PASS", "FAIL", "RUN_INVALID")
P_LATTICE = BS.B_REPLICATIONS + 1                       # 2000
Q975_P_BOUNDARY = 51.0 / P_LATTICE                     # 0.0255, derived above
T_EQUALITY_TOL = 1e-6                                  # hac_t vs t_obs, same formula
REL_TOL = 1e-9                                         # exact recomputations of producer formulae
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CELL_NAME = re.compile(r"^(N0|N1|N2|N3|N4|P0)_(\d{2})\.json$")
SELECTOR_ID = "POLITIS_WHITE_2004_PPW_2009"
CLAMP_VALUES = ("lower", "none", "upper")

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
INFINITY_PERMITTED_PATHS = ("secondary.non_overlap_z", "secondary.legacy_iid_z")
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
    """The payload does not match its separately trusted commitment, or
    cannot be committed unambiguously."""


# ---------------------------------------------------------------- strict primitives
def _is_int(v) -> bool:
    """A genuine int. bool is excluded; a float equal to an int is NOT an int."""
    return isinstance(v, int) and not isinstance(v, bool)


def _is_real(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _finite(v) -> bool:
    return _is_real(v) and math.isfinite(float(v))


def _not_nan(v) -> bool:
    return _is_real(v) and not math.isnan(float(v))


def _close(a, b, rel=REL_TOL) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


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


def expected_selector_constants(n: int) -> dict:
    """The selector's deterministic constants for series length n, taken
    from the frozen producer's own function."""
    k = BS.selector_constants(n)
    return {"K_N": k["K_N"], "m_max": k["m_max"], "autocov_lags_available": BS.required_autocov_lags(n),
            "band": 2.0 * math.sqrt(math.log10(n) / n)}


def decision(mean_d: float, p: float) -> str:
    """THE SEALED DECISION RULE, restated once: SIGNAL_DETECTED iff mean(d) > 0 and p <= alpha."""
    return "SIGNAL_DETECTED" if (mean_d > 0 and p <= BS.ALPHA) else "NO_SIGNAL"


# ---------------------------------------------------------------- nested structures
def selector_failures(so, n_eval) -> list:
    """block.selector_output: every field typed, finite where the producer
    is finite, and equal to the producer's own deterministic relationships."""
    f = []
    if not isinstance(so, dict) or tuple(sorted(so)) != tuple(sorted(SELECTOR_KEYS)):
        return ["block.selector_output structure invalid: %s" % (sorted(so) if isinstance(so, dict) else type(so).__name__)]
    if so["selector"] != SELECTOR_ID:
        f.append("selector %r != %r" % (so["selector"], SELECTOR_ID))
    if so["variant"] != "circular":
        f.append("selector variant %r is not the frozen circular variant" % (so["variant"],))
    for k in ("n", "K_N", "m_max", "autocov_lags_available", "max_lag_read", "m_hat", "M"):
        if not _is_int(so[k]):
            f.append("selector.%s is %s (%r), not an int" % (k, type(so[k]).__name__, so[k]))
    for k in ("band", "G_hat", "D_hat", "b_opt"):
        if not _finite(so[k]):
            f.append("selector.%s is not a finite real number: %r" % (k, so[k]))
    if f:
        return f                                                    # relationships need well-typed inputs
    n = so["n"]
    if not _is_int(n_eval) or n != n_eval:
        f.append("selector n %r != n_eval %r" % (n, n_eval))
        return f
    exp = expected_selector_constants(n)
    for k in ("K_N", "m_max", "autocov_lags_available"):
        if so[k] != exp[k]:
            f.append("selector.%s %r != producer value %r for n=%d" % (k, so[k], exp[k], n))
    if not _close(so["band"], exp["band"]):
        f.append("selector.band %r != 2*sqrt(log10(n)/n) = %r" % (so["band"], exp["band"]))
    if not (0 <= so["m_hat"] <= exp["m_max"]):
        f.append("selector.m_hat %r outside [0, m_max=%d]" % (so["m_hat"], exp["m_max"]))
    if so["M"] != max(1, 2 * so["m_hat"]):
        f.append("selector.M %r != max(1, 2*m_hat)" % (so["M"],))
    if so["max_lag_read"] != max(so["M"], so["m_hat"] + exp["K_N"]):
        f.append("selector.max_lag_read %r != max(M, m_hat + K_N)" % (so["max_lag_read"],))
    if so["D_hat"] < 0:
        f.append("selector.D_hat %r < 0 (D = 4/3 S^2)" % (so["D_hat"],))
    if so["b_opt"] < 0:
        f.append("selector.b_opt %r < 0" % (so["b_opt"],))
    if so["D_hat"] > 0:
        b = ((2.0 * so["G_hat"] * so["G_hat"] / so["D_hat"]) ** (1.0 / 3.0)) * (n ** (1.0 / 3.0))
        if not _close(so["b_opt"], b):
            f.append("selector.b_opt %r != (2G^2/D)^(1/3) n^(1/3) = %r" % (so["b_opt"], b))
    elif so["b_opt"] != 0.0:
        f.append("selector.b_opt %r must be 0 when D_hat == 0" % (so["b_opt"],))
    return f


def block_failures(blk, top_block_length, n_eval) -> list:
    f = []
    if not isinstance(blk, dict) or tuple(sorted(blk)) != tuple(sorted(BLOCK_KEYS)):
        return ["block structure invalid: %s" % (sorted(blk) if isinstance(blk, dict) else type(blk).__name__)]
    if blk["rule"] != BS.BLOCK_RULE:
        f.append("block.rule is not the frozen BLOCK_RULE")
    for k in ("lower", "upper", "proposed", "block_length"):
        if not _is_int(blk[k]):
            f.append("block.%s is %s (%r), not an int" % (k, type(blk[k]).__name__, blk[k]))
    if not isinstance(blk["clamped"], str) or blk["clamped"] not in CLAMP_VALUES:
        f.append("block.clamped %r not in %s" % (blk["clamped"], CLAMP_VALUES))
    if not _is_int(top_block_length):
        f.append("block_length %r is not an integer" % (top_block_length,))
    f += selector_failures(blk["selector_output"], n_eval)
    if any("not an int" in m or "not an integer" in m for m in f):
        return f
    if top_block_length != blk["block_length"]:
        f.append("block_length %r != block.block_length %r" % (top_block_length, blk["block_length"]))
    if blk["lower"] != BS.BLOCK_LOWER:
        f.append("block.lower %r != %d" % (blk["lower"], BS.BLOCK_LOWER))
    if _is_int(n_eval) and blk["upper"] != n_eval // BS.MIN_BLOCKS:
        f.append("block.upper %r != floor(n_eval/%d)" % (blk["upper"], BS.MIN_BLOCKS))
    prop = blk["proposed"]
    chosen = min(max(BS.BLOCK_LOWER, prop), blk["upper"])
    if blk["block_length"] != chosen:
        f.append("block.block_length %r != clamp(proposed=%r)" % (blk["block_length"], prop))
    clamp = "lower" if prop < BS.BLOCK_LOWER else ("upper" if prop > blk["upper"] else "none")
    if blk["clamped"] in CLAMP_VALUES and blk["clamped"] != clamp:
        f.append("block.clamped %r inconsistent with proposed %r" % (blk["clamped"], prop))
    so = blk["selector_output"]
    if isinstance(so, dict) and _finite(so.get("b_opt")) and prop != int(round(so["b_opt"])):
        f.append("block.proposed %r != round(b_opt=%r)" % (prop, so["b_opt"]))
    return f


def secondary_failures(sec, t_obs) -> list:
    f = []
    if not isinstance(sec, dict) or tuple(sorted(sec)) != tuple(sorted(SECONDARY_KEYS)):
        return ["secondary structure invalid: %s" % (sorted(sec) if isinstance(sec, dict) else type(sec).__name__)]
    if not _finite(sec["hac_t"]):
        f.append("secondary.hac_t not finite: %r" % (sec["hac_t"],))
    elif _finite(t_obs) and abs(sec["hac_t"] - t_obs) > T_EQUALITY_TOL * max(1.0, abs(t_obs)):
        f.append("secondary.hac_t %r != t_obs %r (same HAC studentiser)" % (sec["hac_t"], t_obs))
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

    # ---- identity (strings)
    for k in ("cell_id", "court_id", "court_hash", "control", "identity", "namespace", "purpose", "runner",
              "verdict", "executed_split_hash"):
        if not isinstance(cell[k], str):
            f.append("%s is %s, not a string" % (k, type(cell[k]).__name__))
    ctl = cell["control"]
    if ctl not in F.CONTROLS:
        f.append("unknown control %r" % (ctl,))
        return f
    if cell["identity"] != F.IDENTITY[ctl]:
        f.append("control identity %r != %r" % (cell["identity"], F.IDENTITY[ctl]))
    idx = cell["index"]
    if not _is_int(idx) or idx not in expected_index_range:
        f.append("invalid index %r (%s)" % (idx, type(idx).__name__))
    if not (isinstance(cell["cell_id"], str) and _HEX64.match(cell["cell_id"])):
        f.append("cell_id is not a sha256 hex")
    if not (isinstance(cell["court_hash"], str) and _HEX64.match(cell["court_hash"])):
        f.append("court_hash is not a sha256 hex")
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
        f.append("primary_seed %r (%s) is not an int in [0, 2^31-1)" % (seed, type(seed).__name__))
    elif _is_int(idx) and idx in expected_index_range:
        if seed != F.derive_seed(ctl, F.PRIMARY_ROLE[ctl], idx, defn.namespace):
            f.append("primary_seed does not derive from (namespace, %s, %s, %s)" % (ctl, F.PRIMARY_ROLE[ctl], idx))
    comp = cell["companion_seed"]
    if ctl in ("N0", "N3"):
        if not _is_int(comp) or not (0 <= comp < F.SEED_MODULUS):
            f.append("companion_seed %r (%s) is not an int in [0, 2^31-1)" % (comp, type(comp).__name__))
        elif _is_int(seed) and comp != expected_companion_seed(ctl, seed):
            f.append("companion_seed %r != frozen derivation %r" % (comp, expected_companion_seed(ctl, seed)))
    elif comp is not None:
        f.append("companion_seed must be null for %s, got %r" % (ctl, comp))
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
        f.append("n_eval %r (%s) != %d" % (cell["n_eval"], type(cell["n_eval"]).__name__, exp_eval))
    if not _is_int(cell["n_train"]) or cell["n_train"] != exp_train:
        f.append("n_train %r (%s) != %d" % (cell["n_train"], type(cell["n_train"]).__name__, exp_train))
    if cell["executed_split_hash"] != expected_split_hash(ctl):
        f.append("executed_split_hash does not match the frozen %s split at E=%d" % ("N1" if ctl == "N1" else "standard", F.E))

    # ---- adjudication numerics (all finite by contract)
    p, t, m, sd, acf, q975 = cell["p"], cell["t_obs"], cell["mean_d"], cell["sd_d"], cell["acf1_d"], cell["t_star_q975"]
    for name, v in (("p", p), ("t_obs", t), ("mean_d", m), ("sd_d", sd), ("acf1_d", acf), ("t_star_q975", q975)):
        if not _finite(v):
            f.append("%s is not a finite real number: %r (%s)" % (name, v, type(v).__name__))
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

    # ---- nested structures
    f += block_failures(cell["block"], cell["block_length"], cell["n_eval"])
    f += secondary_failures(cell["secondary"], t)
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


# ---------------------------------------------------------------- court audit (directory level)
def _sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def audit_court(out_dir: str, defn: F.FinalCourtDefinition, *, expected_indices=None,
                aggregate_name: str = "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json",
                manifest_name: str = "seed_manifest.json") -> dict:
    """READ-ONLY audit of a court directory: inventory, per-cell validation,
    manifest agreement, individual-vs-aggregate agreement, recount. Returns a
    structured report; `ok` is True only when every check passed. Never
    writes, never executes a cell. (The required-check REGISTRY that turns
    this and the identity/linkage checks into an overall verdict lives in
    courts.result_audit.)"""
    expected_indices = list(range(F.N_INDEX)) if expected_indices is None else list(expected_indices)
    idx_range = range(min(expected_indices), max(expected_indices) + 1) if expected_indices else range(0)
    rep = {"validator": VALIDATOR_VERSION, "court_id": defn.court_id, "court_hash": defn.court_hash,
           "namespace": defn.namespace, "purpose": defn.purpose, "failures": [], "cell_failures": {},
           "file_sha256": {}, "cells": {}}
    cells_dir = os.path.join(out_dir, "cells")
    expected = {"%s_%02d.json" % (c, i) for c in F.CONTROLS for i in expected_indices}
    found = sorted(os.listdir(cells_dir)) if os.path.isdir(cells_dir) else []
    misnamed = [n for n in found if not _CELL_NAME.match(n)]
    named = [n for n in found if _CELL_NAME.match(n)]
    rep["inventory"] = {"expected": len(expected), "found_files": len(found), "misnamed": misnamed,
                        "missing": sorted(expected - set(named)), "unexpected": sorted(set(named) - expected),
                        "cells_dir_present": os.path.isdir(cells_dir)}
    if not os.path.isdir(cells_dir):
        rep["failures"].append("cells directory absent")
    if misnamed:
        rep["failures"].append("misnamed cell files: %s" % misnamed)
    if rep["inventory"]["missing"]:
        rep["failures"].append("missing cells: %d" % len(rep["inventory"]["missing"]))
    if rep["inventory"]["unexpected"]:
        rep["failures"].append("unexpected cells: %s" % rep["inventory"]["unexpected"])

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
    rep["cells"] = cells
    dup_ids = {k: v for k, v in ids.items() if len(v) > 1}
    dup_keys = {"%s/%s" % k: v for k, v in keys_seen.items() if len(v) > 1}
    rep["inventory"].update({"unique_cell_ids": len(ids), "duplicate_cell_ids": dup_ids, "duplicate_control_index": dup_keys})
    if dup_ids or dup_keys:
        rep["failures"].append("duplicate cells: ids %s keys %s" % (dup_ids, dup_keys))
    if rep["cell_failures"]:
        rep["failures"].append("%d cell(s) failed validation" % len(rep["cell_failures"]))

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
        rep["manifest"] = {"rows": len(rows), "failures": mf, "status": "PRESENT"}
        rep["failures"].extend(mf)
    else:
        rep["manifest"] = {"status": "ABSENT", "failures": ["seed manifest absent"]}
        rep["failures"].append("seed manifest absent")

    agg_path = os.path.join(out_dir, aggregate_name)
    if os.path.exists(agg_path):
        rep["file_sha256"][aggregate_name] = _sha256_file(agg_path)
        try:
            agg = json.load(open(agg_path))
        except ValueError as e:
            agg = None
        if agg is None:
            rep["aggregate"] = {"status": "CORRUPT", "failures": ["aggregate artifact is not valid JSON"]}
            rep["failures"].append("aggregate artifact is not valid JSON")
        else:
            af = aggregate_failures(agg, defn, cells, expected_count=len(expected))
            rep["aggregate"] = {"failures": af, "status": agg.get("FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"), "present": True}
            rep["failures"].extend(af)
    else:
        rep["aggregate"] = {"status": "ABSENT", "failures": ["aggregate artifact absent"]}
        rep["failures"].append("aggregate artifact absent")

    valid = [c for n, c in cells.items() if n not in rep["cell_failures"]]
    rep["valid_cells"] = valid
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


# ---------------------------------------------------------------- RESULT_COMMITMENT_V1 (preserved verbatim)
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
    """V1: deterministic, strict serialisation: sorted keys, no whitespace,
    ASCII escapes, no NaN/inf, floats in Python's shortest round-trip repr.
    Cannot represent the producer's legitimate diagnostic infinities -- that
    is why V1.1 exists. V1 is kept so the historical snapshot root stays
    reproducible."""
    return json.dumps(_strict(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def cell_digest(cell: dict) -> str:
    """V1 digest (preserved). sha256 over ALL adjudication-relevant fields."""
    missing = [k for k in ADJUDICATION_FIELDS if k not in cell]
    if missing:
        raise CommitmentFailure("cannot commit a cell missing %s" % missing)
    body = {k: cell[k] for k in ADJUDICATION_FIELDS}
    return hashlib.sha256(("%s|cell|" % COMMITMENT_VERSION).encode() + strict_canonical_bytes(body)).hexdigest()


def _commitment(cells: list, version: str, digest_fn) -> dict:
    entries = []
    seen = set()
    for c in cells:
        key = (c["control"], c["index"])
        if key in seen:
            raise CommitmentFailure("duplicate cell %s/%s in commitment set" % key)
        seen.add(key)
        entries.append({"control": c["control"], "index": c["index"], "cell_id": c["cell_id"], "digest": digest_fn(c)})
    entries.sort(key=lambda e: (F.CONTROLS.index(e["control"]) if e["control"] in F.CONTROLS else 99, e["index"]))
    lines = "\n".join("%s|%d|%s|%s" % (e["control"], e["index"], e["cell_id"], e["digest"]) for e in entries)
    root = hashlib.sha256(("%s|root|%d|" % (version, len(entries))).encode() + lines.encode()).hexdigest()
    return {"version": version, "fields": list(ADJUDICATION_FIELDS), "cells": len(entries), "entries": entries, "root": root}


def court_commitment(cells: list) -> dict:
    """V1 manifest (preserved): one entry per cell ordered by (control, index)
    and a root over the ordered entry lines."""
    return _commitment(cells, COMMITMENT_VERSION, cell_digest)


def _verify(cells, trusted_root, trusted_entries, version, commit_fn):
    if not isinstance(trusted_root, str) or not _HEX64.match(trusted_root):
        raise CommitmentFailure("a trusted root must be supplied separately from the payload (got %r)" % (trusted_root,))
    com = commit_fn(cells)
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
    return {"version": version, "root": com["root"], "cells": com["cells"], "verified": True,
            "trust_boundary": "the root was supplied by the caller; this proves the payload matches THAT root, "
                              "not that the root itself is authentic"}


def verify_commitment(cells: list, trusted_root: str, *, trusted_entries: list | None = None) -> dict:
    """V1 verify (preserved). Refuses a None/empty root."""
    return _verify(cells, trusted_root, trusted_entries, COMMITMENT_VERSION, court_commitment)


# ---------------------------------------------------------------- RESULT_COMMITMENT_V1.1 (tagged-leaf canonical form)
# Every leaf is emitted as a type-tagged string, so no payload value can
# collide with the representation of another type:
#   null -> "n" · bool -> "b:true"/"b:false" · int -> "i:<decimal>" ·
#   finite float -> "f:<repr>" · +inf -> "inf:+" · -inf -> "inf:-" ·
#   str -> "s:<text>".
# A literal string "inf" is "s:inf", never "inf:+". Positive and negative
# infinity differ. NaN is refused everywhere. Infinity is admitted only at
# INFINITY_PERMITTED_PATHS (the frozen producer's zero-variance diagnostics).
def _tag(obj, path, permitted_inf):
    if obj is None:
        return "n"
    if isinstance(obj, bool):
        return "b:true" if obj else "b:false"
    if isinstance(obj, int):
        return "i:%d" % obj
    if isinstance(obj, float):
        if math.isnan(obj):
            raise CommitmentFailure("%s is NaN; a commitment over NaN is meaningless" % path)
        if math.isinf(obj):
            if path not in permitted_inf:
                raise CommitmentFailure("%s is %r; infinity is only admitted at %s" % (path, obj, list(permitted_inf)))
            return "inf:+" if obj > 0 else "inf:-"
        return "f:%r" % obj
    if isinstance(obj, str):
        return "s:" + obj
    if isinstance(obj, (list, tuple)):
        return [_tag(v, "%s[%d]" % (path, i), permitted_inf) for i, v in enumerate(obj)]
    if isinstance(obj, dict):
        out = {}
        for k in sorted(obj):
            if not isinstance(k, str):
                raise CommitmentFailure("%s has a non-string key %r" % (path, k))
            out[k] = _tag(obj[k], "%s.%s" % (path, k) if path else k, permitted_inf)
        return out
    raise CommitmentFailure("%s has unserialisable type %s" % (path, type(obj).__name__))


def tagged_canonical_bytes(obj, *, permitted_inf_paths=INFINITY_PERMITTED_PATHS, root_path="") -> bytes:
    """V1.1 canonical form. Paths are dotted from the cell root
    ('secondary.non_overlap_z'), so `root_path=""` when `obj` is a cell body."""
    return json.dumps(_tag(obj, root_path, tuple(permitted_inf_paths)), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def cell_digest_v11(cell: dict) -> str:
    missing = [k for k in ADJUDICATION_FIELDS if k not in cell]
    if missing:
        raise CommitmentFailure("cannot commit a cell missing %s" % missing)
    body = {k: cell[k] for k in ADJUDICATION_FIELDS}
    return hashlib.sha256(("%s|cell|" % COMMITMENT_VERSION_V11).encode() + tagged_canonical_bytes(body)).hexdigest()


def court_commitment_v11(cells: list) -> dict:
    com = _commitment(cells, COMMITMENT_VERSION_V11, cell_digest_v11)
    com["representation"] = ("tagged-leaf canonical JSON: n | b:true/false | i:<int> | f:<repr> | inf:+ | inf:- | s:<str>; "
                             "sorted keys; ASCII; NaN refused; infinity only at %s" % list(INFINITY_PERMITTED_PATHS))
    return com


def verify_commitment_v11(cells: list, trusted_root: str, *, trusted_entries: list | None = None) -> dict:
    return _verify(cells, trusted_root, trusted_entries, COMMITMENT_VERSION_V11, court_commitment_v11)
