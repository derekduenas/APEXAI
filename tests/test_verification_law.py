"""VERIFY THE ARTIFACT, NOT THE ECHO -- the law, enforced.

Each test below corresponds to a real failure that happened on
2026-08-23. They exist so those failures cannot recur silently.
"""
from __future__ import annotations

import json

import pytest

from apex.governance.verification import (
    StaleArtifact, VerificationFailed, code_digest, load_verified,
    provenance, stamp, verify_artifact_is_current, verify_source_contains)


# ---------------------------------------------- the echo failure
# `s.replace(old, new)` returns the ORIGINAL string when `old` is
# absent, so an edit script can print "installed" having changed
# nothing. This happened twice in one session.

def test_a_missing_edit_is_caught_not_believed():
    with pytest.raises(VerificationFailed) as e:
        verify_source_contains(
            "apex/governance/verification.py",
            "a_string_that_was_never_written_into_this_module_xyz")
    assert "did NOT land" in str(e.value)


def test_a_present_edit_verifies():
    out = verify_source_contains(
        "apex/governance/verification.py",
        "VERIFY THE ARTIFACT, NOT THE ECHO",
        "def verify_artifact_is_current")
    assert out["verdict"] == "SOURCE_CHANGE_PRESENT"
    assert out["checked"] == 2


def test_verifying_a_missing_file_fails_loudly():
    with pytest.raises(VerificationFailed):
        verify_source_contains("apex/does/not/exist.py", "anything")


# ---------------------------------------------- the stale artifact
# An audit read the PREVIOUS run's output while the real run was still
# writing, and reported a vacuous "0 failures".

def test_an_unstamped_artifact_is_refused():
    with pytest.raises(StaleArtifact) as e:
        verify_artifact_is_current({"summary": {"failures": 0}})
    assert "not evidence" in str(e.value)


def test_an_artifact_with_no_module_list_falls_back_to_the_commit():
    art = stamp({"result": "clean"})            # no code_paths given
    art["provenance"]["commit"] = "0" * 40
    art["provenance"]["commit_short"] = "0000000"
    with pytest.raises(StaleArtifact) as e:
        verify_artifact_is_current(art)
    assert "no module list was recorded" in str(e.value)


def test_an_unrelated_commit_does_not_invalidate_a_still_current_run():
    """A long job whose own modules are untouched is still current.
    Invalidating it because some other file was committed would make
    the law unusable and train us to ignore it."""
    paths = ["apex/governance/verification.py"]
    art = stamp({"result": "clean"}, paths)
    art["provenance"]["commit"] = "0" * 40      # unrelated commits since
    art["provenance"]["commit_short"] = "0000000"
    out = verify_artifact_is_current(art, code_paths=paths)
    assert out["verdict"] == "ARTIFACT_CURRENT"


def test_an_artifact_from_edited_code_is_refused():
    paths = ["apex/governance/verification.py"]
    art = stamp({"result": "clean"}, paths)
    art["provenance"]["code_digest"] = "deadbeef" * 8
    with pytest.raises(StaleArtifact) as e:
        verify_artifact_is_current(art, code_paths=paths)
    assert "differ from the modules on disk" in str(e.value)


def test_a_current_artifact_passes():
    paths = ["apex/governance/verification.py"]
    art = stamp({"result": "clean"}, paths)
    out = verify_artifact_is_current(art, code_paths=paths)
    assert out["verdict"] == "ARTIFACT_CURRENT"


def test_zero_failures_from_a_stale_artifact_is_never_reported(tmp_path):
    """The exact shape of the incident: a result file saying nothing is
    wrong, which is worthless because it describes a different run."""
    p = tmp_path / "replay.json"
    art = stamp({"summary": {"identity_failures": 0}})
    art["provenance"]["commit"] = "0" * 40
    p.write_text(json.dumps(art))
    with pytest.raises(StaleArtifact):
        load_verified(p)


def test_provenance_records_what_is_needed_to_attribute_a_run():
    prov = provenance(["apex/governance/verification.py"])
    for k in ("commit", "code_digest", "started_utc", "host", "argv",
              "working_tree_dirty"):
        assert k in prov
    assert prov["law"] == "VERIFY THE ARTIFACT, NOT THE ECHO"


def test_code_digest_is_sensitive_to_content_not_just_the_commit():
    """A commit sha cannot detect an uncommitted edit; the digest can."""
    a = code_digest(["apex/governance/verification.py"])
    b = code_digest(["apex/governance/verification.py",
                     "apex/governance/chain_ledger.py"])
    assert a != b
    assert a == code_digest(["apex/governance/verification.py"])


def test_a_missing_code_path_still_produces_a_stable_digest():
    d = code_digest(["apex/definitely/missing.py"])
    assert d == code_digest(["apex/definitely/missing.py"])
