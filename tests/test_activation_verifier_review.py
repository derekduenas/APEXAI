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
