"""WM-0E-R7/R7.1 structural proofs: seed derivation, collision audit,
definition sealing, exactly-once primitives, two-world integrity, frozen
engine/surface, judge rules. Uses the DEVELOPMENT qualification namespace
for shape tests; acceptance-namespace tests run only once it is minted
(inspection for provenance/collision only -- never execution)."""
import json

import pytest

from apex.world_model import bootstrap as BS, controls_r3 as R3, controls_r4 as R4, controls_r51 as R51
from apex.world_model.budget import wm0e_r51_truth
from courts import final_court as F
from regression import runner as RR

FROZEN_ENGINE = "af3ae117a69ee485bf8ac2fa86c7b962db7f21ab639507dffb6389ed0a2f35ac"
FROZEN_SURFACE = "f6b87f2947e2bf62403a04dcaeda0805bc62e8ca1cfebacdc7b14ef10856439d"
DEV_NS = F.QUALIFICATION_NAMESPACE
minted = pytest.mark.skipif(F.NAMESPACE is None, reason="acceptance namespace not minted yet")


def test_engine_and_surface_frozen():
    assert BS.content_identity() == FROZEN_ENGINE
    assert RR.scientific_surface_hash(".")["hash"] == FROZEN_SURFACE


def test_seed_derivation_deterministic_role_labelled(ns=DEV_NS):
    man = F.seed_manifest(ns)
    assert man["indices"] == 50 and len(man["cells"]) == 300 and man["manifest_hash"] == F.seed_manifest(ns)["manifest_hash"]
    a = F.derive_seed("N1", "world", 3, ns); assert a == F.derive_seed("N1", "world", 3, ns) != F.derive_seed("N1", "world", 4, ns)
    assert F.derive_seed("N0", "feature_world", 0, ns) != F.derive_seed("N3", "target_world", 0, ns)
    n0 = [c for c in man["cells"] if c["control"] == "N0"]; n3 = [c for c in man["cells"] if c["control"] == "N3"]
    assert all(c["companion_seed"] == R51.target_seed(c["primary_seed"]) != c["primary_seed"] for c in n0)
    assert all(c["companion_seed"] == R3.shadow_seed(c["primary_seed"]) != c["primary_seed"] for c in n3)
    assert len({c["primary_seed"] for c in man["cells"]}) == 300
    assert F.seed_manifest(DEV_NS)["manifest_hash"] != F.seed_manifest(F.BURNED_R7_NAMESPACE)["manifest_hash"]


def test_prior_universe_includes_burned_r7_and_qualification_seeds():
    u = F.prior_seed_universe()
    for k in ("V0_dev_25", "V2_1_consumed_50", "R3_N3_dev_100", "R3_N3_dev_shadow_100", "R3_P0_dev_50", "R4_P0_dev_50",
              "R5_dev_100", "R5_N3V1_shadow_100", "R51_dev_100", "R51_N0V1_target_100", "calibration_fixture_prng",
              "R7_consumed_primary_and_companion_400", "R7_partially_executed_N0_index0_pair", "R7_1_runner_qualification_dev"):
        assert k in u, k
    assert len(u["R7_consumed_primary_and_companion_400"]) == 400 and len(u["R7_partially_executed_N0_index0_pair"]) == 2
    assert set(u["R7_partially_executed_N0_index0_pair"]) <= set(u["R7_consumed_primary_and_companion_400"])
    fake = {"cells": [{"control": "N2", "index": 0, "primary_seed": u["R7_consumed_primary_and_companion_400"][0]}]}
    assert F.collision_audit(fake)["count"] >= 1                     # the burned set is now caught


@minted
def test_minted_acceptance_namespace_is_new_and_collision_free():
    assert F.NAMESPACE not in F.CONSUMED_NAMESPACES and F.NAMESPACE != DEV_NS
    aud = F.collision_audit(F.seed_manifest())
    assert aud["count"] == 0, aud["collisions"]


def test_definition_is_pure_and_commits_to_everything():
    kw = dict(namespace=DEV_NS, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    d1 = F.define("TESTCOMMIT", 0.0, FROZEN_SURFACE, **kw); d2 = F.define("TESTCOMMIT", 0.0, FROZEN_SURFACE, **kw)
    assert d1.court_hash == d2.court_hash and d1.court_id == d2.court_id
    assert F.define("OTHER", 0.0, FROZEN_SURFACE, **kw).court_hash != d1.court_hash
    c = d1.canonical()
    assert c["court_version"] == "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1" and c["authority"] == "SYNTHETIC_RESEARCH_ONLY"
    assert c["runner"]["version"] == "FINAL_COURT_RUNNER_V0.1" and len(c["runner"]["source_sha256"]) == 64
    assert c["inference"]["contract_hash"] == FROZEN_ENGINE and c["inference"]["B"] == 1999 and c["inference"]["alpha"] == 0.025
    assert c["M0"]["config_hash"].startswith("b6aec556e20cf6617cf7797cb0ef0d84")
    assert c["cells_expected"] == 300 and c["rescue_logic"] == "NONE" and c["development_inside_court"] == "NONE"
    assert tuple(c["geometry"]["expected_usable_and_train"]["N1"]) == (1860, 501) and tuple(c["geometry"]["expected_usable_and_train"]["P0"]) == (1860, 701)
    assert "ONE two-independent-world" in c["acceptance"]["family"]
    assert len(c["control_source_sha256"]) == 5 and c["control_contracts"]["P0"]["mu_multiplier"] == 1.0
    assert c["research_budget_snapshot_hash"] == F.r7_budget_snapshot()["snapshot_hash"]
    assert list(c["seeds"]["consumed_namespaces_never_reused"]) == list(F.CONSUMED_NAMESPACES)


def test_budget_snapshot_carries_the_whole_history_without_touching_the_surface():
    d = F.r7_budget_snapshot(); c = d["ledger"]["counts"]
    assert d["ledger_hash"] == wm0e_r51_truth().budget_hash
    assert c["court_sitting"] == 3 and c["inference_rule_revision"] == 3 and c["implementation_repair"] == 1
    assert c["null_control_design"] == 3 and c["positive_control_power_level"] == 5 and c["positive_control_evaluation_length"] == 4
    h = d["additional_history"]
    assert len(h["regression_infrastructure"]) == 4 and len(h["failed_court_sittings"]) == 4 and h["one_model_one_test"] is False


def test_write_once_refuses_overwrite(tmp_path):
    p = str(tmp_path / "c.json"); F._write_once(p, {"a": 1})
    with pytest.raises(FileExistsError):
        F._write_once(p, {"a": 2})
    assert json.load(open(p)) == {"a": 1}


def test_run_cell_refuses_unexpected_control_or_index(tmp_path):
    d = F.define("TESTCOMMIT", 0.0, FROZEN_SURFACE, namespace=DEV_NS, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    with pytest.raises(F.CourtIntegrityFailure):
        F.run_cell(d, "N9", 0, str(tmp_path))
    with pytest.raises(F.CourtIntegrityFailure):
        F.run_cell(d, "N2", 50, str(tmp_path))


def test_cell_id_binds_worlds_and_index():
    a = F.cell_id("C", "N0", 1, {"feature_world": "x", "target_world": "y"})
    assert a == F.cell_id("C", "N0", 1, {"feature_world": "x", "target_world": "y"})
    assert a != F.cell_id("C", "N0", 2, {"feature_world": "x", "target_world": "y"})
    assert a != F.cell_id("C", "N0", 1, {"feature_world": "x", "target_world": "z"})


def test_two_world_integrity_on_development_seeds_without_running_models():
    man = F.seed_manifest(DEV_NS)
    for c in man["cells"][:0] + [c for c in man["cells"] if c["control"] in ("N0", "N3") and c["index"] < 5]:
        a = R4.r4_world(c["primary_seed"])
        b = R51.target_world(a) if c["control"] == "N0" else R3.shadow_world(a)
        assert b.world_hash != a.world_hash and b.config.seed == c["companion_seed"] != c["primary_seed"]
        assert b.config.params == a.config.params and b.config.n_steps == a.config.n_steps == 2595


def test_judge_rules_per_control_and_never_pools():
    def cell(ctl, i, det, pos=True):
        return {"control": ctl, "index": i, "verdict": "SIGNAL_DETECTED" if det else "NO_SIGNAL", "p": 0.01 if det else 0.5,
                "t_obs": 3.0 if det else -1.0, "block_length": 30, "t_star_q975": 3.0, "acf1_d": 0.8, "positive": pos,
                "n_eval": 1860, "n_train": 501 if ctl == "N1" else 701,
                "secondary": {"hac_verdict": "NO_SIGNAL", "non_overlap_verdict": "NO_SIGNAL"}}
    cells = []
    for ctl in ("N0", "N1", "N2", "N3", "N4"):
        k = 6 if ctl == "N3" else 0
        cells += [cell(ctl, i, i < k) for i in range(50)]
    cells += [cell("P0", i, i < 46, pos=i < 48) for i in range(50)]
    j = F.judge(cells)
    assert j["controls"]["N3"]["verdict"] == "FAIL" and j["controls"]["N0"]["verdict"] == "PASS"
    assert j["controls"]["P0"]["verdict"] == "PASS" and j["all_pass"] is False
    assert "DESCRIPTIVE ONLY" in j["cross_control"]["pooled_negative_detections"]
    cells2 = [c for c in cells if c["control"] != "P0"] + [cell("P0", i, i < 39) for i in range(50)]
    assert F.judge(cells2)["controls"]["P0"]["verdict"] == "FAIL"
