"""WM-0E RESULT-INTEGRITY CLOSURE V1 -- RESULT_VALIDATOR_V1 / RESULT_COMMITMENT_V1.

1. Reproduces, THROUGH THE REAL FROZEN READER (courts.final_court.load_cell,
   real identity helpers, real files on disk), the review finding that an
   altered verdict / p / direction still reloads. Development-only cells,
   produced by the real run_cell on the development qualification namespace.
   No historical court artifact is read or mutated here.
2. Proves the versioned validator fails closed on every listed alteration
   and still accepts legitimate NO_SIGNAL and SIGNAL_DETECTED cells.
3. Proves the payload commitment catches a coherent alteration the
   consistency validator cannot, and refuses to verify without a
   separately supplied trusted root.
"""
import copy
import hashlib
import json
import math
import os
import shutil

import pytest

from courts import final_court as F
from courts import result_validator as RV
from regression import runner as RR

FROZEN_SURFACE = "f6b87f2947e2bf62403a04dcaeda0805bc62e8ca1cfebacdc7b14ef10856439d"
FROZEN_RUNNER_SHA_PREFIX = "8ef67c48b70d4d9204a50918ab7654fb79065759"     # R7_1_COURT_OPENED.runner_sha256
QUAL_NS = F.QUALIFICATION_NAMESPACE


@pytest.fixture(scope="module")
def dev(tmp_path_factory):
    """Real run_cell, development namespace, index 0 for every control; P0
    index 1..2 added only until a SIGNAL_DETECTED exists for the positive
    fixture. All of these seeds are already inside prior_seed_universe()."""
    out = str(tmp_path_factory.mktemp("ri_dev"))
    defn = F.define("QUALIFICATION", 0.0, FROZEN_SURFACE, namespace=QUAL_NS,
                    purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    cells = {ctl: F.run_cell(defn, ctl, 0, out) for ctl in F.CONTROLS}
    detected = [c for c in cells.values() if c["verdict"] == "SIGNAL_DETECTED"]
    extra = 1
    while not detected and extra <= 2:
        c = F.run_cell(defn, "P0", extra, out); cells["P0_%d" % extra] = c
        if c["verdict"] == "SIGNAL_DETECTED":
            detected.append(c)
        extra += 1
    no_signal = [c for c in cells.values() if c["verdict"] == "NO_SIGNAL"]
    assert no_signal, "development fixture produced no NO_SIGNAL cell"
    assert detected, "development fixture produced no SIGNAL_DETECTED cell in P0 index 0..2"
    return {"out": out, "defn": defn, "cells": cells, "no_signal": no_signal[0], "signal": detected[0]}


def _write(dirpath, name, cell):
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    json.dump(cell, open(p, "w"), indent=1, default=str)
    return p


# ---------------------------------------------------------------- §1 the gap, through the real reader
def test_frozen_reader_and_surface_are_untouched():
    assert RR.scientific_surface_hash(".")["hash"] == FROZEN_SURFACE
    assert hashlib.sha256(open(F.__file__, "rb").read()).hexdigest().startswith(FROZEN_RUNNER_SHA_PREFIX)
    assert F.RUNNER_VERSION == "FINAL_COURT_RUNNER_V0.1"


@pytest.mark.parametrize("field,value,reason", [
    ("verdict", "SIGNAL_DETECTED", "contradicts"),
    ("p", float("nan"), "not a finite"),
    ("positive", True, "contradicts"),
])
def test_original_reader_accepts_altered_result_field_but_validator_refuses(dev, tmp_path, field, value, reason):
    """GAP REPRODUCTION. Baseline: the real load_cell accepts the genuine
    cell. Altered: the SAME reader, same identity helpers, accepts the file
    with verdict / p / positive changed -- because cell_id binds court,
    control, index and worlds, not the result payload. The validator refuses."""
    base = copy.deepcopy(dev["no_signal"])
    assert base["verdict"] == "NO_SIGNAL" and base["positive"] is False
    good = _write(str(tmp_path / "cells"), "%s_%02d.json" % (base["control"], base["index"]), base)
    assert F.load_cell(good, dev["defn"])["cell_id"] == base["cell_id"]           # baseline acceptance
    bad = copy.deepcopy(base); bad[field] = value
    badp = _write(str(tmp_path / "altered"), "%s_%02d.json" % (base["control"], base["index"]), bad)
    reloaded = F.load_cell(badp, dev["defn"])                                    # the gap: accepted
    if field == "p":
        assert math.isnan(reloaded["p"])
    else:
        assert reloaded[field] == value
    with pytest.raises(RV.ResultValidationFailure, match=reason):
        RV.load_and_validate_cell(badp, dev["defn"])


# ---------------------------------------------------------------- §2 legitimate results still pass
def test_valid_no_signal_and_signal_detected_cells_pass(dev):
    for c in (dev["no_signal"], dev["signal"]):
        assert RV.cell_failures(c, dev["defn"]) == []
        assert RV.validate_cell(c, dev["defn"]) is c
    assert dev["signal"]["p"] <= 0.025 and dev["signal"]["mean_d"] > 0 and dev["signal"]["positive"] is True


def test_every_development_cell_validates_and_identity_helpers_are_the_real_ones(dev):
    for c in dev["cells"].values():
        assert RV.cell_failures(c, dev["defn"]) == [], c["control"]
        assert c["primary_seed"] == F.derive_seed(c["control"], F.PRIMARY_ROLE[c["control"]], c["index"], QUAL_NS)
        assert c["executed_split_hash"] == RV.expected_split_hash(c["control"])
    n0 = dev["cells"]["N0"]; n3 = dev["cells"]["N3"]
    assert n0["companion_seed"] == RV.expected_companion_seed("N0", n0["primary_seed"])
    assert n3["companion_seed"] == RV.expected_companion_seed("N3", n3["primary_seed"])


def test_load_and_validate_runs_the_frozen_reader_first(dev, tmp_path):
    other = F.define("OTHER", 0.0, FROZEN_SURFACE, namespace=QUAL_NS, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    p = _write(str(tmp_path), "N2_00.json", dev["cells"]["N2"])
    with pytest.raises(F.CourtIntegrityFailure):
        RV.load_and_validate_cell(p, other)


# ---------------------------------------------------------------- §5 adversarial: cell level
def _mut(**changes):
    def apply(c):
        for k, v in changes.items():
            if callable(v):
                v(c)
            else:
                c[k] = v
    return apply


def _set_nested(path, value):
    def apply(c):
        d = c
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value
    return apply


def _del(key):
    def apply(c):
        del c[key]
    return apply


CELL_ATTACKS = [
    ("contradictory_verdict", _mut(verdict="SIGNAL_DETECTED"), "contradicts"),
    ("p_nan", _mut(p=float("nan")), "not a finite"),
    ("p_inf", _mut(p=float("inf")), "not a finite"),
    ("t_obs_nan", _mut(t_obs=float("nan")), "not a finite"),
    ("mean_d_inf", _mut(mean_d=float("-inf")), "not a finite"),
    ("t_star_nan", _mut(t_star_q975=float("nan")), "not a finite"),
    ("p_above_one", _mut(p=1.5), "outside"),
    ("p_zero", _mut(p=0.0), "outside"),
    ("p_off_lattice", _mut(p=0.0251), "lattice"),
    ("p_bool", _mut(p=True), "not a finite"),
    ("p_string", _mut(p="0.5"), "not a finite"),
    ("index_bool", _mut(index=True), "invalid index"),
    ("direction_flipped", _mut(positive=True), "contradicts"),
    ("direction_int_not_bool", _mut(positive=0), "not bool"),
    ("unknown_verdict", _mut(verdict="MAYBE"), "unknown verdict"),
    ("unknown_control", _mut(control="N9"), "unknown control"),
    ("wrong_identity", _mut(identity="N2_SOMETHING_ELSE"), "identity"),
    ("wrong_runner", _mut(runner="FINAL_COURT_RUNNER_V0"), "runner"),
    ("wrong_namespace", _mut(namespace="WM0E_R7_1_FINAL_ACCEPTANCE_V1"), "namespace"),
    ("wrong_purpose", _mut(purpose="ACCEPTANCE"), "purpose"),
    ("wrong_split_hash", _mut(executed_split_hash="0" * 64), "executed_split_hash"),
    ("wrong_n_train", _mut(n_train=700), "n_train"),
    ("wrong_seed", lambda c: c.__setitem__("primary_seed", c["primary_seed"] + 1), "does not derive"),
    ("seed_bool", _mut(primary_seed=True), "primary_seed"),
    ("block_length_mismatch", lambda c: c.__setitem__("block_length", c["block_length"] + 1), "block.block_length"),
    ("block_upper_wrong", _set_nested(("block", "upper"), 999), "block.upper"),
    ("block_clamped_inconsistent", lambda c: c["block"].__setitem__("clamped", "upper" if c["block"]["clamped"] != "upper" else "lower"), "clamped"),
    ("block_proposed_not_round_bopt", lambda c: c["block"].__setitem__("proposed", c["block"]["proposed"] + 7), "proposed"),
    ("block_missing_key", lambda c: c["block"].pop("selector_output"), "block structure"),
    ("selector_n_wrong", _set_nested(("block", "selector_output", "n"), 1000), "selector n"),
    ("secondary_hac_contradiction", lambda c: c["secondary"].__setitem__("hac_verdict", "SIGNAL_DETECTED" if c["secondary"]["hac_verdict"] == "NO_SIGNAL" else "NO_SIGNAL"), "hac_verdict"),
    ("secondary_hac_t_drift", lambda c: c["secondary"].__setitem__("hac_t", c["t_obs"] + 0.5), "hac_t"),
    ("secondary_nan", _set_nested(("secondary", "non_overlap_z"), float("nan")), "NaN"),
    ("secondary_missing_key", lambda c: c["secondary"].pop("legacy_iid_z"), "secondary structure"),
    ("secondary_extra_key", _set_nested(("secondary", "bonus"), 1.0), "secondary structure"),
    ("missing_field", _del("t_star_q975"), "missing fields"),
    ("extra_field", _mut(note="hello"), "unexpected fields"),
    ("sd_zero", _mut(sd_d=0.0), "sd_d"),
    ("acf_out_of_range", _mut(acf1_d=1.5), "acf1_d"),
    ("utc_string", _mut(utc="yesterday"), "utc"),
    ("court_hash_wrong", _mut(court_hash="f" * 64), "court_hash"),
]


@pytest.mark.parametrize("name,attack,reason", CELL_ATTACKS, ids=[a[0] for a in CELL_ATTACKS])
def test_validator_refuses_each_cell_alteration(dev, name, attack, reason):
    c = copy.deepcopy(dev["no_signal"])
    attack(c)
    fails = RV.cell_failures(c, dev["defn"])
    assert fails, name
    assert any(reason in msg for msg in fails), (name, fails)
    with pytest.raises(RV.ResultValidationFailure):
        RV.validate_cell(c, dev["defn"])


def test_signal_detected_cell_with_p_raised_above_alpha_is_contradictory(dev):
    c = copy.deepcopy(dev["signal"]); c["p"] = 0.5
    assert any("contradicts" in m for m in RV.cell_failures(c, dev["defn"]))


def test_t_obs_versus_bootstrap_quantile_versus_p_relationship(dev):
    c = copy.deepcopy(dev["no_signal"])
    c["t_obs"] = c["t_star_q975"] + 1.0; c["secondary"]["hac_t"] = c["t_obs"]; c["mean_d"] = abs(c["mean_d"]) + 1e-6
    c["positive"] = True                                                    # keep everything else coherent
    fails = RV.cell_failures(c, dev["defn"])
    assert any("t_star_q975" in m for m in fails), fails


@pytest.mark.parametrize("attack,reason", [
    (lambda c: c.__setitem__("companion_seed", c["companion_seed"] + 1), "companion_seed"),
    (lambda c: c.__setitem__("companion_seed", None), "companion_seed"),
    (lambda c: c.__setitem__("worlds", {"feature_world": c["worlds"]["feature_world"], "shadow_world": c["worlds"]["target_world"]}), "world roles"),
    (lambda c: c.__setitem__("worlds", {"feature_world": c["worlds"]["feature_world"], "target_world": c["worlds"]["feature_world"]}), "identical world hashes"),
    (lambda c: c.__setitem__("worlds", {"feature_world": c["worlds"]["feature_world"], "target_world": "zz" * 32}), "sha256 hex"),
])
def test_validator_refuses_wrong_companion_or_world_role_provenance(dev, attack, reason):
    c = copy.deepcopy(dev["cells"]["N0"]); attack(c)
    fails = RV.cell_failures(c, dev["defn"])
    assert any(reason in m for m in fails), fails


# ---------------------------------------------------------------- §5 adversarial: court level
def _mini_court(dev, root):
    """A development 'court' directory of the six index-0 cells with the
    runner's aggregate shape (expected_indices=[0])."""
    cells = [dev["cells"][ctl] for ctl in F.CONTROLS]
    for c in cells:
        _write(os.path.join(root, "cells"), "%s_%02d.json" % (c["control"], c["index"]), c)
    man = F.seed_manifest(QUAL_NS)
    json.dump(man, open(os.path.join(root, "seed_manifest.json"), "w"), indent=1)
    agg = {"court_id": dev["defn"].court_id, "court_hash": dev["defn"].court_hash, "code_commit": dev["defn"].code_commit,
           "precourt_tree_commit": "DEV", "surface_hash": FROZEN_SURFACE, "precourt_regression_artifact_sha256": "0" * 64,
           "cells_expected": 6, "cells_executed": 6, "duplicate_cells": 0, "missing_cells": 0, "integrity_failure": None,
           "judgement": F.judge(cells), "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1": "FAIL", "runner": F.RUNNER_VERSION,
           "oom_kill_before": 0, "oom_kill_after": 0, "elapsed_s": 1.0, "resource": {}, "cells": copy.deepcopy(cells)}
    json.dump(agg, open(os.path.join(root, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"), "w"), indent=1, default=str)
    return root


def test_mini_court_audit_is_clean_and_recount_matches_stored(dev, tmp_path):
    root = _mini_court(dev, str(tmp_path / "court"))
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0])
    assert rep["ok"], rep["failures"]
    inv = rep["inventory"]
    assert inv["expected"] == inv["found_files"] == inv["unique_cell_ids"] == 6
    assert not inv["missing"] and not inv["unexpected"] and not inv["misnamed"]
    for ctl, r in rep["recount"]["controls"].items():
        assert r["stored_matches_recount"] and r["cells"] == 1
    assert all(r["verdict"] == "NOT_ADJUDICABLE" for r in rep["recount"]["controls"].values())   # 1 cell is never PASS
    assert rep["recount"]["all_pass"] is False
    assert len(rep["file_sha256"]) == 6 + 2


def test_missing_cell_is_refused(dev, tmp_path):
    root = _mini_court(dev, str(tmp_path / "court")); os.remove(os.path.join(root, "cells", "N4_00.json"))
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0])
    assert rep["inventory"]["missing"] == ["N4_00.json"] and not rep["ok"]
    with pytest.raises(RV.ResultValidationFailure, match="missing"):
        RV.validate_court(root, dev["defn"], expected_indices=[0])


def test_unexpected_and_misnamed_cells_are_refused(dev, tmp_path):
    root = _mini_court(dev, str(tmp_path / "court"))
    shutil.copy(os.path.join(root, "cells", "N2_00.json"), os.path.join(root, "cells", "N2_07.json"))
    open(os.path.join(root, "cells", "notes.json"), "w").write("{}")
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0])
    assert rep["inventory"]["unexpected"] == ["N2_07.json"] and rep["inventory"]["misnamed"] == ["notes.json"] and not rep["ok"]


def test_duplicate_cell_content_under_another_name_is_refused(dev, tmp_path):
    root = _mini_court(dev, str(tmp_path / "court"))
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0, 1])           # index 1 expected but absent
    assert len(rep["inventory"]["missing"]) == 6
    shutil.copy(os.path.join(root, "cells", "N2_00.json"), os.path.join(root, "cells", "N2_01.json"))
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0, 1])
    # The frozen reader ACCEPTS the copy (its content is a valid index-0 cell;
    # load_cell never sees the file name). The validator catches it twice:
    # file-name/content disagreement and a duplicated cell_id.
    assert any("file name N2_01.json disagrees with content" in m for m in rep["cell_failures"]["N2_01.json"])
    assert list(rep["inventory"]["duplicate_cell_ids"].values()) == [["N2_00.json", "N2_01.json"]]
    assert "N2/0" in rep["inventory"]["duplicate_control_index"] and not rep["ok"]


def test_duplicate_cell_id_inside_aggregate_is_refused(dev, tmp_path):
    root = _mini_court(dev, str(tmp_path / "court")); ap = os.path.join(root, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json")
    agg = json.load(open(ap)); agg["cells"].append(copy.deepcopy(agg["cells"][0])); agg["cells_executed"] = 7
    json.dump(agg, open(ap, "w"))
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0])
    assert any("duplicate cell_ids" in m for m in rep["failures"]) and any("duplicate_cells" in m for m in rep["failures"])


def test_individual_versus_aggregate_disagreement_is_refused(dev, tmp_path):
    root = _mini_court(dev, str(tmp_path / "court")); ap = os.path.join(root, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json")
    agg = json.load(open(ap)); tgt = next(c for c in agg["cells"] if c["control"] == "N2")
    tgt["p"] = tgt["p"] + (1.0 / RV.P_LATTICE if tgt["p"] < 1 else -1.0 / RV.P_LATTICE)   # coherent on its own
    json.dump(agg, open(ap, "w"))
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0])
    assert any("N2_00.json differs from its aggregate counterpart in ['p']" in m for m in rep["failures"])


def test_manifest_disagreement_is_refused(dev, tmp_path):
    root = _mini_court(dev, str(tmp_path / "court")); mp = os.path.join(root, "seed_manifest.json")
    man = json.load(open(mp)); man["cells"][0]["primary_seed"] += 1; json.dump(man, open(mp, "w"))
    rep = RV.audit_court(root, dev["defn"], expected_indices=[0])
    assert any("manifest_hash does not recompute" in m for m in rep["failures"])
    assert any("seeds disagree with the manifest row" in m for m in rep["failures"])


# ---------------------------------------------------------------- §4 commitment
def test_commitment_is_deterministic_and_order_independent(dev):
    c = dev["no_signal"]
    shuffled = {k: c[k] for k in reversed(list(c))}
    assert RV.cell_digest(c) == RV.cell_digest(shuffled)
    cells = [dev["cells"][k] for k in F.CONTROLS]
    a = RV.court_commitment(cells); b = RV.court_commitment(list(reversed(cells)))
    assert a["root"] == b["root"] and a["entries"] == b["entries"] and a["cells"] == 6


def test_commitment_binds_every_adjudication_field_but_not_the_clock(dev):
    c = copy.deepcopy(dev["no_signal"]); base = RV.cell_digest(c)
    c2 = copy.deepcopy(c); c2["utc"] = c["utc"] + 1000
    assert RV.cell_digest(c2) == base                                          # instance identity is not content
    for k in RV.ADJUDICATION_FIELDS:
        c3 = copy.deepcopy(c)
        if isinstance(c3[k], bool):
            c3[k] = not c3[k]
        elif isinstance(c3[k], (int, float)):
            c3[k] = c3[k] + 1
        elif isinstance(c3[k], str):
            c3[k] = c3[k] + "x"
        elif isinstance(c3[k], dict):
            c3[k] = {**c3[k], "extra": 1}
        else:
            c3[k] = "changed"
        assert RV.cell_digest(c3) != base, k


def test_commitment_serialisation_is_strict():
    with pytest.raises(RV.CommitmentFailure, match="non-finite"):
        RV.strict_canonical_bytes({"p": float("nan")})
    with pytest.raises(RV.CommitmentFailure, match="non-finite"):
        RV.strict_canonical_bytes({"p": float("inf")})
    with pytest.raises(RV.CommitmentFailure, match="non-string key"):
        RV.strict_canonical_bytes({1: "x"})
    with pytest.raises(RV.CommitmentFailure, match="unserialisable"):
        RV.strict_canonical_bytes({"x": object()})
    assert RV.strict_canonical_bytes({"a": True}) != RV.strict_canonical_bytes({"a": 1}) != RV.strict_canonical_bytes({"a": 1.0})
    assert RV.strict_canonical_bytes({"b": 1, "a": 2}) == RV.strict_canonical_bytes({"a": 2, "b": 1}) == b'{"a":2,"b":1}'
    with pytest.raises(RV.CommitmentFailure, match="missing"):
        RV.cell_digest({"cell_id": "x"})


def test_coherent_alteration_passes_validation_but_fails_the_trusted_commitment(dev):
    """The reason a commitment exists: a change that keeps every decision
    relationship intact is invisible to consistency validation."""
    cells = [copy.deepcopy(dev["cells"][k]) for k in F.CONTROLS]
    trusted = RV.court_commitment(cells)                                   # obtained BEFORE the alteration
    victim = next(c for c in cells if c["verdict"] == "NO_SIGNAL" and c["p"] > 0.1)
    step = 1.0 / RV.P_LATTICE if victim["p"] < 1.0 else -1.0 / RV.P_LATTICE
    victim["p"] = victim["p"] + step                                       # still on lattice, still NO_SIGNAL
    assert RV.cell_failures(victim, dev["defn"]) == []                     # validator: nothing to see
    with pytest.raises(RV.CommitmentFailure, match="does not match its trusted digest"):
        RV.verify_commitment(cells, trusted["root"], trusted_entries=trusted["entries"])
    with pytest.raises(RV.CommitmentFailure, match="root mismatch"):
        RV.verify_commitment(cells, trusted["root"])
    victim["p"] = victim["p"] - step                                       # restored: verifies again
    assert RV.verify_commitment(cells, trusted["root"], trusted_entries=trusted["entries"])["verified"] is True


def test_commitment_refuses_to_trust_a_root_stored_next_to_the_payload(dev):
    cells = [dev["cells"][k] for k in F.CONTROLS]
    with pytest.raises(RV.CommitmentFailure, match="trusted root must be supplied"):
        RV.verify_commitment(cells, None)
    with pytest.raises(RV.CommitmentFailure, match="trusted root must be supplied"):
        RV.verify_commitment(cells, "")
    com = RV.court_commitment(cells)
    # An attacker who rewrites the payload AND its co-located root produces a
    # self-consistent pair; verify() cannot know, and says so in its return.
    altered = [copy.deepcopy(c) for c in cells]; altered[0]["p"] = altered[0]["p"] + (1.0 / RV.P_LATTICE if altered[0]["p"] < 1 else -1.0 / RV.P_LATTICE)
    colocated = RV.court_commitment(altered)["root"]
    r = RV.verify_commitment(altered, colocated)
    assert r["verified"] is True and "not that the root itself is authentic" in r["trust_boundary"]
    assert colocated != com["root"]


def test_commitment_refuses_duplicates_and_names_missing_trusted_entries(dev):
    cells = [dev["cells"][k] for k in F.CONTROLS]
    with pytest.raises(RV.CommitmentFailure, match="duplicate"):
        RV.court_commitment(cells + [cells[0]])
    trusted = RV.court_commitment(cells[:5])
    with pytest.raises(RV.CommitmentFailure, match="no trusted entry"):
        RV.verify_commitment(cells, trusted["root"], trusted_entries=trusted["entries"])
