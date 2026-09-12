"""M4 — Multiverse and market-implied comparison on synthetic worlds. Establishes: the conditional
simulator's moments, tails, path dependence, horizon aggregation and the analytic Gaussian special
case; sampling error reported separately from model uncertainty; unweighted stresses carry no
probability; pricing parity, IV inversion round trip and refusals outside no-arbitrage bounds,
Greeks against finite differences, American >= European, refusal of the European formula on an
American instrument without a declared approximation, instrument conventions; SVI round trip with
butterfly/calendar diagnostics recorded; expression comparison under common paths with WAIT, costs
once, IV sensitivity and no arbitrage label. Nothing here uses market data."""
import math

import numpy as np
import pytest

from apex.multiverse_wb import expression_war as EW, pricing as PR, simulator as SIM, surface as SF
from apex.worldmodel_wb import vol_models as VM

T0 = 1_789_000_000.0


# ================================================================== simulator

def test_simulator_moments_tails_horizon_and_analytic_special_case():
    h = 1e-8
    sim = SIM.ConditionalSimulator(S0=645.0, variance_model={"kind": "FLAT", "h": h}, nu=None, iv0=0.18, spread_bps0=40.0, cutoff_epoch=T0)
    out = sim.simulate(horizon_bars=15, n_paths=40000, seed=1)
    ref = SIM.analytic_gaussian_check(h=h, horizon_bars=15)
    assert out["moments"]["var_log_return"] == pytest.approx(ref["var"], rel=0.05)
    assert abs(out["moments"]["mean_log_return"]) < 4 * out["sampling_error"]["se_mean"]
    assert abs(out["moments"]["kurtosis_excess"]) < 0.3
    # horizon aggregation: the 15-step log return is the sum of the 15 one-step returns (path-consistent)
    S = out["S"]
    assert np.allclose(np.log(S[:, -1] / S[:, 0]), np.sum(np.diff(np.log(S), axis=1), axis=1))
    assert np.allclose(out["h"][:, 0], h) and out["restrictions"][0].startswith("IV held fixed")
    # heavy tails with t innovations under GARCH
    g = SIM.ConditionalSimulator(S0=645.0, variance_model={"kind": "GARCH", "omega": 2e-8, "alpha": 0.08, "beta": 0.9, "gamma": 0.0, "h_next": 2e-6},
                                 nu=5.0, iv0=0.18, spread_bps0=40.0, cutoff_epoch=T0)
    og = g.simulate(horizon_bars=15, n_paths=40000, seed=2)
    assert og["moments"]["kurtosis_excess"] > 0.3
    assert og["model_uncertainty"]["fit"].startswith("NOT_PROPAGATED") and og["sampling_error"]["se_var"] > 0
    # more draws shrink the sampling error, not the model
    og2 = g.simulate(horizon_bars=15, n_paths=160000, seed=2)
    assert og2["sampling_error"]["se_mean"] < og["sampling_error"]["se_mean"]
    assert og2["parameter_hash"] == og["parameter_hash"]


def test_regime_mixture_iv_and_spread_processes_and_unweighted_stresses():
    base = {"kind": "FLAT", "h": 1e-8}
    mix = SIM.ConditionalSimulator(S0=100.0, variance_model=base, nu=None, iv0=0.2, spread_bps0=30.0,
                                   regime={"probabilities": [0.7, 0.3], "variance_multipliers": [1.0, 4.0]}, iv_process="IV_STRESS_MULT", iv_param=1.5,
                                   spread_process="SPREAD_STRESS_MULT", spread_param=2.0, cutoff_epoch=T0)
    out = mix.simulate(horizon_bars=15, n_paths=30000, seed=3)
    assert out["moments"]["var_log_return"] == pytest.approx(1e-8 * 15 * (0.7 + 0.3 * 4.0), rel=0.06)
    assert out["iv"][0, -1] == pytest.approx(0.3) and out["spread_bps"][0, 0] == 60.0 and set(np.unique(out["state"])) == {0, 1}
    assert "mixture over 2 states" in out["model_uncertainty"]["regime"] and "no regime mixture" not in out["restrictions"]
    st = SIM.ConditionalSimulator.stress_branches(out)
    assert len(st) == 9 and all(s["probability"] is None and s["kind"] == "UNWEIGHTED_STRESS" for s in st)
    with pytest.raises(SIM.SimulatorRefused, match="REGIME_PROBABILITIES_INVALID"):
        SIM.ConditionalSimulator(S0=100.0, variance_model=base, nu=None, iv0=0.2, spread_bps0=30.0, regime={"probabilities": [0.7, 0.7], "variance_multipliers": [1, 1]})
    with pytest.raises(SIM.SimulatorRefused, match="PROCESS_UNKNOWN"):
        SIM.ConditionalSimulator(S0=100.0, variance_model=base, nu=None, iv0=0.2, spread_bps0=30.0, iv_process="IV_MAGIC")


def test_fitted_garch_feeds_the_simulator_consistently():
    x = VM.simulate_garch(n=4000, omega=2e-8, alpha=0.08, beta=0.9, nu=7.0, seed=9)
    m = VM.GARCH(); p = m.fit([{"event_time": i * 60.0, "available": i * 60.0 + 60, "ret_1": float(v)} for i, v in enumerate(x)], cutoff_epoch=1e9)
    f = m.forecast(cutoff_epoch=1e9, created_epoch=1e9, horizon_bars=15)
    sim = SIM.ConditionalSimulator(S0=645.0, variance_model={"kind": "GARCH", **{k: p[k] for k in ("omega", "alpha", "beta", "gamma")}, "h_next": f.meta["next_bar_variance"]},
                                   nu=p["nu"], iv0=0.18, spread_bps0=40.0, cutoff_epoch=1e9)
    out = sim.simulate(horizon_bars=15, n_paths=30000, seed=4)
    # ONE state convention: the first simulated bar's variance IS the forecast's next_bar_variance, exactly (no extra recurrence step)
    assert out["h_next"] == f.meta["next_bar_variance"] and np.all(out["h"][:, 0] == f.meta["next_bar_variance"])
    assert out["moments"]["var_log_return"] == pytest.approx(f.variance(), rel=0.15)
    with pytest.raises(SIM.SimulatorRefused, match="VARIANCE_STATE_CONVENTION"):
        SIM.ConditionalSimulator(S0=645.0, variance_model={"kind": "GARCH", "omega": 1e-8, "alpha": 0.05, "beta": 0.9, "gamma": 0.0, "h_last": 1e-6, "e_last": 0.0},
                                 nu=6.0, iv0=0.18, spread_bps0=40.0)


def test_innovations_have_finite_exponential_moments_and_the_truncation_is_declared():
    import math
    from scipy import stats
    tr = SIM.truncated_t_scale(4.0, 8.0)
    assert 0 < tr["truncated_mass"] < 1e-2 and tr["renormalization"] > 1.0
    rng = np.random.default_rng(0)
    z = SIM.draw_innovations(rng, nu=4.0, n=400000, innovations="TRUNCATED_T", tail_cap_sd=8.0)
    assert np.max(np.abs(z)) <= 8.0 * tr["renormalization"] + 1e-9 and np.var(z) == pytest.approx(1.0, rel=0.02)
    # bounded support => E[exp(sigma Z)] finite for every sigma; the untruncated t (nu=4) has none: its sample mean of exp(sigma z) explodes with n
    assert np.isfinite(np.mean(np.exp(3.0 * z)))
    sim = SIM.ConditionalSimulator(S0=100.0, variance_model={"kind": "FLAT", "h": 1e-6}, nu=4.0, iv0=0.2, spread_bps0=30.0)
    d = sim.describe()
    assert d["innovations"]["family"] == "TRUNCATED_T" and d["innovations"]["tail_cap_sd"] == 8.0 and d["innovations"]["finite_exponential_moments"] is True
    assert any("TRUNCATED" in r for r in sim.restrictions())
    with pytest.raises(SIM.SimulatorRefused, match="TAIL_CAP_INVALID"):
        SIM.ConditionalSimulator(S0=100.0, variance_model={"kind": "FLAT", "h": 1e-6}, nu=4.0, iv0=0.2, spread_bps0=30.0, tail_cap_sd=2.0)
    # the cap is part of the parameter hash: a different explicit choice is a different model
    d2 = SIM.ConditionalSimulator(S0=100.0, variance_model={"kind": "FLAT", "h": 1e-6}, nu=4.0, iv0=0.2, spread_bps0=30.0, tail_cap_sd=6.0).describe()
    assert d2["parameter_hash"] != d["parameter_hash"]


# ================================================================== pricing

def test_put_call_parity_greeks_and_iv_round_trip():
    S, K, T, sig, r, q = 645.0, 650.0, 21 / 365, 0.18, 0.04, 0.012
    C = PR.bsm_price(S=S, K=K, T=T, sigma=sig, r=r, q=q, right="CALL"); P = PR.bsm_price(S=S, K=K, T=T, sigma=sig, r=r, q=q, right="PUT")
    assert C - P == pytest.approx(S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-9)
    g = PR.bsm_greeks(S=S, K=K, T=T, sigma=sig, r=r, q=q, right="CALL")
    eps = 1e-3
    fd_delta = (PR.bsm_price(S=S + eps, K=K, T=T, sigma=sig, r=r, q=q) - PR.bsm_price(S=S - eps, K=K, T=T, sigma=sig, r=r, q=q)) / (2 * eps)
    fd_vega = (PR.bsm_price(S=S, K=K, T=T, sigma=sig + 1e-5, r=r, q=q) - PR.bsm_price(S=S, K=K, T=T, sigma=sig - 1e-5, r=r, q=q)) / 2e-5
    assert g["delta"] == pytest.approx(fd_delta, abs=1e-5) and g["vega"] == pytest.approx(fd_vega, rel=1e-4)
    iv = PR.implied_vol(price=C, S=S, K=K, T=T, r=r, q=q, right="CALL")
    assert iv["iv"] == pytest.approx(sig, abs=1e-8)
    with pytest.raises(PR.PricingRefused, match="OUTSIDE_NO_ARBITRAGE"):
        PR.implied_vol(price=S + 1, S=S, K=K, T=T, r=r, q=q, right="CALL")
    with pytest.raises(PR.PricingRefused, match="PRICE_AT_INTRINSIC"):
        PR.implied_vol(price=S * math.exp(-q * T) - 600.0 * math.exp(-r * T), S=S, K=600.0, T=T, r=r, q=q, right="CALL")


def test_american_engine_and_exercise_conventions():
    inst_am = PR.instrument(symbol="SPY", expiration="2026-10-09", strike=650.0, right="PUT", exercise="AMERICAN", settlement="PHYSICAL", dividend_yield=0.012)
    inst_eu = PR.instrument(symbol="SPX", expiration="2026-10-09", strike=650.0, right="PUT", exercise="EUROPEAN", settlement="CASH")
    S, T, sig, r = 645.0, 21 / 365, 0.18, 0.04
    am = PR.price(inst_am, S=S, T=T, sigma=sig, r=r)
    eu = PR.price(inst_eu, S=S, T=T, sigma=sig, r=r)
    assert am["engine"].startswith("CRR_AMERICAN") and eu["engine"] == "BSM_EUROPEAN" and am["price"] >= eu["price"] - 1e-9
    # deep ITM American put carries an early-exercise premium
    deep_am = PR.crr_american(S=500.0, K=650.0, T=0.5, sigma=0.18, r=0.05, right="PUT"); deep_eu = PR.bsm_price(S=500.0, K=650.0, T=0.5, sigma=0.18, r=0.05, right="PUT")
    assert deep_am > deep_eu + 1.0
    # CRR converges to BSM for a European-equivalent case (American call, no dividend)
    call_am = PR.crr_american(S=S, K=650.0, T=T, sigma=sig, r=r, right="CALL", steps=800)
    assert call_am == pytest.approx(PR.bsm_price(S=S, K=650.0, T=T, sigma=sig, r=r, right="CALL"), rel=2e-3)
    approx = PR.price(inst_am, S=S, T=T, sigma=sig, r=r, approximation="EUROPEAN_APPROX")
    assert approx["approximation"].startswith("EUROPEAN_APPROX declared")
    with pytest.raises(PR.PricingRefused, match="UNKNOWN_APPROXIMATION"):
        PR.price(inst_am, S=S, T=T, sigma=sig, r=r, approximation="WHATEVER")
    with pytest.raises(PR.PricingRefused, match="ADJUSTED_CONTRACT_REFUSED"):
        PR.instrument(symbol="X", expiration="2026-10-09", strike=10.0, right="CALL", exercise="AMERICAN", settlement="PHYSICAL", adjusted=True)
    with pytest.raises(PR.PricingRefused, match="MULTIPLIER_NOT_100"):
        PR.instrument(symbol="X", expiration="2026-10-09", strike=10.0, right="CALL", exercise="AMERICAN", settlement="PHYSICAL", multiplier=10.0)
    assert "assignment" in inst_am["early_exercise_note"]


def test_quote_sanitation_refuses_bad_quotes_and_never_cleans_them():
    good = {"bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": 12, "timestamp_epoch": T0 - 1}
    s = PR.sanitize_quote(good, now=T0)
    assert s["mid"] == 2.45 and s["usable_for_iv"] is True
    for bad, why in ((dict(good, bid=2.6), "CROSSED"), (dict(good, ask=0.0), "NO_ASK"), (dict(good, ask_size=0), "SIZE_INVALID"),
                     (dict(good, timestamp_epoch=T0 - 20), "STALE"), (dict(good, bid=float("nan")), "NONFINITE"), (dict(good, ask=True), "NONFINITE")):
        with pytest.raises(PR.PricingRefused, match=why):
            PR.sanitize_quote(bad, now=T0)


# ================================================================== surface

def test_svi_round_trip_and_arbitrage_diagnostics_are_recorded():
    true = {"a": 0.0004, "b": 0.01, "rho": -0.4, "m": 0.0, "sigma": 0.08}
    k = np.linspace(-0.15, 0.15, 25); T = 21 / 365
    w = SF.svi_w(k, **true)
    fit = SF.fit_svi_slice(k=k, w=w, T=T)
    assert fit["fit_ok"] and fit["rmse_total_variance"] < 2e-6 and fit["butterfly"]["arbitrage_free_butterfly"]
    assert np.allclose(SF.svi_w(k, **fit["params"]), w, atol=5e-6)      # total variance ~4e-4: ~1% round trip
    # a crafted slice that violates the butterfly condition is RECORDED as such, not repaired
    bad = {"a": -0.0004, "b": 0.05, "rho": 0.95, "m": 0.0, "sigma": 0.01}
    diag = SF.butterfly_diagnostic(bad, k_grid=np.linspace(-0.3, 0.3, 101))
    assert diag["arbitrage_free_butterfly"] is False and diag["violations"] > 0
    # calendar: the longer expiry must have >= total variance
    s1 = {"T": 21 / 365, "params": true}; s2 = {"T": 49 / 365, "params": {**true, "a": 0.0002}}      # crafted violation
    cal = SF.calendar_diagnostic([s1, s2], k_grid=np.linspace(-0.2, 0.2, 41))
    assert cal["arbitrage_free_calendar"] is False and cal["problems"][0]["k_violations"] > 0
    surf = SF.Surface([fit, {**fit, "T": 49 / 365, "params": {**true, "a": 0.0009}, "fit_ok": True}], source="SYNTHETIC", quote_quality={"n_used": 25})
    d = surf.describe()
    assert d["european_only"] is True and d["calendar"]["arbitrage_free_calendar"] is True
    assert surf.iv(0.0, T)["interpolated"] is False and surf.iv(0.0, 35 / 365)["interpolated"] is True
    with pytest.raises(PR.PricingRefused, match="T_OUTSIDE"):
        surf.iv(0.0, 100 / 365)
    with pytest.raises(PR.PricingRefused, match="SVI_INPUT_INVALID"):
        SF.fit_svi_slice(k=k[:3], w=w[:3], T=T)


# ================================================================== expression war

def test_expression_comparison_under_common_paths_records_everything():
    sim = SIM.ConditionalSimulator(S0=645.0, variance_model={"kind": "FLAT", "h": 2e-8}, nu=6.0, iv0=0.18, spread_bps0=400.0, cutoff_epoch=T0)
    paths = sim.simulate(horizon_bars=15, n_paths=4000, seed=7)
    atm = PR.instrument(symbol="SPY", expiration="2026-10-09", strike=645.0, right="CALL", exercise="AMERICAN", settlement="PHYSICAL")
    otm = PR.instrument(symbol="SPY", expiration="2026-10-09", strike=655.0, right="CALL", exercise="AMERICAN", settlement="PHYSICAL")
    T = 21 / 365
    fair_atm = PR.bsm_price(S=645.0, K=645.0, T=T, sigma=0.18); fair_otm = PR.bsm_price(S=645.0, K=655.0, T=T, sigma=0.18)
    cands = [{"label": "ATM_CALL", "instrument": atm, "quote": {"bid": fair_atm * 0.98, "ask": fair_atm * 1.02, "bid_size": 9, "ask_size": 12, "timestamp_epoch": T0 - 1}},
             {"label": "OTM_CALL", "instrument": otm, "quote": {"bid": fair_otm * 0.98, "ask": fair_otm * 1.02, "bid_size": 9, "ask_size": 12, "timestamp_epoch": T0 - 1}},
             {"label": "STALE_CALL", "instrument": otm, "quote": {"bid": 1.0, "ask": 1.1, "bid_size": 9, "ask_size": 12, "timestamp_epoch": T0 - 60}}]
    cmp = EW.compare(paths=paths, candidates=cands, T_years_by_contract={"ATM_CALL": T, "OTM_CALL": T, "STALE_CALL": T}, horizon_years=15 / (252 * 390),
                     r=0.0, fees_entry=0.97, fees_exit=1.0, now=T0)
    labels = {c["label"]: c for c in cmp["candidates"]}
    assert labels["WAIT"]["status"] == "ELIGIBLE" and labels["WAIT"]["expected_net_pnl"] == 0.0
    assert labels["STALE_CALL"]["status"] == "REJECTED" and labels["STALE_CALL"]["why"].startswith("QUOTE: QUOTE_STALE")
    for lab in ("ATM_CALL", "OTM_CALL"):
        c = labels[lab]
        assert c["status"] == "ELIGIBLE" and c["expected_value_established"] is False       # IV held fixed
        assert c["expected_net_pnl"] < 0                                                    # spread crossing + fees + 15 min of theta, zero drift
        assert c["certified_max_loss"] == pytest.approx(100 * c["entry_ask"] + 1.97)
        assert set(c["iv_sensitivity_of_expected_pnl"]) == {"-0.2", "-0.1", "0.0", "0.1", "0.2"}
        assert c["iv_sensitivity_of_expected_pnl"]["0.2"] > c["iv_sensitivity_of_expected_pnl"]["-0.2"]
        assert 0 < c["p_loss"] <= 1 and c["mc_se_mean"] > 0
    assert cmp["selection_authority"].startswith("NONE") and cmp["expected_value_note"].startswith("UNESTABLISHED")
    assert cmp["costs"]["double_counting"].startswith("spread crossing is in the quoted sides only")
    assert cmp["common_paths"]["seed"] == 7 and cmp["common_paths"]["parameter_hash"] == paths["parameter_hash"]
    pv = EW.physical_vs_implied(physical_var_15m=2e-8 * 15, implied_iv_annual=0.18)
    assert pv["risk_premium_disclosed"] is True and "not a mechanical arbitrage signal" in pv["interpretation"] and pv["log_ratio"] is not None


def test_sanitize_quote_refuses_non_finite_or_mistyped_timestamps_before_arithmetic():
    from apex.multiverse_wb.pricing import PricingRefused, sanitize_quote
    good = {"bid": 1.0, "ask": 1.1, "bid_size": 5, "ask_size": 5, "timestamp_epoch": 1000.0}
    assert sanitize_quote(good, now=1001.0, max_age_s=15.0)["age_s"] == 1.0
    for bad in (float("nan"), float("inf"), -float("inf"), "1000", True, None):
        with pytest.raises(PricingRefused, match="QUOTE_TIMESTAMP_INVALID"):
            sanitize_quote({**good, "timestamp_epoch": bad}, now=1001.0, max_age_s=15.0)
    with pytest.raises(PricingRefused, match="CLOCK_INVALID"):
        sanitize_quote(good, now=float("nan"), max_age_s=15.0)
    with pytest.raises(PricingRefused, match="MAX_AGE_INVALID"):
        sanitize_quote(good, now=1001.0, max_age_s=-1.0)
    with pytest.raises(PricingRefused, match="QUOTE_SIZE_INVALID"):
        sanitize_quote({**good, "bid_size": -1}, now=1001.0, max_age_s=15.0)
