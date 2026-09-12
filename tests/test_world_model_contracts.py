"""WM-0B -- the input and forecast contracts must refuse malformed truth.

Every fixture here is hand-built. No real market observation, no
resolved outcome, no label. That is not a formality: the whole point of
the contract is that it can be exercised before any real data is
permitted, so the boundary is proven while it is still cheap.
"""
import math

import pytest

from apex.world_model.canonical import (NumericContractViolation,
                                        content_hash, strict_float,
                                        strict_probability)
from apex.world_model.forecast import (H_5M, H_SESSION_CLOSE, HORIZONS,
                                       HORIZON_MINUTES,
                                       ForecastContractViolation,
                                       PredictiveDistribution,
                                       WorldModelForecast)
from apex.world_model.inputs import (A0_CORE, A1_OPTIONS, B_FULL_JOINT,
                                     Component, InputContractViolation,
                                     WorldModelInput)
from apex.world_model.quality import (NOT_AVAILABLE, NOT_ESTIMABLE,
                                      PROVIDER_ERROR, QualityContractViolation,
                                      SESSION_INAPPLICABLE, STALE, UNKNOWN,
                                      VALID)

T0 = 1_756_800_000.0


def _c(name, family, quality=VALID, value=1.0, as_of=None, kf=None):
    return Component(name=name, family=family,
                     as_of=T0 - 30 if as_of is None else as_of,
                     known_from=T0 - 20 if kf is None else kf,
                     quality=quality, value=value, source="SYNTHETIC")


def _inp(tier=A0_CORE, comps=None, **kw):
    d = dict(input_id="in-1", information_tier=tier, subject="SYN",
             state_time=T0, state_complete_time=T0 + 5,
             scheduled_time=T0 - 1, known_from=T0 + 10,
             source_state_id="twin-1", source_state_hash="deadbeef",
             feature_family_versions={"price_path": "v1"},
             components=tuple(comps if comps is not None
                              else [_c("close", "price_path")]))
    d.update(kw)
    return WorldModelInput(**d)


# =============================================== tiers, without mixing
def test_valid_A0_A1_B_inputs():
    a0 = _inp(A0_CORE, [_c("close", "price_path"), _c("nbbo", "sip_quotes_nbbo")])
    assert a0.input_hash
    a1 = _inp(A1_OPTIONS, [_c("close", "price_path"), _c("iv30", "implied_volatility")])
    assert a1.input_hash
    b = _inp(B_FULL_JOINT, [_c("close", "price_path"),
                            _c("iv30", "implied_volatility"),
                            _c("headline", "catalyst", value=None,
                               quality=UNKNOWN)])
    assert b.input_hash
    assert len({a0.input_hash, a1.input_hash, b.input_hash}) == 3


def test_A0_may_not_carry_options_state():
    """The leak that would make A0-vs-A1 comparisons meaningless."""
    with pytest.raises(InputContractViolation, match="not permitted in tier"):
        _inp(A0_CORE, [_c("iv30", "implied_volatility")])


def test_A1_may_not_carry_catalyst_or_cross_asset():
    for fam in ("catalyst", "macro_politics", "cross_asset_btc"):
        with pytest.raises(InputContractViolation, match="not permitted"):
            _inp(A1_OPTIONS, [_c("x", fam)])


def test_unknown_tier_refused():
    with pytest.raises(InputContractViolation, match="unknown information_tier"):
        _inp("A2_MAGIC")


# ============================================= asynchronous component time
def test_components_keep_their_own_timing():
    comps = [_c("daily_bar", "price_path", as_of=T0 - 86400, kf=T0 - 80000),
             _c("nbbo", "sip_quotes_nbbo", as_of=T0 - 0.04, kf=T0 - 0.02),
             _c("premkt", "premarket", as_of=T0 - 20000, kf=T0 - 19000)]
    i = _inp(A0_CORE, comps)
    got = {c["name"]: c["as_of"] for c in i.canonical()["components"]}
    assert len(set(got.values())) == 3, (
        "component timings were flattened -- the asynchrony IS the signal")


def test_component_cannot_describe_the_future_of_its_own_state():
    with pytest.raises(InputContractViolation, match="as_of.*state_time"):
        _inp(A0_CORE, [_c("peek", "price_path", as_of=T0 + 1)])


def test_component_cannot_be_knowable_after_the_sealed_input():
    with pytest.raises(InputContractViolation,
                       match="known_from.*input known_from"):
        _inp(A0_CORE, [_c("late", "price_path", kf=T0 + 999)])


@pytest.mark.parametrize("kw,match", [
    (dict(state_time=T0 + 100), "state_time.*state_complete_time"),
    (dict(state_complete_time=T0 + 999), "state_complete_time.*known_from"),
    (dict(state_time=T0 + 50, state_complete_time=T0 + 60, known_from=T0 + 20),
     "state_complete_time.*known_from"),
    (dict(scheduled_time=T0 + 6), "scheduled_time.*state_complete_time"),
])
def test_temporally_impossible_declarations_refused(kw, match):
    with pytest.raises(InputContractViolation, match=match):
        _inp(**kw)


def test_state_time_after_known_from_is_future_leakage():
    with pytest.raises(InputContractViolation):
        _inp(state_time=T0 + 500, state_complete_time=T0 + 600,
             known_from=T0 + 400)


# =================================================== missing is not zero
@pytest.mark.parametrize("q", [UNKNOWN, NOT_AVAILABLE, NOT_ESTIMABLE,
                               PROVIDER_ERROR, SESSION_INAPPLICABLE])
def test_non_observed_component_may_not_carry_a_number(q):
    with pytest.raises(QualityContractViolation, match="silently becomes zero"):
        _inp(A0_CORE, [_c("x", "price_path", quality=q, value=0.0)])


def test_the_seven_states_stay_distinct():
    comps = [_c("a", "price_path", VALID, 1.0),
             _c("b", "volume", STALE, 2.0),
             _c("c", "microstructure", UNKNOWN, None),
             _c("d", "breadth_context", NOT_AVAILABLE, None),
             _c("e", "market_relative", NOT_ESTIMABLE, None),
             _c("f", "sector_relative", PROVIDER_ERROR, None),
             _c("g", "pit_population", SESSION_INAPPLICABLE, None)]
    m = _inp(A0_CORE, comps).missingness()
    assert m == {VALID: 1, STALE: 1, UNKNOWN: 1, NOT_AVAILABLE: 1,
                 NOT_ESTIMABLE: 1, PROVIDER_ERROR: 1,
                 SESSION_INAPPLICABLE: 1}
    assert NOT_AVAILABLE in m and SESSION_INAPPLICABLE in m, (
        "session-inapplicable collapsed into missing provider data")


def test_stale_is_observed_and_keeps_its_value():
    i = _inp(A0_CORE, [_c("s", "price_path", STALE, 42.0)])
    v = i.canonical()["components"][0]
    assert v["quality"] == STALE and v["value"] == 42.0


def test_unknown_quality_state_refused():
    with pytest.raises(QualityContractViolation, match="unknown quality"):
        _inp(A0_CORE, [_c("x", "price_path", quality="PROBABLY_OK")])


# ============================================== no decision semantics
@pytest.mark.parametrize("bad", ["buy", "SELL", "attack", "hold", "exit",
                                 "position_size", "kelly", "order_ready",
                                 "trade_confidence", "signal_strength",
                                 "target_size", "entry_side"])
def test_decision_vocabulary_refused_in_an_input(bad):
    with pytest.raises(InputContractViolation, match="decision vocabulary"):
        _inp(A0_CORE, [_c(bad, "price_path")])


def test_documented_factual_names_are_allowed():
    """Genuine measurements that contain an instruction word are
    enumerated explicitly, not waved through by a loose pattern."""
    for ok in ("close", "vwap", "spread_bps", "order_book_imbalance",
               "buy_volume_fraction", "sell_volume_fraction",
               "buy_sell_imbalance"):
        _inp(A0_CORE, [_c(ok, "microstructure")])


def test_the_documented_list_does_NOT_open_a_prefix_loophole():
    """buy_volume_fraction being allowed must not admit buy_signal."""
    for bad in ("buy_signal", "sell_recommendation", "buy_action",
                "sell_side", "buy_target_size"):
        with pytest.raises(InputContractViolation,
                           match="decision vocabulary"):
            _inp(A0_CORE, [_c(bad, "microstructure")])


# =============================================== strict numeric admission
@pytest.mark.parametrize("bad", [float("nan"), float("inf"),
                                 float("-inf"), True, False, "0.03",
                                 None, [1.0], {"a": 1}])
def test_strict_float_refuses_everything_that_is_not_a_real_number(bad):
    with pytest.raises(NumericContractViolation):
        strict_float(bad, field="x")


def test_none_is_allowed_only_when_explicitly_permitted():
    assert strict_float(None, field="x", allow_none=True) is None


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -5.0])
def test_probabilities_are_refused_not_clamped(bad):
    with pytest.raises(NumericContractViolation, match="NOT clamped"):
        strict_probability(bad, field="p")


# ==================================================== forecast contract
def _dist(**kw):
    d = dict(expected_return=0.001, median_return=0.0008,
             quantiles={"0.05": -0.01, "0.5": 0.0008, "0.95": 0.012},
             prob_return_gt_zero=0.54, prob_return_lt_zero=0.44,
             expected_mfe=0.006, expected_mae=-0.004,
             predictive_intervals={"0.9": [-0.01, 0.012]},
             total_uncertainty=0.008)
    d.update(kw)
    return PredictiveDistribution(**d)


def _fc(inp, **kw):
    d = dict(forecast_id="fc-1", input_id=inp.input_id,
             input_hash=inp.input_hash, model_id="m", model_version="0.0.1",
             model_family="SYNTHETIC_NULL",
             information_tier=inp.information_tier,
             creation_time=T0 + 11, known_from=T0 + 11,
             forecast_horizon=H_5M, distribution=_dist())
    d.update(kw)
    return WorldModelForecast(**d)


def test_a_valid_probabilistic_forecast():
    i = _inp()
    f = _fc(i)
    assert f.forecast_hash
    s = f.sealed()
    assert s["TRADING_AUTHORITY"] == "NONE"
    assert s["PREDICTION_AUTHORITY"] == "FORECAST_REPRESENTATION_ONLY"


def test_the_contract_carries_a_distribution_not_a_direction():
    d = _dist().canonical()
    for k in ("quantiles", "expected_mfe", "expected_mae",
              "predictive_intervals", "total_uncertainty"):
        assert d[k] is not None, "%s missing -- this is UP/DOWN, not a distribution" % k


def test_unavailable_uncertainty_stays_unavailable():
    d = _dist(epistemic_uncertainty=None, aleatoric_uncertainty=None).canonical()
    assert d["epistemic_uncertainty"] is None
    assert d["aleatoric_uncertainty"] is None, (
        "an unestimated quantity was fabricated as a number")


def test_non_monotonic_quantiles_refused_not_sorted():
    with pytest.raises(ForecastContractViolation, match="not monotonic"):
        _dist(quantiles={"0.05": 0.02, "0.5": 0.001, "0.95": 0.03}).canonical()


def test_inverted_interval_refused_not_reordered():
    with pytest.raises(ForecastContractViolation, match="inverted"):
        _dist(predictive_intervals={"0.9": [0.05, -0.05]}).canonical()


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_invalid_probability_in_distribution_refused(bad):
    with pytest.raises(NumericContractViolation):
        _dist(prob_return_gt_zero=bad).canonical()


def test_probabilities_that_oversum_refused():
    with pytest.raises(ForecastContractViolation, match="sum to more than 1"):
        _dist(prob_return_gt_zero=0.7, prob_return_lt_zero=0.7).canonical()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "0.01"])
def test_malformed_numerics_in_distribution_refused(bad):
    with pytest.raises(NumericContractViolation):
        _dist(expected_return=bad).canonical()


def test_unknown_horizon_refused():
    i = _inp()
    with pytest.raises(ForecastContractViolation, match="unknown forecast_horizon"):
        _fc(i, forecast_horizon="H_TOMORROW").content()


def test_session_close_horizon_has_no_assumed_duration():
    """The realised close is not knowable when the forecast is made."""
    assert HORIZON_MINUTES[H_SESSION_CLOSE] is None
    assert set(HORIZONS) == {"H_5M", "H_15M", "H_30M", "H_60M",
                             "H_SESSION_CLOSE"}
    i = _inp()
    c = _fc(i, forecast_horizon=H_SESSION_CLOSE).content()
    assert c["horizon_minutes"] is None


# ============================================== identity and binding
def test_same_semantic_input_same_hash():
    assert _inp().input_hash == _inp().input_hash


def test_component_order_does_not_change_identity():
    a = _inp(A0_CORE, [_c("a", "price_path"), _c("b", "volume")])
    b = _inp(A0_CORE, [_c("b", "volume"), _c("a", "price_path")])
    assert a.input_hash == b.input_hash, (
        "scientific identity depends on incidental ordering")


@pytest.mark.parametrize("kw", [
    dict(subject="OTHER"), dict(state_time=T0 - 1),
    dict(known_from=T0 + 11), dict(information_tier=A1_OPTIONS),
    dict(source_state_hash="cafe"), dict(source_state_id="twin-2"),
    dict(feature_family_versions={"price_path": "v2"}),
])
def test_tampering_the_input_changes_its_hash(kw):
    assert _inp(**kw).input_hash != _inp().input_hash


def test_tampering_a_component_changes_the_input_hash():
    base = _inp().input_hash
    assert _inp(A0_CORE, [_c("close", "price_path", value=999.0)]).input_hash != base
    assert _inp(A0_CORE, [_c("close", "price_path", quality=STALE)]).input_hash != base


def test_forecast_commits_to_the_exact_input():
    i = _inp()
    f = _fc(i)
    assert f.binds_to(i)
    other = _inp(subject="OTHER")
    assert not f.binds_to(other), (
        "a forecast bound to nothing cannot be checked against what it saw")


def test_forecast_with_a_stale_input_hash_does_not_bind():
    i = _inp()
    f = _fc(i, input_hash="0" * 64)
    assert not f.binds_to(i)


def test_forecast_without_an_input_hash_refused():
    i = _inp()
    with pytest.raises(ForecastContractViolation, match="does not commit"):
        _fc(i, input_hash="").content()


@pytest.mark.parametrize("kw", [
    dict(model_version="0.0.2"), dict(forecast_horizon="H_60M"),
    dict(input_hash="a" * 64), dict(information_tier=B_FULL_JOINT),
    dict(known_from=T0 + 12),
])
def test_tampering_the_forecast_changes_its_hash(kw):
    i = _inp()
    assert _fc(i, **kw).forecast_hash != _fc(i).forecast_hash


def test_tampering_the_distribution_changes_the_hash():
    i = _inp()
    assert _fc(i, distribution=_dist(expected_return=0.002)).forecast_hash \
        != _fc(i).forecast_hash


# ------------------------------------------- content vs instance identity
def test_content_identity_excludes_creation_time():
    i = _inp()
    a, b = _fc(i, creation_time=T0 + 11), _fc(i, creation_time=T0 + 9999)
    assert a.forecast_hash == b.forecast_hash, (
        "scientific identity depends on when a script happened to run")
    assert a.instance()["creation_time"] != b.instance()["creation_time"]


def test_instance_identity_still_records_creation_time():
    i = _inp()
    assert _fc(i).sealed()["creation_time"] == T0 + 11


# ------------------------------------------------------------ authority
def test_neither_contract_has_trading_capital_or_order_authority():
    i = _inp()
    for sealed in (i.sealed(), _fc(i).sealed()):
        assert sealed["TRADING_AUTHORITY"] == "NONE"
        assert sealed["CAPITAL_AUTHORITY"] == "NONE"
        assert sealed["ORDER_AUTHORITY"] == "NONE"
    assert i.sealed()["PREDICTION_AUTHORITY"] == "NONE"


def test_contract_modules_import_no_production_apex_and_no_broker():
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


def test_real_data_firewall_still_holds_under_the_new_contracts():
    from apex.world_model import admit
    from apex.world_model.sources import SourceAdmissionRefused
    with pytest.raises(SourceAdmissionRefused, match="REAL_EVIDENCE_PATH"):
        admit("/apex-data/core/btc/window_outcomes.jsonl",
              declared_class="SYNTHETIC_FIXTURE")
