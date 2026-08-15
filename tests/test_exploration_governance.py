"""Track 5 adversarial suite: the machinery must FAIL CLOSED on every listed
leak. Not happy paths -- each test is an attack that must be caught.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.exploration.accounting import TrialLedger
from apex.exploration.candidate import CandidateRefused, emit_candidate
from apex.exploration.cv import (
    ExplorationError, PurgedKFold, require_exploration_window, walk_forward,
)
from apex.exploration.stats import deflated_sharpe, pbo_cscv

CFG = load_config("experiment", "costs", "synthetic", "sharadar")


# --- overlapping-label leakage: purging visibly removes the inflation --------

def test_purged_cv_removes_overlap_inflation():
    """Two halves: (a) the leak is REAL -- under near-naive folds, a test
    sample near the fold boundary correlates ~0.9 with its nearest train
    LABEL, because 20-day labels share 19 days; (b) purge+embargo makes the
    channel STRUCTURALLY IMPOSSIBLE -- no test sample sits within the label
    horizon of any train sample, so there is nothing left to copy."""
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, 620)
    y = pd.Series(noise).rolling(20).mean().shift(-19).dropna().to_numpy()
    n = len(y)
    horizon = 20

    # (a) the attack works on near-naive folds
    boundary_pairs = []
    for train, test in PurgedKFold(5, label_horizon=1, embargo=1).split(n):
        for t in test:
            d = np.abs(train - t)
            if d.min() <= 6:                       # boundary-exposed sample
                boundary_pairs.append((y[t], y[train[np.argmin(d)]]))
    a = np.array(boundary_pairs)
    assert len(a) > 20
    leak_corr = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
    assert leak_corr > 0.6, f"the overlap leak should be blatant; got {leak_corr:.2f}"

    # (b) purged folds leave NO test sample inside the horizon of ANY train
    for train, test in PurgedKFold(5, label_horizon=horizon,
                                   embargo=horizon).split(n):
        min_gap = min(int(np.abs(train - t).min()) for t in test)
        assert min_gap > horizon - 1, (
            f"a test sample sits {min_gap} from train; the label windows "
            f"overlap and the leak channel is open")


def test_counterexample_an_insufficient_embargo_is_refused_not_warned():
    with pytest.raises(ExplorationError, match="Refused, not warned"):
        PurgedKFold(n_splits=5, label_horizon=20, embargo=5)


def test_walk_forward_train_never_reaches_unresolved_labels():
    for train, fold in walk_forward(500, 4, label_horizon=20):
        assert train.max() < fold.min() - 19, (
            "training on labels that resolve inside the test fold is lookahead")


# --- holdout / validation access: structurally unreachable -------------------

def test_exploration_window_refuses_validation_and_holdout_dates():
    val_start = pd.Timestamp(CFG.period("validation")["start"])
    with pytest.raises(ExplorationError, match="in-sample only"):
        require_exploration_window(
            pd.bdate_range(val_start - pd.Timedelta(days=30), periods=60), CFG)
    with pytest.raises(ExplorationError):
        require_exploration_window(
            pd.DatetimeIndex([pd.Timestamp(CFG.period("holdout")["end"])]), CFG)


def test_counterexample_a_pure_in_sample_window_is_admitted():
    require_exploration_window(pd.bdate_range("2010-01-01", "2015-12-31"), CFG)


# --- trial accounting: the sweep cannot hide ---------------------------------

def test_every_fit_in_a_sweep_is_its_own_trial(tmp_path):
    led = TrialLedger(tmp_path / "trials.jsonl")
    rng = np.random.default_rng(1)
    for lr in (0.1, 0.3):
        for depth in (2, 3, 4):
            for w in (5, 10):
                led.record("gbm_family", {"lr": lr, "depth": depth, "w": w},
                           float(rng.normal()), "purged5")
    assert led.denominator("gbm_family") == 12
    assert led.verify() == 12


def test_counterexample_underreporting_the_denominator_is_refused(tmp_path):
    led = TrialLedger(tmp_path / "trials.jsonl")
    for i in range(30):
        led.record("fam", {"i": i}, float(i), "purged5")
    with pytest.raises(CandidateRefused, match="not negotiable"):
        emit_candidate(hypothesis="h", family="fam", feature_definitions={"f": "x"},
                       claimed_trials=1, ledger=led, purged_cv_score=0.1,
                       walk_forward_score=0.1, observed_sr=0.2, n_periods=200,
                       pbo=0.2, correlation_to_validated={"gp": 0.1})


def test_the_dsr_is_computed_at_the_true_denominator(tmp_path):
    """Winner selection cannot launder itself: 30 trials, and the emitted
    DSR must be the 30-trial DSR, not a self-reported 1-trial one."""
    led = TrialLedger(tmp_path / "trials.jsonl")
    for i in range(30):
        led.record("fam", {"i": i}, float(i), "purged5")
    cand = emit_candidate(hypothesis="h", family="fam",
                          feature_definitions={"f": "x"}, claimed_trials=30,
                          ledger=led, purged_cv_score=0.1, walk_forward_score=0.1,
                          observed_sr=0.2, n_periods=200, pbo=0.2,
                          correlation_to_validated={"gp": 0.1})
    assert cand.dsr["n_trials"] == 30
    solo = deflated_sharpe(0.2, 1, 200)
    assert cand.dsr["dsr"] < solo["dsr"], (
        "30-way selection must deflate the Sharpe below the 1-trial reading")


def test_no_select_best_exists_anywhere_in_the_package():
    import apex.exploration.accounting as A
    import apex.exploration.candidate as C
    import apex.exploration.cv as V
    import apex.exploration.stats as S
    for mod in (A, C, V, S):
        for banned in ("select_best", "best_model", "pick_winner", "optimise",
                       "optimize"):
            assert not hasattr(mod, banned), f"{mod.__name__} exposes {banned}"


# --- PBO: overfit selection exposed, genuine skill acquitted ----------------

def test_pbo_exposes_random_winner_selection_and_acquits_skill():
    rng = np.random.default_rng(7)
    random_scores = rng.normal(0, 1, (240, 40))         # 40 skill-less trials
    skilled = rng.normal(0, 1, (240, 40))
    skilled[:, 7] += 0.6                                # one real performer
    assert pbo_cscv(random_scores)["pbo"] > 0.35, "random selection must look overfit"
    assert pbo_cscv(skilled)["pbo"] < 0.15, "genuine skill must survive CSCV"


def test_deflated_sharpe_reference_values():
    d = deflated_sharpe(0.15, n_trials=1, n_periods=252)
    assert d["sr0_expected_max"] == 0.0
    assert d["dsr"] == pytest.approx(0.9913, abs=0.002)  # plain SR test
    d100 = deflated_sharpe(0.15, n_trials=100, n_periods=252)
    assert d100["sr0_expected_max"] > 0.1
    assert d100["dsr"] < d["dsr"]


# --- regime hindsight --------------------------------------------------------

def test_a_regime_feature_without_labelstore_provenance_is_refused(tmp_path):
    led = TrialLedger(tmp_path / "trials.jsonl")
    led.record("fam", {}, 0.1, "purged5")
    with pytest.raises(CandidateRefused, match="hindsight"):
        emit_candidate(hypothesis="h", family="fam",
                       feature_definitions={"vol_regime_flag": "hmm"},
                       claimed_trials=1, ledger=led, purged_cv_score=0.1,
                       walk_forward_score=0.1, observed_sr=0.1, n_periods=100,
                       pbo=0.3, correlation_to_validated={"gp": 0.0})
    # with provenance cited, the same candidate emits
    emit_candidate(hypothesis="h", family="fam",
                   feature_definitions={"vol_regime_flag": "hmm"},
                   claimed_trials=1, ledger=led, purged_cv_score=0.1,
                   walk_forward_score=0.1, observed_sr=0.1, n_periods=100,
                   pbo=0.3, correlation_to_validated={"gp": 0.0},
                   regime_feature_provenance="results/world/labels.jsonl")


def test_a_candidate_without_correlation_to_validated_is_refused(tmp_path):
    led = TrialLedger(tmp_path / "trials.jsonl")
    led.record("fam", {}, 0.1, "purged5")
    with pytest.raises(CandidateRefused, match="already tested"):
        emit_candidate(hypothesis="h", family="fam", feature_definitions={"f": "x"},
                       claimed_trials=1, ledger=led, purged_cv_score=0.1,
                       walk_forward_score=0.1, observed_sr=0.1, n_periods=100,
                       pbo=0.3, correlation_to_validated={})


# --- determinism -------------------------------------------------------------

def test_folds_are_deterministic():
    a = [(t.tolist(), f.tolist()) for t, f in
         PurgedKFold(5, 20, 20).split(500)]
    b = [(t.tolist(), f.tolist()) for t, f in
         PurgedKFold(5, 20, 20).split(500)]
    assert a == b
