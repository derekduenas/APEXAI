"""Annulment: voiding a spend that never produced a result. APPEND-ONLY.

INCIDENT-001 left an APEX-002 validation spend with no result. The
no-second-look guard keys on the spend, so it blocked the governed replacement
the operator had authorised. Deleting the spend was considered and REJECTED:
that is the operation the hash chain and external anchor exist to detect, and
it would have erased the incident from the only tamper-evident record of it.

The narrowing here is exactly one governed case wide. Every way it could be
widened is a test below, and each one asserts a REFUSAL.
"""

from __future__ import annotations

import pytest

from apex.governance.ledger import (
    AlreadyEvaluated,
    LedgerError,
    ResearchLedger,
)

PERIOD = "validation"
DATASET = "d" * 64


def _ledger(tmp_path) -> ResearchLedger:
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    return ResearchLedger(tmp_path / "results" / "ledger.jsonl", budget=5)


def _spend(ledger: ResearchLedger, experiment: str = "APEX-002") -> None:
    ledger.spend(
        experiment_id=experiment, hypothesis="h", period=PERIOD,
        config_hash="c" * 64, protocol_hash="p" * 64,
        conventions_hash="v" * 64, dataset_hash=DATASET,
        git_sha="0" * 40, reason="test",
    )


def _annul(ledger: ResearchLedger, experiment: str = "APEX-002"):
    return ledger.annul(
        experiment_id=experiment, period=PERIOD,
        reason="INCIDENT-001: execution failed before any result was recorded.",
    )


# --- REQUIREMENT 1: an annulled spend allows exactly one rerun --------------

def test_an_annulled_spend_allows_a_replacement(tmp_path):
    ledger = _ledger(tmp_path)
    _spend(ledger)
    _annul(ledger)

    assert ledger.already_evaluated("APEX-002", PERIOD) is None
    _spend(ledger)                                   # must not raise

    kinds = [e.kind for e in ledger.entries()]
    assert kinds == ["spend", "annulment", "spend"]


# --- REQUIREMENT 2: a non-annulled second spend still raises ---------------

def test_counterexample_a_second_spend_without_annulment_is_refused(tmp_path):
    """The no-second-look rule, unchanged for every un-annulled case."""
    ledger = _ledger(tmp_path)
    _spend(ledger)

    assert ledger.already_evaluated("APEX-002", PERIOD) is not None
    with pytest.raises(AlreadyEvaluated):
        _spend(ledger)


def test_counterexample_the_replacement_itself_blocks_a_third_run(tmp_path):
    """One annulment buys ONE replacement, and the replacement is then binding."""
    ledger = _ledger(tmp_path)
    _spend(ledger)
    _annul(ledger)
    _spend(ledger)

    assert ledger.already_evaluated("APEX-002", PERIOD) is not None
    with pytest.raises(AlreadyEvaluated):
        _spend(ledger)


# --- REQUIREMENT 3: multiple annulments do not open multiple reruns --------

def test_counterexample_a_second_annulment_is_refused(tmp_path):
    """An annulment cannot be banked against a future execution."""
    ledger = _ledger(tmp_path)
    _spend(ledger)
    _annul(ledger)

    with pytest.raises(LedgerError, match="nothing to annul"):
        _annul(ledger)


def test_counterexample_excess_annulments_cannot_bank_capacity(tmp_path):
    """Read-side proof, independent of the write-side refusal above.

    Even if two annulments somehow existed against one spend, the guard must
    not grant two replacements. Entries are replayed in order and an annulment
    with no active spend voids nothing.
    """
    ledger = _ledger(tmp_path)
    _spend(ledger)
    _annul(ledger)

    # Forge the state the write-side refuses, to prove the READ side is safe.
    # Written through _append so the chain and the head anchor stay consistent
    # -- the point is a surplus annulment, not a tampered ledger.
    ledger._append(                                            # noqa: SLF001
        ledger._next(kind="annulment", experiment_id="APEX-002",  # noqa: SLF001
                     period=PERIOD, reason="excess")
    )
    _spend(ledger)                                   # the one replacement

    assert ledger.already_evaluated("APEX-002", PERIOD) is not None, (
        "a surplus annulment banked capacity; two annulments bought two reruns"
    )


# --- REQUIREMENT 4: annulment without a prior spend fails ------------------

def test_counterexample_annulment_without_a_prior_spend_is_refused(tmp_path):
    ledger = _ledger(tmp_path)

    with pytest.raises(LedgerError, match="nothing to annul"):
        _annul(ledger)


def test_counterexample_annulment_cannot_reach_another_experiment(tmp_path):
    """An annulment is scoped to one (experiment, period)."""
    ledger = _ledger(tmp_path)
    _spend(ledger, "APEX-001")

    with pytest.raises(LedgerError, match="nothing to annul"):
        _annul(ledger, "APEX-002")

    assert ledger.already_evaluated("APEX-001", PERIOD) is not None


# --- the protection that makes annulment safe ------------------------------

def test_counterexample_a_spend_that_produced_a_result_cannot_be_annulled(tmp_path):
    """THE containment. Without this, annulment erases real observations.

    A recorded result is an experimental observation. Annulling it would turn
    this mechanism into exactly the re-look the ledger exists to forbid.
    """
    ledger = _ledger(tmp_path)
    _spend(ledger)
    ledger.record_result("APEX-002", PERIOD, p_value=0.4, t_stat=0.9,
                         verdict="INCONCLUSIVE", dataset_hash=DATASET)

    with pytest.raises(LedgerError, match="a result was recorded"):
        _annul(ledger)

    assert ledger.already_evaluated("APEX-002", PERIOD) is not None


def test_an_annulment_requires_a_written_reason(tmp_path):
    ledger = _ledger(tmp_path)
    _spend(ledger)

    with pytest.raises(LedgerError, match="requires a written reason"):
        ledger.annul(experiment_id="APEX-002", period=PERIOD, reason="   ")


# --- append-only and chain integrity ---------------------------------------

def test_annulment_appends_and_leaves_the_chain_verifiable(tmp_path):
    ledger = _ledger(tmp_path)
    _spend(ledger)
    before = [e.entry_hash for e in ledger.entries()]

    entry = _annul(ledger)

    after = [e.entry_hash for e in ledger.entries()]
    assert after[:len(before)] == before, "an existing entry was rewritten"
    assert entry.prev_hash == before[-1], "the annulment does not chain"
    ledger.verify_chain()                            # must not raise


def test_counterexample_deleting_the_spend_would_break_the_chain(tmp_path):
    """Why annulment rather than deletion.

    The rejected alternative, demonstrated: removing the entry and leaving the
    anchor is detected. This is the operation the ledger was built to catch.
    """
    from apex.governance.ledger import LedgerTampered

    ledger = _ledger(tmp_path)
    _spend(ledger)
    _spend(ledger, "APEX-001")

    path = tmp_path / "results" / "ledger.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")    # lop the last entry

    with pytest.raises(LedgerTampered):
        ResearchLedger(path, budget=5).verify_chain()
