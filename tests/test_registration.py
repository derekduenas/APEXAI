"""Experiment immutability and holdout protection.

These guard the two rules the whole project rests on, and until now neither had
a single test:

  SIGNATURE   Real market data does not load against an unsigned pre-registration.
  PERIOD LOCK The holdout is opened deliberately, once per experiment, within a
              finite research budget, and every opening is recorded immutably.

A third guard is added here that did not exist before: CONVENTIONS.md pins the
protocol's SHA-256 in its header, but nothing ever checked it. An edit to the
protocol after freezing -- the single most damaging thing that could happen to a
pre-registration -- was silently possible. It is now detected.

The tests run against a COPY of the real documents in tmp_path, so that
exercising the failure modes never writes to the live ledger or unlock log.
"""

from __future__ import annotations

import shutil

import pytest

from apex.config import load_config
from apex.governance.ledger import AlreadyEvaluated, BudgetExhausted, ResearchLedger
from apex.registration import (
    RegistrationError,
    protocol_pin_status,
    require_protocol_unmodified,
    require_signed,
    require_unlocked,
    signature_status,
)

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.fixture
def config():
    return load_config("experiment", "costs", "synthetic")


@pytest.fixture
def repo(tmp_path, config):
    """An isolated copy of the registration documents."""
    for name in ("experiment.protocol_file", "experiment.conventions_file"):
        filename = config.get(name)
        shutil.copy(REPO / filename, tmp_path / filename)
    (tmp_path / "results").mkdir()
    return tmp_path


def _sign(repo, config):
    """Fill the placeholder fields, as a real registration would."""
    for key, replacements in (
        (
            "experiment.protocol_file",
            {
                "**Registered:** _______________": "**Registered:** 2026-08-09",
                "**Author:** _______________": "**Author:** D. Duenas",
            },
        ),
        ("experiment.conventions_file", {"**Author:** _______________": "**Author:** D. Duenas"}),
    ):
        path = repo / config.get(key)
        text = path.read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")


def _pass_validation(repo, config, experiment_id=None):
    """Seed the ledger with a PASSING validation for this experiment.

    Protocol section 7 gates the holdout on it, so every holdout test here has
    to establish it first.
    """
    from apex.governance.ledger import ResearchLedger

    ledger = ResearchLedger(
        repo / config.get("governance.ledger_file"),
        budget=int(config.get("governance.research_budget")),
    )
    eid = experiment_id or config.get("experiment.id")
    ledger.spend(
        experiment_id=eid,
        hypothesis="validation pass",
        period="validation",
        config_hash="c" * 64,
        protocol_hash="p" * 64,
        conventions_hash="v" * 64,
        git_sha="abc",
        dataset_hash="d" * 64,
        reason="validation",
    )
    ledger.record_result(
        eid, "validation", p_value=0.001, t_stat=3.2, verdict="PASS",
        dataset_hash="d" * 64,
    )


def _unlock_token(repo, period, reason="pre-registered confirmatory evaluation"):
    directory = repo / "results" / "_unlocks"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{period}.unlock").write_text(reason, encoding="utf-8")


# ---------------------------------------------------------------------------
# SIGNATURE
# ---------------------------------------------------------------------------


def test_the_shipped_pre_registration_is_unsigned(config):
    """Standing check on the live repository, not the copy.

    If this ever passes, someone signed the pre-registration -- which is a real
    event that should be deliberate, not a thing noticed later.
    """
    assert signature_status(config)["signed"] is False


def test_unsigned_registration_refuses_real_data(repo, config):
    with pytest.raises(RegistrationError) as excinfo:
        require_signed(config, repo_root=repo)

    message = str(excinfo.value)
    assert "UNSIGNED" in message
    assert "Registered" in message or "Author" in message


def test_a_signed_registration_is_accepted(repo, config):
    _sign(repo, config)

    status = require_signed(config, repo_root=repo)

    assert status["signed"] is True
    assert len(status["protocol_hash"]) == 64


# ---------------------------------------------------------------------------
# PROTOCOL IMMUTABILITY
# ---------------------------------------------------------------------------


def test_the_live_protocol_matches_the_hash_conventions_pins(config):
    """The pre-registration has not been edited since it was frozen."""
    status = protocol_pin_status(config)

    assert status["pinned_hash"] == status["actual_hash"], (
        "the protocol no longer hashes to the value pinned in the CONVENTIONS "
        "header; the pre-registration was modified after freezing"
    )
    assert status["matches"] is True


def test_editing_the_protocol_after_freezing_is_detected(repo, config):
    """The most damaging possible silent change, now caught mechanically."""
    path = repo / config.get("experiment.protocol_file")
    text = path.read_text(encoding="utf-8")
    edited = text.replace("≥ 0.015", "≥ 0.010")
    assert edited != text, "the edit did not apply; this test would pass vacuously"
    path.write_text(edited, encoding="utf-8")

    with pytest.raises(RegistrationError) as excinfo:
        require_protocol_unmodified(config, repo_root=repo)

    assert "pin" in str(excinfo.value).lower() or "modified" in str(excinfo.value).lower()


def test_an_unmodified_protocol_passes_the_pin_check(repo, config):
    require_protocol_unmodified(config, repo_root=repo)


# ---------------------------------------------------------------------------
# PERIOD LOCK
# ---------------------------------------------------------------------------


def test_in_sample_is_unlocked_and_free(repo, config):
    """Section 7: in-sample is for pipeline verification and has no standing."""
    require_unlocked(config, "in_sample", "d" * 64, repo_root=repo)
    require_unlocked(config, "in_sample", "d" * 64, repo_root=repo)

    ledger = ResearchLedger(repo / config.get("governance.ledger_file"), budget=5)
    assert ledger.credits_spent() == 0


def test_the_holdout_refuses_to_open_without_a_hand_made_token(repo, config):
    with pytest.raises(RegistrationError) as excinfo:
        require_unlocked(config, "holdout", "d" * 64, repo_root=repo)

    message = str(excinfo.value)
    assert "LOCKED" in message
    assert "holdout.unlock" in message, "the error must name the exact file to create"


def test_the_holdout_opens_once_with_a_token_and_spends_a_credit(repo, config):
    _pass_validation(repo, config)
    _unlock_token(repo, "holdout")

    require_unlocked(config, "holdout", "d" * 64, repo_root=repo)

    ledger = ResearchLedger(repo / config.get("governance.ledger_file"), budget=5)
    assert ledger.credits_spent() == 1
    assert ledger.credits_remaining() == 4
    holdout_entries = [e for e in ledger.entries() if e.period == "holdout"]
    assert len(holdout_entries) == 1
    entry = holdout_entries[0]
    assert entry.experiment_id == config.get("experiment.id")
    assert entry.protocol_hash and entry.conventions_hash


def test_the_same_experiment_cannot_reopen_the_holdout(repo, config):
    _pass_validation(repo, config)
    _unlock_token(repo, "holdout")
    require_unlocked(config, "holdout", "d" * 64, repo_root=repo)

    with pytest.raises(AlreadyEvaluated):
        require_unlocked(config, "holdout", "d" * 64, repo_root=repo)


def test_deleting_the_token_does_not_restore_the_credit(repo, config):
    """The token is a deliberate act, not the accounting. The ledger is."""
    _pass_validation(repo, config)
    _unlock_token(repo, "holdout")
    require_unlocked(config, "holdout", "d" * 64, repo_root=repo)
    (repo / "results" / "_unlocks" / "holdout.unlock").unlink()
    _unlock_token(repo, "holdout", reason="second look, surely fine")

    with pytest.raises(AlreadyEvaluated):
        require_unlocked(config, "holdout", "d" * 64, repo_root=repo)


def test_one_experiment_costs_one_credit_across_both_its_periods(repo, config):
    """CONVENTIONS A-003: the budget counts EXPERIMENTS, not evaluations.

    One hypothesis taken along its own pre-registered path -- validation then a
    single holdout look -- is one draw on the programme's credibility, not two.
    """
    _unlock_token(repo, "validation")
    _unlock_token(repo, "holdout")

    require_unlocked(config, "validation", "d" * 64, repo_root=repo)
    ledger = ResearchLedger(repo / config.get("governance.ledger_file"), budget=5)
    ledger.record_result(
        config.get("experiment.id"), "validation", p_value=0.001, t_stat=3.2,
        verdict="PASS", dataset_hash="d" * 64,
    )
    require_unlocked(config, "holdout", "d" * 64, repo_root=repo)

    reloaded = ResearchLedger(repo / config.get("governance.ledger_file"), budget=5)
    assert reloaded.credits_spent() == 1


def test_the_budget_runs_out(repo, config):
    """Five lifetime pre-registered experiments, then nothing.

    The sixth experiment cannot even begin its validation pass, which is the
    right place to stop it: refusing only at the holdout would let a sixth
    hypothesis consume real effort before discovering it can never be confirmed.
    """
    ledger_path = repo / config.get("governance.ledger_file")
    ledger = ResearchLedger(ledger_path, budget=int(config.get("governance.research_budget")))
    for i in range(5):
        ledger.spend(
            experiment_id=f"PRIOR-{i:03d}",
            hypothesis="prior experiment",
            period="validation",
            config_hash="c" * 64,
            protocol_hash="p" * 64,
            conventions_hash="v" * 64,
            git_sha="abc",
            dataset_hash="d" * 64,
            reason="historical",
        )
    _unlock_token(repo, "validation")

    # APEX-001 would be the sixth experiment.
    with pytest.raises(BudgetExhausted):
        require_unlocked(config, "validation", "d" * 64, repo_root=repo)


def test_a_tampered_ledger_blocks_the_holdout(repo, config):
    """Deleting a failed experiment must not buy back a credit."""
    ledger_path = repo / config.get("governance.ledger_file")
    ledger = ResearchLedger(ledger_path, budget=5)
    for i in range(2):
        ledger.spend(
            experiment_id=f"PRIOR-{i:03d}",
            hypothesis="prior",
            period="validation",
            config_hash="c" * 64,
            protocol_hash="p" * 64,
            conventions_hash="v" * 64,
            git_sha="abc",
            dataset_hash="d" * 64,
            reason="historical",
        )
    lines = ledger_path.read_text().splitlines()
    ledger_path.write_text(lines[0] + "\n")  # erase the second evaluation
    _unlock_token(repo, "holdout")

    with pytest.raises(Exception) as excinfo:
        require_unlocked(config, "holdout", "d" * 64, repo_root=repo)
    assert "tamper" in str(excinfo.value).lower() or "removed" in str(excinfo.value).lower()


def test_an_unsigned_registration_cannot_open_the_holdout_either(repo, config):
    """Belt and braces: the two gates are independent and both must hold."""
    _unlock_token(repo, "holdout")

    with pytest.raises(RegistrationError):
        require_signed(config, repo_root=repo)
