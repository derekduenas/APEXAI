"""Observe actual model calls on the premarket -> FULL -> Book path.

Wrappers pass inputs and return values through unchanged. No model is stubbed.
Synthetic recipe is fixed; a refused GARCH fit fails this flight, not a fallback
silently counted as GARCH. This is wiring/numeric evidence, not calibration.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import numpy as np
import pytest

from apex.court.court import FunnelCourt
from apex.court import world as W
from apex.court.verify import reconstruct
from apex.decision_wb import engine as E
from apex.pulse_options.inference import FrozenArtifact
from apex.worldmodel_wb.vol_models import GARCH
from apex.worldmodel_wb.regime import MarkovSwitching2
from tests.test_premarket_twin_handoff import morning, NOW, FX


def path_digest(paths):
    out = {}
    for key in ("S", "h", "iv", "spread_bps"):
        a = np.ascontiguousarray(paths[key])
        out[key] = {"shape": list(a.shape), "sha256": hashlib.sha256(a.tobytes()).hexdigest(),
                    "finite": bool(np.isfinite(a).all())}
    return out


def training_bars():
    """Existing funnel test's Student-t recipe, expressed as causal OHLC bars.

    No search over seeds or fitted parameters. Unit conversion is exp(log return),
    not an arithmetic-return approximation. The current tape is a separate segment.
    """
    midnight = datetime.fromisoformat(FX.TRADING_DATE).replace(tzinfo=timezone.utc).timestamp()
    x = np.random.default_rng(3).standard_t(6, 2000) * 2.5e-4 / np.sqrt(1.5)
    prices = 646 * np.exp(np.r_[0., np.cumsum(x)])
    bars = []
    for i, p in enumerate(prices):
        at = midnight - (len(prices) - i) * 60
        bars.append({"event_time": at, "receipt_time": at + 60, "bar_complete": at + 60,
                     "open": float(p), "high": float(p), "low": float(p), "close": float(p),
                     "volume": 1000., "vwap": float(p), "source": "SYNTHETIC_STUDENT_T_SEED_3"})
    return bars + W.bars(n=65, end_epoch=NOW, drift_bp_per_bar=0.8, vol_bp_per_bar=4.)


@pytest.fixture(scope="module")
def model_flight(morning, tmp_path_factory):
    # MonkeyPatch context restores all readers, including on a failed flight.
    observed = {"fits": [], "variance": [], "regime": [], "simulations": [], "comparisons": [],
                "supervision": [], "implied": [], "forecasts": [], "call_order": []}
    original_fit, original_forecast = GARCH.fit, GARCH.forecast
    original_location = FrozenArtifact.forecast
    original_filter = MarkovSwitching2.filtered
    original_sim = E.ConditionalSimulator.simulate
    original_compare, original_sup, original_iv = E.EW.compare, E.supervise, E.implied_vol

    def location(self, snapshot, **kw):
        result = original_location(self, snapshot, **kw)
        observed["call_order"].append("LOCATION_FORECAST")
        observed["forecasts"].append({"snapshot": deepcopy(snapshot), "output": deepcopy(result)})
        return result

    def fit(self, rows, **kw):
        result = original_fit(self, rows, **kw)
        observed["call_order"].append("GARCH_FIT")
        observed["fits"].append({"n_rows": len(rows), "max_available": max(r["available"] for r in rows),
                                  "cutoff": kw["cutoff_epoch"], "parameters": deepcopy(self.p)})
        return result

    def forecast(self, **kw):
        result = original_forecast(self, **kw)
        observed["call_order"].append("GARCH_FORECAST")
        observed["variance"].append({"parameters": deepcopy(self.p), "arguments": deepcopy(kw),
                                      "output": deepcopy(result.meta)})
        return result

    def filtered(self, *args, **kw):
        result = original_filter(self, *args, **kw)
        observed["call_order"].append("REGIME_FILTER")
        observed["regime"].append({"output": deepcopy(result), "sigma": list(self.p["sigma"])})
        return result

    def simulate(self, **kw):
        result = original_sim(self, **kw)
        observed["call_order"].append("MULTIVERSE")
        # Reconstruct shocks from prices, not from the simulator's innovation
        # array; then independently check its documented GARCH recurrence.
        shocks = np.log(result["S"][:, 1:] / result["S"][:, :-1]) - self.drift_per_bar
        multipliers = np.asarray(self.regime["variance_multipliers"])[result["state"]]
        raw_h = result["h"][:, :-1] / multipliers[:, None]
        expected_h = (self.vm["omega"] + (self.vm["alpha"] + self.vm["gamma"] * (shocks < 0)) * shocks**2
                      + self.vm["beta"] * raw_h) * multipliers[:, None]
        returns = np.log(result["S"][:, -1] / result["S"][:, 0])
        observed["simulations"].append({"inputs": deepcopy(self.describe()), "paths": path_digest(result),
            "moments": deepcopy(result["moments"]), "first_h": result["h"][:, 0].tolist(),
            "independent_math": {"mean": float(returns.mean()), "variance": float(returns.var()),
                "max_recurrence_relative_error": float(np.max(np.abs(expected_h-result["h"][:, 1:]) / expected_h)),
                "iv_fixed": bool(np.all(result["iv"] == self.iv0)),
                "spread_fixed": bool(np.all(result["spread_bps"] == self.spread0))},
            "states": result["state"].tolist() if result["state"] is not None else None})
        return result

    def compare(**kw):
        from scipy.special import ndtr
        received = path_digest(kw["paths"])
        result = original_compare(**kw)
        observed["call_order"].append("EXPRESSION_PRICING")
        expected = {}
        paths = kw["paths"]
        for c in kw["candidates"]:
            inst = c["instrument"]
            assert kw["r"] == 0 and inst.get("dividend_yield", 0) == 0
            s, vol, strike = paths["S"][:, -1], paths["iv"][:, -1], inst["strike"]
            t = kw["T_years_by_contract"][c["label"]] - kw["horizon_years"]
            d1 = (np.log(s / strike) + .5 * vol**2 * t) / (vol * np.sqrt(t))
            d2 = d1 - vol * np.sqrt(t)
            mid = s * ndtr(d1) - strike * ndtr(d2) if inst["right"] == "CALL" else strike * ndtr(-d2) - s * ndtr(-d1)
            bid = np.maximum(mid * (1 - paths["spread_bps"][:, -1] / 20000), 0)
            pnl = 100 * (bid - c["quote"]["ask"]) - kw["fees_entry"] - kw["fees_exit"]
            expected[c["label"]] = {"mean": float(pnl.mean()), "p_loss": float(np.mean(pnl < 0))}
        observed["comparisons"].append({"paths_received": received, "output": deepcopy(result),
                                         "independent_values": expected})
        return result

    def supervise(**kw):
        result = original_sup(**kw)
        observed["call_order"].append("PRIME")
        observed["supervision"].append({"regime": deepcopy(kw["regime"]),
            "candidate": kw["candidate_label"], "variance": kw["forecast"].variance(),
            "comparison": deepcopy(kw["comparison"]), "output": deepcopy(result)})
        return result

    def implied(**kw):
        result = original_iv(**kw)
        observed["call_order"].append("IMPLIED_VOL")
        observed["implied"].append({"input": deepcopy(kw), "output": deepcopy(result)})
        return result

    root = tmp_path_factory.mktemp("full-model-path")
    chain = [{"expiration": "2026-10-09", "strike": k, "right": r, "ask": 2.45}
             for k in (640., 645., 650., 655.) for r in ("CALL", "PUT")]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FrozenArtifact, "forecast", location)
        mp.setattr(GARCH, "fit", fit)
        mp.setattr(GARCH, "forecast", forecast)
        mp.setattr(MarkovSwitching2, "filtered", filtered)
        mp.setattr(E.ConditionalSimulator, "simulate", simulate)
        mp.setattr(E.EW, "compare", compare)
        mp.setattr(E, "supervise", supervise)
        mp.setattr(E, "implied_vol", implied)
        c = FunnelCourt(run_id="garch-flight", out_root=root, t0=NOW,
                        premarket_root=morning, synthetic_bars=training_bars(), synthetic_chain=chain)
        out = c.run()
    rows = [json.loads(s) for s in (c.dir / "ledger.jsonl").read_text().splitlines()]
    observed["court"] = out
    observed["ledger"] = rows
    observed["reconstruction"] = reconstruct(c.dir)
    # Independent witness file, retained beside the real ledger for diagnosis.
    (c.dir / "model_observations.json").write_text(json.dumps(observed, indent=1, default=str))
    return observed


def test_twin_numbers_and_location_reach_multiverse(model_flight):
    o = model_flight
    assert len(o["forecasts"]) == 1
    fc = o["forecasts"][0]
    closes = [b["close"] for b in training_bars()[-65:]]
    fields = fc["snapshot"]["fields"]
    for length in (1, 5, 15):
        assert fields["ret_%d" % length]["value"] == pytest.approx(
            np.log(closes[-1] / closes[-1-length]), abs=1e-14)
    recent = np.diff(np.log(closes[-31:]))
    assert fields["rv_30"]["value"] == pytest.approx(np.sqrt(np.mean(recent**2)), abs=1e-14)
    for sim in o["simulations"]:
        assert sim["inputs"]["S0"] == closes[-1]
        assert sim["inputs"]["drift_per_bar"] == fc["output"]["location"] / 15
    persisted = next(r for r in o["ledger"] if r["kind"] == "pilot_forecast")
    assert persisted["location"] == fc["output"]["location"]
    assert persisted["inputs"]["snapshot_id"] == fc["snapshot"]["snapshot_id"]


def test_garch_really_fitted_and_forecasted(model_flight):
    o = model_flight
    assert len(o["fits"]) == len(o["variance"]) == 1, o["court"]
    f = o["fits"][0]
    assert f["n_rows"] >= 400 and f["max_available"] <= f["cutoff"]
    assert f["parameters"]["persistence"] < .999
    assert o["court"]["engine"]["fit"]["variance_kind"] == "GARCH-t (walk-forward)"
    order = o["call_order"]
    required = ["LOCATION_FORECAST", "GARCH_FIT", "REGIME_FILTER", "GARCH_FORECAST", "IMPLIED_VOL",
                "MULTIVERSE", "EXPRESSION_PRICING", "PRIME"]
    assert [order.index(name) for name in required] == sorted(order.index(name) for name in required)


def test_garch_numbers_independently_recur_to_simulator(model_flight):
    o = model_flight
    assert o["variance"] and o["simulations"], o["court"]
    f = o["variance"][0]
    p = f["parameters"]
    h, e = p["h_last"], p["e_last"]
    def step(h, e):
        return p["omega"] + (p["alpha"] + (p["gamma"] if e < 0 else 0)) * e**2 + p["beta"] * h
    for e_new in f["arguments"]["recent"]:
        h, e = step(h, e), e_new
    h1 = step(h, e)
    assert f["output"]["next_bar_variance"] == pytest.approx(h1, rel=1e-12)
    integrated, expected = 0., h1
    for _ in range(15):
        integrated += expected
        expected = p["omega"] + (p["alpha"] + p["beta"] + p["gamma"] / 2) * expected
    assert f["output"]["integrated_variance"] == pytest.approx(integrated, rel=1e-12)
    for sim in o["simulations"]:
        vm = sim["inputs"]["variance_model"]
        assert vm["kind"] == "GARCH" and vm["h_next"] == h1
        for key in ("omega", "alpha", "beta", "gamma"):
            assert vm[key] == p[key]
        assert sim["inputs"]["nu"] == p["nu"]
        assert sim["inputs"]["innovations"]["family"] == "TRUNCATED_T"


def test_regime_and_iv_are_consumed_by_real_simulations(model_flight):
    o = model_flight
    assert o["regime"] and o["implied"] and o["simulations"]
    reg = o["regime"][0]
    probabilities = reg["output"]["probabilities"]
    base = sum(p*s*s for p, s in zip(probabilities, reg["sigma"]))
    for sim in o["simulations"]:
        cfg = sim["inputs"]["regime"]
        assert cfg is not None, o["court"]
        assert cfg["probabilities"] == probabilities
        assert cfg["variance_multipliers"] == pytest.approx([s*s/base for s in reg["sigma"]])
        expected = [sim["inputs"]["variance_model"]["h_next"] * cfg["variance_multipliers"][k]
                    for k in sim["states"]]
        assert sim["first_h"] == pytest.approx(expected)
        assert sim["inputs"]["iv0"] == np.mean([v["output"]["iv"] for v in o["implied"]])


def test_actual_common_paths_reach_pricing_and_prime(model_flight):
    o = model_flight
    assert len(o["simulations"]) == len(o["comparisons"]) == 3, o["court"]
    for sim, cmp in zip(o["simulations"], o["comparisons"]):
        assert sim["paths"] == cmp["paths_received"]
        assert all(v["finite"] and v["shape"] == [2000, 16] for v in sim["paths"].values())
    assert len(o["supervision"]) == 1
    sup = o["supervision"][0]
    assert sup["variance"] == o["simulations"][0]["moments"]["var_log_return"]
    assert sup["regime"]["probabilities"] == o["regime"][0]["output"]["probabilities"]
    assert any(c["label"] == sup["candidate"] for c in o["comparisons"][0]["output"]["candidates"])


def test_simulation_recurrence_and_pricing_math(model_flight):
    for sim in model_flight["simulations"]:
        independent = sim["independent_math"]
        assert independent["max_recurrence_relative_error"] < 1e-9
        assert independent["mean"] == pytest.approx(sim["moments"]["mean_log_return"], abs=1e-14)
        assert independent["variance"] == pytest.approx(sim["moments"]["var_log_return"], abs=1e-14)
        assert independent["iv_fixed"] and independent["spread_fixed"]
    for cmp in model_flight["comparisons"]:
        n = 0
        for row in cmp["output"]["candidates"]:
            if row["label"] == "WAIT" or row["status"] != "ELIGIBLE":
                continue
            expected = cmp["independent_values"][row["label"]]
            assert row["expected_net_pnl"] == pytest.approx(expected["mean"], abs=1e-8)
            assert row["p_loss"] == expected["p_loss"]
            n += 1
        assert n > 0


def test_trade_path_and_unavailable_layers_are_explicit(model_flight):
    o = model_flight
    assert o["court"]["decision"] == "TRADE", o["court"]
    assert o["reconstruction"]["problems"] == []
    assert o["reconstruction"]["execution_verification"]["open_positions"] == 0
    forecast = next(r for r in o["ledger"] if r["kind"] == "pilot_forecast")
    assert forecast["inputs"]["premarket_context"]["status"] == "ATTACHED_CONTEXT"
    assert not forecast["inputs"]["premarket_context"]["model_consumed"]
    absent = o["court"]["engine"]["layers_not_invoked"]
    assert set(absent) == {"svi_surface", "fusion", "enrichment", "jumps"}


def test_simulator_refusal_stops_pricing_and_entry(tmp_path, monkeypatch):
    """Deliberate fault injection, separate from the unchanged positive flight."""
    calls = []
    def refused(self, **kw):
        calls.append("simulator")
        raise E.SimulatorRefused("AUDIT_INJECTED_FAILURE")
    def must_not_price(**kw):
        pytest.fail("pricing ran after simulation failed")
    monkeypatch.setattr(E.ConditionalSimulator, "simulate", refused)
    monkeypatch.setattr(E.EW, "compare", must_not_price)
    c = FunnelCourt(run_id="simulation-refused", out_root=tmp_path)
    out = c.run()
    assert calls == ["simulator"]
    assert out["decision"] == "WAIT" and "AUDIT_INJECTED_FAILURE" in out["why"]
    assert not out["ledger_kinds"].get("pilot_intent")
    assert not out["ledger_kinds"].get("pilot_fill")


def test_insufficient_history_stops_models_and_simulation(tmp_path, monkeypatch):
    def must_not_run(*args, **kw):
        pytest.fail("model ran after insufficient training history")
    monkeypatch.setattr(GARCH, "fit", must_not_run)
    monkeypatch.setattr(E.ConditionalSimulator, "simulate", must_not_run)
    c = FunnelCourt(run_id="history-refused", out_root=tmp_path, n_bars=40)
    out = c.run()
    assert out["decision"] == "WAIT" and "INSUFFICIENT_HISTORY" in out["why"]
    assert not out["ledger_kinds"].get("pilot_fill")
