"""Independent adversarial review of RESEARCH_ACTIVATION_V1's verifiers.

The wrapper was rewritten as V1 after the reviewer proved V0 DESCRIBED actions
rather than performing them. V1 performs. This module asks the next question:
does each stage's verify actually test the property the stage exists to
establish, or does it test something adjacent and cheaper?

Every test here asserts the CORRECT behaviour. A failure is a reproduction.
No test needs root, and none touches production paths.
"""
import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "research_activation", Path(__file__).resolve().parents[1] / "scripts" / "research_activation.py")
ra = importlib.util.module_from_spec(_spec)
sys.modules["research_activation"] = ra          # dataclasses resolve via sys.modules
_spec.loader.exec_module(ra)

ABSENT_ACCOUNT = "nosuchresearchuser_review"


def targets(tmp_path):
    return ra.Targets(research_user=ABSENT_ACCOUNT,
                      runner_root=tmp_path / "runner",
                      research_root=tmp_path / "research")


def build_runner_tree(t, *, venv_mode=0o755, root_mode=0o755):
    t.runner_root.mkdir(parents=True)
    t.venv.mkdir(parents=True)
    (t.venv / "bin").mkdir()
    (t.venv / "bin" / "python").write_text("#!/bin/sh\n")
    os.chmod(t.venv, venv_mode)
    os.chmod(t.runner_root, root_mode)


def test_harden_refuses_a_runner_root_the_research_account_could_own(tmp_path):
    """harden_runner exists to make the runner tree unmodifiable by the
    research account. It chowns to root. But verify only reads mode bits, and
    mode bits are not a defence against the OWNER -- an owner can chmod at
    will. Verifying permissions while ignoring ownership tests the weaker
    property."""
    t = targets(tmp_path)
    build_runner_tree(t)
    assert os.stat(t.runner_root).st_uid != 0, "test must run non-root to be meaningful"
    with pytest.raises(ra.ActivationRefused) as e:
        ra.stages(t)[9].verify(t, {})
    assert "OWN" in str(e.value).upper()


def test_harden_refuses_a_group_writable_file_inside_the_venv(tmp_path):
    """The action is `chmod -R go-w`, recursive. The check looked only at the
    two top directories, so verification was weaker than the action it
    verified: a writable file deep in the venv passed."""
    t = targets(tmp_path)
    build_runner_tree(t)
    os.chmod(t.venv / "bin" / "python", 0o775)          # group-writable interpreter
    with pytest.raises(ra.ActivationRefused):
        ra.stages(t)[9].verify(t, {})


def test_directory_verify_refuses_a_mode_it_did_not_ask_for(tmp_path):
    """s_mkdir requests 0755 and then reports whatever mode it finds as
    evidence, without comparing the two. A world-writable evidence directory
    would be recorded as created and verified."""
    t = targets(tmp_path)
    t.research_root.mkdir(parents=True)
    os.chmod(t.research_root, 0o777)
    with pytest.raises(ra.ActivationRefused):
        ra.stages(t)[0].verify(t, {})


def test_ownership_stage_refuses_when_the_account_does_not_exist(tmp_path):
    """v_own guards its only assertion behind `if account present`. With no
    account the stage passes having checked nothing -- the precise shape of
    the V0 defect the reviewer caught, surviving in one verifier."""
    t = targets(tmp_path)
    t.research_root.mkdir(parents=True)
    assert not ra.account_facts(t.research_user)["present"]
    with pytest.raises(ra.ActivationRefused):
        ra.stages(t)[3].verify(t, {})


def test_a_correct_tree_still_passes(tmp_path):
    """The repairs must not make the verifiers unsatisfiable. Ownership is
    checked against the account that should own the tree, so when no root-owned
    tree can be built non-root, the mode checks must still pass on their own."""
    t = targets(tmp_path)
    build_runner_tree(t)
    ev = ra.stages(t)[9].verify(t, {"expect_uid": os.getuid()})
    assert ev["runner_root_uid"] == os.getuid()


def test_production_targets_demand_root_and_full_uid_separation():
    """The strict setting must be the default. A harness opts out explicitly;
    production never has to opt in."""
    t = ra.production_targets()
    assert t.runner_owner_uid == 0
    assert t.uid_separation_exercisable is True


def test_evidence_records_whether_uid_separation_was_actually_checked(tmp_path):
    """An opt-out that leaves no trace is indistinguishable from a check that
    passed. The waiver has to travel in the evidence."""
    t = ra.Targets(research_user=ABSENT_ACCOUNT, runner_root=tmp_path / "runner",
                   research_root=tmp_path / "research", runner_owner_uid=os.getuid(),
                   uid_separation_exercisable=False)
    build_runner_tree(t)
    ev = ra.stages(t)[9].verify(t, {})
    assert ev["uid_separation_checked"] is False
    assert ev["runner_root_uid"] == os.getuid()


# ==================== the admission request is not an admission ===========
REQUEST = Path(__file__).resolve().parents[1] / "results" / "exp001b_admission_request.json"


def test_the_admission_request_is_complete_as_a_template():
    """The authority should have to judge, not to hunt for fields. Every field
    the boundary requires is present and filled from measurement."""
    import json
    from apex.world_model.real_data.boundary import REQUIRED_BODY
    doc = json.loads(REQUEST.read_text())
    for k, subs in REQUIRED_BODY.items():
        assert k in doc, k
        for sub in (subs or ()):
            assert sub in doc[k], "%s.%s" % (k, sub)
    assert doc["dataset"]["manifest_sha256"] == (
        "3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39")
    assert doc["purpose"]["experiment_id"] == "ALPHA-EXP-001B"
    assert doc["scope"]["temporal_range"]["end"] == "2021-12-31"


def test_the_admission_request_cannot_be_used_as_an_admission():
    """If this file were ever handed to the boundary it must be refused. The
    decision field is not ADMIT and the provenance names no authority, so the
    two checks that exist to stop self-admission both fire."""
    import json
    doc = json.loads(REQUEST.read_text())
    assert doc["decision"] != "ADMIT"
    assert doc["provenance"]["decided_utc"] is None
    assert doc["provenance"]["decided_by"].upper() not in ("CALLER", "ENGINEERING", "SELF", "")
    assert not (REQUEST.parent / (REQUEST.name + ".sig")).exists()


# ===================== the signing package is self-consistent =============
PKG = Path(__file__).resolve().parents[1] / "results" / "exp001b_signing_package.json"


def _pkg():
    import json
    return json.loads(PKG.read_text())


def test_the_prepared_checkout_matches_the_wrapper_under_review():
    """An auditor opening the checkout must not find an older tree than the one
    being reviewed."""
    p = _pkg()["identifiers"]
    assert p["prepared_checkout_commit"] == p["wrapper_commit"]
    assert p["bound_source_tree_sha256"] == (
        "616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545")
    assert p["registration_hash"] == (
        "b3930727334f24379f72df3919c98d689448b2f3f265b2fa6013559ee1bef5c9")
    assert p["dataset_manifest_sha256"] == (
        "3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39")
    assert p["admitted_sessions"] == 1511


def test_the_launch_uses_the_configuration_that_was_probed():
    assert _pkg()["launch"]["probe_used_identical_configuration"] is True


def test_the_signed_scope_permits_train_and_validation_only():
    sc = _pkg()["scope"]
    assert sc["evaluation_admitted"] is False
    assert sc["economics_permitted_in_this_run"] is False
    assert sc["validation_is_distributional_only"] is True
    assert sc["train"][0] == "2016-01-04" and sc["validation"][1] == "2021-12-31"


def test_no_private_signing_key_belongs_on_the_research_host():
    a = _pkg()["authority"]
    assert a["private_key_on_research_host"] is False
    assert a["signature_namespace"] == "apex-admission"
    assert "OFF-HOST" in a["boundary"]


def test_the_package_does_not_overstate_what_has_happened():
    st = _pkg()["state"]
    assert st["admission_issued"] is False and st["experiment_run"] is False
    assert st["alpha_claimed"] is False and st["independently_reviewed"] is False


def test_the_evaluation_read_incident_stays_disclosed():
    """The evaluation set is no longer untouched. That must not quietly revert
    to a cleaner-sounding claim in a later edit."""
    import json
    st = _pkg()["state"]
    assert st["evaluation_set_untouched"] is False
    assert "EVALUATION_READ_INCIDENT_001" in st["disclosed_incidents"]
    inc = json.loads((Path(__file__).resolve().parents[1] / "results" /
                      "evaluation_read_incident_001.json").read_text())
    assert inc["bytes_exposed"] == 60
    assert inc["exposed_content_classification"]["prices"] is False
    assert inc["exposed_content_classification"]["any_timestamp_value"] is False
    assert inc["disposition"]["holdout_replaced"] is False
    assert inc["disposition"]["registration_amended"] is False
    assert inc["influence_on_research_decisions"]["model_fit"] is False


def test_bound_tree_equality_is_not_claimed_to_protect_the_wrapper():
    """The narrowed claim: the wrapper is outside the bound surface, so launch
    invariance was measured rather than inferred from the hash."""
    r = _pkg()["repin"]
    assert r["wrapper_in_bound_surface"] is False
    assert r["launch_argv_identical_measured"] is True
    assert r["probe_properties_changed"] is True
    assert r["wrapper_sha256_at_pinned_commit"] == r["wrapper_sha256_at_branch_head"]


def test_evaluation_exclusion_is_scoped_to_the_sandboxed_process():
    """The measured truth, not the comfortable one."""
    e = _pkg()["evaluation_exclusion"]
    assert e["holds_for"].startswith("the process")
    assert e["does_not_hold_for"] == "the research account generally"
    assert e["measured_outside_sandbox"]["evaluation_file_readable"] is True


def test_the_request_pins_the_commit_that_is_actually_prepared():
    """The request and the prepared checkout must not drift apart: a decision
    pinning a commit other than the one in the checkout would be refused at
    launch, after signing, which is the worst moment to discover it."""
    import json
    req = json.loads((Path(__file__).resolve().parents[1] /
                      "results" / "exp001b_admission_request.json").read_text())
    assert req["code"]["commit"] == _pkg()["identifiers"]["prepared_checkout_commit"]
    assert req["code"]["source_tree_sha256"] == _pkg()["identifiers"]["bound_source_tree_sha256"]
