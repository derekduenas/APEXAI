"""The unlock-token check: does it read the place tokens actually live?

WHY THIS FILE EXISTS
--------------------
The dry-run certification reported

    [PASS] no validation unlock token exists

while `results/_unlocks/validation.unlock` was sitting on disk holding an
APEX-001 authorisation. The check resolved `REPO/validation.unlock` -- a path
nothing ever writes -- so it could not fail. It was a vacuous pass in the
governance section of a report used as evidence that a credit was safe to spend.

The enforcement gate (`require_unlocked`) was never wrong; it always read the
correct path and would have refused APEX-002 against an APEX-001 token. Only
the REPORT was wrong, which is worse in one specific way: the gate fails loudly
when it matters, and a false report is believed in advance.

Every test here drives `apex.registration.unlock_token_path` -- the same
function the gate resolves through. A counterexample against a locally
recomputed path would prove only that the local copy works, which is the
mistake being corrected.
"""

from __future__ import annotations

import pytest

from apex.config import load_config
from apex.registration import (
    RegistrationError,
    require_unlocked,
    unlock_token_path,
    unlock_token_status,
)

CFG = load_config("experiment", "costs", "synthetic", "sharadar")


def test_the_token_path_is_where_tokens_are_actually_written():
    path = unlock_token_path("validation", repo_root=None)

    assert path.parent.name == "_unlocks"
    assert path.parent.parent.name == "results"
    assert path.name == "validation.unlock"


def test_counterexample_the_repo_root_path_is_the_one_that_never_exists(tmp_path):
    """The exact defect, pinned so it cannot return.

    A token written to the TRUE path must be invisible to the wrong path and
    visible to the right one. If both agreed, the original bug would be
    undetectable.
    """
    (tmp_path / "results" / "_unlocks").mkdir(parents=True)
    (tmp_path / "results" / "_unlocks" / "validation.unlock").write_text(
        "2026-08-12 APEX-002 validation authorized\n"
    )

    wrong = tmp_path / "validation.unlock"          # what the report checked
    right = unlock_token_path("validation", tmp_path)  # what the gate checks

    assert not wrong.exists(), "the wrong path found a token; test is inert"
    assert right.exists(), "the canonical path did not find a real token"


def test_the_status_reports_absent_when_no_token_exists(tmp_path):
    status = unlock_token_status("validation", tmp_path)

    assert status["present"] is False
    assert status["authorises"] is None


def test_counterexample_the_status_reports_present_when_a_token_exists(tmp_path):
    """Prove the check can report PRESENT.

    A check that only ever returns 'absent' is the vacuous pass again, wearing
    a corrected path.
    """
    (tmp_path / "results" / "_unlocks").mkdir(parents=True)
    unlock_token_path("validation", tmp_path).write_text(
        "2026-08-12 APEX-002 validation authorized\n"
    )

    status = unlock_token_status("validation", tmp_path)

    assert status["present"] is True
    assert "APEX-002" in status["authorises"]


def test_the_status_never_creates_the_token(tmp_path):
    """Reading governance state must not change it."""
    unlock_token_status("validation", tmp_path)

    assert not unlock_token_path("validation", tmp_path).exists()
    assert not (tmp_path / "results").exists()


# --- the gate itself, which was always correct ------------------------------

class _Source:
    name = "stub"
    requires_signed_registration = False
    dataset_fingerprint = "a" * 64          # confirmatory-looking, not dev-

    def load(self):
        raise AssertionError("must not load data for a refused period")


def test_a_locked_period_without_a_token_is_refused(tmp_path):
    with pytest.raises(RegistrationError, match="LOCKED"):
        require_unlocked(CFG, "validation", _Source.dataset_fingerprint, tmp_path)


def test_counterexample_a_stale_token_naming_another_experiment_is_refused(tmp_path):
    """The live situation on 2026-08-12.

    APEX-001's token survived the run that spent it. A per-experiment binding
    is the only thing stopping it from opening validation for APEX-002.
    """
    (tmp_path / "results" / "_unlocks").mkdir(parents=True)
    unlock_token_path("validation", tmp_path).write_text(
        "2026-08-11 APEX-001 validation authorized\n"
    )

    live = CFG.get("experiment.id")   # tracks the registered experiment
    with pytest.raises(RegistrationError,
                       match=f"does not authorise '{live}'"):
        require_unlocked(CFG, "validation", _Source.dataset_fingerprint, tmp_path)


def test_an_unlocked_period_needs_no_token(tmp_path):
    """in-sample is free and must not be gated."""
    require_unlocked(CFG, "in_sample", "dev-anything", tmp_path)


# --- the REPORT's predicate, not just the status it reads -------------------

def authorises_experiment(status: dict, experiment: str) -> bool:
    """The predicate the dry-run report evaluates.

    Extracted so it can be driven with a counterexample. Inline in the script
    it was untestable, which is how the vacuous version survived.
    """
    return bool(status["present"] and experiment in (status["authorises"] or ""))


def _write(tmp_path, text: str):
    (tmp_path / "results" / "_unlocks").mkdir(parents=True, exist_ok=True)
    unlock_token_path("validation", tmp_path).write_text(text)
    return unlock_token_status("validation", tmp_path)


def test_the_report_check_passes_when_no_token_exists(tmp_path):
    assert not authorises_experiment(
        unlock_token_status("validation", tmp_path), "APEX-002"
    )


def test_the_report_check_passes_on_a_token_naming_another_experiment(tmp_path):
    status = _write(tmp_path, "2026-08-11 APEX-001 validation authorized\n")

    assert status["present"] is True
    assert not authorises_experiment(status, "APEX-002"), (
        "an APEX-001 token must not count as authorisation for APEX-002"
    )


def test_counterexample_the_report_check_FAILS_on_a_token_naming_this_experiment(tmp_path):
    """The demonstration the original check could never make.

    With the old `REPO/validation.unlock` path this returned False no matter
    what was on disk. It must now return True.
    """
    status = _write(tmp_path, "2026-08-12 APEX-002 validation authorized\n")

    assert authorises_experiment(status, "APEX-002"), (
        "a token explicitly naming APEX-002 was not detected; the corrected "
        "check is still vacuous"
    )
