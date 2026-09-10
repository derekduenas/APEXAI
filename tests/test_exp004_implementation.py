"""EXP-004 implementation checks under the frozen registration: N1-N8,
declared refusals, all 16 primary-flag combinations, integrity precedence,
six-hypothesis Holm per method, bootstrap intervals and adapter equivalence.

These establish IMPLEMENTATION BEHAVIOUR on deterministic synthetic fixtures.
They do not establish market signal, statistical size, or power."""
import copy
import itertools
import json
import math
import random

import numpy as np
import pytest

from apex.world_model.exp001b import bars as B
from apex.world_model.exp002.bootstrap import session_stationary_bootstrap as boot_orig
from apex.world_model.exp002 import studentt as T
from apex.world_model.exp004 import (bootstrap_adapter as BA, dispersion as D, features as F,
                                     inference as I, models as M, run as R)
from apex.world_model.exp004.registration import ARMS, BUDGET, WINDOW_BARS, registration_hash
from tests import exp004_fixtures as X

REG_HASH = "9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9"


@pytest.fixture(scope="module")
def world():
    fit = X.fit_sessions()
    dev = X.dev_sessions_years()                 # 2019, 2020, 2021 x 4 sessions, chronological
    prep = R.prepare_fit(fit)
    return {"fit": fit, "dev": dev, "prep": prep}


# ------------------------------------------------------------------ N1-N4: representation

def test_n1_identical_closes_identical_legacy_inputs_different_F():
    day = X.trading_days("2018-03-01", 1)[0]
    bars1 = X.build_bars(day, X.SEEDS["n"])
    closes = [b["close"] for b in bars1]
    bars2 = X.build_bars(day, X.SEEDS["n"] + 1, closes=closes, vol_scale=1.7, body_sign=-1.0)
    s1, s2 = X.session_from_bars(day, bars1), X.session_from_bars(day, bars2)
    vbar = {m: 60_000.0 for m in range(400)}
    r1, _ = F.eligible_rows(s1, vbar); r2, _ = F.eligible_rows(s2, vbar)
    assert len(r1) == len(r2) > 200
    diffF = 0
    for (a, ya, _), (b, yb, _) in zip(r1, r2):
        assert a["event_time"] == b["event_time"] and ya == yb
        for k in ("ret_1", "ret_5", "rv_30"):
            assert a["features"][k] == b["features"][k]              # legacy inputs bit-identical
        diffF += int(a["features"]["F"] != b["features"]["F"])
    assert diffF > 0.95 * len(r1)


def test_n2_identical_ingredients_different_alignment():
    rng = random.Random(X.SEEDS["n"])
    bars = [{"open": 100 - x, "high": 100.5, "low": 99.5, "close": 100, "volume": v, "minute": i}
            for i, (x, v) in enumerate(zip([rng.uniform(-0.4, 0.4) for _ in range(WINDOW_BARS)],
                                           [rng.uniform(1e4, 9e4) for _ in range(WINDOW_BARS)]))]
    vbars = [5e4] * WINDOW_BARS
    a = F.pressure_from_window(bars, vbars)
    rev = [dict(b, volume=v) for b, v in zip(bars, [b["volume"] for b in bars][::-1])]
    b = F.pressure_from_window(rev, vbars)
    assert math.isclose(a["Bbar"], b["Bbar"]) and math.isclose(a["P"], b["P"])
    assert not math.isclose(a["F"], b["F"], rel_tol=1e-6)
    # the raw identity F = Bbar*P + W*Cov_W(B,V)/sum(vbar), divisor W
    bs = [F.body(x)[0] for x in bars]; vs = [x["volume"] for x in bars]; W = WINDOW_BARS
    cov = sum((bb - a["Bbar"]) * (v - sum(vs) / W) for bb, v in zip(bs, vs)) / W
    assert math.isclose(a["F"], a["Bbar"] * a["P"] + W * cov / sum(vbars), rel_tol=1e-12)


def test_n3_one_dominant_bar_equals_ten_uniform_bars():
    vbars = [5e4] * WINDOW_BARS
    uniform = [{"open": 99.8, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1e4, "minute": i} for i in range(WINDOW_BARS)]
    dominant = [{"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 0.0, "minute": i} for i in range(WINDOW_BARS - 1)]
    dominant.append({"open": 99.8, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1e5, "minute": 9})
    u, d = F.pressure_from_window(uniform, vbars), F.pressure_from_window(dominant, vbars)
    assert math.isclose(u["F"], d["F"], rel_tol=1e-12) and math.isclose(u["P"], d["P"])
    assert not math.isclose(u["Bbar"], d["Bbar"])        # documents what F does NOT distinguish
    assert d["zero_range_bars"] == 0


def test_n4_features_use_only_prior_completed_bars():
    day = X.trading_days("2018-03-05", 1)[0]
    bars = X.build_bars(day, X.SEEDS["n"] + 2)
    s = X.session_from_bars(day, bars)
    vbar = {m: 60_000.0 for m in range(400)}
    rows, _ = F.eligible_rows(s, vbar)
    r = rows[len(rows) // 2][0]; t = r["event_time"]
    fut = [dict(b, volume=b["volume"] * 3, open=b["close"] + (b["close"] - b["open"]),
                high=b["high"] + 1, low=b["low"] - 1) if X.datetime.strptime(b["event_time_utc"], "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=X.timezone.utc).timestamp() > t else b for b in bars]
    rows2, _ = F.eligible_rows(X.session_from_bars(day, fut), vbar)
    r2 = next(x for x, _, _ in rows2 if x["event_time"] == t)
    assert r2["features"] == r["features"]                             # future bars cannot change the row
    inside = [dict(b, volume=b["volume"] * 3) if abs(X.datetime.strptime(b["event_time_utc"], "%Y-%m-%dT%H:%M:%SZ")
              .replace(tzinfo=X.timezone.utc).timestamp() - (t - 120)) < 1 else b for b in bars]
    rows3, _ = F.eligible_rows(X.session_from_bars(day, inside), vbar)
    r3 = next(x for x, _, _ in rows3 if x["event_time"] == t)
    assert r3["features"]["P"] != r["features"]["P"]                   # a bar inside the window does


# ------------------------------------------------------------------ N5, N6

def test_n5_c_is_distinct_from_ax_out_of_sample_and_degenerate_columns_refused(world):
    prep, dev = world["prep"], world["dev"]
    rows, _, _ = F.eligible_rows_many(dev, prep["vbar"]); F.apply_clipping(rows, prep["clipping"])
    rr = [r for r, _, _ in rows]
    diff = np.abs(M.means_of(prep["location"]["specs"]["C"], rr) - M.means_of(prep["location"]["specs"]["AX"], rr))
    assert diff.max() > 0 and np.isfinite(diff).all()
    assert prep["location"]["specs"]["C"]["rank"] == 7 and prep["location"]["specs"]["AX"]["rank"] == 6
    fit_rows, _, _ = F.eligible_rows_many(world["fit"][:5], prep["vbar"], role="fit"); F.apply_clipping(fit_rows, prep["clipping"])
    zero = copy.deepcopy(fit_rows)
    for r, _, _ in zero:
        r["features"]["F_c"] = 0.3
    with pytest.raises(M.ArmRefused, match="ZERO_VARIANCE_FEATURE"):
        M.fit_arm(zero, "C")
    dup = copy.deepcopy(fit_rows)
    for r, _, _ in dup:
        r["features"]["ret_5"] = 2.0 * r["features"]["ret_1"]
    with pytest.raises(M.ArmRefused, match="RANK_DEFICIENT"):
        M.fit_arm(dup, "L")


def test_n6_dispersion_identity_check_passes_and_has_teeth(world):
    d0, d1 = world["prep"]["dispersion"]["D0"], world["prep"]["dispersion"]["D1"]
    assert d1["identity_check"]["ok"] and d1["identity_check"]["rel_diff"] <= 1e-9
    rng = np.random.default_rng(X.SEEDS["n"]); z = rng.standard_t(6.0, 500) * 2.0; p = rng.uniform(0, 2, 500)
    ok = D.identity_check(z, p, math.log(2.0), 6.0); assert ok["ok"]
    assert not math.isclose(D.J1(z, p, math.log(2.0), 0.5, 6.0), D.J0(z, math.log(2.0), math.log(6.0)), rel_tol=1e-9)
    wrong = float(np.sum(-(math.log(2.0)) - D._log_t_unit(z / 2.0, 6.0)))   # sign-flipped Jacobian
    assert abs(wrong - ok["J0"]) / abs(ok["J0"]) > 1e-3
    assert d1["nu0"] == d0["nu0"]                                       # nu frozen, not re-estimated


# ------------------------------------------------------------------ refusals

def test_dispersion_refusals(monkeypatch):
    rng = np.random.default_rng(X.SEEDS["n"] + 5)
    z = rng.standard_t(6.0, 800) * 1.5; p = rng.uniform(0, 1.5, 800)
    with pytest.raises(D.DispersionRefused, match="NONFINITE_RESIDUALS"):
        D.fit_d0(np.concatenate([z, [np.nan]]))
    with pytest.raises(D.DispersionRefused, match="INSUFFICIENT_RESIDUALS"):
        D.fit_d0(z[:99])
    d0 = D.fit_d0(z)
    with pytest.raises(D.DispersionRefused, match="NONFINITE_OR_MISALIGNED_P"):
        D.fit_d1(z, p[:-1], nu0=d0["nu0"], s0=d0["s0"])
    with pytest.raises(D.DispersionRefused, match="OPTIMIZER_NO_CONVERGENCE"):
        D.fit_d1(z, p, nu0=d0["nu0"], s0=d0["s0"], max_iter=1)
    real = D._nelder_mead
    for lam in (2.0, -2.0 + 5e-4, 1.9995):
        monkeypatch.setattr(D, "_nelder_mead", lambda f, x0, **k: (np.array([x0[0], lam]), 1.0, True, 3))
        with pytest.raises(D.DispersionRefused, match="LAMBDA_AT_BOUND"):
            D.fit_d1(z, p, nu0=d0["nu0"], s0=d0["s0"])
    monkeypatch.setattr(D, "_nelder_mead", lambda f, x0, **k: (np.array([x0[0], 1.5]), 1.0, True, 3))
    assert D.fit_d1(z, p, nu0=d0["nu0"], s0=d0["s0"])["lambda"] == 1.5      # inside the bounds: accepted
    monkeypatch.setattr(D, "_nelder_mead", real)
    monkeypatch.setattr(T, "fit_scale_nu", lambda zz: {"s": 1.0, "nu": 2.1004, "nll": 1.0, "iterations": 3, "converged": True,
                                                        "nu_at_upper_bound": False, "nu_at_lower_bound": True})
    with pytest.raises(D.DispersionRefused, match="NU_AT_LOWER_BOUND"):
        D.fit_d0(z)
    with pytest.raises(D.DispersionRefused, match="NONFINITE_SCALE"):
        D.check_scales({"spec": "D1", "s1": 1.0, "lambda": 2.0, "nu0": 6.0}, np.ones(3) * 1e-3, np.array([0.0, 1.0, 1e6]), "x")


def test_feature_refusals_and_valid_cases():
    day = X.trading_days("2018-03-06", 1)[0]
    s = X.make_session(day, X.SEEDS["n"] + 7)
    by_t = {b["event_time"]: b for b in s["rows"]}
    vbar_ok = {m: 60_000.0 for m in range(400)}
    row = s["rows"][100]
    f, why = F.pressure_for_row(row, by_t, vbar_ok); assert why is None and f["W"] == WINDOW_BARS
    gap = dict(by_t); gap.pop(row["event_time"] - 3 * 60)
    assert F.pressure_for_row(row, gap, vbar_ok)[1] == "MISSING_PRESSURE_BARS"
    bad = dict(by_t); bad[row["event_time"]] = dict(row, high=row["low"] - 1)
    assert F.pressure_for_row(row, bad, vbar_ok)[1] == "INVALID_OHLC"
    neg = dict(by_t); neg[row["event_time"]] = dict(row, volume=-1.0)
    assert F.pressure_for_row(row, neg, vbar_ok)[1] == "INVALID_OHLC"
    assert F.pressure_for_row(row, by_t, {m: 60_000.0 for m in range(400) if m != row["minute"]})[1] == "NO_BASELINE_SUPPORT"
    assert F.pressure_for_row(row, by_t, {m: 0.0 for m in range(400)})[1] == "ZERO_BASELINE"
    zv = dict(by_t); zv[row["event_time"]] = dict(row, volume=0.0)           # present zero volume is VALID
    f0, why0 = F.pressure_for_row(row, zv, vbar_ok); assert why0 is None and f0["P"] < f["P"]
    zr = dict(by_t); zr[row["event_time"]] = dict(row, high=row["close"], low=row["close"], open=row["close"])
    fz, whyz = F.pressure_for_row(row, zr, vbar_ok); assert whyz is None and fz["zero_range_bars"] == 1
    with pytest.raises(F.FeatureRefused, match="DUPLICATE_SESSION"):           # copies cannot fabricate support
        F.fit_baselines([s] * 5)
    five = [X.make_session(d, X.SEEDS["n"] + 20 + i) for i, d in enumerate(X.trading_days("2018-04-02", 5))]
    assert F.fit_baselines(five)["minutes_with_baseline"] == 0                # 5 unique sessions < 100 -> no baseline
    assert F.order_statistic(list(range(1, 101)), 99, 100) == 99 and F.order_statistic(list(range(1, 11)), 99, 100) == 10


# ------------------------------------------------------------------ classification, Holm, integrity

def test_all_sixteen_primary_flag_combinations():
    for combo in itertools.product([True, False], repeat=4):
        dec = dict(zip(("HAC_D0", "BOOT_D0", "HAC_D1", "BOOT_D1"), combo))
        c = I.classify(dec)
        assert c["outcome"] == ("SELECTED" if all(combo) else "NOT_SELECTED")
        assert c["flags"]["INFERENCE_DISAGREEMENT_D0"] == (combo[0] != combo[1])
        assert c["flags"]["INFERENCE_DISAGREEMENT_D1"] == (combo[2] != combo[3])
        assert c["flags"]["SPECIFICATION_SENSITIVE"] == ((combo[0] and combo[1]) != (combo[2] and combo[3]))
    both = I.classify({"HAC_D0": True, "BOOT_D0": False, "HAC_D1": True, "BOOT_D1": True})
    assert both["flags"]["INFERENCE_DISAGREEMENT_D0"] and both["flags"]["SPECIFICATION_SENSITIVE"]  # co-occur, no precedence


def test_integrity_precedence_over_statistics():
    c = I.classify({"HAC_D0": True, "BOOT_D0": True, "HAC_D1": True, "BOOT_D1": True},
                   integrity_ok=False, integrity_reason="SOURCE_IDENTITY_MISMATCH")
    assert c["outcome"] == "INTEGRITY_FAILURE" and "flags" not in c and "SOURCE" in c["reason"]


def _manual_holm(p):
    items = sorted(p.items(), key=lambda kv: kv[1]); m, out, run = len(items), {}, 0.0
    for i, (k, v) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v)); out[k] = run
    return out


def test_holm_six_hypotheses_separately_by_method():
    keys = ["%s_%s" % (s, sp) for s in ("S1", "S2", "S3") for sp in ("D0", "D1")]
    rng = random.Random(X.SEEDS["n"] + 9)
    ph = {k: rng.uniform(0.001, 0.5) for k in keys}; pb = {k: rng.uniform(0.001, 0.5) for k in keys}
    fam = I.secondary_family(ph, pb)
    assert fam["m"] == 6 and fam["holm_hac"] == _manual_holm(ph) and fam["holm_bootstrap"] == _manual_holm(pb)
    fam2 = I.secondary_family(ph, {k: v / 3 for k, v in pb.items()})
    assert fam2["holm_hac"] == fam["holm_hac"] and fam2["holm_bootstrap"] != fam["holm_bootstrap"]
    with pytest.raises(ValueError):
        I.secondary_family({k: ph[k] for k in keys[:5]}, pb)


# ------------------------------------------------------------------ bootstrap: N8 and intervals

def _unequal():
    rng = np.random.default_rng(X.SEEDS["n"] + 11)
    counts = [50, 5, 120, 1, 33, 77, 2, 64]
    sids = [f"S{i}" for i, c in enumerate(counts) for _ in range(c)]
    return rng.standard_normal(len(sids)) * 1e-3 + 2e-4, sids, counts


def test_n8_adapter_equivalence_to_existing_function():
    d, sids, _ = _unequal()
    for seed in (1, 20260909, 7):
        for L in (1, 5, 10):
            a = boot_orig(d, sids, expected_block_sessions=L, n_resamples=300, seed=seed, threshold=0.0228)
            b = BA.session_stationary_bootstrap_ext(d, sids, expected_block_sessions=L, n_resamples=300, seed=seed, threshold=0.0228)
            for k in ("mean", "boot_se", "exceedances", "p_one_sided", "pass", "n_rows", "n_sessions", "raw_fraction_k_over_B"):
                assert a[k] == b[k], (k, seed, L)


def test_bootstrap_interval_indexing_and_unequal_session_counts():
    d, sids, counts = _unequal()
    b = BA.session_stationary_bootstrap_ext(d, sids, expected_block_sessions=5, n_resamples=40, seed=3, threshold=0.0228)
    srt = np.sort(b["replicate_means"]); pi = b["percentile_interval"]
    assert (pi["lower_order_index"], pi["upper_order_index"]) == (1, 39)
    assert pi["lower"] == srt[0] and pi["upper"] == srt[38]
    assert b["session_counts"] == counts and b["mean"] == float(np.mean(d))
    big = BA.session_stationary_bootstrap_ext(d, sids, expected_block_sessions=5, n_resamples=10000, seed=3, threshold=0.0228)
    assert (big["percentile_interval"]["lower_order_index"], big["percentile_interval"]["upper_order_index"]) == (250, 9750)
    assert "replicate_means" not in BA.strip_arrays(big) and "percentile_interval" in BA.strip_arrays(big)
    # ratio-of-sums estimand: a replicate drawing every session once equals the pooled mean
    tot = sum(d[i] for i in range(len(d))); assert math.isclose(tot / len(d), b["mean"])


# ------------------------------------------------------------------ session validation, fit bars, guards, budget

def test_session_identity_and_chronology_are_validated_not_trusted(world):
    fit, dev, prep = world["fit"], world["dev"], world["prep"]
    for bad, kind in ((dev + [dev[0]], "DUPLICATE_SESSION"), (list(reversed(dev)), "NON_CHRONOLOGICAL_SESSIONS"),
                      ([dev[0], dev[2], dev[1]], "NON_CHRONOLOGICAL_SESSIONS"), ([], "NO_SESSIONS")):
        with pytest.raises(F.FeatureRefused, match=kind):
            F.validate_sessions(bad, role="development")
    other = copy.deepcopy(dev); other[1]["symbol"] = "QQQ"
    with pytest.raises(F.FeatureRefused, match="SYMBOL_MISMATCH"):
        F.validate_sessions(other, role="development")
    # through the runner: a reversed development list is refused BEFORE any statistic is computed
    rec = R.tournament(fit, list(reversed(dev)), bootstrap_resamples=50)
    assert rec["status"] == "INTEGRITY_FAILURE" and "NON_CHRONOLOGICAL_SESSIONS" in rec["refusal"]["detail"]
    assert "development" not in rec
    dup_fit = fit[:99] + [fit[50]] + fit[99:]
    rec = R.tournament(dup_fit, dev, bootstrap_resamples=50)
    assert rec["status"] == "INTEGRITY_FAILURE" and "DUPLICATE_SESSION" in rec["refusal"]["detail"]
    # row order is checked independently of session validation; a session revisited later in the
    # list necessarily breaks (date, time) monotonicity, so it is caught as ROWS_OUT_OF_ORDER
    with pytest.raises(F.FeatureRefused, match="ROWS_OUT_OF_ORDER"):
        R._check_row_order([("2019-06-03", 1), ("2019-06-04", 2), ("2019-06-03", 3)], "x")
    with pytest.raises(F.FeatureRefused, match="ROWS_OUT_OF_ORDER"):
        R._check_row_order([("2019-06-03", 5), ("2019-06-03", 4)], "x")


def test_invalid_fit_bar_is_refused_by_name_not_excluded(world):
    fit = copy.deepcopy(world["fit"])
    day = fit[7]["session_date"]; bars = X.build_bars(day, X.SEEDS["fit"] + 7)
    bars[123]["high"] = bars[123]["low"] - 1.0                  # one impossible bar among ~43,000
    fit[7] = X.session_from_bars(day, bars)
    with pytest.raises(F.FeatureRefused, match="INVALID_FIT_BAR: %s minute 123" % day):
        F.validate_fit_bars(fit)
    rec = R.tournament(fit, world["dev"], bootstrap_resamples=50)
    assert rec["status"] == "INTEGRITY_FAILURE" and "INVALID_FIT_BAR" in rec["refusal"]["detail"]
    assert "fit" not in rec and "development" not in rec


def test_nonfinite_values_are_integrity_refusals_never_not_selected(world, monkeypatch):
    with pytest.raises(D.DispersionRefused, match="NONFINITE_VALUES"):
        D.logpdf(np.array([1e308, 1e308]), np.zeros(2), np.array([1e-300, 1e-300]), 6.0)
    with pytest.raises(I.InferenceRefused, match="NONFINITE_DIFFERENTIALS"):
        I.hac_decision([float("nan")] * 60)
    with pytest.raises(I.InferenceRefused, match="NONFINITE_DIFFERENTIALS"):
        I.hac_decision([1.0] * 30 + [float("inf")])
    with pytest.raises(ValueError):
        R.strict_json({"x": float("nan")})
    with pytest.raises(ValueError):
        R.strict_json({"x": float("inf")})
    real = M.means_of
    def poisoned(spec, rows):
        out = real(spec, rows)
        if spec["arm"] == "C":
            out = out.copy(); out[len(out) // 2] = float("nan")
        return out
    monkeypatch.setattr(M, "means_of", poisoned)
    rec = R.tournament(world["fit"], world["dev"], bootstrap_resamples=50)
    assert rec["status"] == "INTEGRITY_FAILURE"
    assert rec["refusal"]["kind"] == "DispersionRefused" and "NONFINITE_VALUES: means C" in rec["refusal"]["detail"]
    assert "development" not in rec and rec["classification"]["outcome"] == "INTEGRITY_FAILURE"


def test_fit_budget_is_counted_on_the_real_fitters_and_enforced(world, monkeypatch):
    est = world["prep"]["estimations"]
    assert {k: est[k] for k in ("baselines", "clipping_constants", "location_fits", "dispersion_fits", "total")} == \
        {"baselines": 1, "clipping_constants": 3, "location_fits": 4, "dispersion_fits": 2, "total": 10}
    assert est["total"] == BUDGET["total_fit_split_estimations"]
    assert [k for k, _ in est["call_log"]].count("location_fits") == 4 and len(est["call_log"]) == 10
    assert est["call_log"][-2:] == [("dispersion_fits", "fit_d0"), ("dispersion_fits", "fit_d1")]
    real = M.fit_all
    def one_extra(rows_y):
        out = real(rows_y); M.fit_arm(rows_y, "L"); return out          # a fifth location fit
    monkeypatch.setattr(M, "fit_all", one_extra)
    rec = R.tournament(world["fit"], world["dev"], bootstrap_resamples=50)
    assert rec["status"] == "INTEGRITY_FAILURE" and "BUDGET_EXCEEDED: location_fits call 5 > 4" in rec["refusal"]["detail"]


# ------------------------------------------------------------------ N8: replicate SEQUENCE preserved

class _TracingRandom(random.Random):
    trace = []
    def random(self):
        v = super().random(); _TracingRandom.trace.append(("random", v)); return v
    def randrange(self, *a, **k):
        v = super().randrange(*a, **k); _TracingRandom.trace.append(("randrange", v)); return v


def test_n8_adapter_preserves_the_exact_rng_draw_sequence(monkeypatch):
    import apex.world_model.exp002.bootstrap as ORIG
    d, sids, _ = _unequal()
    traces = {}
    for name, mod, fn in (("orig", ORIG, boot_orig), ("ext", BA, BA.session_stationary_bootstrap_ext)):
        _TracingRandom.trace = []
        monkeypatch.setattr(mod.random, "Random", _TracingRandom)
        out = fn(d, sids, expected_block_sessions=5, n_resamples=200, seed=20260909, threshold=0.0228)
        traces[name] = (list(_TracingRandom.trace), out)
        monkeypatch.undo()
    t_orig, o = traces["orig"]; t_ext, e = traces["ext"]
    assert len(t_orig) == len(t_ext) > 1000
    assert t_orig == t_ext                                                  # identical draws, identical order
    assert o["boot_se"] == e["boot_se"] and o["exceedances"] == e["exceedances"] and o["p_one_sided"] == e["p_one_sided"]
    # the exposed replicate means reproduce the aggregate the original computed from its own (unexposed) replicates
    rm = e["replicate_means"]
    assert math.isclose(float((rm - e["mean"]).std(ddof=1)), o["boot_se"], rel_tol=1e-12)
    assert int(np.sum((rm - e["mean"]) >= e["mean"])) == o["exceedances"]


# ------------------------------------------------------------------ N7 + end to end, fixed three-year reporting

def test_n7_and_end_to_end_tournament_with_fixed_year_cells(world, tmp_path):
    fit, dev, prep = world["fit"], world["dev"], world["prep"]
    dev2 = copy.deepcopy(dev)
    day = dev2[3]["session_date"]; bars = X.build_bars(day, X.SEEDS["dev"] + 100 + 3)
    bars[200]["high"] = bars[200]["close"] - 0.01                # pressure-only refusals on ten rows (2019)
    dev2[3] = X.session_from_bars(day, bars)
    rows, ref = F.eligible_rows(dev2[3], prep["vbar"])
    assert ref["INVALID_OHLC"] == WINDOW_BARS
    legacy = B.observable_rows(dev2[3]); tg = B.targets(dev2[3], legacy); t_bad = dev2[3]["rows"][200]["event_time"]
    assert all(r["features"] is not None for r, _ in zip(legacy, tg) if t_bad <= r["event_time"] < t_bad + WINDOW_BARS * 60)
    assert not any(t_bad <= r["event_time"] < t_bad + WINDOW_BARS * 60 for r, _, _ in rows)
    rec = R.tournament(fit, dev2, bootstrap_resamples=1000)
    assert rec["status"] in ("SELECTED", "NOT_SELECTED"), rec.get("refusal")
    assert rec["registration_hash"] == registration_hash() == REG_HASH
    dv = rec["development"]
    assert dv["row_key_population"]["identical_across_all_comparisons"] is True and dv["row_key_population"]["key_sets"] == 1
    assert {c[sp]["n_rows"] for c in dv["comparisons"].values() for sp in ("D0", "D1")} == {dv["n_rows"]}
    assert dv["development_refusals"]["INVALID_OHLC"] == WINDOW_BARS
    assert set(dv["development_refusals_by_session"]) == {s["session_date"] for s in dev2}
    assert rec["fit"]["estimations"]["total"] == 10 and rec["fit"]["fit_bars"]["bars_validated"] > 40000
    assert rec["fit"]["dispersion"]["D1"]["nu0"] == rec["fit"]["dispersion"]["D0"]["nu0"]
    assert set(dv["comparisons"]) == {"P1", "S1", "S2", "S3", "C_vs_L"} and dv["comparisons"]["P1"]["D0"]["pair"] == ["C", "AX"]
    assert dv["secondary_family"]["m"] == 6
    # fixed report cells: every registered year present, refusals attached, every comparison and both specs
    assert list(dv["per_year"]) == ["2019", "2020", "2021"] and dv["years_outside_registered_report"] == []
    for yr, cell in dv["per_year"].items():
        assert cell["status"] == "REPORTED" and cell["refusals"]["eligible"] == cell["n_rows"] > 0
        assert set(cell["comparisons"]) == {"P1", "S1", "S2", "S3", "C_vs_L"}
        for c in cell["comparisons"].values():
            for sp in ("D0", "D1"):
                assert "percentile_interval" in c[sp]["bootstrap"] and "interval_95" in c[sp]["hac"]
                assert set(c[sp]["bootstrap_sensitivities"]) == {"1", "10"}
        assert cell["dispersion_improvement"]["pair"] == "AX@D1 - AX@D0"
    assert dv["per_year"]["2019"]["refusals"]["INVALID_OHLC"] == WINDOW_BARS and dv["per_year"]["2020"]["refusals"]["INVALID_OHLC"] == 0
    for c in dv["comparisons"].values():
        for sp in ("D0", "D1"):
            assert "replicate_means" not in c[sp]["bootstrap"]
    json.loads(R.strict_json(rec))                                       # standard JSON, no NaN/Infinity
    (tmp_path / "ok.json").write_text(R.strict_json(rec))
    # a registered year with no sessions -> explicit NOT_AVAILABLE cell, never omitted
    two = X.dev_sessions_years(years=("2019", "2020"))
    rec2 = R.tournament(fit, two, bootstrap_resamples=200)
    assert rec2["status"] in ("SELECTED", "NOT_SELECTED")
    cell = rec2["development"]["per_year"]["2021"]
    assert cell["status"] == "NOT_AVAILABLE" and cell["n_rows"] == 0 and cell["refusals"] is None and cell["comparisons"] is None
    assert list(rec2["development"]["per_year"]) == ["2019", "2020", "2021"]
    # refused record: no eligible development rows -> INTEGRITY_FAILURE, no statistics
    broken = [X.session_from_bars(s["session_date"], [dict(b, open=b["high"] + 1) for b in X.build_bars(s["session_date"], 1)])
              for s in dev[:2]]
    bad = R.tournament(fit, broken, bootstrap_resamples=50)
    assert bad["status"] == "INTEGRITY_FAILURE" and "development" not in bad
    assert "INSUFFICIENT_DEVELOPMENT_ROWS" in bad["refusal"]["detail"] and bad["classification"]["outcome"] == "INTEGRITY_FAILURE"
    (tmp_path / "refused.json").write_text(R.strict_json(bad))
