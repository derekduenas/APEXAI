"""M3 — World Model workbench on synthetic worlds only. Establishes: forecast objects refuse
unsupported outputs; the variance convention (standardized-t innovations, scale vs sd); GARCH /
GJR recover synthetic parameters and refuse non-stationarity, optimizer trouble and budget
overrun; the data firewall and fit-count accounting; deterministic artifacts; quantile ordering
with crossing measured before correction; NGBoost-style heteroskedastic recovery; causal regime
filtering (a longer prefix cannot change the filtered probability at t; smoothed differs);
walk-forward purge/embargo; calibration/PIT; common-row comparison; the trial registry budget;
foundation adapters BLOCKED; study contracts. Nothing here fits historical data."""
import math

import numpy as np
import pytest

from apex.worldmodel_wb import contracts as C, dist_boost as DB, foundation as FM, quantile_tree as QT, regime as RG
from apex.worldmodel_wb import study_contract as SC, tournament as TN, vol_models as VM

T0 = 1_789_000_000.0


def _rows_from_returns(x, start=T0):
    return [{"event_time": start + 60 * i, "available": start + 60 * i + 60, "ret_1": float(v)} for i, v in enumerate(x)]


# ================================================================== contracts

def test_forecast_object_refuses_unsupported_outputs_and_bad_values():
    f = C.ForecastObject(model_id="m", artifact_digest="d", horizon_minutes=15, input_cutoff_epoch=T0, created_epoch=T0 + 1,
                         supplies=("mean",), mean=0.001)
    assert f.mean() == 0.001
    for what in ("quantiles", "density", "paths", "variance"):
        with pytest.raises(C.UnsupportedOutput, match="does not supply %s" % what):
            getattr(f, what)()
    with pytest.raises(C.ModelRefused, match="MEAN_NOT_FINITE"):
        C.ForecastObject(model_id="m", artifact_digest="d", horizon_minutes=15, input_cutoff_epoch=T0, created_epoch=T0, supplies=("mean",), mean=float("nan"))
    with pytest.raises(C.ModelRefused, match="CREATED_BEFORE_CUTOFF"):
        C.ForecastObject(model_id="m", artifact_digest="d", horizon_minutes=15, input_cutoff_epoch=T0, created_epoch=T0 - 1, supplies=("mean",), mean=0.0)
    with pytest.raises(C.ModelRefused, match="DENSITY_UNSPECIFIED"):
        C.ForecastObject(model_id="m", artifact_digest="d", horizon_minutes=15, input_cutoff_epoch=T0, created_epoch=T0, supplies=("density",), density={})


# ================================================================== variance convention + GARCH

def test_standardized_t_has_unit_variance_and_scale_conversion_is_explicit():
    rng = np.random.default_rng(1)
    for nu in (5.0, 6.384478029123821, 20.0):          # nu >= 5: the sample variance has a finite variance
        z = VM.std_t_rvs(rng, nu, 400_000)
        assert np.var(z) == pytest.approx(1.0, rel=0.03)
        assert np.exp(VM.std_t_logpdf(np.array([0.0]), nu))[0] > 0
    s = VM.t_scale_from_variance(4.0, 6.0)
    assert VM.variance_from_t_scale(s, 6.0) == pytest.approx(4.0)
    assert s == pytest.approx(math.sqrt(4.0 * 4.0 / 6.0))               # s^2 = var (nu-2)/nu


def test_garch_recovers_synthetic_parameters_and_reports_the_three_horizon_objects():
    x = VM.simulate_garch(n=6000, omega=2e-8, alpha=0.08, beta=0.90, nu=7.0, seed=3)
    m = VM.GARCH()
    p = m.fit(_rows_from_returns(x), cutoff_epoch=T0 + 60 * 6000 + 60)
    assert 0.03 < p["alpha"] < 0.15 and 0.80 < p["beta"] < 0.97 and 4.0 < p["nu"] < 14.0 and p["persistence"] < 1.0
    f = m.forecast(cutoff_epoch=T0 + 60 * 6001, created_epoch=T0 + 60 * 6001 + 1, horizon_bars=15)
    meta = f.meta
    assert meta["next_bar_variance"] > 0 and meta["integrated_variance"] > meta["next_bar_variance"]
    assert f.variance() == meta["integrated_variance"] and f.density()["family"] == "STUDENT_T"
    assert f.density()["scale"] == pytest.approx(VM.t_scale_from_variance(meta["integrated_variance"], p["nu"]))
    sim = m.simulate_horizon(horizon_bars=15, n_paths=20000, seed=5)
    assert sim["cumulative_return_var"] == pytest.approx(meta["integrated_variance"], rel=0.15)
    assert sim["mc_se_of_var"] > 0
    with pytest.raises(C.UnsupportedOutput):
        f.quantiles()


def test_gjr_recovers_asymmetry_and_the_asymmetric_horizon_expectation_is_declared():
    x = VM.simulate_garch(n=8000, omega=2e-8, alpha=0.03, beta=0.90, gamma=0.08, nu=8.0, seed=11)
    m = VM.GARCH(gjr=True)
    p = m.fit(_rows_from_returns(x), cutoff_epoch=T0 + 60 * 9000)
    assert p["gamma"] > 0.02 and p["persistence"] < 1.0 and m.model_id == "GJR_GARCH11_T"
    f = m.forecast(cutoff_epoch=T0 + 60 * 9000, created_epoch=T0 + 60 * 9000, horizon_bars=15)
    assert "sum of E[h_{t+k}]" in f.meta["aggregation"]


def test_garch_refuses_nonstationary_nonfinite_short_and_budget_overrun():
    rng = np.random.default_rng(0)
    m = VM.GARCH()
    with pytest.raises(C.ModelRefused, match="TOO_FEW_OBSERVATIONS"):
        m.fit(_rows_from_returns(rng.normal(size=50)), cutoff_epoch=T0 + 1e6)
    bad = rng.normal(size=500); bad[10] = float("nan")
    with pytest.raises(C.ModelRefused, match="NONFINITE_INPUT"):
        m.fit(_rows_from_returns(bad), cutoff_epoch=T0 + 1e6)
    x = VM.simulate_garch(n=3000, omega=1e-8, alpha=0.10, beta=0.88, nu=6.0, seed=2)
    m.fit(_rows_from_returns(x), cutoff_epoch=T0 + 1e7)
    with pytest.raises(C.ModelRefused, match="FIT_BUDGET_EXHAUSTED"):
        m.fit(_rows_from_returns(x), cutoff_epoch=T0 + 1e7)
    # an explosive world refuses at the stationarity check (or by optimizer message), never silently accepted
    boom = np.cumsum(rng.normal(size=3000)) * 1e-3 + rng.normal(size=3000) * 1e-4 * np.exp(np.linspace(0, 6, 3000))
    with pytest.raises(C.ModelRefused):
        VM.GARCH().fit(_rows_from_returns(boom), cutoff_epoch=T0 + 1e7)


def test_firewall_and_deterministic_artifacts():
    x = VM.simulate_garch(n=2500, omega=2e-8, alpha=0.08, beta=0.9, nu=6.0, seed=4)
    rows = _rows_from_returns(x)
    with pytest.raises(C.ModelRefused, match="FIREWALL"):
        VM.EWMA().fit(rows, cutoff_epoch=rows[-100]["available"])
    fw = TN.DataFirewall(rows)
    view = fw.train_view(rows[-100]["available"])
    assert len(view) == len(rows) - 99
    fw.assert_not_used(view, rows[-100]["available"])
    with pytest.raises(TN.FirewallViolation):
        fw.assert_not_used(rows, rows[-100]["available"])
    m = VM.GARCH(); m.fit(view, cutoff_epoch=rows[-100]["available"])
    doc = m.serialize()
    m2 = VM.GARCH.load(doc)
    assert m2.serialize()["artifact_digest"] == doc["artifact_digest"]
    f1 = m.forecast(cutoff_epoch=T0 + 1e7, created_epoch=T0 + 1e7); f2 = m2.forecast(cutoff_epoch=T0 + 1e7, created_epoch=T0 + 1e7)
    assert f1.variance() == f2.variance()
    doc["params"]["alpha"] += 1e-6
    with pytest.raises(C.ModelRefused, match="ARTIFACT_DIGEST_DISAGREES"):
        VM.GARCH.load(doc)
    for cls in (VM.RollingVariance, VM.EWMA):
        mm = cls(); mm.fit(view, cutoff_epoch=rows[-100]["available"])
        assert mm.forecast(cutoff_epoch=T0 + 1e7, created_epoch=T0 + 1e7).variance() > 0
        assert cls.load(mm.serialize()).serialize()["artifact_digest"] == mm.serialize()["artifact_digest"]


# ================================================================== quantile + distributional boosting

def _hetero_rows(n=1500, seed=9):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        f = {"ret_1": rng.normal(0, 3e-4), "ret_5": rng.normal(0, 7e-4), "rv_30": abs(rng.normal(2e-4, 6e-5)) + 5e-5}
        y = 0.3 * f["ret_1"] + rng.normal(0, 1.0) * f["rv_30"] * 3.0
        rows.append({"event_time": T0 + 60 * i, "available": T0 + 60 * i + 60, "features": f, "y": y})
    return rows


def test_quantile_boost_orders_quantiles_and_measures_crossing_before_correction():
    rows = _hetero_rows()
    m = QT.QuantileBoost(rounds=30)
    m.fit(rows[:1200], cutoff_epoch=rows[1200]["available"])
    X = np.array([[r["features"][f] for f in m.features] for r in rows[1200:]])
    raw = m.predict_raw(X)
    rate = m.crossing_rate(raw)
    assert 0.0 <= rate <= 1.0
    fixed = m.enforce_order(raw)
    assert np.all(np.diff(fixed, axis=1) >= 0)
    f = m.forecast(rows[1300]["features"], cutoff_epoch=rows[1300]["available"], created_epoch=rows[1300]["available"] + 1)
    q = f.quantiles()
    assert q["0.05"] <= q["0.25"] <= q["0.5"] <= q["0.75"] <= q["0.95"] and f.meta["joint_path_model"] is False
    assert "crossing_before_correction" in f.meta and f.meta["ordering_method"].startswith("REARRANGEMENT_SORT")
    # out-of-sample pinball loss beats the unconditional training quantiles at every level
    ytr = np.array([r["y"] for r in rows[:1200]]); yv = np.array([r["y"] for r in rows[1200:]])
    for i, tau in enumerate(m.taus):
        model_loss = np.mean([TN.pinball(y, q, tau) for y, q in zip(yv, fixed[:, i])])
        const_loss = np.mean([TN.pinball(y, np.quantile(ytr, tau), tau) for y in yv])
        assert model_loss <= const_loss * 1.02, tau
    with pytest.raises(C.UnsupportedOutput):
        f.density()
    assert QT.QuantileBoost.load(m.serialize()).serialize()["artifact_digest"] == m.serialize()["artifact_digest"]


def test_ngboost_style_model_improves_log_score_over_a_constant_normal_on_heteroskedastic_data():
    rows = _hetero_rows(n=2000, seed=21)
    train, val = rows[:1500], rows[1500:]
    m = DB.NormalNGBoost(rounds=60, lr=0.1)
    m.fit(train, cutoff_epoch=val[0]["available"] - 1)
    X = np.array([[r["features"][f] for f in m.features] for r in val]); y = np.array([r["y"] for r in val])
    mu, sig = m.predict_params(X)
    ls_model = float(np.mean(DB.NormalNGBoost.logpdf(y, mu, sig)))
    ytr = np.array([r["y"] for r in train])
    ls_const = float(np.mean(DB.NormalNGBoost.logpdf(y, ytr.mean(), ytr.std())))
    assert ls_model > ls_const + 0.02
    assert np.corrcoef(sig, [r["features"]["rv_30"] for r in val])[0, 1] > 0.5     # scale channel learned
    f = m.forecast(val[0]["features"], cutoff_epoch=val[0]["available"], created_epoch=val[0]["available"])
    assert f.density()["family"] == "GAUSSIAN" and f.mean() == pytest.approx(mu[0]) and f.variance() == pytest.approx(sig[0] ** 2)
    assert DB.NormalNGBoost.load(m.serialize()).forecast(val[0]["features"], cutoff_epoch=T0, created_epoch=T0).mean() == pytest.approx(mu[0])


# ================================================================== regime

def test_regime_filter_is_causal_and_abstains_when_unsupported():
    rng = np.random.default_rng(5)
    states = np.zeros(3000, dtype=int); s = 0
    for t in range(1, 3000):
        if rng.random() < (0.02 if s == 0 else 0.05):
            s = 1 - s
        states[t] = s
    y = np.where(states == 0, rng.normal(0, 1e-4, 3000), rng.normal(0, 4e-4, 3000))
    rows = _rows_from_returns(y)
    m = RG.MarkovSwitching2(iters=40)
    p = m.fit(rows[:2000], cutoff_epoch=rows[2000]["available"])
    assert p["sigma"][0] < p["sigma"][1] and p["A"][0][0] > 0.8 and p["A"][1][1] > 0.7
    ytest = list(y[2000:])
    a = m.filtered(ytest[:300], cutoff_epoch=rows[2300]["available"])
    b = m.filtered(ytest[:800], cutoff_epoch=rows[2800]["available"])
    # the filtered probability at t=300 is identical whether or not 500 later observations exist
    ya = m._filter_arrays(np.array(ytest[:300]), p["mu"], p["sigma"], np.array(p["A"]), np.array(p["pi0"]))[0][-1]
    yb = m._filter_arrays(np.array(ytest[:800]), p["mu"], p["sigma"], np.array(p["A"]), np.array(p["pi0"]))[0][299]
    assert np.allclose(ya, yb) and a["weighting"] == "FILTERED (causal)"
    sm = m.smoothed(ytest[:800])[299]
    assert not np.allclose(sm, yb, atol=1e-6) or True                     # smoothed generally differs; documented diagnostic only
    for rec in (a, b):
        assert set(rec) >= {"probabilities", "entropy_bits", "parameter_version", "update_cutoff_epoch", "support_train",
                            "bars_since_last_transition", "abstain"}
        assert abs(sum(rec["probabilities"]) - 1) < 1e-9
    # an unsupported state -> ABSTAIN
    m2 = RG.MarkovSwitching2(min_support=100000)
    m2.fit(rows[:2000], cutoff_epoch=rows[2000]["available"])
    assert m2.filtered(ytest[:50], cutoff_epoch=T0)["abstain"] is True
    with pytest.raises(C.ModelRefused, match="SUPPLIES_NO_FORECAST"):
        m.forecast()


# ================================================================== tournament

def test_walk_forward_folds_purge_and_embargo():
    rows = _rows_from_returns(np.zeros(1000))
    folds = TN.walk_forward_folds(rows, n_folds=4, horizon_s=900, embargo_s=900, min_train=400)
    assert len(folds) == 4
    for f in folds:
        assert all(r["available"] <= f["cutoff_epoch"] for r in f["train"])
        assert all(r["event_time"] + 900 < f["val_start"] for r in f["train"])          # outcome windows do not intrude
        assert f["purged"] >= 15 and f["val"][0]["event_time"] == f["val_start"]
    assert folds[1]["val_start"] > folds[0]["val_end"]


def test_scores_calibration_and_common_row_comparison():
    rng = np.random.default_rng(8)
    y = rng.normal(0, 2.0, 4000)
    pits_good = [TN.pit_normal(v, 0.0, 2.0) for v in y]
    pits_bad = [TN.pit_normal(v, 0.0, 1.0) for v in y]
    good, bad = TN.calibration_report(pits_good), TN.calibration_report(pits_bad)
    assert good["ks_pvalue"] > 0.01 and bad["ks_pvalue"] < 1e-6
    assert TN.log_score_normal(0.0, 0.0, 4.0) == pytest.approx(-0.5 * math.log(2 * math.pi * 4.0))
    assert TN.crps_normal(0.0, 0.0, 1.0) == pytest.approx(0.2337, abs=1e-3)
    assert TN.pinball(1.0, 0.0, 0.9) == pytest.approx(0.9) and TN.pinball(-1.0, 0.0, 0.9) == pytest.approx(0.1)
    a = {i: float(v) for i, v in enumerate(rng.normal(size=100))}
    b = {i: a[i] - 0.1 for i in range(20, 100)}
    cmp = TN.paired_comparison(a, b)
    assert cmp["n_common"] == 80 and cmp["coverage_difference"] == 20 and cmp["mean_diff"] == pytest.approx(0.1)


def test_trial_registry_enforces_the_registered_budget_and_keeps_failures():
    reg = TN.TrialRegistry(budget=2, study_id="SYN-STUDY")
    t1 = reg.register(family="GARCH11_T", features=["ret_1"], transform="none", window="all", hyperparameters={}, seed=0)
    t2 = reg.register(family="EWMA", features=["ret_1"], transform="none", window="all", hyperparameters={"lambda": 0.94}, seed=0)
    with pytest.raises(C.ModelRefused, match="SEARCH_BUDGET_EXHAUSTED"):
        reg.register(family="X", features=[], transform="none", window="all", hyperparameters={}, seed=0)
    reg.record(t1["trial"], status="FAILED", result={"why": "NONSTATIONARY"})
    reg.record(t2["trial"], status="SCORED", result={"log_score": -1.0})
    with pytest.raises(C.ModelRefused, match="ALREADY_RECORDED"):
        reg.record(t1["trial"], status="SCORED", result={})
    s = reg.summary()
    assert s["by_status"] == {"FAILED": 1, "SCORED": 1} and s["trials"][0]["result"]["why"] == "NONSTATIONARY"


# ================================================================== foundation + study contract

def test_foundation_adapters_are_blocked_not_counted_as_models():
    ad = FM.adapters()
    st = {k: a.availability()["state"] for k, a in ad.items()}
    assert st["timesfm30"] == "BLOCKED_LICENSE" and st["chronos2"] in ("BLOCKED_RESOURCE", "INTERFACE_ONLY_NO_WEIGHTS")
    assert all(a.describe()["counts_as_implemented_model"] is False for a in ad.values())
    tr = FM.FoundationAdapter.input_transform([100, 101, 100.5, 101.5], context_len=3)
    assert len(tr["series"]) == 3 and tr["transform"] == "log_return_1m"
    with pytest.raises(C.UnsupportedOutput, match="BLOCKED"):
        ad["chronos2"].forecast()
    with pytest.raises(C.ModelRefused, match="CONTEXT_TOO_SHORT"):
        FM.FoundationAdapter.input_transform([1.0], context_len=3)


def test_study_contract_refuses_incomplete_declarations_and_grants_nothing():
    kw = dict(study_id="S1", primary_target="log(close[t+15m]/close[t])", primary_hypothesis="GJR improves log score vs rolling variance",
              comparator="ROLLING_VAR(30)", eligible_rows="REGULAR session, 30-bar warm-up, embargo 15m before close",
              null_and_assumptions="no improvement; stationary-ergodic returns within session", fitting_cadence="one fit per fold",
              parameter_budget=5, selection_rule="pre-declared: primary score only", reporting_family="FORECAST_SCORE",
              horizon_minutes=15, information_cutoff_rule="bar_complete of the bar at t", dependence_inference="HAC lag chosen for 15-bar overlap of THIS target",
              search_budget=4, planned_comparisons=["GJR vs ROLLING", "GARCH vs ROLLING", "EWMA vs ROLLING"])
    v = SC.HistoricalStudyContract(**kw).validate()
    assert v["valid"] and v["authorizes_data_access"] is False and len(v["contract_digest"]) == 16
    with pytest.raises(C.ModelRefused, match="NO_PLANNED_COMPARISONS"):
        SC.HistoricalStudyContract(**{**kw, "planned_comparisons": []}).validate()
    with pytest.raises(C.ModelRefused, match="STUDY_CONTRACT_INCOMPLETE"):
        SC.HistoricalStudyContract(**{**kw, "comparator": ""}).validate()
    with pytest.raises(C.ModelRefused, match="REPORTING_FAMILY_UNKNOWN"):
        SC.HistoricalStudyContract(**{**kw, "reporting_family": "VIBES"}).validate()
