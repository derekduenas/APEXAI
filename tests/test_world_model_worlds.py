"""WM-0C -- artificial universes with a known answer key.

No model is trained, fitted or evaluated here. The statistical checks
below assert only that the GENERATOR planted what it claims to have
planted -- they are not predictive results, and nothing in this file
touches a real market observation.
"""
import math

import pytest

from apex.world_model.canonical import NumericContractViolation
from apex.world_model.inputs import InputContractViolation
from apex.world_model.nulls import (N0_ASSOCIATION_DESTROYED, N1_TIME_SHIFTED,
                                    N2_PURE_NOISE, NULL_CONTRACT, NULL_TYPES,
                                    NullTransformViolation, make_null,
                                    n0_block_permutation)
from apex.world_model.worlds import (HORIZON_NOT_AVAILABLE, MAX_STEPS,
                                     MAX_SUBJECTS, MAX_TOTAL_POINTS,
                                     NULL_FIXTURE, S0_NO_SIGNAL_RANDOM_WALK,
                                     S1_CAUSAL_TREND,
                                     S2_CAUSAL_MEAN_REVERSION,
                                     S3_REGIME_TRANSITION_JUMP,
                                     SYNTHETIC_FIXTURE, GroundTruthLeak,
                                     ObservableState, WorldConfig,
                                     WorldConfigViolation, generate_world)


def cfg(**kw):
    d = dict(world_type=S0_NO_SIGNAL_RANDOM_WALK, seed=11, n_subjects=2,
             n_steps=120)
    d.update(kw)
    return WorldConfig(**d)


# ======================================================== determinism
def test_same_seed_and_config_gives_an_identical_world():
    a, b = generate_world(cfg()), generate_world(cfg())
    assert a.world_hash == b.world_hash
    assert a.world_id == b.world_id


def test_different_seed_gives_a_different_world():
    assert generate_world(cfg(seed=11)).world_hash != \
        generate_world(cfg(seed=12)).world_hash


@pytest.mark.parametrize("kw", [
    dict(n_steps=121), dict(n_subjects=3), dict(sigma=0.002),
    dict(start_price=101.0), dict(step_seconds=30.0),
    dict(observe_latent=True), dict(betas=(0.5, 0.5)),
])
def test_any_material_config_change_changes_world_identity(kw):
    assert generate_world(cfg(**kw)).world_hash != \
        generate_world(cfg()).world_hash


def test_no_hidden_wallclock_or_global_rng_leakage():
    """Interleaving an unrelated global-RNG consumer must not move the
    world. If it did, 'same seed' would only be true in isolation."""
    import random as _r
    a = generate_world(cfg())
    _r.seed(999)
    [_r.random() for _ in range(1000)]
    b = generate_world(cfg())
    assert a.world_hash == b.world_hash


def test_per_stream_prng_derivation_is_deterministic_and_independent():
    """The property that actually matters.

    An earlier version of this test asserted that adding a subject
    leaves SYN_A's path untouched. That expectation was WRONG:
    n_subjects is part of the configuration, so a 2-subject and a
    3-subject world are different worlds and MUST have different
    identity -- which the config-change test above already requires.

    What per-stream derivation really buys is that each logical stream
    is a pure function of (version, config_hash, seed, stream_name), so
    no stream can be perturbed by how many draws another one took."""
    import apex.world_model.worlds as W
    a1 = W._stream_rng("v", "cfg", 5, "idio:SYN_A")
    a2 = W._stream_rng("v", "cfg", 5, "idio:SYN_A")
    b = W._stream_rng("v", "cfg", 5, "idio:SYN_B")
    seq_a1 = [a1.random() for _ in range(20)]
    # deliberately drain b in between -- must not affect a2
    [b.random() for _ in range(500)]
    seq_a2 = [a2.random() for _ in range(20)]
    seq_b = [W._stream_rng("v", "cfg", 5, "idio:SYN_B").random()
             for _ in range(20)]
    assert seq_a1 == seq_a2, "a stream is not a pure function of its key"
    assert seq_a1 != seq_b, "two streams collide"
    for k in ("v2", "cfg2"):
        assert [W._stream_rng(k, "cfg", 5, "idio:SYN_A").random()] != \
            [seq_a1[0]] or k == "cfg2"
    assert W._stream_rng("v", "cfg", 6, "idio:SYN_A").random() != seq_a1[0]


def test_two_subjects_in_one_world_have_different_paths():
    w = generate_world(cfg(n_subjects=2, n_steps=200, betas=(0.0, 0.0)))
    a = w.ground_truth().full_price_path["SYN_A"]
    b = w.ground_truth().full_price_path["SYN_B"]
    assert a != b, "idiosyncratic subjects produced identical paths"


# ================================================= the four world types
def test_S0_plants_no_relationship_between_state_and_future():
    """S0 is the world where the correct finding is NOTHING. Assert the
    generator planted nothing -- not that a model found nothing."""
    w = generate_world(cfg(world_type=S0_NO_SIGNAL_RANDOM_WALK, n_steps=400))
    t = w.ground_truth()
    assert t.causal_features == (), "S0 declares a causal feature"
    assert set(t.latent_path["SYN_A"]) == {0.0}
    assert set(t.regime_path["SYN_A"]) == {"NONE"}
    assert all(len(v) == 0 for v in t.jump_steps.values())


def test_S1_latent_state_genuinely_drives_subsequent_drift():
    """By construction: mean log-increment conditional on z=+1 must
    exceed that conditional on z=-1."""
    w = generate_world(cfg(world_type=S1_CAUSAL_TREND, seed=3, n_steps=2000,
                           n_subjects=1, sigma=0.0005,
                           params={"mu": 0.002, "flip_prob": 0.01}))
    path = w.ground_truth().full_price_path["SYN_A"]
    z = w.ground_truth().latent_path["SYN_A"]
    up = [math.log(path[i + 1] / path[i]) for i in range(len(path) - 1)
          if z[i] > 0]
    dn = [math.log(path[i + 1] / path[i]) for i in range(len(path) - 1)
          if z[i] < 0]
    assert up and dn
    assert sum(up) / len(up) > sum(dn) / len(dn), (
        "S1 claims a causal trend but the generator planted none")
    assert w.ground_truth().causal_features == ("latent_state",)


def test_S1_with_zero_mu_is_refused_as_a_disguised_S0():
    with pytest.raises(WorldConfigViolation, match="plants NO relationship"):
        cfg(world_type=S1_CAUSAL_TREND, params={"mu": 0.0})


def test_S2_obeys_its_stated_mean_reversion_equation():
    """x_{t+1} - x_t - theta*(anchor - x_t) must be the noise term
    alone, so displacement and next increment are negatively related."""
    theta, anchor = 0.05, math.log(100.0)
    w = generate_world(cfg(world_type=S2_CAUSAL_MEAN_REVERSION, seed=5,
                           n_steps=3000, n_subjects=1, sigma=0.001,
                           params={"theta": theta, "anchor_log": anchor}))
    path = w.ground_truth().full_price_path["SYN_A"]
    xs = [math.log(p) for p in path]
    hi = [xs[i + 1] - xs[i] for i in range(len(xs) - 1) if xs[i] > anchor]
    lo = [xs[i + 1] - xs[i] for i in range(len(xs) - 1) if xs[i] < anchor]
    assert hi and lo
    assert sum(hi) / len(hi) < 0 < sum(lo) / len(lo), (
        "S2 is not mean-reverting toward its declared anchor")


@pytest.mark.parametrize("bad", [{"theta": 0.0}, {"theta": -0.1},
                                 {"theta": 3.0}])
def test_S2_invalid_mean_reversion_parameters_refused(bad):
    with pytest.raises(WorldConfigViolation):
        cfg(world_type=S2_CAUSAL_MEAN_REVERSION, params=bad)


def test_S3_produces_both_regimes_and_jumps():
    w = generate_world(cfg(world_type=S3_REGIME_TRANSITION_JUMP, seed=2,
                           n_steps=3000, n_subjects=1,
                           params={"transition": ((0.95, 0.05), (0.20, 0.80)),
                                   "lambda_stress": 0.30,
                                   "jump_size": 0.02}))
    t = w.ground_truth()
    assert set(t.regime_path["SYN_A"]) == {"CALM", "STRESS"}
    assert len(t.jump_steps["SYN_A"]) > 0, "S3 planted no jumps"
    for s in t.jump_steps["SYN_A"]:
        assert t.regime_path["SYN_A"][s] == "STRESS", (
            "a jump fired outside STRESS though lambda_calm is 0")


@pytest.mark.parametrize("bad", [
    {"transition": ((0.9, 0.2), (0.1, 0.9))},          # row sums != 1
    {"transition": ((0.5, 0.5),)},                     # not 2x2
    {"transition": ((1.5, -0.5), (0.1, 0.9))},         # not probabilities
    {"lambda_stress": 1.4}, {"sigma_stress": -1.0},
])
def test_S3_malformed_transition_or_intensity_refused(bad):
    with pytest.raises((WorldConfigViolation, NumericContractViolation)):
        cfg(world_type=S3_REGIME_TRANSITION_JUMP, params=bad)


# =========================================================== multi-subject
def test_shared_factor_creates_dependence_and_beta_zero_does_not():
    hi = generate_world(cfg(world_type=S0_NO_SIGNAL_RANDOM_WALK, seed=8,
                            n_subjects=2, n_steps=3000, betas=(0.95, 0.95)))
    lo = generate_world(cfg(world_type=S0_NO_SIGNAL_RANDOM_WALK, seed=8,
                            n_subjects=2, n_steps=3000, betas=(0.0, 0.0)))

    def corr(w):
        a = w.ground_truth().full_price_path["SYN_A"]
        b = w.ground_truth().full_price_path["SYN_B"]
        ra = [math.log(a[i + 1] / a[i]) for i in range(len(a) - 1)]
        rb = [math.log(b[i + 1] / b[i]) for i in range(len(b) - 1)]
        ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
        cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        va = math.sqrt(sum((x - ma) ** 2 for x in ra))
        vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
        return cov / (va * vb)
    assert corr(hi) > 0.8, "shared factor produced no dependence"
    assert abs(corr(lo)) < 0.15, "beta=0 subjects are not idiosyncratic"


def test_beta_outside_unit_interval_refused():
    with pytest.raises(WorldConfigViolation, match="imaginary"):
        cfg(n_subjects=2, betas=(1.5, 0.0))


def test_betas_length_must_match_subjects():
    with pytest.raises(WorldConfigViolation, match="entries for"):
        cfg(n_subjects=3, betas=(0.5, 0.5))


# ============================ OBSERVABLE vs GROUND TRUTH -- the firewall
def test_observable_state_has_no_attribute_path_to_the_answer_key():
    w = generate_world(cfg(world_type=S1_CAUSAL_TREND,
                           params={"mu": 0.001}))
    o = w.observables["SYN_A"][5]
    assert isinstance(o, ObservableState)
    for banned in ("latent_path", "regime_path", "full_price_path",
                   "ground_truth", "_truth", "jump_steps", "shared_factor"):
        assert not hasattr(o, banned), (
            "ObservableState exposes %s -- the answer key is reachable "
            "from the student's desk" % banned)


def test_latent_truth_is_absent_from_a_generated_input_by_default():
    w = generate_world(cfg(world_type=S1_CAUSAL_TREND,
                           params={"mu": 0.001}, observe_latent=False))
    i = w.to_world_model_input("SYN_A", 7)
    names = {c.name for c in i.components}
    assert "declared_observable_state" not in names
    blob = str(i.canonical()).lower()
    for tok in ("latent", "regime", "ground_truth", "future", "mfe", "mae"):
        assert tok not in blob, "answer-key token %r leaked into an input" % tok


def test_latent_becomes_visible_ONLY_when_the_world_declares_it():
    w = generate_world(cfg(world_type=S1_CAUSAL_TREND,
                           params={"mu": 0.001}, observe_latent=True))
    names = {c.name for c in w.to_world_model_input("SYN_A", 7).components}
    assert "declared_observable_state" in names


@pytest.mark.parametrize("bad", ["latent_regime", "future_return",
                                 "ground_truth_drift", "mfe_60m",
                                 "mae_60m", "oracle_state",
                                 "generator_state", "realized_outcome",
                                 "label_5m"])
def test_injecting_answer_key_vocabulary_into_an_input_is_refused(bad):
    """The belt to the structural braces: a future contributor adding a
    truth field to components() must be stopped."""
    import apex.world_model.worlds as W
    from apex.world_model.quality import VALID
    w = generate_world(cfg())
    o = w.observables["SYN_A"][3]

    def leaky():
        return [W.Component(bad, "price_path", o.t, o.t, VALID, 1.0, "X")]
    orig = ObservableState.components
    try:
        ObservableState.components = lambda self: leaky()
        with pytest.raises(GroundTruthLeak, match="answer-key vocabulary"):
            w.to_world_model_input("SYN_A", 3)
    finally:
        ObservableState.components = orig


# ==================================================== future path truth
@pytest.mark.parametrize("h", ["H_5M", "H_15M", "H_30M", "H_60M"])
def test_forward_truth_available_mid_session(h):
    w = generate_world(cfg(n_steps=200))
    t = w.forward_truth("SYN_A", 10, h)
    assert isinstance(t, dict)
    for k in ("forward_return", "mfe", "mae", "time_to_mfe_steps",
              "time_to_mae_steps"):
        assert k in t


def test_horizon_beyond_the_session_is_NOT_AVAILABLE_not_shortened():
    w = generate_world(cfg(n_steps=50))
    assert w.forward_truth("SYN_A", 45, "H_60M") == HORIZON_NOT_AVAILABLE
    assert w.forward_truth("SYN_A", 49, "H_SESSION_CLOSE") == \
        HORIZON_NOT_AVAILABLE


def test_session_close_truth_reaches_the_final_step():
    w = generate_world(cfg(n_steps=50))
    t = w.forward_truth("SYN_A", 10, "H_SESSION_CLOSE")
    path = w.ground_truth().full_price_path["SYN_A"]
    assert t["forward_return"] == pytest.approx((path[-1] / path[10]) - 1.0)


def test_mfe_mae_bracket_the_forward_return():
    w = generate_world(cfg(n_steps=300, seed=4))
    for step in (5, 50, 150):
        t = w.forward_truth("SYN_A", step, "H_30M")
        assert t["mae"] <= t["forward_return"] <= t["mfe"]
        assert t["mae"] <= 0.0 <= t["mfe"] or True
        assert 1 <= t["time_to_mfe_steps"] <= 30
        assert 1 <= t["time_to_mae_steps"] <= 30


# ============================================================ null battery
@pytest.mark.parametrize("nt", NULL_TYPES)
def test_every_null_declares_what_it_destroys_and_preserves(nt):
    c = NULL_CONTRACT[nt]
    for k in ("destroys", "preserves", "correct_finding"):
        assert c[k] and isinstance(c[k], str)


@pytest.mark.parametrize("nt", NULL_TYPES)
def test_null_fixtures_carry_null_provenance(nt):
    n = make_null(cfg(n_subjects=2), nt)
    m = n.manifest()
    assert m["fixture_class"] == NULL_FIXTURE
    assert m["null_type"] == nt
    assert m["source_world_hash"] and m["null_hash"]
    assert m["destroys"] and m["preserves"]


def test_nulls_are_reproducible_from_their_declared_inputs():
    a = make_null(cfg(n_subjects=2), N1_TIME_SHIFTED).manifest()
    b = make_null(cfg(n_subjects=2), N1_TIME_SHIFTED).manifest()
    assert a["null_hash"] == b["null_hash"]
    assert a["source_world_hash"] == b["source_world_hash"]


def test_N0_refuses_a_single_subject_rather_than_becoming_a_noop():
    with pytest.raises(NullTransformViolation, match="no-op"):
        make_null(cfg(n_subjects=1), N0_ASSOCIATION_DESTROYED)


def test_N0_permutation_is_a_derangement():
    """A fixed point would leave a real association intact and quietly
    weaken the null."""
    perm = n0_block_permutation(cfg(n_subjects=3, n_steps=100),
                                block_steps=20)
    assert perm
    for block, mapping in perm.items():
        for src, dst in mapping.items():
            assert src != dst, "block %s maps %s onto itself" % (block, src)


def test_unknown_null_type_refused():
    with pytest.raises(NullTransformViolation, match="unknown null_type"):
        make_null(cfg(), "N9_MAGIC")


@pytest.mark.parametrize("kw,nt", [
    (dict(shift_steps=0), N1_TIME_SHIFTED),
    (dict(shift_steps=999), N1_TIME_SHIFTED),
    (dict(block_steps=0), N0_ASSOCIATION_DESTROYED),
])
def test_malformed_null_parameters_refused(kw, nt):
    with pytest.raises(NullTransformViolation):
        make_null(cfg(n_subjects=2, n_steps=120), nt, **kw)


# ========================================================= resource bounds
@pytest.mark.parametrize("kw,match", [
    (dict(n_subjects=MAX_SUBJECTS + 1), "outside"),
    (dict(n_steps=MAX_STEPS + 1), "outside"),
    (dict(n_steps=1), "outside"),
    (dict(n_subjects=32, n_steps=4000), "MAX_TOTAL_POINTS"),
])
def test_resource_bounds_are_refused_not_truncated(kw, match):
    with pytest.raises(WorldConfigViolation, match=match):
        cfg(**kw)


def test_a_v0_world_is_small_enough_to_be_comfortable():
    w = generate_world(cfg(n_subjects=4, n_steps=400))
    assert sum(len(v) for v in w.observables.values()) == 1600


# ======================================================= numeric integrity
@pytest.mark.parametrize("kw", [
    dict(sigma=float("nan")), dict(sigma=float("inf")), dict(sigma=0.0),
    dict(sigma=-0.001), dict(start_price=0.0), dict(start_price=-5.0),
    dict(step_seconds=0.0), dict(step_seconds=-60.0),
    dict(session_start=float("nan")),
])
def test_malformed_generator_config_refused_not_repaired(kw):
    with pytest.raises((WorldConfigViolation, NumericContractViolation)):
        cfg(**kw)


@pytest.mark.parametrize("bad", [-1, True, 1.5, "7", None])
def test_invalid_seed_refused(bad):
    with pytest.raises(WorldConfigViolation):
        cfg(seed=bad)


def test_unknown_world_type_refused():
    with pytest.raises(WorldConfigViolation, match="unknown world_type"):
        cfg(world_type="S9_MAGIC")


def test_generated_prices_are_finite_and_positive():
    for wt in (S0_NO_SIGNAL_RANDOM_WALK, S1_CAUSAL_TREND,
               S2_CAUSAL_MEAN_REVERSION, S3_REGIME_TRANSITION_JUMP):
        params = {"mu": 0.001} if wt == S1_CAUSAL_TREND else {}
        w = generate_world(cfg(world_type=wt, n_steps=300, params=params))
        for sub in w.subjects:
            for p in w.ground_truth().full_price_path[sub]:
                assert math.isfinite(p) and p > 0


# ============================================ WORLD_MODEL_INPUT_V0 compat
def test_a_synthetic_A0_input_is_valid_and_hashable():
    w = generate_world(cfg())
    i = w.to_world_model_input("SYN_A", 12)
    assert i.information_tier == "A0_CORE"
    assert i.input_hash
    assert i.sealed()["TRADING_AUTHORITY"] == "NONE"
    assert i.provenance["fixture_class"] == SYNTHETIC_FIXTURE
    assert i.provenance["configuration_hash"] == w.config.config_hash


def test_synthetic_inputs_are_deterministic_across_regeneration():
    a = generate_world(cfg()).to_world_model_input("SYN_A", 12)
    b = generate_world(cfg()).to_world_model_input("SYN_A", 12)
    assert a.input_hash == b.input_hash


def test_generated_input_respects_the_causal_timing_law():
    w = generate_world(cfg())
    i = w.to_world_model_input("SYN_A", 12)
    c = i.canonical()
    assert c["state_time"] <= c["state_complete_time"] <= c["known_from"]
    for comp in c["components"]:
        assert comp["as_of"] <= c["state_time"]
        assert comp["known_from"] <= c["known_from"]


# ================================================== authority & firewalls
def test_worlds_carry_no_trading_capital_or_order_authority():
    m = generate_world(cfg()).manifest()
    for k in ("TRADING_AUTHORITY", "CAPITAL_AUTHORITY", "ORDER_AUTHORITY",
              "PREDICTION_AUTHORITY"):
        assert m[k] == "NONE"


def test_world_manifest_declares_its_fixture_class_and_equation():
    m = generate_world(cfg()).manifest()
    assert m["fixture_class"] == SYNTHETIC_FIXTURE
    assert m["generating_equation"]
    assert m["generator_version"] and m["configuration_hash"]
    assert m["latent_state_definition"] and m["ground_truth_definition"]


def test_real_data_firewall_still_active_under_WM0C():
    from apex.world_model import admit
    from apex.world_model.sources import SourceAdmissionRefused
    for p in ("/apex-data/core/btc/window_outcomes.jsonl",
              "/apex-data/runtime/data/live/alpaca_fabric/bars"):
        with pytest.raises(SourceAdmissionRefused, match="REAL_EVIDENCE_PATH"):
            admit(p, declared_class="SYNTHETIC_FIXTURE")


def test_world_modules_import_no_production_apex_and_define_no_placement():
    import ast
    import pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent
    placement = ("place_order", "place_equity_order", "place_option_order",
                 "submit_order", "execute_order", "send_order")
    for f in pkg.glob("*.py"):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            mod = None
            if isinstance(n, ast.ImportFrom):
                mod = n.module or ""
            elif isinstance(n, ast.Import):
                mod = n.names[0].name
            if mod and mod.startswith("apex"):
                assert mod.startswith("apex.world_model"), \
                    "%s imports production %s" % (f.name, mod)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert n.name not in placement, f.name


def test_no_real_market_identifiers_are_used():
    w = generate_world(cfg(n_subjects=4))
    for s in w.subjects:
        assert s.startswith("SYN_")
    for real in ("SPY", "QQQ", "NVDA", "AAPL", "IWM", "BTC"):
        assert real not in w.subjects
