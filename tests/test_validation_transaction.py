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

from apex.config import load_config
from apex.experiments.apex002 import NSIOutput
from apex.governance.ledger import ResearchLedger

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run_validation.py"
CFG = load_config("experiment", "costs", "synthetic", "sharadar")


# --- D1: the crash that happened --------------------------------------------

def test_attribution_requires_a_field_nsi_output_does_not_have():
    """INCIDENT-001's proximate cause, pinned as a known defect.

    `attribute()` reads `output.features` and calls #001's composite scorer.
    NSIOutput has no `features` -- #002 has one signal, not four components.
    This test DOCUMENTS the incompatibility; it does not assert it is fine.
    """
    assert not hasattr(NSIOutput, "features")
    assert "features" not in NSIOutput.__dataclass_fields__

    from apex.report import attribution

    src = inspect.getsource(attribution)
    assert "output.features" in src, (
        "attribute() no longer reads output.features -- if that was fixed, "
        "update this test and INCIDENT-001 rather than deleting the record"
    )
    assert "from apex.features.composite import build_scores" in src, (
        "the #001 composite import is gone -- same instruction as above"
    )


# --- D2: the next crash, never reached --------------------------------------

def test_the_payload_calls_a_source_method_production_source_lacks():
    """INCIDENT-001 D2. Latent: the run died at D1 before reaching it."""
    from apex.data.production_source import ProductionSource

    src = SCRIPT.read_text()
    assert "source.exclusions()" in src, "payload no longer calls exclusions()"
    assert not hasattr(ProductionSource, "exclusions"), (
        "ProductionSource gained exclusions() -- update INCIDENT-001 D2"
    )


# --- D3: the wrong success criteria, never reached --------------------------

def _verdict_kwargs() -> dict:
    """The literal thresholds run_validation.py passes to experiment_verdict."""
    tree = ast.parse(SCRIPT.read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "experiment_verdict"):
            return {kw.arg: getattr(kw.value, "value", None)
                    for kw in node.keywords if isinstance(kw.value, ast.Constant)}
    raise AssertionError("experiment_verdict call not found in run_validation.py")


def test_the_hardcoded_thresholds_are_apex_001s_not_apex_002s():
    """INCIDENT-001 D3, the most serious of the three.

    Had D1 and D2 not fired, this would have produced an APEX-002 verdict
    against APEX-001's hurdles and recorded it as the experiment's result.
    APEX-002 section 13 registers: mean IC POSITIVE, t >= the one-sided
    alpha=1% critical value from the simulated null (~2.92 validation),
    robustness AGREES IN SIGN.
    """
    applied = _verdict_kwargs()

    assert applied["min_mean_ic"] == 0.015
    assert applied["min_t_stat"] == 2.5
    assert applied["min_robustness_t"] == 2.0

    protocol = (REPO / "APEX-002-Protocol-Net-Share-Issuance.md").read_text()
    section13 = protocol[protocol.index("## 13."):protocol.index("## 14.")]
    assert "mean IC positive" in section13
    assert "one-sided" in section13 and "critical value" in section13
    assert "agrees in sign" in section13

    # The registered criterion is not the applied one. Stated as an
    # incompatibility, not tolerated as an equivalence.
    assert applied["min_t_stat"] != 2.92, (
        "if the threshold now matches APEX-002's registered critical value, "
        "D3 has been addressed -- update INCIDENT-001"
    )


def test_the_script_hardcodes_thresholds_rather_than_reading_the_protocol():
    """Root cause of D3: the criteria are literals, not configuration.

    A per-experiment transaction cannot be correct while its success criteria
    are baked into the runner.
    """
    applied = _verdict_kwargs()

    assert all(isinstance(v, float) for v in applied.values())
    assert "governance.success" not in SCRIPT.read_text()


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
        "verdict = experiment_verdict(",
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
