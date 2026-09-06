"""WM-0E RESULT-INTEGRITY CLOSURE V1 / V1.1 -- RESULT_VALIDATOR_V1.1, RESULT_COMMITMENT_V1 (preserved), V1.1.

1. Reproduces, THROUGH THE REAL FROZEN READER (courts.final_court.load_cell,
   real identity helpers, real files on disk), the review finding that an
   altered verdict / p / direction still reloads. Development-only cells,
   produced by the real run_cell on the development qualification namespace.
   No historical court artifact is read or mutated here.
2. Proves the validator fails closed on every listed alteration -- top-level
   AND nested (Astra V1.1 finding 1) -- and still accepts legitimate
   NO_SIGNAL and SIGNAL_DETECTED cells.
3. Proves RESULT_COMMITMENT_V1.1 commits producer-legitimate diagnostic
   infinities unambiguously (finding 3), that V1 semantics are preserved,
   and that coherent alterations fail against a separately trusted root.
"""
import copy
import hashlib
import json
import math
import os
import shutil

import pytest

from apex.world_model import bootstrap as BS
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
    assert RV.VALIDATOR_VERSION == "RESULT_VALIDATOR_V1.1" and "V1" in RV.VALIDATOR_HISTORY
    assert RV.COMMITMENT_VERSION == "RESULT_COMMITMENT_V1" and RV.COMMITMENT_VERSION_V11 == "RESULT_COMMITMENT_V1.1"


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
        so = c["block"]["selector_output"]
        exp = RV.expected_selector_constants(c["n_eval"])
        assert so["K_N"] == exp["K_N"] == BS.selector_constants(c["n_eval"])["K_N"] and so["m_max"] == exp["m_max"]
        assert so["autocov_lags_available"] == BS.required_autocov_lags(c["n_eval"])
    n0 = dev["cells"]["N0"]; n3 = dev["cells"]["N3"]
    assert n0["companion_seed"] == RV.expected_companion_seed("N0", n0["primary_seed"])
    assert n3["companion_seed"] == RV.expected_companion_seed("N3", n3["primary_seed"])


def test_load_and_validate_runs_the_frozen_reader_first(dev, tmp_path):
    other = F.define("OTHER", 0.0, FROZEN_SURFACE, namespace=QUAL_NS, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    p = _write(str(tmp_path), "N2_00.json", dev["cells"]["N2"])
    with pytest.raises(F.CourtIntegrityFailure):
        RV.load_and_validate_cell(p, other)


# ---------------------------------------------------------------- §5 adversarial: cell level (top-level fields)
def _mut(**changes):
    def apply(c):
        for k, v in changes.items():
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
    ("index_float", lambda c: c.__setitem__("index", float(c["index"])), "invalid index"),
    ("direction_flipped", _mut(positive=True), "contradicts"),
    ("direction_int_not_bool", _mut(positive=0), "not bool"),
    ("unknown_verdict", _mut(verdict="MAYBE"), "unknown verdict"),
    ("unknown_control", _mut(control="N9"), "unknown control"),
    ("control_not_string", _mut(control=2), "unknown control"),
    ("wrong_identity", _mut(identity="N2_SOMETHING_ELSE"), "identity"),
    ("wrong_runner", _mut(runner="FINAL_COURT_RUNNER_V0"), "runner"),
    ("wrong_namespace", _mut(namespace="WM0E_R7_1_FINAL_ACCEPTANCE_V1"), "namespace"),
    ("wrong_purpose", _mut(purpose="ACCEPTANCE"), "purpose"),
    ("wrong_split_hash", _mut(executed_split_hash="0" * 64), "executed_split_hash"),
    ("split_hash_not_string", _mut(executed_split_hash=None), "not a string"),
    ("wrong_n_train", _mut(n_train=700), "n_train"),
    ("n_train_float", lambda c: c.__setitem__("n_train", float(c["n_train"])), "n_train"),
    ("n_eval_float", lambda c: c.__setitem__("n_eval", float(c["n_eval"])), "n_eval"),
    ("n_eval_bool", _mut(n_eval=True), "n_eval"),
    ("wrong_seed", lambda c: c.__setitem__("primary_seed", c["primary_seed"] + 1), "does not derive"),
    ("seed_bool", _mut(primary_seed=True), "primary_seed"),
    ("seed_float", lambda c: c.__setitem__("primary_seed", float(c["primary_seed"])), "primary_seed"),
    ("block_length_mismatch", lambda c: c.__setitem__("block_length", c["block_length"] + 1), "block.block_length"),
    ("block_length_float", lambda c: c.__setitem__("block_length", float(c["block_length"])), "not an integer"),
    ("block_missing_key", lambda c: c["block"].pop("selector_output"), "block structure"),
    ("secondary_missing_key", lambda c: c["secondary"].pop("legacy_iid_z"), "secondary structure"),
    ("secondary_extra_key", _set_nested(("secondary", "bonus"), 1.0), "secondary structure"),
    ("missing_field", _del("t_star_q975"), "missing fields"),
    ("extra_field", _mut(note="hello"), "unexpected fields"),
    ("sd_zero", _mut(sd_d=0.0), "sd_d"),
    ("acf_out_of_range", _mut(acf1_d=1.5), "acf1_d"),
    ("utc_string", _mut(utc="yesterday"), "utc"),
    ("court_hash_wrong", _mut(court_hash="f" * 64), "court_hash"),
    ("court_hash_not_hex", _mut(court_hash="nope"), "sha256 hex"),
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


# ---------------------------------------------------------------- §5 adversarial: NESTED fields (Astra V1.1 finding 1)
INT_SELECTOR = ("n", "K_N", "m_max", "autocov_lags_available", "max_lag_read", "m_hat", "M")
FLOAT_SELECTOR = ("band", "G_hat", "D_hat", "b_opt")
INT_BLOCK = ("lower", "upper", "proposed", "block_length")


def _nested_cases():
    cases = []
    for k in INT_SELECTOR:
        cases += [("selector.%s=True" % k, ("block", "selector_output", k), True, "not an int"),
                  ("selector.%s=float" % k, ("block", "selector_output", k), "FLOAT_OF_SELF", "not an int"),
                  ("selector.%s=str" % k, ("block", "selector_output", k), "7", "not an int"),
                  ("selector.%s=None" % k, ("block", "selector_output", k), None, "not an int"),
                  ("selector.%s+1" % k, ("block", "selector_output", k), "PLUS_ONE", "selector")]
    for k in FLOAT_SELECTOR:
        cases += [("selector.%s=NaN" % k, ("block", "selector_output", k), float("nan"), "not a finite"),
                  ("selector.%s=inf" % k, ("block", "selector_output", k), float("inf"), "not a finite"),
                  ("selector.%s=True" % k, ("block", "selector_output", k), True, "not a finite"),
                  ("selector.%s=str" % k, ("block", "selector_output", k), "1.0", "not a finite"),
                  ("selector.%s*1.01" % k, ("block", "selector_output", k), "TIMES_1_01", "selector")]
    for k in INT_BLOCK:
        cases += [("block.%s=True" % k, ("block", k), True, "not an int"),
                  ("block.%s=float" % k, ("block", k), "FLOAT_OF_SELF", "not an int"),
                  ("block.%s=str" % k, ("block", k), "15", "not an int")]
    cases += [("block.clamped=unknown", ("block", "clamped"), "sideways", "clamped"),
              ("block.clamped=None", ("block", "clamped"), None, "clamped"),
              ("block.rule=other", ("block", "rule"), "some other rule", "BLOCK_RULE"),
              ("selector.selector=other", ("block", "selector_output", "selector"), "OTHER", "selector"),
              ("selector.variant=stationary", ("block", "selector_output", "variant"), "stationary", "circular"),
              ("secondary.hac_t=NaN", ("secondary", "hac_t"), float("nan"), "hac_t"),
              ("secondary.hac_t=True", ("secondary", "hac_t"), True, "hac_t"),
              ("secondary.non_overlap_z=NaN", ("secondary", "non_overlap_z"), float("nan"), "NaN"),
              ("secondary.non_overlap_z=str", ("secondary", "non_overlap_z"), "inf", "NaN or not a number"),
              ("secondary.non_overlap_z=True", ("secondary", "non_overlap_z"), True, "NaN or not a number"),
              ("secondary.legacy_iid_z=NaN", ("secondary", "legacy_iid_z"), float("nan"), "NaN"),
              ("secondary.legacy_iid_z=str", ("secondary", "legacy_iid_z"), "-inf", "NaN or not a number"),
              ("secondary.hac_verdict=other", ("secondary", "hac_verdict"), "MAYBE", "unknown verdict"),
              ("secondary.non_overlap_verdict=int", ("secondary", "non_overlap_verdict"), 1, "unknown verdict")]
    return cases


NESTED = _nested_cases()


@pytest.mark.parametrize("name,path,value,reason", NESTED, ids=[n[0] for n in NESTED])
def test_validator_refuses_each_nested_field_alteration(dev, name, path, value, reason):
    c = copy.deepcopy(dev["no_signal"])
    d = c
    for k in path[:-1]:
        d = d[k]
    cur = d[path[-1]]
    if value == "FLOAT_OF_SELF":
        value = float(cur)
    elif value == "PLUS_ONE":
        value = cur + 1
    elif value == "TIMES_1_01":
        value = cur * 1.01 if cur != 0 else 1.0
    d[path[-1]] = value
    fails = RV.cell_failures(c, dev["defn"])
    assert fails, name
    assert any(reason in m for m in fails), (name, fails)


def test_one_world_cell_with_a_companion_seed_is_refused(dev):
    c = copy.deepcopy(dev["cells"]["N2"]); c["companion_seed"] = 12345
    assert any("companion_seed must be null" in m for m in RV.cell_failures(c, dev["defn"]))


def test_selector_relationships_are_the_producers_own(dev):
    c = copy.deepcopy(dev["no_signal"]); so = c["block"]["selector_output"]; n = c["n_eval"]
    k = BS.selector_constants(n)
    assert so["K_N"] == k["K_N"] and so["m_max"] == k["m_max"] and so["autocov_lags_available"] == k["required_lags"]
    assert abs(so["band"] - 2.0 * math.sqrt(math.log10(n) / n)) < 1e-12
    assert so["M"] == max(1, 2 * so["m_hat"]) and so["max_lag_read"] == max(so["M"], so["m_hat"] + so["K_N"])
    if so["D_hat"] > 0:
        assert abs(so["b_opt"] - ((2 * so["G_hat"] ** 2 / so["D_hat"]) ** (1 / 3)) * n ** (1 / 3)) < 1e-9 * max(1, so["b_opt"])
    assert c["block"]["proposed"] == int(round(so["b_opt"]))
    # a coherent-looking but wrong G_hat breaks the b_opt relationship
    so["G_hat"] = so["G_hat"] * 2 if so["G_hat"] else 1.0
    assert any("b_opt" in m for m in RV.cell_failures(c, dev["defn"]))


def test_signal_detected_cell_with_p_raised_above_alpha_is_contradictory(dev):
    c = copy.deepcopy(dev["signal"]); c["p"] = 0.5
    assert any("contradicts" in m for m in RV.cell_failures(c, dev["defn"]))


def test_t_obs_versus_bootstrap_quantile_versus_p_relationship(dev):
    c = copy.deepcopy(dev["no_signal"])
    c["t_obs"] = c["t_star_q975"] + 1.0; c["secondary"]["hac_t"] = c["t_obs"]; c["mean_d"] = abs(c["mean_d"]) + 1e-6
    c["positive"] = True
    fails = RV.cell_failures(c, dev["defn"])
    assert any("t_star_q975" in m for m in fails), fails


@pytest.mark.parametrize("attack,reason", [
    (lambda c: c.__setitem__("companion_seed", c["companion_seed"] + 1), "companion_seed"),
    (lambda c: c.__setitem__("companion_seed", None), "companion_seed"),
    (lambda c: c.__setitem__("companion_seed", float(c["companion_seed"])), "not an int"),
    (lambda c: c.__setitem__("companion_seed", True), "not an int"),
    (lambda c: c.__setitem__("companion_seed", str(c["companion_seed"])), "not an int"),
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


# ---------------------------------------------------------------- §4 commitment V1 (preserved) and V1.1
@pytest.mark.parametrize("digest,commit,verify", [(RV.cell_digest, RV.court_commitment, RV.verify_commitment),
                                                   (RV.cell_digest_v11, RV.court_commitment_v11, RV.verify_commitment_v11)],
                         ids=["V1", "V1.1"])
def test_commitment_is_deterministic_and_order_independent(dev, digest, commit, verify):
    c = dev["no_signal"]
    shuffled = {k: c[k] for k in reversed(list(c))}
    assert digest(c) == digest(shuffled)
    cells = [dev["cells"][k] for k in F.CONTROLS]
    a = commit(cells); b = commit(list(reversed(cells)))
    assert a["root"] == b["root"] and a["entries"] == b["entries"] and a["cells"] == 6
    assert verify(cells, a["root"], trusted_entries=a["entries"])["verified"] is True


@pytest.mark.parametrize("digest", [RV.cell_digest, RV.cell_digest_v11], ids=["V1", "V1.1"])
def test_commitment_binds_every_adjudication_field_but_not_the_clock(dev, digest):
    c = copy.deepcopy(dev["no_signal"]); base = digest(c)
    c2 = copy.deepcopy(c); c2["utc"] = c["utc"] + 1000
    assert digest(c2) == base                                                  # instance identity is not content
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
        assert digest(c3) != base, k


def test_v1_and_v11_roots_differ_by_version_but_both_are_stable(dev):
    cells = [dev["cells"][k] for k in F.CONTROLS]
    assert RV.court_commitment(cells)["root"] != RV.court_commitment_v11(cells)["root"]
    assert RV.court_commitment(cells)["version"] == "RESULT_COMMITMENT_V1"
    assert RV.court_commitment_v11(cells)["version"] == "RESULT_COMMITMENT_V1.1"


def test_v1_serialisation_is_strict():
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


def test_v11_tagged_representation_is_unambiguous():
    tb = RV.tagged_canonical_bytes
    assert tb({"a": None}) == b'{"a":"n"}'
    assert tb({"a": True}) == b'{"a":"b:true"}' and tb({"a": 1}) == b'{"a":"i:1"}' and tb({"a": 1.0}) == b'{"a":"f:1.0"}'
    assert tb({"a": "inf"}) == b'{"a":"s:inf"}'                                           # a literal string is tagged s:
    assert tb({"secondary": {"non_overlap_z": float("inf")}}) == b'{"secondary":{"non_overlap_z":"inf:+"}}'
    assert tb({"secondary": {"non_overlap_z": float("-inf")}}) == b'{"secondary":{"non_overlap_z":"inf:-"}}'
    assert tb({"secondary": {"non_overlap_z": "inf"}}) != tb({"secondary": {"non_overlap_z": float("inf")}})
    assert tb({"b": 1, "a": [1, "x"]}) == tb({"a": [1, "x"], "b": 1})
    with pytest.raises(RV.CommitmentFailure, match="NaN"):
        tb({"secondary": {"non_overlap_z": float("nan")}})
    with pytest.raises(RV.CommitmentFailure, match="only admitted"):
        tb({"p": float("inf")})                                                          # inf outside the permitted paths
    with pytest.raises(RV.CommitmentFailure, match="only admitted"):
        tb({"secondary": {"hac_t": float("inf")}})
    with pytest.raises(RV.CommitmentFailure, match="non-string key"):
        tb({1: "x"})
    with pytest.raises(RV.CommitmentFailure, match="unserialisable"):
        tb({"x": object()})


def _inf_fixture(dev):
    c = copy.deepcopy(dev["no_signal"])
    c["secondary"]["non_overlap_z"] = float("inf"); c["secondary"]["non_overlap_verdict"] = "SIGNAL_DETECTED"
    c["secondary"]["legacy_iid_z"] = float("-inf")
    return c


def test_legitimate_infinity_diagnostic_validates_commits_and_verifies_under_v11(dev):
    """Astra V1.1 finding 3. The frozen producer emits +/-inf for a
    zero-variance non-overlap subset (and the legacy iid rule). V1 accepted
    it in validation but could not commit it; V1.1 does both."""
    c = _inf_fixture(dev)
    assert RV.cell_failures(c, dev["defn"]) == []                              # validator: legitimate
    with pytest.raises(RV.CommitmentFailure, match="non-finite"):
        RV.cell_digest(c)                                                       # V1 semantics preserved: refuses
    d = RV.cell_digest_v11(c)
    cells = [c] + [dev["cells"][k] for k in F.CONTROLS if k != c["control"]]
    com = RV.court_commitment_v11(cells)
    assert RV.verify_commitment_v11(cells, com["root"], trusted_entries=com["entries"])["verified"] is True
    flipped = copy.deepcopy(c); flipped["secondary"]["legacy_iid_z"] = float("inf")
    assert RV.cell_digest_v11(flipped) != d                                     # sign preserved
    as_str = copy.deepcopy(c); as_str["secondary"]["legacy_iid_z"] = "-inf"
    assert any("NaN or not a number" in m for m in RV.cell_failures(as_str, dev["defn"]))   # validator refuses the string
    assert RV.cell_digest_v11(as_str) != d                                      # and the commitment distinguishes it anyway
    cells_flipped = [flipped] + cells[1:]
    with pytest.raises(RV.CommitmentFailure, match="does not match its trusted digest"):
        RV.verify_commitment_v11(cells_flipped, com["root"], trusted_entries=com["entries"])


def test_infinity_in_a_finite_by_contract_field_is_refused_by_both_layers(dev):
    c = copy.deepcopy(dev["no_signal"]); c["secondary"]["hac_t"] = float("inf")
    assert any("hac_t" in m for m in RV.cell_failures(c, dev["defn"]))
    with pytest.raises(RV.CommitmentFailure, match="only admitted"):
        RV.cell_digest_v11(c)
    c2 = copy.deepcopy(dev["no_signal"]); c2["t_obs"] = float("-inf")
    assert any("t_obs" in m for m in RV.cell_failures(c2, dev["defn"]))
    with pytest.raises(RV.CommitmentFailure):
        RV.cell_digest_v11(c2)


@pytest.mark.parametrize("commit,verify", [(RV.court_commitment, RV.verify_commitment), (RV.court_commitment_v11, RV.verify_commitment_v11)],
                         ids=["V1", "V1.1"])
def test_coherent_alteration_passes_validation_but_fails_the_trusted_commitment(dev, commit, verify):
    """The reason a commitment exists: a change that keeps every decision
    relationship intact is invisible to consistency validation."""
    cells = [copy.deepcopy(dev["cells"][k]) for k in F.CONTROLS]
    trusted = commit(cells)                                                    # anchored when the results were produced
    victim = next(c for c in cells if c["verdict"] == "NO_SIGNAL" and c["p"] > 0.1)
    step = 1.0 / RV.P_LATTICE if victim["p"] < 1.0 else -1.0 / RV.P_LATTICE
    victim["p"] = victim["p"] + step                                           # still on lattice, still NO_SIGNAL
    assert RV.cell_failures(victim, dev["defn"]) == []                         # validator: nothing to see
    with pytest.raises(RV.CommitmentFailure, match="does not match its trusted digest"):
        verify(cells, trusted["root"], trusted_entries=trusted["entries"])
    with pytest.raises(RV.CommitmentFailure, match="root mismatch"):
        verify(cells, trusted["root"])
    victim["p"] = victim["p"] - step                                           # restored: verifies again
    assert verify(cells, trusted["root"], trusted_entries=trusted["entries"])["verified"] is True


@pytest.mark.parametrize("commit,verify", [(RV.court_commitment, RV.verify_commitment), (RV.court_commitment_v11, RV.verify_commitment_v11)],
                         ids=["V1", "V1.1"])
def test_commitment_refuses_to_trust_a_root_stored_next_to_the_payload(dev, commit, verify):
    cells = [dev["cells"][k] for k in F.CONTROLS]
    with pytest.raises(RV.CommitmentFailure, match="trusted root must be supplied"):
        verify(cells, None)
    with pytest.raises(RV.CommitmentFailure, match="trusted root must be supplied"):
        verify(cells, "")
    com = commit(cells)
    altered = [copy.deepcopy(c) for c in cells]; altered[0]["p"] = altered[0]["p"] + (1.0 / RV.P_LATTICE if altered[0]["p"] < 1 else -1.0 / RV.P_LATTICE)
    colocated = commit(altered)["root"]
    r = verify(altered, colocated)
    assert r["verified"] is True and "not that the root itself is authentic" in r["trust_boundary"]
    assert colocated != com["root"]


def test_commitment_refuses_duplicates_and_names_missing_trusted_entries(dev):
    cells = [dev["cells"][k] for k in F.CONTROLS]
    for commit, verify in ((RV.court_commitment, RV.verify_commitment), (RV.court_commitment_v11, RV.verify_commitment_v11)):
        with pytest.raises(RV.CommitmentFailure, match="duplicate"):
            commit(cells + [cells[0]])
        trusted = commit(cells[:5])
        with pytest.raises(RV.CommitmentFailure, match="no trusted entry"):
            verify(cells, trusted["root"], trusted_entries=trusted["entries"])
