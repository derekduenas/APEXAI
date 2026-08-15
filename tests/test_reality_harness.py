"""The five directive-mandated test families for the Reality Loop (v2.0 §1.7).

1. immutability      -- append-only, chain, truncation, frozen resolution rule
2. scoring reference -- Brier/log-loss vs hand-computed; calibration against a
                        generator with KNOWN calibration
3. resolution determinism
4. unresolved penalty
5. baseline isolation -- the blind twin can receive no market data
"""

from __future__ import annotations

import inspect
import json

import numpy as np
import pandas as pd
import pytest

from apex.reality import producers as P
from apex.reality.harness import (
    PredictionLedger, RealityError, brier, calibration_curve, canonical_hash,
    log_loss, make_prediction, reliability_resolution, resolve, scoreable,
)

NOW = "2026-08-14T00:00:00+00:00"


def _pred(**kw):
    base = dict(trade_date="2026-07-06", horizon_days=20, subject="S1",
                claim_type="direction", probability=0.6, epistemic_tier=1,
                producer="t", inputs={"x": 1}, rationale={},
                resolution_rule="direction_up", resolution_params={},
                created_at=NOW)
    base.update(kw)
    return make_prediction(**base)


# --- 1. immutability --------------------------------------------------------

def test_chain_appends_and_verifies(tmp_path):
    led = PredictionLedger(tmp_path / "p.jsonl")
    led.append_prediction(_pred())
    led.append_prediction(_pred(subject="S2"))
    assert led.verify() == 2


def test_counterexample_an_edited_entry_breaks_the_chain(tmp_path):
    led = PredictionLedger(tmp_path / "p.jsonl")
    led.append_prediction(_pred(probability=0.6))
    lines = (tmp_path / "p.jsonl").read_text().splitlines()
    doctored = json.loads(lines[0])
    doctored["probability"] = 0.9          # revise history
    (tmp_path / "p.jsonl").write_text(json.dumps(doctored, sort_keys=True) + "\n")
    with pytest.raises(RealityError, match="modified"):
        led.verify()


def test_counterexample_truncation_disagrees_with_the_anchor(tmp_path):
    led = PredictionLedger(tmp_path / "p.jsonl")
    led.append_prediction(_pred())
    led.append_prediction(_pred(subject="S2"))
    lines = (tmp_path / "p.jsonl").read_text().splitlines()
    (tmp_path / "p.jsonl").write_text(lines[0] + "\n")   # drop the last entry
    with pytest.raises(RealityError, match="TRUNCATION"):
        led.verify()


def test_the_resolution_rule_is_frozen_at_creation():
    p = _pred()
    with pytest.raises(Exception):        # frozen dataclass
        p.resolution_rule = "close_in_range"
    with pytest.raises(RealityError, match="unknown resolution_rule"):
        _pred(resolution_rule="chosen_later")


def test_certainty_is_rejected():
    for bad in (0.0, 1.0, -0.1, 1.1):
        with pytest.raises(RealityError, match="strictly inside"):
            _pred(probability=bad)


# --- 2. scoring reference ---------------------------------------------------

def test_brier_and_log_loss_match_hand_computation():
    rows = [{"probability": 0.8, "outcome": 1.0},
            {"probability": 0.8, "outcome": 0.0},
            {"probability": 0.3, "outcome": 0.0}]
    assert brier(rows) == pytest.approx((0.04 + 0.64 + 0.09) / 3)
    assert log_loss(rows) == pytest.approx(
        -(np.log(0.8) + np.log(0.2) + np.log(0.7)) / 3)


def test_calibration_curve_recovers_a_known_calibrated_generator():
    rng = np.random.default_rng(7)
    rows = []
    for p in (0.25, 0.55, 0.85):
        rows += [{"probability": p, "outcome": float(rng.random() < p)}
                 for _ in range(4000)]
    for b in calibration_curve(rows):
        assert abs(b["stated_mean"] - b["realized_freq"]) < 0.03, b


def test_a_deliberately_overconfident_generator_is_exposed():
    rng = np.random.default_rng(8)
    # says 0.9, is right 60% of the time
    rows = [{"probability": 0.9, "outcome": float(rng.random() < 0.6)}
            for _ in range(4000)]
    d = reliability_resolution(rows)
    assert d["reliability"] > 0.05, "overconfidence must show up as reliability"


def test_a_base_rate_parrot_is_reliable_but_has_zero_resolution():
    rng = np.random.default_rng(9)
    rows = [{"probability": 0.5, "outcome": float(rng.random() < 0.5)}
            for _ in range(4000)]
    d = reliability_resolution(rows)
    assert d["reliability"] < 0.01
    assert d["resolution"] < 0.01, "saying 50% to everything informs nothing"


# --- 3. resolution determinism ----------------------------------------------

def _prices():
    days = pd.bdate_range("2026-07-01", periods=30)
    return pd.DataFrame(
        {"S1": np.linspace(100, 110, 30), "S2": np.linspace(100, 95, 30),
         "S3": np.linspace(100, 101, 30), "S4": np.linspace(100, 99, 30)},
        index=days)


def test_every_rule_resolves_the_same_way_twice():
    prices = _prices()
    td = str(prices.index[2].date())
    preds = [
        _pred(trade_date=td, horizon_days=10).__dict__ | {},
        _pred(trade_date=td, horizon_days=10, claim_type="relative",
              resolution_rule="relative_vs_peer_median",
              resolution_params={"peers": ["S2", "S3", "S4"]}).__dict__ | {},
        _pred(trade_date=td, horizon_days=10, claim_type="volatility",
              resolution_rule="realized_vol_above",
              resolution_params={"threshold": 0.5}).__dict__ | {},
        _pred(trade_date=td, horizon_days=10, claim_type="range",
              resolution_rule="close_in_range",
              resolution_params={"low": 100, "high": 106}).__dict__ | {},
    ]
    first = [resolve(prices, dict(p)) for p in preds]
    second = [resolve(prices, dict(p)) for p in preds]
    assert first == second == [1.0, 1.0, 0.0, 1.0]


def test_a_prediction_before_data_reaches_the_horizon_is_not_resolvable():
    prices = _prices()
    td = str(prices.index[-5].date())
    assert resolve(prices, dict(_pred(trade_date=td, horizon_days=10).__dict__)) is None


# --- 4. unresolved penalty --------------------------------------------------

def test_a_past_due_unresolved_prediction_scores_as_a_failure():
    p = dict(_pred(trade_date="2026-01-05", probability=0.8).__dict__)
    rows = scoreable([p], {}, data_through="2026-08-13")
    assert len(rows) == 1 and rows[0]["penalised"]
    assert rows[0]["outcome"] == 0.0, "0.8 confidence must be punished, not excused"
    low = dict(_pred(trade_date="2026-01-05", probability=0.2).__dict__)
    assert scoreable([low], {}, "2026-08-13")[0]["outcome"] == 1.0


def test_counterexample_a_not_yet_due_prediction_is_simply_not_scored():
    p = dict(_pred(trade_date="2026-08-10").__dict__)
    assert scoreable([p], {}, data_through="2026-08-13") == []


# --- 5. baseline isolation --------------------------------------------------

def test_the_blind_twin_signature_cannot_carry_market_data():
    params = set(inspect.signature(P.blind_producer).parameters)
    assert params == {"name", "trade_date", "created_at", "subjects", "peers"}, (
        "the blind producer grew an argument that could smuggle market data")


def test_the_blind_twin_inputs_hash_is_the_hash_of_nothing():
    preds = P.blind_producer("blind", "2026-07-06", NOW, ["S1"], ["S2", "S3"])
    assert preds[0].inputs_hash == canonical_hash({})
    assert preds[0].probability == 0.5


def test_counterexample_the_rank_producer_hash_reflects_its_market_input():
    ranks = pd.Series({"S1": 0.9})
    a = P.rank_producer("r", "2026-07-06", NOW, ranks, ["S1"], ["S2"])[0]
    b = P.rank_producer("r", "2026-07-06", NOW,
                        pd.Series({"S1": 0.1}), ["S1"], ["S2"])[0]
    assert a.inputs_hash != b.inputs_hash, (
        "different market inputs must produce different inputs hashes")
    assert a.probability == pytest.approx(0.58)
    assert b.probability == pytest.approx(0.42)


# --- the harness fixes (operator review, 2026-08-15) ------------------------

def test_momentum_rank_baseline_uses_the_same_frozen_mapping():
    """Baseline 2 in biting form: same subjects, same mapping as gp_rank."""
    mom = pd.Series({"S1": 0.30, "S2": -0.10, "S3": 0.05})
    preds = P.momentum_rank_producer("2026-07-06", NOW, mom, ["S1", "S2"],
                                     ["S1", "S2", "S3"])
    by = {p.subject: p for p in preds}
    assert by["S1"].probability == pytest.approx(0.5 + 0.2 * (1.0 - 0.5))
    assert by["S2"].probability == pytest.approx(0.5 + 0.2 * (1 / 3 - 0.5))
    assert by["S1"].claim_type == "relative"


def test_the_stripped_prompt_contains_no_market_numbers():
    from apex.reality.llm_producer import WITHHELD, build_prompts
    ctx = {"security_id": "S1", "ticker": "ACME", "trade_date": "2026-08-04",
           "close": 12.34, "mcap_m": 456.0, "r20": 0.0812, "r60": -0.043,
           "r120": 0.221, "gp_assets": 0.317, "btm": 0.912}
    full, stripped = build_prompts(ctx)
    assert WITHHELD in stripped
    # per-name VALUES must be absent (the universe description in the shared
    # instructions legitimately says "market cap" -- that is not a leak)
    for leak in ("12.34", "456", "8.1%", "0.317", "0.912", "market cap ($M):"):
        assert leak not in stripped, f"stripped prompt leaks {leak!r}"
        assert leak in full, f"the full prompt should carry {leak!r}"


def test_probability_parsing_rejects_garbage_and_clamps_certainty():
    from apex.reality.llm_producer import parse_probability
    assert parse_probability('{"probability": 0.65}') == 0.65
    assert parse_probability('noise {"probability": 0.999} noise') == 0.98
    assert parse_probability('{"probability": 1.0}') is None
    assert parse_probability("I think it will go up") is None


def test_an_llm_pair_is_all_or_nothing():
    """If either variant fails to parse, NEITHER is recorded -- an unpaired
    variant would bias the exact comparison the pair exists to make."""
    from apex.reality.llm_producer import llm_predictions
    ctx = {"security_id": "S1", "ticker": "ACME", "trade_date": "2026-08-04",
           "close": 10.0, "mcap_m": 500.0, "r20": 0.01, "r60": 0.02,
           "r120": 0.03, "gp_assets": 0.2, "btm": 0.8}
    calls = iter(['{"probability": 0.7}', "MALFORMED"])
    assert llm_predictions(ctx, ["S2"], NOW, "haiku",
                           run_fn=lambda _p, _m: next(calls)) == []
    ok = iter(['{"probability": 0.7}', '{"probability": 0.5}'])
    pair = llm_predictions(ctx, ["S2"], NOW, "haiku",
                           run_fn=lambda _p, _m: next(ok))
    assert len(pair) == 2
    assert {p.producer.split("/")[0] for p in pair} == {"llm_full", "llm_stripped"}
    assert all("/haiku/" in p.producer for p in pair)


def test_parallel_models_are_distinct_producers_never_substitutes():
    """v3.1 section 1.3: calibration does not transfer across models. Each
    declared model is its own producer identity with its own record; an
    undeclared model is refused rather than silently starting a new clock."""
    import pytest as _pt
    from apex.reality.llm_producer import MODELS, llm_predictions
    assert len(MODELS) >= 2, "at least two parallel producer models required"
    ctx = {"security_id": "S1", "ticker": "ACME", "trade_date": "2026-08-04",
           "close": 10.0, "mcap_m": 500.0, "r20": 0.01, "r60": 0.02,
           "r120": 0.03, "gp_assets": 0.2, "btm": 0.8}
    ids = set()
    for m in MODELS:
        ok = iter(['{"probability": 0.7}', '{"probability": 0.5}'])
        for p in llm_predictions(ctx, ["S2"], NOW, m,
                                 run_fn=lambda _p, _m: next(ok)):
            ids.add(p.producer)
    assert len(ids) == 2 * len(MODELS), "each model must have its own pair identity"
    with _pt.raises(ValueError, match="not a declared parallel producer"):
        llm_predictions(ctx, ["S2"], NOW, "gpt-99",
                        run_fn=lambda _p, _m: '{"probability": 0.5}')


def test_scores_are_stamped_preliminary_until_ten_effective_dates():
    from apex.reality.harness import score_by_producer
    preds = [dict(_pred(trade_date="2026-01-05", subject=f"S{i}").__dict__)
             for i in range(50)]
    res = {p["prediction_id"]: {"outcome": 1.0} for p in preds}
    rep = score_by_producer(preds, res, "2026-08-13")["t"]
    assert rep["n_scored"] == 50 and rep["n_effective_dates"] == 1
    assert rep["status"].startswith("PRELIMINARY"), (
        "50 claims from one date must not read as n=50")
