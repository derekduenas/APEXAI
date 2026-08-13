"""APEX Screening Protocol v1.0, rules S1-S12. Each rule, with a counterexample.

The screen exists to reject cheaply and to be incapable of improving anything.
Every test that proves a refusal also proves the refusal can fire -- a guard
that cannot fail is not a guard, which this project has now established four
separate times.

No hypothesis is selected here. The dossiers below are inert fixtures with
deliberately fictional content; none is a candidate for APEX-003.
"""

from __future__ import annotations

import json

import pytest

from pathlib import Path

from apex.config import load_config
from apex.governance.screening import (
    REJECT,
    SURVIVE,
    AlreadyRejected,
    Dossier,
    DossierIncomplete,
    HoldoutRequested,
    NondeterministicScreen,
    OptimisationLeak,
    ScreenLog,
    ScreenLogTampered,
    ScreenOutcome,
    ScreenWindow,
    ScreeningError,
    run_screen,
)

CFG = load_config("experiment", "costs", "synthetic", "sharadar")
REPO = Path(__file__).resolve().parents[1]


def _content(**overrides) -> dict:
    """An inert, complete fixture. NOT a candidate hypothesis."""
    base = {
        # scientific requirements (protocol)
        "hypothesis": "A placeholder used only to exercise the governance layer.",
        "economic_rationale": "None. This fixture exists to test refusals.",
        "signal_definition": "placeholder",
        "directional_prediction": "none; a fixture predicts nothing",
        "timing": "not applicable",
        "data_requirements": "none",
        "universe": "frozen section 3",
        "horizon": "20 trading days",
        "falsification_criterion": "not applicable to a fixture",
        # governance metadata
        "title": "FIXTURE — not a candidate",
        "author": "test",
        "date": "2026-08-12",
    }
    base.update(overrides)
    return base


def _log(tmp_path) -> ScreenLog:
    return ScreenLog(tmp_path / "results" / "screen_log.jsonl")


def _window() -> ScreenWindow:
    return ScreenWindow.in_sample(CFG)


def _survives(_dossier, _window) -> ScreenOutcome:
    return ScreenOutcome(verdict=SURVIVE, reasons=("fixture",))


def _rejects(_dossier, _window) -> ScreenOutcome:
    return ScreenOutcome(verdict=REJECT, reasons=("fixture",))


# --- S1: a dossier must be complete ----------------------------------------

def test_a_complete_dossier_is_accepted():
    assert Dossier(content=_content()).hash


def test_counterexample_an_incomplete_dossier_cannot_be_screened():
    with pytest.raises(DossierIncomplete, match="economic_rationale"):
        Dossier(content=_content(economic_rationale="   "))


def test_the_required_fields_are_transcribed_from_the_protocol():
    """S1. The implementation may not define what a valid hypothesis is.

    An earlier version enforced a ten-field list the protocol never mentioned,
    which is a hidden selection criterion inside a system built to eliminate
    hidden selection criteria. The protocol now names them; this checks the
    code did not add to, or drop from, that list.
    """
    from apex.governance.screening import GOVERNANCE_FIELDS, SCIENTIFIC_FIELDS

    protocol = (REPO / "APEX-SCREENING-PROTOCOL-v1.0.md").read_text()
    stated = protocol[protocol.index("## What a dossier must contain"):
                      protocol.index("## The file-drawer rule")]

    for field in SCIENTIFIC_FIELDS + GOVERNANCE_FIELDS:
        assert f"`{field}`" in stated, f"{field} is enforced but not in the protocol"

    # and the removed inventions must not have crept back
    for invention in ("prior_literature", "why_it_might_fail"):
        assert invention not in SCIENTIFIC_FIELDS + GOVERNANCE_FIELDS


def test_counterexample_the_transcription_check_would_notice_an_added_field():
    """Prove the check above can fail rather than merely reporting clean."""
    protocol = (REPO / "APEX-SCREENING-PROTOCOL-v1.0.md").read_text()
    stated = protocol[protocol.index("## What a dossier must contain"):
                      protocol.index("## The file-drawer rule")]

    assert "`sharpe_target`" not in stated, "the fixture field is not fictional"


def test_scientific_and_governance_requirements_are_reported_separately():
    """A missing title is administrative; a missing rationale is scientific.

    Collapsing the two would let a bookkeeping omission read as a scientific
    defect, and vice versa.
    """
    with pytest.raises(DossierIncomplete, match="governance metadata missing"):
        Dossier(content=_content(title=""))

    with pytest.raises(DossierIncomplete, match="scientific requirements missing"):
        Dossier(content=_content(falsification_criterion=""))


# --- S13: a screening outcome is not evidence ------------------------------

def test_the_evaluation_path_cannot_read_the_screen_log():
    """S13, enforced structurally: no evaluation module imports screening.

    "It already looked good in screening" must have nowhere to enter from.
    """
    from apex.audit.execution_path import module_closure

    for entry in ("apex.pipeline", "apex.experiments.apex002",
                  "apex.evaluate.criteria", "apex.evaluate.verdict",
                  "apex.evaluate.ic", "apex.report.attribution"):
        closure = module_closure(REPO, entry)
        assert "apex.governance.screening" not in closure, (
            f"{entry} can reach the screen log; a screening outcome could "
            f"enter the experiment's evidence"
        )


def test_counterexample_the_s13_isolation_check_detects_a_reachable_screen():
    """Prove the closure check can fail.

    A module that DOES import screening must be detected, otherwise the check
    above is reporting the absence of an import it could never see.
    """
    from apex.audit.execution_path import module_closure

    closure = module_closure(REPO, "apex.governance.screening")

    assert "apex.governance.screening" in closure, (
        "the closure walk cannot see apex.governance.screening at all; the "
        "S13 check above proves nothing"
    )


def test_the_screen_outcome_carries_no_statistic_for_evidence():
    """S13 and S7 meet here: an eligibility decision has no test statistic."""
    outcome = ScreenOutcome(verdict=SURVIVE, reasons=("x",))

    for statistical in ("p_value", "t_stat", "ic", "mean_ic", "effect_size"):
        assert not hasattr(outcome, statistical)


# --- S2: content hash ------------------------------------------------------

def test_the_hash_is_content_addressed_not_order_dependent():
    a = _content()
    b = dict(reversed(list(a.items())))

    assert Dossier(content=a).hash == Dossier(content=b).hash


def test_counterexample_a_changed_dossier_gets_a_different_hash():
    """S8. Iteration is permitted and must be VISIBLE, never laundered."""
    original = Dossier(content=_content())
    changed = Dossier(content=_content(horizon="60 trading days"))

    assert original.hash != changed.hash, (
        "a materially changed hypothesis kept its identity; iteration could "
        "be hidden inside one dossier"
    )


# --- S3: everything is logged, permanently ---------------------------------

def test_a_rejection_is_logged_as_permanently_as_a_survival(tmp_path):
    log = _log(tmp_path)
    d = Dossier(content=_content())

    run_screen(d, _rejects, log, _window(), CFG)

    assert log.counts() == {"screens": 1, "rejected": 1, "survived": 0,
                            "distinct_dossiers": 1}
    assert log.history(d.hash)[0].verdict == REJECT


def test_counterexample_an_unlogged_rejection_cannot_silently_disappear(tmp_path):
    """The file-drawer rule. Deleting a rejection must be detectable.

    If rejections could vanish, the survivors would look stronger than they
    are, because the denominator would be missing.
    """
    log = _log(tmp_path)
    run_screen(Dossier(content=_content(title="A")), _rejects, log, _window(), CFG)
    run_screen(Dossier(content=_content(title="B")), _survives, log, _window(), CFG)

    path = tmp_path / "results" / "screen_log.jsonl"
    lines = path.read_text().splitlines()
    path.write_text(lines[1] + "\n")            # drop the rejection

    with pytest.raises(ScreenLogTampered):
        ScreenLog(path).verify_chain()


def test_counterexample_editing_a_logged_reason_is_detected(tmp_path):
    log = _log(tmp_path)
    run_screen(Dossier(content=_content()), _rejects, log, _window(), CFG)

    path = tmp_path / "results" / "screen_log.jsonl"
    raw = json.loads(path.read_text())
    raw["reasons"] = ["a more flattering reason"]
    path.write_text(json.dumps(raw, sort_keys=True) + "\n")

    with pytest.raises(ScreenLogTampered, match="edited"):
        ScreenLog(path).verify_chain()


# --- S4 / S7: two outcomes, no optimisation information --------------------

def test_counterexample_a_score_is_not_a_verdict():
    with pytest.raises(ScreeningError, match="no score, rank"):
        ScreenOutcome(verdict="0.62", reasons=("x",))

    for bad in ("PROMISING", "BORDERLINE", "MAYBE", "survive"):
        with pytest.raises(ScreeningError):
            ScreenOutcome(verdict=bad, reasons=("x",))


def test_the_outcome_type_cannot_express_tuning_information():
    """S7 is structural: there is nowhere to put a sweep or a ranking."""
    fields = set(ScreenOutcome.__dataclass_fields__)

    assert fields == {"verdict", "reasons"}
    for forbidden in ("score", "rank", "by_variant", "best_period",
                      "suggested_parameters", "sweep"):
        assert forbidden not in fields


def test_counterexample_a_screen_returning_optimisation_data_is_refused(tmp_path):
    """A screen that hands back a tuning payload instead of a verdict."""
    class _Tuned:
        verdict = SURVIVE
        best_window = 9
        by_variant = {6: 0.4, 9: 0.7, 12: 0.5}

    def optimising_screen(_d, _w):
        return _Tuned()

    with pytest.raises(OptimisationLeak, match="must return ScreenOutcome"):
        run_screen(Dossier(content=_content()), optimising_screen,
                   _log(tmp_path), _window(), CFG)


# --- S5: rejection is terminal ---------------------------------------------

def test_counterexample_a_rejected_dossier_cannot_be_screened_again(tmp_path):
    log = _log(tmp_path)
    d = Dossier(content=_content())
    run_screen(d, _rejects, log, _window(), CFG)

    with pytest.raises(AlreadyRejected, match="terminal"):
        run_screen(d, _survives, log, _window(), CFG)

    assert log.counts()["screens"] == 1, "the refused re-screen was logged anyway"


def test_a_changed_dossier_after_rejection_is_a_new_event(tmp_path):
    """S8. The rejected idea stays rejected; a different idea is different."""
    log = _log(tmp_path)
    run_screen(Dossier(content=_content()), _rejects, log, _window(), CFG)

    revised = Dossier(content=_content(hypothesis="materially different"))
    run_screen(revised, _survives, log, _window(), CFG)

    assert log.counts() == {"screens": 2, "rejected": 1, "survived": 1,
                            "distinct_dossiers": 2}


# --- S6: survival is not authorisation -------------------------------------

def test_survive_grants_eligibility_only(tmp_path):
    log = _log(tmp_path)
    d = Dossier(content=_content())

    run_screen(d, _survives, log, _window(), CFG)

    assert log.is_eligible_for_registration(d.hash) is True


def test_counterexample_a_survivor_creates_no_experiment_and_spends_no_credit(tmp_path):
    """S6 and S10 together."""
    from apex.registration import open_ledger

    before = open_ledger(CFG)
    spent_before = before.credits_spent()
    entries_before = len(before.entries())

    log = _log(tmp_path)
    run_screen(Dossier(content=_content()), _survives, log, _window(), CFG)

    after = open_ledger(CFG)
    assert after.credits_spent() == spent_before, "screening consumed a credit"
    assert len(after.entries()) == entries_before, "screening wrote to the ledger"
    after.verify_chain()


def test_counterexample_an_unregistered_survivor_cannot_enter_validation(tmp_path):
    """S6. Surviving the screen is not a registration.

    A dossier is not an experiment id. The gated path refuses anything that is
    not a registered experiment, and a screen cannot register one.
    """
    import copy

    from apex.pipeline import UnregisteredExperiment, run_period

    log = _log(tmp_path)
    d = Dossier(content=_content())
    run_screen(d, _survives, log, _window(), CFG)

    tampered = copy.deepcopy(CFG.data)
    tampered["experiment"]["id"] = d.hash        # a survivor, posing as an id
    cfg = type(CFG)(data=tampered, sources=CFG.sources)

    class _Source:
        name = "stub"
        requires_signed_registration = False
        dataset_fingerprint = "dev-stub"
        root = "."

        def load(self):
            raise AssertionError("a survivor must not reach a data load")

    with pytest.raises(UnregisteredExperiment):
        run_period(_Source(), cfg, "in_sample")


# --- S9: determinism -------------------------------------------------------

def test_re_screening_the_same_frozen_dossier_is_deterministic(tmp_path):
    log = _log(tmp_path)
    d = Dossier(content=_content())

    first = run_screen(d, _survives, log, _window(), CFG)
    second = run_screen(d, _survives, log, _window(), CFG)

    assert first.verdict == second.verdict == SURVIVE
    assert log.counts()["screens"] == 2, "both screening events must be logged"


def test_counterexample_a_flip_flopping_screen_is_refused(tmp_path):
    """S9. A verdict that depends on when it was run is not evidence."""
    log = _log(tmp_path)
    d = Dossier(content=_content())
    run_screen(d, _survives, log, _window(), CFG)

    with pytest.raises(NondeterministicScreen, match="deterministic"):
        run_screen(d, _rejects, log, _window(), CFG)


# --- S11: the holdout is untouchable ---------------------------------------

def test_the_default_window_is_in_sample():
    window = _window()

    assert window.start == CFG.period("in_sample")["start"]
    assert window.end == CFG.period("in_sample")["end"]
    window.assert_excludes_locked_periods(CFG)          # must not raise


def test_counterexample_a_window_touching_the_holdout_is_refused():
    holdout = CFG.period("holdout")

    with pytest.raises(HoldoutRequested, match="holdout"):
        ScreenWindow(start=str(holdout["start"]),
                     end=str(holdout["end"])).assert_excludes_locked_periods(CFG)


def test_counterexample_a_window_touching_validation_is_refused():
    validation = CFG.period("validation")

    with pytest.raises(HoldoutRequested, match="validation"):
        ScreenWindow(start=str(validation["start"]),
                     end=str(validation["end"])).assert_excludes_locked_periods(CFG)


def test_counterexample_a_window_merely_overlapping_the_holdout_is_refused():
    """Not just containment -- any overlap at all."""
    holdout = CFG.period("holdout")

    with pytest.raises(HoldoutRequested):
        ScreenWindow(start="2017-01-01",
                     end=str(holdout["start"])).assert_excludes_locked_periods(CFG)


def test_counterexample_run_screen_refuses_a_locked_window(tmp_path):
    holdout = CFG.period("holdout")
    window = ScreenWindow(start=str(holdout["start"]), end=str(holdout["end"]))

    with pytest.raises(HoldoutRequested):
        run_screen(Dossier(content=_content()), _survives, _log(tmp_path),
                   window, CFG)


# --- S12: a screen mutates nothing -----------------------------------------

def test_counterexample_a_screen_cannot_mutate_the_dossier(tmp_path):
    def mutating_screen(dossier, _w):
        dossier.content["hypothesis"] = "quietly rewritten to something testable"
        return ScreenOutcome(verdict=SURVIVE, reasons=("mutated",))

    with pytest.raises(ScreeningError, match="mutated the dossier"):
        run_screen(Dossier(content=_content()), mutating_screen,
                   _log(tmp_path), _window(), CFG)


def test_a_screen_does_not_touch_the_protocol_or_criteria(tmp_path):
    from apex.evaluate.criteria import SuccessCriteria
    from apex.registration import protocol_pin_status

    before_pin = protocol_pin_status(CFG, None)["actual_hash"]
    before_criteria = SuccessCriteria.from_config(CFG, "validation").as_dict()

    run_screen(Dossier(content=_content()), _survives, _log(tmp_path),
               _window(), CFG)

    assert protocol_pin_status(CFG, None)["actual_hash"] == before_pin
    assert SuccessCriteria.from_config(CFG, "validation").as_dict() == before_criteria


# --- architecture: why the screen log is a separate chain ------------------

def test_counterexample_extending_ledgerentry_would_break_the_live_chain():
    """The reason screening does not reuse the research ledger.

    `LedgerEntry.payload()` covers every field and `verify_chain` recomputes
    each entry's hash, so adding one field to carry a dossier hash changes the
    hash of every entry already written.
    """
    import hashlib

    from apex.governance.ledger import LedgerEntry

    entry = LedgerEntry(sequence=0, kind="spend", experiment_id="X",
                        period="validation", timestamp="t")
    original = entry.compute_hash()

    extended = entry.payload() | {"dossier_hash": ""}
    with_field = hashlib.sha256(
        json.dumps(extended, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert original != with_field, (
        "adding a field would NOT change the hash; the stated reason for a "
        "separate screen log is wrong and should be revisited"
    )


def test_the_screening_module_never_writes_to_the_research_ledger():
    """S10, S12. Structural: it does not import the spend path at all."""
    import inspect

    from apex.audit.execution_path import executable_source
    from apex.governance import screening

    code = executable_source(inspect.getsource(screening))

    for banned in ("ResearchLedger", "record_result", "require_unlocked",
                   "open_ledger", ".spend("):
        assert banned not in code, f"screening reaches {banned}"


def test_the_screen_log_chain_verifies_after_many_events(tmp_path):
    log = _log(tmp_path)
    for i in range(6):
        fn = _rejects if i % 2 else _survives
        run_screen(Dossier(content=_content(title=f"F{i}")), fn, log,
                   _window(), CFG)

    log.verify_chain()
    assert log.counts() == {"screens": 6, "rejected": 3, "survived": 3,
                            "distinct_dossiers": 6}


def test_counterexample_the_ledger_isolation_scan_detects_an_injected_reference():
    """Prove the S10/S12 source scan can fail, not merely report clean."""
    import inspect

    from apex.audit.execution_path import executable_source
    from apex.governance import screening

    real = executable_source(inspect.getsource(screening))
    assert "ResearchLedger" not in real

    mutated = executable_source(
        "from apex.governance.ledger import ResearchLedger\n"
        + inspect.getsource(screening)
    )

    assert "ResearchLedger" in mutated, "the isolation scan is inert"
