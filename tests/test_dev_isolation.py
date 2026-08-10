"""A development dataset must be structurally incapable of becoming evidence.

Requirement, 2026-08-10: "Build the development path so misuse is structurally
impossible, not merely documented."

The threat is not a dishonest operator. It is an ordinary one, six months from
now, who runs the dev pipeline because it is the one that works, sees a
promising number, and does not know that DATA_LIMITATIONS.md exists. Every
guard below is placed so that person cannot get a verdict, cannot spend a
credit, and cannot open the holdout, no matter what they type.

Four independent refusals, because one of them will eventually be bypassed by
someone refactoring in good faith:

  1. the verdict layer refuses a dev fingerprint
  2. the ledger refuses a dev fingerprint
  3. the holdout gate refuses a dev fingerprint
  4. every dev report is stamped DEVELOPMENT / NON-CONFIRMATORY
"""

from __future__ import annotations

import pytest

from apex.dev.namespace import (
    DEV_PREFIX,
    DevelopmentDatasetRefused,
    dev_fingerprint,
    is_development,
    require_confirmatory,
)


# ---------------------------------------------------------------------------
# the namespace itself
# ---------------------------------------------------------------------------


def test_a_development_fingerprint_is_unmistakable():
    fingerprint = dev_fingerprint("edgar+stooq", "abc123")

    assert fingerprint.startswith(DEV_PREFIX)
    assert is_development(fingerprint)


def test_a_confirmatory_fingerprint_is_not_development():
    assert not is_development("a" * 64)
    assert not is_development("sharadar-snapshot:deadbeef")


def test_the_synthetic_rig_is_not_development_namespaced():
    """Synthetic is a TEST fixture, not a development dataset.

    Keeping them distinct matters: the synthetic null world is used by the
    calibration gates, which must keep working. Only real-but-unfit data gets
    the dev prefix.
    """
    from apex.config import load_config
    from apex.data.synthetic import SyntheticSource

    config = load_config("experiment", "costs", "synthetic")
    fingerprint = SyntheticSource(config=config, seed=1, alpha=0.0).dataset_fingerprint

    assert not is_development(fingerprint)


def test_require_confirmatory_passes_a_real_fingerprint():
    require_confirmatory("a" * 64, context="test")


def test_require_confirmatory_refuses_a_dev_fingerprint():
    with pytest.raises(DevelopmentDatasetRefused) as excinfo:
        require_confirmatory(dev_fingerprint("edgar+stooq", "abc"), context="test")

    message = str(excinfo.value)
    assert "DEVELOPMENT" in message
    assert "DATA_LIMITATIONS.md" in message


def test_an_empty_fingerprint_is_refused_too():
    """Ruling 1 already banned this; the dev guard must not create a hole."""
    with pytest.raises(Exception):
        require_confirmatory("", context="test")


# ---------------------------------------------------------------------------
# 1. THE VERDICT LAYER
# ---------------------------------------------------------------------------


def test_the_verdict_layer_refuses_a_development_dataset():
    """No promotion verdict can be computed from development data."""
    from apex.evaluate.verdict import experiment_verdict_for_dataset

    with pytest.raises(DevelopmentDatasetRefused):
        experiment_verdict_for_dataset(
            dataset_fingerprint=dev_fingerprint("edgar+stooq", "abc"),
            mean_ic=0.05,
            t_stat=9.9,
            robustness_t=8.8,
            min_mean_ic=0.015,
            min_t_stat=2.5,
            min_robustness_t=2.0,
        )


def test_a_spectacular_development_result_still_gets_no_verdict():
    """The dangerous case: numbers so good someone wants to believe them."""
    from apex.evaluate.verdict import experiment_verdict_for_dataset

    with pytest.raises(DevelopmentDatasetRefused) as excinfo:
        experiment_verdict_for_dataset(
            dataset_fingerprint=dev_fingerprint("edgar+stooq", "x"),
            mean_ic=0.42,
            t_stat=40.0,
            robustness_t=35.0,
            min_mean_ic=0.015,
            min_t_stat=2.5,
            min_robustness_t=2.0,
        )
    assert "not evidence" in str(excinfo.value).lower()


def test_the_verdict_layer_still_works_for_confirmatory_data():
    from apex.evaluate.verdict import PASS, experiment_verdict_for_dataset

    verdict = experiment_verdict_for_dataset(
        dataset_fingerprint="a" * 64,
        mean_ic=0.02, t_stat=2.7, robustness_t=2.3,
        min_mean_ic=0.015, min_t_stat=2.5, min_robustness_t=2.0,
    )

    assert verdict.verdict == PASS


# ---------------------------------------------------------------------------
# 2. THE LEDGER
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path):
    from apex.governance.ledger import ResearchLedger

    return ResearchLedger(path=tmp_path / "research_ledger.jsonl", budget=5)


def _spend(ledger, fingerprint, period="validation"):
    return ledger.spend(
        experiment_id="APEX-001",
        hypothesis="dev misuse attempt",
        period=period,
        config_hash="c" * 64,
        protocol_hash="p" * 64,
        conventions_hash="v" * 64,
        git_sha="deadbeef",
        dataset_hash=fingerprint,
        reason="attempting to spend a credit on development data",
    )


def test_the_ledger_refuses_to_spend_a_credit_on_development_data(ledger):
    with pytest.raises(DevelopmentDatasetRefused):
        _spend(ledger, dev_fingerprint("edgar+stooq", "abc"))

    assert ledger.credits_spent() == 0, "a refused dev spend must not cost a credit"


def test_the_ledger_refuses_to_record_a_development_result(ledger):
    _spend(ledger, "a" * 64)

    with pytest.raises(DevelopmentDatasetRefused):
        ledger.record_result(
            "APEX-001", "validation",
            p_value=0.001, t_stat=3.3, verdict="PASS",
            dataset_hash=dev_fingerprint("edgar+stooq", "abc"),
        )


def test_the_ledger_still_accepts_confirmatory_data(ledger):
    _spend(ledger, "a" * 64)
    ledger.record_result(
        "APEX-001", "validation",
        p_value=0.001, t_stat=3.3, verdict="PASS", dataset_hash="a" * 64,
    )

    assert ledger.credits_spent() == 1


def test_no_development_entry_can_exist_in_the_ledger_history(ledger):
    """Belt and braces: nothing dev-flavoured ever reaches the chain."""
    with pytest.raises(DevelopmentDatasetRefused):
        _spend(ledger, dev_fingerprint("edgar+stooq", "abc"))

    assert all(not is_development(e.dataset_hash) for e in ledger.entries())


# ---------------------------------------------------------------------------
# 3. THE HOLDOUT GATE
# ---------------------------------------------------------------------------


def test_the_holdout_gate_refuses_a_development_dataset(tmp_path):
    """Even with a token, a validation PASS and a credit available."""
    import shutil

    from apex.config import load_config
    from apex.registration import require_unlocked

    config = load_config("experiment", "costs", "synthetic")
    repo = tmp_path
    for key in ("experiment.protocol_file", "experiment.conventions_file"):
        name = config.get(key)
        shutil.copy(
            __import__("pathlib").Path(__file__).resolve().parent.parent / name, repo / name
        )
    (repo / "results" / "_unlocks").mkdir(parents=True)
    (repo / "results" / "_unlocks" / "holdout.unlock").write_text("attempting dev holdout")

    with pytest.raises(DevelopmentDatasetRefused):
        require_unlocked(
            config, "holdout", dev_fingerprint("edgar+stooq", "abc"), repo_root=repo
        )


def test_the_holdout_gate_refuses_development_data_even_for_in_sample(tmp_path):
    """in_sample is unlocked and free, so the refusal must come from elsewhere.

    A dev dataset running in-sample is LEGITIMATE -- that is the whole point of
    the development run -- so this must NOT raise. Asserted so nobody
    "hardens" the gate into uselessness.
    """
    from apex.config import load_config
    from apex.registration import require_unlocked

    config = load_config("experiment", "costs", "synthetic")
    require_unlocked(
        config, "in_sample", dev_fingerprint("edgar+stooq", "abc"), repo_root=tmp_path
    )


# ---------------------------------------------------------------------------
# 4. THE LABEL
# ---------------------------------------------------------------------------


def test_every_development_report_is_stamped():
    from apex.dev.namespace import development_banner

    banner = development_banner(dev_fingerprint("edgar+stooq", "abc"))

    assert "DEVELOPMENT" in banner
    assert "NON-CONFIRMATORY" in banner
    assert "DATA_LIMITATIONS.md" in banner


def test_the_banner_refuses_to_stamp_confirmatory_data():
    """The label means something only if it cannot be applied to real results."""
    from apex.dev.namespace import development_banner

    with pytest.raises(ValueError):
        development_banner("a" * 64)


def test_the_limitations_document_exists_and_says_what_it_must():
    """The guards reference this file; it must not be deletable without notice."""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "DATA_LIMITATIONS.md").read_text()

    assert "DEVELOPMENT ONLY" in text
    for topic in ("Delisted", "Corporate actions", "Identity matching", "Licens"):
        assert topic in text, f"DATA_LIMITATIONS.md no longer covers {topic}"
