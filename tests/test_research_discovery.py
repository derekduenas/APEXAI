"""The research discovery layer. Every load-bearing boundary, with counterexamples.

The discovery layer's whole purpose is to let a human ask "why should this
work?" before spending one of three remaining credits, WITHOUT letting the
machine turn an idea into an experiment, tune it, or let a failed result choose
its successor. Each of those is a refusal here, and each refusal is proven able
to fire.

No hypothesis in this file is a candidate for APEX-003. The fixtures are inert.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from apex.config import load_config
from apex.research import gate, hypothesis, novelty, swarm, twin

CFG = load_config("experiment", "costs", "synthetic", "sharadar")
REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# fixtures -- inert, never candidates
# --------------------------------------------------------------------------

def _science(**over) -> dict:
    base = {
        "hypothesis": "fixture placeholder",
        "economic_rationale": "none; a fixture",
        "signal_definition": "placeholder",
        "directional_prediction": "none",
        "timing": "formation T",
        "data_requirements": "none",
        "universe": "frozen section 3",
        "horizon": "20 trading days",
        "falsification_criterion": "not applicable",
        "title": "FIXTURE",
        "author": "test",
        "date": "2026-08-12",
    }
    base.update(over)
    return base


def _hyp(*, feature_set=("prof_gross_profitability",), epoch=hypothesis.BEFORE_002,
         mechanism="fixture mechanism", novelty_claim="fixture claim",
         descends="", **science) -> hypothesis.HypothesisDossier:
    return hypothesis.HypothesisDossier(
        content=_science(**science),
        provenance=hypothesis.Provenance(
            epoch=epoch, author="test", created="2026-08-12T00:00:00+00:00",
            descends_from_experiment=descends,
        ),
        economic_mechanism=mechanism,
        feature_set=tuple(feature_set),
        novelty_claim=novelty_claim,
    )


# --- PART 4: one authoritative definition ----------------------------------

def test_the_screenable_content_is_a_certified_dossier():
    """The hypothesis reuses screening.Dossier -- not a second format."""
    from apex.governance.screening import Dossier

    h = _hyp()
    assert isinstance(h.screenable(), Dossier)
    assert h.dossier_hash == h.screenable().hash


def test_counterexample_an_incomplete_hypothesis_is_refused_by_the_shared_definition():
    """Completeness is judged by the certified Dossier, in one place."""
    from apex.governance.screening import DossierIncomplete

    with pytest.raises(DossierIncomplete):
        _hyp(economic_rationale="   ")


def test_counterexample_a_hypothesis_with_no_features_is_refused():
    with pytest.raises(hypothesis.HypothesisError, match="feature_ids"):
        _hyp(feature_set=())


def test_provenance_is_not_part_of_the_scientific_identity():
    """Part 4/7: re-annotating provenance must not change the idea's hash.

    Iterating the SCIENCE changes identity; noting where it came from does not.
    """
    a = _hyp(epoch=hypothesis.BEFORE_002)
    b = _hyp(epoch=hypothesis.DURING_002)

    assert a.dossier_hash == b.dossier_hash, "provenance leaked into the hash"
    assert a.provenance_hash != b.provenance_hash


def test_counterexample_changing_the_science_changes_the_hash():
    a = _hyp(horizon="20 trading days")
    b = _hyp(horizon="60 trading days")

    assert a.dossier_hash != b.dossier_hash


# --- PART 7: contamination control -----------------------------------------

def test_a_before_002_hypothesis_needs_no_rejustification():
    assert _hyp(epoch=hypothesis.BEFORE_002).requires_independent_rejustification() is False


def test_counterexample_a_postmortem_hypothesis_is_flagged_as_descendant():
    """APEX-002's post-mortem must not silently motivate the next hypothesis."""
    h = _hyp(epoch=hypothesis.POSTMORTEM_002)

    assert h.requires_independent_rejustification() is True
    assert h.provenance.is_descendant_of_failure is True


def test_counterexample_an_explicit_descendant_is_flagged_even_if_epoch_is_clean():
    """Declaring descent from a closed experiment flags it regardless of epoch."""
    h = _hyp(epoch=hypothesis.BEFORE_002, descends="APEX-002")

    assert h.requires_independent_rejustification() is True


def test_counterexample_an_invalid_epoch_is_refused():
    with pytest.raises(hypothesis.HypothesisError, match="epoch"):
        hypothesis.Provenance(epoch="whenever", author="t", created="t")


# --- PART 3: the digital twin is PIT-aware ---------------------------------

def _twin_inputs(feature_asof):
    dates = pd.Index(["A", "B", "C"], name="security_id")
    eligible = pd.Series([True, True, False], index=dates)
    rows = {"f": pd.Series([0.1, 0.2, 0.3], index=dates)}
    return eligible, rows, {"f": feature_asof}


def test_a_twin_state_is_deterministic():
    e, r, k = _twin_inputs("2010-06-01")
    a = twin.build_state(date=pd.Timestamp("2010-06-15"), dataset_fingerprint="fp",
                         eligible_row=e, feature_rows=r, knowable_asof=k)
    b = twin.build_state(date=pd.Timestamp("2010-06-15"), dataset_fingerprint="fp",
                         eligible_row=e, feature_rows=r, knowable_asof=k)
    assert a.digest() == b.digest()
    assert a.eligible_ids == ("A", "B")     # C ineligible, excluded


def test_counterexample_a_twin_that_uses_a_future_filing_is_refused():
    """PIT test: a feed dated after T cannot enter the state."""
    e, r, k = _twin_inputs("2010-07-01")     # after the formation date
    with pytest.raises(twin.TwinLeak, match="unknowable"):
        twin.build_state(date=pd.Timestamp("2010-06-15"), dataset_fingerprint="fp",
                         eligible_row=e, feature_rows=r, knowable_asof=k)


def test_a_twin_at_the_filing_date_itself_is_allowed():
    e, r, k = _twin_inputs("2010-06-15")     # exactly T
    state = twin.build_state(date=pd.Timestamp("2010-06-15"), dataset_fingerprint="fp",
                             eligible_row=e, feature_rows=r, knowable_asof=k)
    state.assert_no_future_leak()


# --- PART 6: novelty is a classification, not a score ----------------------

KNOWN = {"prof_gross_profitability", "val_book_to_market", "nsi",
         "f1_mom_63", "f4_vs_market"}
EXPERIMENTS = {
    "APEX-001": {"f1_mom_63", "f4_vs_market"},
    "APEX-002": {"nsi"},
}


def test_a_new_feature_set_is_novel():
    a = novelty.classify_novelty(
        _hyp(feature_set=("prof_gross_profitability",)),
        known_feature_ids=KNOWN, experiment_signatures=EXPERIMENTS, prior_dossiers={},
    )
    assert a.classification == novelty.NOVEL


def test_counterexample_the_same_feature_set_as_a_closed_experiment_is_a_modification():
    a = novelty.classify_novelty(
        _hyp(feature_set=("nsi",)),
        known_feature_ids=KNOWN, experiment_signatures=EXPERIMENTS, prior_dossiers={},
    )
    assert a.classification == novelty.MODIFICATION
    assert a.nearest_prior == "APEX-002"


def test_counterexample_a_subset_of_a_closed_experiment_is_redundant():
    a = novelty.classify_novelty(
        _hyp(feature_set=("f1_mom_63",)),
        known_feature_ids=KNOWN, experiment_signatures=EXPERIMENTS, prior_dossiers={},
    )
    assert a.classification == novelty.REDUNDANT


def test_counterexample_an_identical_prior_dossier_is_a_duplicate():
    h = _hyp(feature_set=("prof_gross_profitability",))
    a = novelty.classify_novelty(
        h, known_feature_ids=KNOWN, experiment_signatures=EXPERIMENTS,
        prior_dossiers={"otherhash": {"prof_gross_profitability"}},
    )
    assert a.classification == novelty.DUPLICATE


def test_a_multi_family_combination_is_a_recombination():
    a = novelty.classify_novelty(
        _hyp(feature_set=("nsi", "prof_gross_profitability")),
        known_feature_ids=KNOWN, experiment_signatures=EXPERIMENTS, prior_dossiers={},
    )
    assert a.classification == novelty.RECOMBINATION


def test_the_novelty_assessment_carries_no_number():
    a = novelty.classify_novelty(
        _hyp(), known_feature_ids=KNOWN, experiment_signatures=EXPERIMENTS,
        prior_dossiers={},
    )
    for numeric in ("score", "rank", "ic", "confidence"):
        assert not hasattr(a, numeric)


# --- PART 5: combinations need an economic reason, never a search ----------

def test_a_combination_requires_an_economic_reason():
    c = novelty.CombinationProposal(
        combination_class=novelty.RANK_COMPOSITE,
        feature_ids=("nsi", "prof_gross_profitability"),
        economic_reason="issuance and profitability are distinct mechanisms",
    )
    assert c.combination_class == novelty.RANK_COMPOSITE


def test_counterexample_a_combination_without_a_reason_is_refused():
    with pytest.raises(hypothesis.HypothesisError, match="belong together"):
        novelty.CombinationProposal(
            combination_class=novelty.ADDITIVE,
            feature_ids=("nsi", "f1_mom_63"), economic_reason="   ",
        )


def test_counterexample_a_single_feature_is_not_a_combination():
    with pytest.raises(hypothesis.HypothesisError, match="two features"):
        novelty.CombinationProposal(
            combination_class=novelty.ADDITIVE, feature_ids=("nsi",),
            economic_reason="x",
        )


def test_the_combination_object_cannot_hold_a_score():
    c = novelty.CombinationProposal(
        combination_class=novelty.ADDITIVE, feature_ids=("a", "b"),
        economic_reason="x",
    )
    for numeric in ("ic", "sharpe", "weight", "score"):
        assert not hasattr(c, numeric)


# --- PART 2/8: the swarm preserves disagreement, holds no score ------------

def _views(support_adversary=False):
    return (
        swarm.RoleView(role=swarm.THEORIST, supports=True, reasoning="mechanism holds"),
        swarm.RoleView(role=swarm.ADVERSARY, supports=support_adversary,
                       reasoning="looked for look-ahead",
                       objections=() if support_adversary else ("possible accrual artefact",)),
        swarm.RoleView(role=swarm.REPLICATION, supports=True,
                       reasoning="distinct from momentum and issuance"),
    )


def _dossier(h=None, views=None):
    h = h or _hyp()
    a = novelty.classify_novelty(h, known_feature_ids=KNOWN,
                                 experiment_signatures=EXPERIMENTS, prior_dossiers={})
    return swarm.assemble(h, a, views or _views())


def test_a_role_view_cannot_express_a_score():
    v = swarm.RoleView(role=swarm.QUANT, supports=True, reasoning="x")
    for numeric in ("score", "ic", "confidence", "expected_return"):
        assert not hasattr(v, numeric)


def test_counterexample_a_dossier_without_the_adversary_is_refused():
    with pytest.raises(swarm.SwarmError, match="adversarial"):
        swarm.assemble(_hyp(), _dossier().novelty,
                       (swarm.RoleView(role=swarm.THEORIST, supports=True,
                                       reasoning="x"),
                        swarm.RoleView(role=swarm.REPLICATION, supports=True,
                                       reasoning="y")))


def test_counterexample_a_dossier_without_replication_is_refused():
    with pytest.raises(swarm.SwarmError, match="replication"):
        swarm.assemble(_hyp(), _dossier().novelty,
                       (swarm.RoleView(role=swarm.THEORIST, supports=True,
                                       reasoning="x"),
                        swarm.RoleView(role=swarm.ADVERSARY, supports=True,
                                       reasoning="y")))


def test_disagreement_is_preserved_not_averaged():
    d = _dossier(views=_views(support_adversary=False))

    assert d.unrebutted() is True
    assert d.adversary_objections() == ("possible accrual artefact",)
    assert any("adversarial" in x for x in d.dissent())


def test_an_unknown_role_is_refused():
    with pytest.raises(swarm.SwarmError, match="unknown role"):
        swarm.RoleView(role="hype_man", supports=True, reasoning="x")


# --- PART 9/10: the screen/human boundary ----------------------------------

def _log(tmp_path):
    from apex.governance.screening import ScreenLog
    return ScreenLog(tmp_path / "results" / "screen_log.jsonl")


def _window():
    from apex.governance.screening import ScreenWindow
    return ScreenWindow.in_sample(CFG)


def _survives(_d, _w):
    from apex.governance.screening import SURVIVE, ScreenOutcome
    return ScreenOutcome(verdict=SURVIVE, reasons=("fixture",))


def test_a_survivor_reaches_a_review_packet_that_decides_nothing(tmp_path):
    d = _dossier()
    outcome = gate.screen_dossier(d, _survives, _log(tmp_path), _window(), CFG)

    packet = gate.ReviewPacket(dossier=d, screen_verdict=outcome.verdict)
    rendered = packet.render()

    assert packet.eligible_for_human_review() is True
    assert len(rendered["questions_for_the_human"]) == 8
    assert "does not register an experiment and cannot" in rendered["note"]


def test_counterexample_a_redundant_hypothesis_never_reaches_the_screen(tmp_path):
    """Part 9 pre-check: non-novel ideas do not fill the screen log."""
    d = _dossier(h=_hyp(feature_set=("f1_mom_63",)))   # subset of APEX-001

    with pytest.raises(gate.GateError, match="REDUNDANT"):
        gate.screen_dossier(d, _survives, _log(tmp_path), _window(), CFG)


def test_the_human_packet_surfaces_a_descendant_of_failure(tmp_path):
    """Part 7/10: the flag reaches the human, unresolved."""
    d = _dossier(h=_hyp(epoch=hypothesis.POSTMORTEM_002,
                        feature_set=("liq_amihud_illiquidity",)))
    packet = gate.ReviewPacket(dossier=d, screen_verdict="SURVIVE")

    assert any("DESCENDANT OF A FAILED EXPERIMENT" in f for f in packet.flags())


def test_the_discovery_layer_cannot_reach_registration():
    """Final rule, structural: no research module imports the ledger/pipeline."""
    gate.assert_not_auto_registerable()


def test_counterexample_the_no_registration_check_can_detect_a_breach(monkeypatch):
    """Prove the check above can fail: point it at a module that DOES reach
    the ledger, and it must raise."""
    from apex.audit import execution_path

    real = execution_path.module_closure

    def fake(root, name):
        if name.startswith("apex.research"):
            return {"apex.governance.ledger"}
        return real(root, name)

    monkeypatch.setattr("apex.research.gate.module_closure", fake, raising=False)
    # module_closure is imported inside the function, so patch the source
    monkeypatch.setattr(execution_path, "module_closure", fake)

    with pytest.raises(gate.GateError, match="registration"):
        gate.assert_not_auto_registerable()


def test_an_iterated_hypothesis_gets_a_new_identity_after_screening(tmp_path):
    """Part 9: changing the science after a screen is a NEW dossier hash.

    A researcher who edits a horizon after seeing a result cannot reuse the
    screened idea's identity.
    """
    original = _hyp(horizon="20 trading days")
    gate.screen_dossier(_dossier(h=original), _survives, _log(tmp_path), _window(), CFG)

    edited = _hyp(horizon="40 trading days")     # changed after screening
    assert edited.dossier_hash != original.dossier_hash
