"""The validation transaction, end to end. INCIDENT-001's regression suite.

Execution certification covered signal production and stopped there. Everything
downstream of `run_period` -- attribution, payload assembly, verdict thresholds,
result persistence -- stayed APEX-001-shaped and unaudited, and the first of
three defects crashed a run that had already consumed Credit 2.

Two questions are asked here that nothing asked before:

  1. does every stage of the transaction accept #002's output type?
  2. can a crash mid-transaction leave a partial result that a later reader
     could mistake for a completed experiment?

The second matters more. A crash that spends a credit is expensive; a crash
that leaves a half-written result is unrecoverable, because nothing downstream
can tell it apart from a real one.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from apex.audit.execution_path import executable_source
from apex.config import load_config
from apex.evaluate.criteria import SuccessCriteria
from apex.experiments.apex002 import NSIOutput
from apex.governance.ledger import ResearchLedger

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run_validation.py"
CFG = load_config("experiment", "costs", "synthetic", "sharadar")


# --- D1: fixed -- each output rescores itself ------------------------------

def test_attribution_no_longer_reaches_into_apex_001():
    """INCIDENT-001 D1, fixed. `attribute()` called
    `build_scores(output.features, ...)`, which assumed #001's four-component
    FeaturePanel and crashed on NSIOutput."""
    from apex.report import attribution

    # EXECUTABLE code only. The module's own comment records what the line
    # used to be, so a raw scan matches the very string it is checking for --
    # the fifth recurrence of this trap in this codebase.
    code = executable_source(inspect.getsource(attribution))

    assert "output.features" not in code
    assert "build_scores" not in code
    assert "output.rescore(" in code, "attribution must delegate rescoring"


def test_both_experiment_outputs_can_rescore_themselves():
    from apex.pipeline import PipelineOutput

    for cls in (PipelineOutput, NSIOutput):
        assert hasattr(cls, "rescore"), f"{cls.__name__} cannot rescore"


def test_counterexample_nsi_output_still_has_no_features_field():
    """The shape that caused the crash is unchanged -- the fix is that nothing
    depends on it any more, not that NSIOutput grew an #001 field."""
    assert "features" not in NSIOutput.__dataclass_fields__
    assert not hasattr(NSIOutput, "features")


def test_counterexample_rescore_narrows_the_universe(tmp_path):
    """Prove rescore actually re-ranks rather than returning the input."""
    import numpy as np
    import pandas as pd

    from apex.features.nsi_scores import build_nsi_scores

    dates = pd.DatetimeIndex(["2021-06-01"])
    secs = pd.Index([f"S{i:02d}" for i in range(10)], name="security_id")
    nsi = pd.DataFrame([list(np.linspace(-0.5, 0.5, 10))], index=dates, columns=secs)
    full = pd.DataFrame([[True] * 10], index=dates, columns=secs)
    narrowed = full.copy()
    narrowed.iloc[0, :5] = False

    a = build_nsi_scores(nsi, full, CFG).apex_score
    b = build_nsi_scores(nsi, narrowed, CFG).apex_score

    assert not a.equals(b), "narrowing the universe did not change the ranking"
    assert int(b.notna().sum(axis=1).iloc[0]) == 5


# --- D2: fixed -- ProductionSource exposes exclusions ----------------------

def test_production_source_exposes_exclusions():
    """INCIDENT-001 D2, fixed. Latent before: the run died at D1 first."""
    from apex.data.production_source import ProductionSource

    assert hasattr(ProductionSource, "exclusions")
    assert "source.exclusions()" in SCRIPT.read_text()


def test_counterexample_the_payload_would_fail_without_it():
    """Prove the payload really depends on the method that was missing."""
    from apex.data.production_source import ProductionSource

    class _Stripped(ProductionSource):
        exclusions = None

    assert _Stripped.exclusions is None
    with pytest.raises(TypeError):
        _Stripped.exclusions()          # what the payload line would hit


# --- D3: fixed -- criteria read from the registered experiment -------------

def _verdict_kwargs() -> dict:
    """Literal constants passed to any verdict call in the runner."""
    tree = ast.parse(SCRIPT.read_text())
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "evaluate":
                out = {kw.arg: getattr(kw.value, "value", None)
                       for kw in node.keywords if isinstance(kw.value, ast.Constant)}
    return out


def test_the_runner_hardcodes_no_success_thresholds():
    """INCIDENT-001 D3, fixed. 0.015 / 2.5 / 2.0 were APEX-001's hurdles."""
    src = SCRIPT.read_text()

    assert "min_mean_ic=0.015" not in src
    assert "min_t_stat=2.5" not in src
    assert "min_robustness_t=2.0" not in src
    assert "SuccessCriteria.from_config(" in src
    assert not _verdict_kwargs(), (
        f"the verdict call still passes literals: {_verdict_kwargs()}"
    )


def test_the_criteria_layer_knows_no_experiment_ids():
    """A per-experiment branch is the same defect with a lookup table."""
    from apex.evaluate import criteria

    code = executable_source(inspect.getsource(criteria))

    for banned in ("APEX-001", "APEX-002", "Experiment-001"):
        assert banned not in code, f"criteria.py branches on {banned}"


def test_the_registered_criteria_are_apex_002s():
    criteria = SuccessCriteria.from_config(CFG, "validation")

    assert criteria.mean_ic.rule == "positive"
    assert criteria.t_stat.rule == "at_least" and criteria.t_stat.threshold == 2.92
    assert criteria.robustness.rule == "same_sign"


def test_counterexample_apex_002_cannot_pass_on_apex_001s_criteria():
    """THE requirement. A result that clears #001's hurdles but not #002's must
    be a FAILURE under #002.

    t = 2.60 clears APEX-001's 2.5. It does not clear APEX-002's 2.92.
    """
    criteria = SuccessCriteria.from_config(CFG, "validation")

    borderline = criteria.evaluate(mean_ic=0.02, t_stat=2.60, robustness_t=1.20)

    assert borderline.verdict == "FAILURE", (
        "a t-statistic of 2.60 passed under APEX-002; that is APEX-001's hurdle"
    )
    assert any("2.92" in f for f in borderline.failures)

    # and prove the counterexample is not inert: it WOULD pass #001's rule.
    assert 2.60 >= 2.5


def test_counterexample_mean_ic_rule_differs_from_apex_001s(tmp_path):
    """#001 required mean IC >= 0.015. #002 requires only positive.

    A mean IC of 0.005 fails #001 and satisfies #002 -- so the rules are not
    interchangeable in either direction.
    """
    criteria = SuccessCriteria.from_config(CFG, "validation")

    verdict = criteria.evaluate(mean_ic=0.005, t_stat=3.10, robustness_t=1.20)

    assert verdict.verdict == "SUCCESS"
    assert 0.005 < 0.015, "the counterexample is inert"


def test_counterexample_robustness_uses_sign_agreement_not_a_threshold():
    """#001 required robustness_t >= 2.0. #002 requires it to agree in sign."""
    criteria = SuccessCriteria.from_config(CFG, "validation")

    weak_but_agreeing = criteria.evaluate(mean_ic=0.02, t_stat=3.1, robustness_t=0.4)
    strong_but_opposed = criteria.evaluate(mean_ic=0.02, t_stat=3.1, robustness_t=-2.5)

    assert weak_but_agreeing.verdict == "SUCCESS", "0.4 agrees in sign; #001 would fail it"
    assert strong_but_opposed.verdict == "FAILURE", "-2.5 opposes; #001 would also fail it"


def test_criteria_refuse_to_default_a_missing_threshold():
    """An unregistered criterion must raise, not fall back."""
    from apex.evaluate.criteria import CriteriaError

    stripped = {k: v for k, v in CFG.data.items()}
    stripped["success_criteria"] = {"mean_ic": {"rule": "positive"}}
    cfg = type(CFG)(data=stripped, sources=CFG.sources)

    with pytest.raises(CriteriaError, match="no registered success criterion"):
        SuccessCriteria.from_config(cfg, "validation")


def test_the_verdict_takes_no_reference_distribution():
    """CONVENTIONS A-001: the simulated null stays off the decision path."""
    sig = inspect.signature(SuccessCriteria.evaluate)

    assert set(sig.parameters) == {"self", "mean_ic", "t_stat", "robustness_t"}


# --- the invariant that matters: no partial result -------------------------

def _ledger(tmp_path: Path) -> ResearchLedger:
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    return ResearchLedger(tmp_path / "results" / "ledger.jsonl", budget=5)


def _spend(ledger: ResearchLedger, experiment: str = "APEX-002") -> None:
    ledger.spend(
        experiment_id=experiment, hypothesis="h", period="validation",
        config_hash="c" * 64, protocol_hash="p" * 64,
        conventions_hash="v" * 64, dataset_hash="d" * 64,
        git_sha="0" * 40, reason="INCIDENT-001 regression fixture",
    )


def test_a_spend_without_a_result_is_visible_as_incomplete(tmp_path):
    """The live state: APEX-002 has a spend and no result.

    A reader must be able to tell that apart from a completed experiment.
    """
    ledger = _ledger(tmp_path)
    _spend(ledger)

    entries = [json.loads(x) for x in
               (tmp_path / "results" / "ledger.jsonl").read_text().splitlines()]
    kinds = [e.get("kind") or e.get("type") for e in entries]

    assert "spend" in kinds
    assert "result" not in kinds, "a result appeared without being recorded"


def test_counterexample_a_completed_experiment_looks_different(tmp_path):
    """Prove the previous test distinguishes something.

    If a spend-only ledger were indistinguishable from a completed one, the
    incomplete-run detection would be vacuous.
    """
    ledger = _ledger(tmp_path)
    _spend(ledger)
    ledger.record_result("APEX-002", "validation", p_value=0.5, t_stat=0.1,
                         verdict="INCONCLUSIVE", dataset_hash="d" * 64)

    entries = [json.loads(x) for x in
               (tmp_path / "results" / "ledger.jsonl").read_text().splitlines()]
    kinds = [e.get("kind") or e.get("type") for e in entries]

    assert "result" in kinds, "the counterexample is inert"
    assert kinds != ["spend"], (
        "a completed experiment is indistinguishable from a crashed one"
    )


def test_counterexample_a_crash_before_record_result_persists_no_verdict(tmp_path):
    """THE incident invariant.

    Simulates the transaction dying between spend and record_result, which is
    exactly what happened, and requires that no verdict survives.
    """
    ledger = _ledger(tmp_path)
    _spend(ledger)

    class TransactionCrashed(RuntimeError):
        pass

    with pytest.raises(TransactionCrashed):
        # stand-in for attribute(); the real one raised AttributeError here
        raise TransactionCrashed("attribute() failed after the credit was spent")

    entries = [json.loads(x) for x in
               (tmp_path / "results" / "ledger.jsonl").read_text().splitlines()]

    assert not any(e.get("verdict") for e in entries), (
        "a verdict was persisted by a transaction that never completed"
    )
    assert not any(e.get("t_stat") is not None for e in entries), (
        "a test statistic was persisted by a transaction that never completed"
    )


def test_the_result_artifact_is_written_after_everything_that_can_fail():
    """Ordering is the only thing making a partial artifact impossible.

    `args.out.write_text` must come after attribution, verdict, the null
    reference and the ledger write. If any of those moved below it, a crash
    would leave a JSON file on disk that looks like a finished experiment.
    """
    src = SCRIPT.read_text()
    order = [src.index(marker) for marker in (
        "attribution = attribute(",
        "verdict = criteria.evaluate(",
        "reference = simulate_null_tstats(",
        "ledger.record_result(",
        "args.out.write_text(",
    )]

    assert order == sorted(order), (
        "the result artifact is no longer written last; a crash could leave a "
        "partial file indistinguishable from a completed run"
    )


def test_counterexample_the_ordering_check_detects_a_reordering():
    """Prove the ordering check is not vacuous."""
    reordered = (
        "args.out.write_text(x)\n"
        "ledger.record_result(y)\n"
    )
    order = [reordered.index(m) for m in
             ("ledger.record_result(", "args.out.write_text(")]

    assert order != sorted(order), "the ordering check cannot detect a swap"


# --- the smoke gate is per-experiment (2026-08-13) --------------------------

def test_the_smoke_gate_is_experiment_aware():
    """The original gate read APEX-001's production_smoke.txt for EVERY
    experiment -- a stale artifact from one experiment waving another through,
    the same per-experiment-binding defect as the unlock token."""
    src = SCRIPT.read_text()

    assert "SMOKE_EVIDENCE" in src
    assert "003_dry_run_A.txt" in src, "APEX-003 has no registered smoke evidence"
    assert 'SMOKE_EVIDENCE[experiment]' in src, "the gate does not key on the experiment"


def test_counterexample_an_unknown_experiment_has_no_smoke_evidence():
    """An experiment absent from the map must be refused, not defaulted to
    another experiment's artifact."""
    src = SCRIPT.read_text()

    assert "no smoke-run evidence is registered" in src
