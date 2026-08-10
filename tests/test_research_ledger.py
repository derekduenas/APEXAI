"""Cross-experiment research governance -- directive sections 4 and 5.

The repository had excellent PER-EXPERIMENT governance (a signed pre-registration,
a hand-made unlock token, a one-evaluation-ever period lock) and NO cross-experiment
governance at all. That is exactly where the multiple-testing problem lives: a
system that tests enough hypotheses will find a significant one by chance, and no
single experiment's protocol can see that happening.

User ruling, 2026-08-09: the holdout carries FIVE lifetime credits rather than
one, with mandatory multiplicity correction so the family-wise error rate stays
at the level a single test implies.

Two distinct corrections, and conflating them is how a budget silently leaks:

  SEQUENTIAL   Applied at the moment each credit is spent, before the next
               result exists. Bonferroni at alpha/budget is valid sequentially
               and is what actually authorises a promotion.

  RETROSPECTIVE  Holm, applied to the complete family once it exists. Uniformly
                 more powerful than Bonferroni, but it needs every p-value, so
                 it can only ever be a review, never an authorisation.
"""

from __future__ import annotations

import json

import pytest

from apex.governance.ledger import (
    BudgetExhausted,
    LedgerTampered,
    ResearchLedger,
    holm_rejections,
    required_tstat,
)


@pytest.fixture
def ledger(tmp_path):
    return ResearchLedger(path=tmp_path / "research_ledger.jsonl", budget=5)


def _spend(ledger, experiment_id, period="holdout", **kw):
    return ledger.spend(
        experiment_id=experiment_id,
        hypothesis=kw.get("hypothesis", f"{experiment_id}: a fixed composite ranks forward returns"),
        period=period,
        config_hash="c" * 64,
        protocol_hash="p" * 64,
        conventions_hash="v" * 64,
        git_sha="deadbeef",
        reason=kw.get("reason", "pre-registered evaluation"),
    )


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------


def test_a_fresh_ledger_has_the_full_budget(ledger):
    assert ledger.credits_spent() == 0
    assert ledger.credits_remaining() == 5


def test_spending_a_credit_decrements_the_budget(ledger):
    _spend(ledger, "APEX-001")
    assert ledger.credits_spent() == 1
    assert ledger.credits_remaining() == 4


def test_budget_is_exhausted_after_five_holdout_evaluations(ledger):
    for i in range(5):
        _spend(ledger, f"APEX-{i:03d}")

    assert ledger.credits_remaining() == 0
    with pytest.raises(BudgetExhausted) as excinfo:
        _spend(ledger, "APEX-005")
    assert "5" in str(excinfo.value)


def test_the_same_experiment_cannot_evaluate_the_same_period_twice(ledger):
    _spend(ledger, "APEX-001")
    with pytest.raises(Exception) as excinfo:
        _spend(ledger, "APEX-001")
    assert "already" in str(excinfo.value).lower()


def test_a_modified_hypothesis_is_a_new_experiment_and_costs_a_credit(ledger):
    """Protocol section 10: 'A modified specification is a new hypothesis.'"""
    _spend(ledger, "APEX-001", hypothesis="equal-weighted four-factor composite")
    _spend(ledger, "APEX-001b", hypothesis="equal-weighted four-factor composite, 60-day horizon")

    assert ledger.credits_spent() == 2


def test_non_holdout_periods_do_not_consume_credits(ledger):
    """In-sample is for pipeline verification; charging it would be absurd."""
    _spend(ledger, "APEX-001", period="in_sample")
    _spend(ledger, "APEX-001", period="in_sample")

    assert ledger.credits_spent() == 0
    assert ledger.credits_remaining() == 5


# ---------------------------------------------------------------------------
# tamper evidence
# ---------------------------------------------------------------------------


def test_the_ledger_survives_a_reload(ledger, tmp_path):
    _spend(ledger, "APEX-001")
    reloaded = ResearchLedger(path=tmp_path / "research_ledger.jsonl", budget=5)

    assert reloaded.credits_spent() == 1
    assert reloaded.entries()[0].experiment_id == "APEX-001"


def test_each_entry_chains_to_its_predecessor(ledger):
    _spend(ledger, "APEX-001")
    _spend(ledger, "APEX-002")

    first, second = ledger.entries()
    assert second.prev_hash == first.entry_hash
    assert first.prev_hash == "0" * 64


def test_editing_a_recorded_entry_is_detected(ledger, tmp_path):
    """An append-only claim is worthless if a line can be quietly rewritten."""
    _spend(ledger, "APEX-001")
    _spend(ledger, "APEX-002")

    path = tmp_path / "research_ledger.jsonl"
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["reason"] = "actually we looked twice"
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(LedgerTampered):
        ResearchLedger(path=path, budget=5).verify_chain()


def test_deleting_an_entry_from_the_middle_is_detected(ledger, tmp_path):
    """Deleting a failed experiment is the most tempting form of tampering.

    Directive section 34.12: no hiding failed experiments.
    """
    _spend(ledger, "APEX-001")
    _spend(ledger, "APEX-002")

    path = tmp_path / "research_ledger.jsonl"
    lines = path.read_text().splitlines()
    path.write_text(lines[1] + "\n")

    with pytest.raises(LedgerTampered):
        ResearchLedger(path=path, budget=5).verify_chain()


def test_truncating_the_most_recent_entry_is_detected(ledger, tmp_path):
    """A backward chain alone CANNOT catch this, which is why the head anchor exists.

    Lop the last line off and the remainder still verifies perfectly -- nothing
    points forward to what was removed. Since the most recent experiment is
    precisely the one someone would want to disappear after a bad result, the
    chain length is anchored in a separate file.
    """
    _spend(ledger, "APEX-001")
    _spend(ledger, "APEX-002")

    path = tmp_path / "research_ledger.jsonl"
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n")  # erase the LAST entry

    with pytest.raises(LedgerTampered) as excinfo:
        ResearchLedger(path=path, budget=5).verify_chain()
    assert "removed" in str(excinfo.value)


def test_deleting_the_head_anchor_is_detected(ledger, tmp_path):
    """Removing the anchor to enable a silent truncation is itself a tamper."""
    _spend(ledger, "APEX-001")

    (tmp_path / "research_ledger.jsonl.head").unlink()

    with pytest.raises(LedgerTampered):
        ResearchLedger(path=tmp_path / "research_ledger.jsonl", budget=5).verify_chain()


def test_truncation_does_not_refund_a_credit(ledger, tmp_path):
    """The point of catching truncation: a deleted experiment must not buy a credit back."""
    for i in range(5):
        _spend(ledger, f"APEX-{i:03d}")

    path = tmp_path / "research_ledger.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[:3]) + "\n")

    reloaded = ResearchLedger(path=path, budget=5)
    with pytest.raises(LedgerTampered):
        reloaded.spend(
            experiment_id="APEX-099",
            hypothesis="sneaking a sixth look",
            period="holdout",
            config_hash="c" * 64,
            protocol_hash="p" * 64,
            conventions_hash="v" * 64,
            git_sha="deadbeef",
            reason="the budget looked fine to me",
        )


# ---------------------------------------------------------------------------
# results and multiplicity
# ---------------------------------------------------------------------------


def test_a_result_is_recorded_against_its_spend(ledger):
    _spend(ledger, "APEX-001")
    ledger.record_result("APEX-001", "holdout", p_value=0.004, t_stat=2.71, verdict="PASS")

    results = ledger.results()
    assert results["APEX-001"]["p_value"] == 0.004
    assert results["APEX-001"]["verdict"] == "PASS"


def test_a_result_cannot_be_recorded_without_spending_a_credit(ledger):
    with pytest.raises(Exception):
        ledger.record_result("APEX-999", "holdout", p_value=0.01, t_stat=2.6, verdict="PASS")


def test_a_result_cannot_be_overwritten(ledger):
    """Directive section 34.14: no changing thresholds -- or numbers -- after results."""
    _spend(ledger, "APEX-001")
    ledger.record_result("APEX-001", "holdout", p_value=0.30, t_stat=1.0, verdict="FAIL")

    with pytest.raises(Exception):
        ledger.record_result("APEX-001", "holdout", p_value=0.004, t_stat=2.9, verdict="PASS")


def test_sequential_threshold_is_bonferroni_over_the_whole_budget(ledger):
    """Valid before later p-values exist, which is when authorisation happens."""
    assert ledger.sequential_alpha(0.05) == pytest.approx(0.01)
    assert ledger.sequential_alpha(0.10) == pytest.approx(0.02)


def test_sequential_threshold_does_not_loosen_as_credits_are_spent(ledger):
    """The budget is committed up front; spending it must not buy a weaker bar."""
    before = ledger.sequential_alpha(0.05)
    _spend(ledger, "APEX-001")
    _spend(ledger, "APEX-002")

    assert ledger.sequential_alpha(0.05) == before


def test_holm_is_more_powerful_than_bonferroni_on_the_same_family():
    p_values = {"A": 0.004, "B": 0.011, "C": 0.20, "D": 0.44, "E": 0.61}

    holm = holm_rejections(p_values, alpha=0.05)
    bonferroni = {k: v <= 0.05 / 5 for k, v in p_values.items()}

    assert holm["A"] is True
    assert bonferroni["B"] is False
    assert holm["B"] is True, "Holm should reject B where Bonferroni cannot"
    assert not any(holm[k] for k in ("C", "D", "E"))


def test_holm_stops_at_the_first_failure():
    """Step-down: once one hypothesis survives, every LARGER p-value survives too.

    C below would clear its own step threshold (0.031 <= 0.05/1) if each test
    were judged in isolation. Holm accepts it anyway, because B failed earlier in
    the ordering. That carry-forward is the entire point of the procedure, and
    the easiest part to get wrong by testing each threshold independently.
    """
    p_values = {"A": 0.001, "B": 0.030, "C": 0.031}

    holm = holm_rejections(p_values, alpha=0.05)

    assert holm["A"] is True, "0.001 <= 0.05/3 = 0.0167"
    assert holm["B"] is False, "0.030 > 0.05/2 = 0.025, so the step-down halts here"
    assert holm["C"] is False, (
        "C clears its own step threshold (0.031 <= 0.05/1) but must still be "
        "accepted, because Holm halted at B"
    )


def test_holm_on_the_recorded_family(ledger):
    for i, p in enumerate([0.002, 0.30, 0.9]):
        _spend(ledger, f"APEX-{i:03d}")
        ledger.record_result(f"APEX-{i:03d}", "holdout", p_value=p, t_stat=1.0, verdict="X")

    verdicts = ledger.holm(alpha=0.05)

    assert verdicts["APEX-000"] is True
    assert verdicts["APEX-001"] is False


# ---------------------------------------------------------------------------
# the interaction with the HAC finding
# ---------------------------------------------------------------------------


def test_required_tstat_under_the_budget_exceeds_the_preregistered_hurdle():
    """The two findings of 2026-08-09 collide here, and the collision matters.

    The pre-registered promotion hurdle is t >= 2.5 (protocol section 10). Its
    MEASURED one-sided size is ~1.9%, not the 0.621% its nominal reading
    suggests. Bonferroni over a 5-credit budget at family-wise 5% demands 1.0%
    per test. 1.9% > 1.0%, so a result landing exactly on the pre-registered
    hurdle would pass section 10 and still fail family-wise control.

    This is reported, not silently enforced -- section 10 is pre-registered and
    is not being retightened after the fact.
    """
    from apex.evaluate.reference import simulate_null_tstats

    reference = simulate_null_tstats(
        n_obs=1133, overlap=20, lag=25, kernel="bartlett", n_replications=4000, seed=20260809
    )

    needed = required_tstat(reference, alpha=0.01)

    assert needed > 2.5, (
        f"a family-wise-corrected 1% test needs t >= {needed:.2f}; the "
        f"pre-registered hurdle of 2.5 is weaker than that and the gap must be "
        f"disclosed rather than discovered after a result"
    )
    assert needed < 4.0, f"implausible corrected threshold {needed:.2f}"


def test_budget_report_states_every_number_a_reviewer_needs(ledger):
    _spend(ledger, "APEX-001")
    ledger.record_result("APEX-001", "holdout", p_value=0.004, t_stat=2.71, verdict="PASS")

    report = ledger.report(family_alpha=0.05)

    for key in (
        "budget",
        "credits_spent",
        "credits_remaining",
        "sequential_alpha",
        "experiments",
        "chain_verified",
    ):
        assert key in report, f"budget report is missing '{key}'"
    assert report["chain_verified"] is True
