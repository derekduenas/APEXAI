"""WM-0E-R6 §14: the regression runner's refusals, proven on miniature
synthetic inventories (pure functions) and one uncontained miniature
end-to-end run in a temporary directory. Never touches the real suite."""
import json
import os
import subprocess
import sys
import textwrap

import pytest

from regression import runner as R


def _master(nodeids):
    return {"nodeids": list(nodeids), "collected": [{"nodeid": n, "file": n.split("::")[0]} for n in nodeids],
            "inventory_hash": R.canon_hash(list(nodeids)), "collected_count": len(nodeids)}


def _rec(shard, observed, outcomes=None, rc=0, oom=0, reported=True, collect_errors=None):
    results = {n: {"file": shard["module"], "outcome": (outcomes or {}).get(n, "PASS"), "detail": None} for n in observed}
    for n, r in results.items():
        if r["outcome"] == "SKIP":
            r["detail"] = "reason-%s" % n
    rec = {"index": shard["index"], "module": shard["module"], "expected_hash": shard["expected_hash"], "returncode": rc,
           "elapsed_s": 0.1, "oom_delta": oom, "fresh_process": True, "reported": reported,
           "observed": sorted(observed), "observed_hash": R.canon_hash(sorted(observed)), "results": results,
           "totals": {}, "collect_errors": collect_errors or [], "resource": None}
    return R.judge_shard(shard, rec)


M = _master(["tests/a.py::t1", "tests/a.py::t2", "tests/b.py::t3"])
S = R.shards_from_master(M)


def test_shard_plan_one_module_per_shard_sorted():
    assert [s["module"] for s in S] == ["tests/a.py", "tests/b.py"]
    assert S[0]["expected"] == ["tests/a.py::t1", "tests/a.py::t2"] and S[1]["expected"] == ["tests/b.py::t3"]


def test_clean_run_reconciles_and_aggregates_pass_skip_xfail():
    recs = [_rec(S[0], S[0]["expected"], {"tests/a.py::t2": "SKIP"}), _rec(S[1], S[1]["expected"], {"tests/b.py::t3": "XFAIL"})]
    rec = R.reconcile(M, S, recs)
    assert rec["ok"] and rec["totals"] == {"PASS": 1, "FAIL": 0, "ERROR": 0, "SKIP": 1, "XFAIL": 1, "XPASS": 0, "UNREPORTED": 0}
    assert rec["skip_manifest"]["skips"] == {"tests/a.py::t2": "reason-tests/a.py::t2"}
    assert rec["executed_inventory_hash"] == M["inventory_hash"]


def test_refuses_missing_nodeid():
    recs = [_rec(S[0], ["tests/a.py::t1"]), _rec(S[1], S[1]["expected"])]
    assert not recs[0]["ok"] and any("SHARD_COLLECTION_MISMATCH" in p for p in recs[0]["problems"])
    rec = R.reconcile(M, S, recs); assert not rec["ok"] and rec["missing"] == ["tests/a.py::t2"]


def test_refuses_unexpected_nodeid():
    recs = [_rec(S[0], S[0]["expected"] + ["tests/a.py::t9"]), _rec(S[1], S[1]["expected"])]
    assert not recs[0]["ok"]; rec = R.reconcile(M, S, recs); assert rec["unexpected"] == ["tests/a.py::t9"] and not rec["ok"]


def test_refuses_duplicate_execution():
    recs = [_rec(S[0], S[0]["expected"]), _rec(S[1], S[1]["expected"] + ["tests/a.py::t1"])]
    rec = R.reconcile(M, S, recs); assert rec["duplicates"] == ["tests/a.py::t1"] and not rec["ok"]


def test_refuses_process_failure_and_unreported():
    r = _rec(S[1], [], rc=1, reported=False)
    assert "UNREPORTED_RESULT" in r["problems"] and not r["ok"]
    rec = R.reconcile(M, S, [_rec(S[0], S[0]["expected"]), r]); assert rec["unaccounted"] == ["tests/b.py::t3"] and not rec["ok"]


def test_refuses_collection_error_and_oom():
    assert "COLLECTION_ERROR" in _rec(S[1], S[1]["expected"], collect_errors=[{"nodeid": "x", "longrepr": "boom"}])["problems"]
    assert "SHARD_RESOURCE_FAILURE" in _rec(S[1], S[1]["expected"], oom=1)["problems"]


def test_refuses_fail_error_xpass_and_never_reduces_skip_to_pass():
    for bad in ("FAIL", "ERROR", "XPASS", "UNREPORTED"):
        r = _rec(S[1], S[1]["expected"], {"tests/b.py::t3": bad}); assert not r["ok"], bad
    r = _rec(S[1], S[1]["expected"], {"tests/b.py::t3": "SKIP"}); assert r["ok"]
    rec = R.reconcile(M, S, [_rec(S[0], S[0]["expected"]), r]); assert rec["totals"]["SKIP"] == 1 and rec["totals"]["PASS"] == 2


def test_new_unexplained_skip_fails_against_prior_manifest():
    recs = [_rec(S[0], S[0]["expected"], {"tests/a.py::t2": "SKIP"}), _rec(S[1], S[1]["expected"])]
    prior = {"skips": {"tests/a.py::t2": "reason-tests/a.py::t2"}}
    assert R.reconcile(M, S, recs, prior)["ok"]
    prior2 = {"skips": {}}
    rec = R.reconcile(M, S, recs, prior2); assert rec["new_unexplained_skips"] == 1 and not rec["ok"]
    prior3 = {"skips": {"tests/a.py::t2": "other reason"}}
    rec = R.reconcile(M, S, recs, prior3); assert rec["skip_comparison"]["reason_drift"] == ["tests/a.py::t2"] and rec["ok"]


def test_scientific_surface_hash_changes_with_surface(tmp_path):
    (tmp_path / "apex" / "world_model").mkdir(parents=True)
    (tmp_path / "apex" / "world_model" / "m.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir(); (tmp_path / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    h1 = R.scientific_surface_hash(str(tmp_path))["hash"]
    (tmp_path / "tests" / "test_x.py").write_text("def test_x(): assert True\n")
    assert R.scientific_surface_hash(str(tmp_path))["hash"] == h1            # tests excluded
    (tmp_path / "apex" / "world_model" / "m.py").write_text("x = 2\n")
    assert R.scientific_surface_hash(str(tmp_path))["hash"] != h1            # surface included


def test_plugin_classifies_teardown_error_as_error():
    from regression import plugin as P
    assert P._classify({"setup": {"outcome": "passed"}, "call": {"outcome": "passed"}, "teardown": {"outcome": "failed", "longrepr": "x"}})[0] == "ERROR"
    assert P._classify({"setup": {"outcome": "passed"}, "call": {"outcome": "skipped", "reason": "r"}, "teardown": {"outcome": "passed"}}) == ("SKIP", "r")
    assert P._classify({"setup": {"outcome": "passed"}, "call": {"outcome": "skipped", "wasxfail": True, "reason": "r"}, "teardown": {"outcome": "passed"}})[0] == "XFAIL"
    assert P._classify({"setup": {"outcome": "passed"}, "call": {"outcome": "passed", "wasxfail": True}, "teardown": {"outcome": "passed"}})[0] == "XPASS"
    assert P._classify({})[0] == "UNREPORTED"


def test_miniature_end_to_end_uncontained(tmp_path):
    """Two tiny modules in a temp dir: collect, shard, run fresh processes,
    reconcile. Uncontained on purpose (self-test of logic, not of the slice)."""
    root = tmp_path; (root / "tests").mkdir()
    (root / "tests" / "test_one.py").write_text(textwrap.dedent('''
        import pytest
        def test_p(): assert 1 == 1
        @pytest.mark.skip(reason="mini skip")
        def test_s(): pass
        @pytest.mark.xfail(reason="mini xfail")
        def test_x(): assert False
    '''))
    (root / "tests" / "test_two.py").write_text("def test_q(): assert 2 == 2\n")
    (root / "regression").mkdir()
    for f in ("__init__.py", "plugin.py", "runner.py"):
        (root / "regression" / f).write_bytes(open(os.path.join(os.path.dirname(R.__file__), f), "rb").read())
    env = dict(os.environ, PYTHONPATH=str(root))
    out = root / "out"; out.mkdir()
    old = os.environ.copy()
    os.environ.update(env)
    try:
        master = R.collect_master([], str(out / "master.json"), scope="tests", cwd=str(root))
        assert master["ok"] and master["collected_count"] == 4
        shards = R.shards_from_master(master); assert len(shards) == 2
        recs = [R.run_shard(s, [], str(out), cwd=str(root)) for s in shards]
        rec = R.reconcile(master, shards, recs)
        assert rec["ok"], rec
        assert rec["totals"] == {"PASS": 2, "FAIL": 0, "ERROR": 0, "SKIP": 1, "XFAIL": 1, "XPASS": 0, "UNREPORTED": 0}
        assert rec["skip_manifest"]["skips"] == {"tests/test_one.py::test_s": "mini skip"}
    finally:
        os.environ.clear(); os.environ.update(old)
