"""R4 implementation tests against contract blob 902256e3 (docs/R4_JOINT_MARKET_STATE_SPEC.md).

Acceptance = the contract's identity and refusal tests (§6.1) ONLY. Ids below are the contract's T-numbers.
SYNTHETIC INPUTS ONLY: no collector or historical data, no fitting on either, no backtest, no service, no order.
"""
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from apex.joint_wb import accounting as ACC, attribution as ATR, comparators as CMP, decision_rule as DR
from apex.joint_wb import endpoint as EP, engine as ENG, inference as INF, model as MDL, permissions as PRM
from apex.joint_wb import sampler as SMP, state as ST, synthetic_world as SW
from apex.multiverse_wb.pricing import bsm_price
from apex.options_pilot import boundary as B, entrypoint as PEP, ledger as L, session as PS
from apex.options_pilot.fees import SYNTHETIC_FEES
from apex.options_pilot.synthetic_harness import SyntheticHarness

CONTRACT_BLOB = "902256e3c3c5025a450a4bb607410933bb0c4b25"
ET = ZoneInfo("America/New_York")
T_D = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc).timestamp()
EXPIRY = "2026-10-09"
SPOT = 200.0
STRIKES = [190.0, 195.0, 200.0, 205.0, 210.0]
SIGMA_TRUE = np.array([[4e-4, 1e-4, 5e-5, -2e-5], [1e-4, 9e-4, 1e-5, 0.0],
                       [5e-5, 1e-5, 2.5e-3, -3e-4], [-2e-5, 0.0, -3e-4, 4e-3]])
A_TRUE = np.zeros((4, 4)); A_TRUE[0, 1] = -0.6; A_TRUE[2, 2] = 0.4


def test_contract_pin_is_the_one_implemented():
    blob = subprocess.run(["git", "hash-object", "docs/R4_JOINT_MARKET_STATE_SPEC.md"], capture_output=True, text=True).stdout.strip()
    assert blob == CONTRACT_BLOB == PRM.CONTRACT_PIN == ENG.CONTRACT_PIN


# ------------------------------------------------------------------ helpers
def _T(t=T_D):
    return (ST.expiry_epoch_of(EXPIRY) - t) / ST.CALENDAR_YEAR_S


def _quotes(*, t=T_D - 1.0, iv=0.18, skew=-0.35, spread_rel=0.02, size=25, strikes=None, lag=0.5):
    return SW.quotes_for_state(expiration=EXPIRY, strikes=strikes or STRIKES, spot=SPOT, iv=iv, skew=skew,
                               spread_rel=spread_rel, size=size, t=t, T_years=_T(t), available_lag=lag)


def _chain():
    return [{"expiration": EXPIRY, "strike": k, "right": r} for k in STRIKES for r in ("CALL", "PUT")]


def _state(**kw):
    bars, unders = SW.bars_and_underlyings(t_d=T_D, spot=SPOT)
    return ST.compose(symbol="SPY", t_d=T_D, bars=bars, underlyings=unders, chain=_chain(),
                      raw_quotes=kw.pop("quotes", None) or _quotes(), **kw)


def _fitted(*, n_sessions=30, seed=5, A=A_TRUE):
    rows = SW.make_rows(n_sessions=n_sessions, A_true=A, Sigma_true=SIGMA_TRUE, seed=seed)
    built = MDL.build_rows(rows)
    return MDL.fit(built, cutoff_epoch=max(r["available_deadline"] for r in rows) + 1.0, label="fixture")


def _engine(*, comparator="JOINT", n_paths=600, seed=11):
    e = ENG.JointEngine(n_paths=n_paths, seed=seed, comparator=comparator)
    e.attach(_fitted(), permission=SW.permission())
    return e


_MISSING = object()


def _decide(engine, *, ms=None, v_hat=1e-6, drift=0.0, book=_MISSING, h=None):
    return engine.decide(market_state=ms if ms is not None else _state(),
                         variance_state={"kind": "FLAT", "h": h or 1e-6 / 15.0},
                         v_hat=v_hat, nu=None, drift_per_bar=drift, fee_schedule=SYNTHETIC_FEES,
                         book_summary=({"integrity_problems": []} if book is _MISSING else book))


# ------------------------------------------------------------------ §1 inputs, endpoint, permissions
class TestInputsAndEndpoint:
    def test_T1_future_input_is_a_firewall_violation(self):
        bars, unders = SW.bars_and_underlyings(t_d=T_D, spot=SPOT)
        bars[-1]["available_time"] = T_D + 1.0
        with pytest.raises(ST.StateRefused, match="FUTURE_INPUT:bar"):
            ST.compose(symbol="SPY", t_d=T_D, bars=bars, underlyings=unders, chain=_chain(), raw_quotes=_quotes())
        for f in ("event_time", "available_time", "source", "revision_policy", "max_age_s", "quality"):
            b2, u2 = SW.bars_and_underlyings(t_d=T_D, spot=SPOT)
            b2[-1].pop(f)
            with pytest.raises(ST.StateRefused, match="INPUT_CONTRACT_MISSING:%s" % f):
                ST.compose(symbol="SPY", t_d=T_D, bars=b2, underlyings=u2, chain=_chain(), raw_quotes=_quotes())

    def test_T2_revision_after_t_d_is_invisible(self):
        bars, unders = SW.bars_and_underlyings(t_d=T_D, spot=SPOT)
        a = ST.compose(symbol="SPY", t_d=T_D, bars=bars, underlyings=unders, chain=_chain(), raw_quotes=_quotes())
        late = dict(bars[-1]); late["close"] = SPOT * 1.05; late["available_time"] = T_D + 5.0
        visible = [b for b in bars + [late] if b["available_time"] <= T_D]
        b2 = ST.compose(symbol="SPY", t_d=T_D, bars=visible, underlyings=unders, chain=_chain(), raw_quotes=_quotes())
        assert a["state_hash"] == b2["state_hash"]

    def test_T3_invalid_quotes_never_reach_iv_or_pricing(self, monkeypatch):
        seen = []
        real = ST.implied_vol
        monkeypatch.setattr(ST, "implied_vol", lambda **kw: (seen.append(kw), real(**kw))[1])
        q = _quotes()
        for right in ("CALL", "PUT"):
            k = ("2026-10-09", 200.0, right)
            q[k] = {**q[k], "timestamp_epoch": float("nan")}
        with pytest.raises(ST.StateRefused, match="ATM_IV_UNAVAILABLE"):
            _state(quotes=q)
        assert all(kw["K"] != 200.0 for kw in seen), "a NaN-stamped quote must never reach implied_vol"
        assert all(math.isfinite(kw["price"]) and kw["price"] > 0 for kw in seen)

    def test_T4_iv_needs_a_contemporaneous_underlying(self):
        bars, unders = SW.bars_and_underlyings(t_d=T_D, spot=SPOT)   # underlyings span t_d-12 .. t_d-2
        old_q = _quotes(t=T_D - 20.0)                                 # every underlying is NEWER than the quote
        assert ST.underlying_reference(unders, at=T_D - 20.0) is None
        with pytest.raises(ST.StateRefused, match="ATM_IV_UNAVAILABLE"):
            ST.compose(symbol="SPY", t_d=T_D, bars=bars, underlyings=unders, chain=_chain(), raw_quotes=old_q)

    def test_T5_endpoint_selection_is_jointly_coherent(self):
        target = T_D + 900.0
        keys = [(EXPIRY, 200.0, "CALL"), (EXPIRY, 200.0, "PUT")]
        q = _quotes(t=target)
        # per-key earliest quotes never coexist: CALL only early, PUT only late, 50 s apart
        qs = {keys[0]: [{**q[keys[0]], "timestamp_epoch": target - 40.0, "available_time": target - 39.0}],
              keys[1]: [{**q[keys[1]], "timestamp_epoch": target + 20.0, "available_time": target + 21.0}]}
        sel = EP.select_endpoint(qs, target_epoch=target, keys_required=tuple(keys))
        assert sel["t_e"] is None and sel["why"].startswith("ENDPOINT_NOT_COHERENT")
        qs[keys[0]].append({**q[keys[0]], "timestamp_epoch": target + 15.0, "available_time": target + 16.0})
        sel2 = EP.select_endpoint(qs, target_epoch=target, keys_required=tuple(keys))
        assert sel2["t_e"] == target + 20.0 and sel2["slice_dispersion_s"] == 5.0

    def test_T32_delta_zero_cannot_hide_a_stale_quote(self):
        target = T_D + 900.0
        keys = [(EXPIRY, 200.0, "CALL"), (EXPIRY, 200.0, "PUT")]
        q = _quotes(t=target)
        stale = {k: [{**q[k], "timestamp_epoch": target - 119.0, "available_time": target - 118.0}] for k in keys}
        sel = EP.select_endpoint(stale, target_epoch=target, keys_required=tuple(keys))
        assert sel["t_e"] is None, "a 119 s-stale quote must not be usable even at delta = 0"
        assert any("OFFSET_EXCEEDED" in v for vs in sel["census"].values() for v in vs)
        ok = {k: [{**q[k], "timestamp_epoch": target - 10.0, "available_time": target - 9.0}] for k in keys}
        sel2 = EP.select_endpoint(ok, target_epoch=target, keys_required=tuple(keys))
        assert sel2["delta_s"] == 0.0 and sel2["max_abs_offset_s"] == 10.0
        summ = EP.offset_summary(sel2)
        assert summ["estimand"].startswith("TARGET_PROXY_V1") and summ["tight_sensitivity_eligible"] is True
        far = {k: [{**q[k], "timestamp_epoch": target - 40.0, "available_time": target - 39.0}] for k in keys}
        assert EP.offset_summary(EP.select_endpoint(far, target_epoch=target, keys_required=tuple(keys)))["tight_sensitivity_eligible"] is False

    def test_T22_per_key_lookup_is_deterministic_and_total(self):
        t = T_D + 900.0
        base = {"bid": 1.0, "ask": 1.1, "bid_size": 5, "ask_size": 5}
        rows = [{**base, "timestamp_epoch": t - 5, "available_time": t - 4, "source": "B"},
                {**base, "timestamp_epoch": t - 1, "available_time": t - 0.5, "source": "B"},
                {**base, "timestamp_epoch": t - 1, "available_time": t - 0.9, "source": "A"}]
        r = EP.lookup_at(rows, instant=t, key="k")
        assert r["quote"]["source"] == "A" and r["quote"]["timestamp_epoch"] == t - 1
        assert EP.lookup_at(list(reversed(rows)), instant=t, key="k")["quote"]["source"] == "A"
        assert EP.lookup_at([], instant=t, key="k")["why"].startswith("ENDPOINT_KEY_ABSENT")
        tie = [dict(rows[1]), dict(rows[1])]
        assert EP.lookup_at(tie, instant=t, key="k")["why"].startswith("ENDPOINT_AMBIGUOUS")

    def test_permissions_inherit_nothing_and_separate_role_from_run(self):
        with pytest.raises(PRM.PermissionRefused, match="DATASET_NOT_REGISTERED"):
            PRM.require_read("WHATEVER", "FIT")
        with pytest.raises(PRM.PermissionRefused, match="ROLE_FORBIDS_USE"):
            PRM.require_read("HIST-A-OPTIONS/2022-2024", "FIT")          # sealed: no use is permitted at all
        with pytest.raises(PRM.PermissionRefused, match="NO_AUTHORIZATION_OBTAINABLE"):
            PRM.require_read("PILOT-LEDGER", "OUTCOME_EVIDENCE")          # permitted use, but no artefact exists
        with pytest.raises(PRM.PermissionRefused, match="AUTHORIZATION_REQUIRED"):
            PRM.require_read("PILOT-COLLECTION", "FIT")
        role_only = PRM.Authorization("R4-FIT-002", "PILOT-COLLECTION", "FIT")
        with pytest.raises(PRM.PermissionRefused, match="AUTHORIZATION_RUN_FIELDS_MISSING"):
            PRM.require_read("PILOT-COLLECTION", "FIT", authorization=role_only)
        with pytest.raises(PRM.PermissionRefused, match="AUTHORIZATION_ARTEFACT_MISMATCH"):
            PRM.require_read("HIST-A-OPTIONS/2016-2019", "FIT",
                             authorization=PRM.Authorization("EXP-001B", "HIST-A-OPTIONS/2016-2019", "FIT", ("a", "b"), 1.0, "p"))
        ok = PRM.require_read("SYNTHETIC-FIXTURE", "FIT")
        assert ok["authorization"] == "NOT_REQUIRED_FOR_SYNTHETIC" and ok["contract_pin"] == CONTRACT_BLOB

    def test_T16_T23_walk_forward_and_overlap(self):
        assert PRM.walk_forward_problem(decision_epoch=100.0, fit_cutoff=50.0, session_start_epoch=90.0,
                                        training_row_ids={"a"}, evaluation_row_ids={"b"}) is None
        assert "FIT_EVAL_OVERLAP" in PRM.walk_forward_problem(decision_epoch=100.0, fit_cutoff=50.0, session_start_epoch=90.0,
                                                              training_row_ids={"a"}, evaluation_row_ids={"a"})
        assert "FIT_CUTOFF_NOT_BEFORE_SESSION" in PRM.walk_forward_problem(decision_epoch=100.0, fit_cutoff=95.0,
                                                                           session_start_epoch=90.0, training_row_ids=set(), evaluation_row_ids=set())
        rows = SW.make_rows(n_sessions=30, A_true=A_TRUE, Sigma_true=SIGMA_TRUE, seed=1)
        built = MDL.build_rows(rows)
        with pytest.raises(MDL.ModelRefusedR4, match="FIREWALL"):
            MDL.fit(built, cutoff_epoch=min(r["available_deadline"] for r in rows) - 1.0)


# ------------------------------------------------------------------ §2 state, estimator, sampler, pricing
class TestStateAndModel:
    def test_state_variables_are_positivity_safe(self):
        ms = _state()
        assert math.exp(ms["x_iv"]) == pytest.approx(ms["iv_atm"]) and ms["x_iv"] < 0     # IV < 1 => log IV negative
        assert ms["x_sk"] == pytest.approx(-0.35, abs=0.02) and ms["x_sz"] >= 0
        assert math.exp(ms["x_sp"]) == pytest.approx(ms["spread_rel_atm"], rel=1e-9)
        assert ms["identity"]["K_atm"] == 200.0 and ms["identity"]["expiry_epoch"] == ST.expiry_epoch_of(EXPIRY)

    def test_T26_predictor_domain_refuses_before_log_or_sqrt(self):
        for bad in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ST.StateRefused, match="SCALE_VARIANCE_INVALID"):
                ST.predictor_vector(r=0.0, q=1e-6, v_hat=bad)
            with pytest.raises(ST.StateRefused, match="PREDICTOR_INVALID"):
                ST.predictor_vector(r=0.0, q=bad, v_hat=1e-6)
        assert ST.predictor_vector(r=0.0, q=1e-6, v_hat=1e-6) == (1.0, 0.0, 0.0, 0.0)
        e = _engine(n_paths=50)
        r = _decide(e, v_hat=0.0)
        assert r["decision"] == "WAIT" and "SCALE_VARIANCE_INVALID" in r["why"] and "no path simulated" in r["why"]

    def test_T7_estimator_identity_and_orientation(self):
        f = _fitted()
        Z, Y = f["Z"], f["Y"]
        B = np.linalg.solve(Z.T @ Z, Z.T @ Y)
        assert np.max(np.abs(f["B"] - B)) < 1e-12
        assert np.max(np.abs(f["A"] - B.T)) < 1e-12
        E = Y - Z @ B
        assert np.max(np.abs(f["Sigma"] - (E.T @ E) / (f["n"] - 4))) < 1e-12
        z = Z[7]
        assert np.max(np.abs(MDL.forecast_mean(f, z) - (Z @ B)[7])) < 1e-12      # A z reproduces the row's fitted mean
        assert np.max(np.abs((f["B"] @ z) - (Z @ B)[7])) > 1e-6                   # the transpose matters

    def test_T7_only_complete_rows_enter_the_fit(self):
        rows = SW.make_rows(n_sessions=30, A_true=A_TRUE, Sigma_true=SIGMA_TRUE, seed=2)
        rows[3]["end"]["x_sk"] = None
        rows[4]["endpoint_missing"] = True
        rows[5]["iv_source_changed"] = True
        built = MDL.build_rows(rows)
        assert built["n_complete"] == len(rows) - 3
        assert built["census"] == {"INCOMPLETE_OUTCOMES": 1, "ENDPOINT_MISSING": 1, "IV_SOURCE_CHANGED": 1}
        assert "ENGINEERING REFUSAL THRESHOLD" in built["ceiling_note"]
        ids = {r["row_id"] for r in built["rows"]}
        assert rows[3]["row_id"] not in ids and rows[4]["row_id"] not in ids

    def test_T15_T26_numerical_refusals(self):
        rows = SW.make_rows(n_sessions=30, A_true=A_TRUE, Sigma_true=SIGMA_TRUE, seed=3)
        few = MDL.build_rows(rows[:100])
        with pytest.raises(MDL.ModelRefusedR4, match="INSUFFICIENT_HISTORY"):
            MDL.fit(few, cutoff_epoch=1e12)
        flat = SW.make_rows(n_sessions=30, A_true=None, Sigma_true=SIGMA_TRUE, seed=4)
        for r in flat:
            r["end"]["x_sk"] = r["start"]["x_sk"]
        with pytest.raises(MDL.ModelRefusedR4, match="DEGENERATE_STATE"):
            MDL.fit(MDL.build_rows(flat), cutoff_epoch=1e12)
        missing = SW.make_rows(n_sessions=30, A_true=A_TRUE, Sigma_true=SIGMA_TRUE, seed=6)
        for r in missing[: int(0.2 * len(missing))]:
            r["endpoint_missing"] = True
        with pytest.raises(MDL.ModelRefusedR4, match="ENDPOINT_MISSINGNESS_EXCESSIVE"):
            MDL.fit(MDL.build_rows(missing), cutoff_epoch=1e12)
        floored = SW.make_rows(n_sessions=30, A_true=A_TRUE, Sigma_true=SIGMA_TRUE, seed=7)
        for r in floored[: int(0.1 * len(floored))]:
            r["spread_floored"] = True
        with pytest.raises(MDL.ModelRefusedR4, match="SPREAD_FLOOR_EXCESSIVE"):
            MDL.fit(MDL.build_rows(floored), cutoff_epoch=1e12)
        nonfinite = SW.make_rows(n_sessions=30, A_true=A_TRUE, Sigma_true=SIGMA_TRUE, seed=8)
        nonfinite[10]["end"]["x_iv"] = float("nan")
        b = MDL.build_rows(nonfinite)
        assert b["census"].get("NONFINITE_ROW") == 1                      # EXCLUDED during construction
        f = MDL.fit(b, cutoff_epoch=1e12)
        f["Z"][0, 0] = float("nan")
        with pytest.raises(MDL.ModelRefusedR4, match="NONFINITE_INPUT"):   # REFUSED in the assembled matrices
            MDL.fit({"rows": [{"row_id": "x", "session": "s", "z": (float("nan"), 1, 1, 1), "y": (0, 0, 0, 0),
                               "spread_floored": False, "available_deadline": 0.0}] * 250,
                     "census": {}, "n_offered": 250, "exclusion_rate": 0.0}, cutoff_epoch=1e12)

    def test_T8_T35_sampler_identities_and_shared_blocks(self):
        assert SMP.kappa(2) == pytest.approx(float(SMP.chi2.cdf(SMP.c2(2), 4) / SMP.chi2.cdf(SMP.c2(2), 2)), abs=1e-12)
        pre = SMP.pregenerate(sigma=SIGMA_TRUE, n_paths=4000, seed=21)
        mi = SMP.moment_identities(pre)
        assert np.max(np.abs(mi["cov_e2_joint"] - mi["target_S22"])) < 1e-15
        assert np.max(np.abs(mi["cov_e1_e2_joint"] - mi["target_S12"])) < 1e-15
        j = SMP.innovations(pre, comparator="JOINT")
        d = SMP.innovations(pre, comparator="C_DIAG")
        iv = SMP.innovations(pre, comparator="C_IVSK")
        one = SMP.innovations(pre, comparator="C_IV")
        assert np.array_equal(j[:, :2], d[:, :2]) and np.array_equal(j[:, :2], iv[:, :2])   # shared block 1, bitwise
        assert np.array_equal(one[:, 0], j[:, 0]) and np.all(one[:, 1:] == 0)               # C_IV is a projection
        assert not np.array_equal(j[:, 2:], d[:, 2:])
        # construction identity: JOINT's exec block is M e1 + chol(C) w2; C_DIAG's is chol(S22) w2
        h = pre["e"]["horizon"]; b = pre["blocks"]
        assert np.max(np.abs(j[:, 2:] - (h["e1"] @ b["M"].T + h["w2"] @ b["LC"].T))) < 1e-12
        assert np.max(np.abs(d[:, 2:] - (h["w2"] @ b["L22"].T))) < 1e-12
        # the difference is NOT merely the conditional-mean shift: the conditional residual covariance changes too
        residual = (j[:, 2:] - h["e1"] @ b["M"].T) - d[:, 2:]
        assert np.max(np.abs(residual)) > 1e-6, "chol(C) w2 != chol(S22) w2; the contrast is compound, not a pure mean shift"
        assert "COMPOUND_COUPLING_LAW_CONTRAST" in pre["compound_label"]

    def test_T35_equal_variance_is_not_equal_marginal_law(self):
        pre = SMP.pregenerate(sigma=SIGMA_TRUE, n_paths=200000, seed=22)
        j, d = pre["e"]["horizon"]["e2_joint"][:, 0], pre["e"]["horizon"]["e2_diag"][:, 0]
        assert abs(j.var() - d.var()) / d.var() < 0.05                      # equal covariance in population
        k_j = float(((j - j.mean()) ** 4).mean() / j.var() ** 2)
        k_d = float(((d - d.mean()) ** 4).mean() / d.var() ** 2)
        assert abs(k_j - k_d) > 1e-4, "a sum of two bounded vectors does not share the single transform's tail shape"

    def test_T27_anchor_identity(self):
        x_iv, x_sk = math.log(0.2), -0.4
        got = ACC.slice_iv(x_iv=np.array([x_iv]), x_sk=np.array([x_sk]), K=200.0, K_atm=200.0)
        assert float(got[0]) == pytest.approx(x_iv, abs=1e-15)
        S_H = np.array([211.0])                                             # S_H != K_atm, skew != 0
        pr = ACC.price_paths(S=S_H, x_iv=np.array([x_iv]), x_sk=np.array([x_sk]), x_sp=np.array([math.log(0.02)]),
                             x_sz=np.array([math.log(26)]), K=200.0, K_atm=200.0, right="CALL",
                             expiry_epoch=ST.expiry_epoch_of(EXPIRY), t_eval=T_D + 900.0)
        assert float(pr["iv"][0]) == pytest.approx(math.exp(x_iv), abs=1e-15)
        wrong = x_iv + x_sk * math.log(200.0 / 211.0)                       # the Draft 2.1 (spot-anchored) form
        assert abs(wrong - x_iv) > 1e-3

    def test_T9_pricing_identity_guards_and_clocks(self):
        x_iv, x_sk = math.log(0.2), 0.0
        t_eval = T_D + 900.0
        pr = ACC.price_paths(S=np.array([SPOT]), x_iv=np.array([x_iv]), x_sk=np.array([x_sk]),
                             x_sp=np.array([math.log(0.02)]), x_sz=np.array([math.log(26)]), K=200.0, K_atm=200.0,
                             right="CALL", expiry_epoch=ST.expiry_epoch_of(EXPIRY), t_eval=t_eval)
        ref = bsm_price(S=SPOT, K=200.0, T=ACC.T_at(ST.expiry_epoch_of(EXPIRY), t_eval), sigma=0.2, right="CALL")
        assert float(pr["mid"][0]) == pytest.approx(ref, abs=1e-10)
        t_ext = T_D + 900.0 + 120.0
        assert ACC.T_at(ST.expiry_epoch_of(EXPIRY), t_eval) - ACC.T_at(ST.expiry_epoch_of(EXPIRY), t_ext) == pytest.approx(120.0 / ACC.CALENDAR_YEAR_S, abs=1e-15)
        for xiv in (math.log(1e-5), math.log(60.0)):
            bad = ACC.price_paths(S=np.array([SPOT]), x_iv=np.array([xiv]), x_sk=np.array([0.0]), x_sp=np.array([0.0]),
                                  x_sz=np.array([0.0]), K=200.0, K_atm=200.0, right="CALL",
                                  expiry_epoch=ST.expiry_epoch_of(EXPIRY), t_eval=t_eval)
            assert bad["unpriceable"].all() and "LOG_IV" in bad["why"]
        past = ACC.price_paths(S=np.array([SPOT]), x_iv=np.array([x_iv]), x_sk=np.array([0.0]), x_sp=np.array([0.0]),
                               x_sz=np.array([0.0]), K=200.0, K_atm=200.0, right="CALL",
                               expiry_epoch=ST.expiry_epoch_of(EXPIRY), t_eval=ST.expiry_epoch_of(EXPIRY) + 1)
        assert past["unpriceable"].all() and past["why"] == "T_NOT_POSITIVE"


# ------------------------------------------------------------------ §3 accounting
class TestAccounting:
    def _pr(self, bid, mid, size, n=4):
        return {"unpriceable": np.zeros(n, dtype=bool), "mid": np.full(n, mid), "bid": np.full(n, bid),
                "size": np.full(n, size), "iv": np.full(n, 0.2), "spread_rel": np.full(n, 0.02), "T": 0.08}

    def test_T13_every_path_gets_both_scenarios(self):
        prim = self._pr(bid=-0.5, mid=0.4, size=0.0)                        # bid <= 0 AND size < 1
        a = ACC.account(primary=prim, extension=None, entry_ask=2.0, fees_in=0.97, fees_out=0.05, size_policy="MODELLED_SIZE")
        assert a["refused"] is None and len(a["S1"]) == 4 and len(a["S2"]) == 4
        assert float(a["S1"][0]) == pytest.approx(-100 * 2.0 - 0.97)
        assert float(a["S2"][0]) == pytest.approx(100 * (0.4 - 2.0) - 0.97 - 0.05)
        assert a["counters"]["not_achievable_n"] == 4 and a["availability_failure_rate"] == 1.0
        assert "not bounds" in a["labels"]["scenarios"]

    def test_T28_scenarios_are_not_ordered_and_the_gate_cannot_invert(self):
        prim = self._pr(bid=-0.1, mid=0.0004, size=0.0)                     # mid_last < fees_out / 100
        a = ACC.account(primary=prim, extension=None, entry_ask=2.0, fees_in=0.97, fees_out=0.05, size_policy="MODELLED_SIZE")
        assert a["mean_S2"] < a["mean_S1"], "S2 - S1 = 100*mid - fees_out is negative here"
        assert a["E_sel"] == min(a["mean_S1"], a["mean_S2"]) == a["mean_S2"] and a["U"] >= 0
        assert a["U"] == abs(a["mean_S1"] - a["mean_S2"]) and a["selected_scenario"] == "S2"

    def test_T24_extension_resolution_rows(self):
        good = self._pr(bid=3.0, mid=3.05, size=10.0)
        a = ACC.account(primary=good, extension=None, entry_ask=2.0, fees_in=0.97, fees_out=0.05)
        assert a["counters"]["achieved_primary_n"] == 4 and a["counters"]["achieved_extension_n"] == 0
        prim = self._pr(bid=-0.1, mid=2.5, size=0.0)
        ext = self._pr(bid=3.0, mid=3.1, size=10.0)
        b = ACC.account(primary=prim, extension=ext, entry_ask=2.0, fees_in=0.97, fees_out=0.05, size_policy="MODELLED_SIZE")
        assert b["counters"]["achieved_extension_n"] == 4 and b["scenarios_from"]["EXTENSION"] == 4
        c = ACC.account(primary=prim, extension={"undefined": True}, entry_ask=2.0, fees_in=0.97, fees_out=0.05, size_policy="MODELLED_SIZE")
        assert c["counters"]["extension_undefined_n"] == 4 and c["scenarios_from"]["PRIMARY"] == 4
        assert float(c["S2"][0]) == pytest.approx(100 * (2.5 - 2.0) - 0.97 - 0.05)   # valued from PRIMARY, never dropped

    def test_T14_unpriceable_refuses_the_candidate_with_its_stage(self):
        prim = self._pr(bid=1.0, mid=1.1, size=5.0)
        prim["unpriceable"] = np.array([False, True, False, False]); prim["why"] = "LOG_IV_OUT_OF_RANGE"; prim["first_bad"] = 1
        a = ACC.account(primary=prim, extension=None, entry_ask=2.0, fees_in=0.97, fees_out=0.05)
        assert a["refused"] == "UNPRICEABLE_PATH_PRESENT" and a["stage"] == "PRIMARY" and a["count"] == 1 and a["first_bad"] == 1
        ok = self._pr(bid=-1.0, mid=1.1, size=5.0)
        ext = self._pr(bid=1.0, mid=1.1, size=5.0); ext["unpriceable"] = np.array([True, False, False, False])
        b = ACC.account(primary=ok, extension=ext, entry_ask=2.0, fees_in=0.97, fees_out=0.05)
        assert b["refused"] == "UNPRICEABLE_PATH_PRESENT" and b["stage"] == "EXTENSION"


# ------------------------------------------------------------------ §4 comparators
class TestComparators:
    def test_T10_decomposition_identity(self):
        V = {"MATCHED_FROZEN": 1.0, "C_IV": 1.4, "C_IVSK": 1.7, "C_EXEC": 1.3, "C_DIAG": 2.2, "JOINT": 2.9}
        d = CMP.decompose(V)
        assert abs(d["identity_residual"]) < 1e-12
        assert abs(d["J_total"] - (d["Sh_F1_iv_block"] + d["Sh_F2_exec_block"] + d["D_coupling"])) < 1e-12
        assert "COMPOUND_COUPLING_LAW_CONTRAST" in d["labels"]["D"] and "INCLUDES_SIZE_VETO_POLICY" in d["labels"]["D"]
        fq = CMP.decompose(V, functional="FORECAST_QUALITY")
        assert "Sh_F2_exec_block" not in fq["labels"]                      # the veto bundling is economics-only
        assert "C_PERM" not in CMP.TABLE and "SYNTHETIC-ONLY" in CMP.describe()["C_PERM"]

    def test_T25_refusal_keeps_the_scan_and_labels_the_scored_population(self):
        scans = [{"session": "d1", "variants": {"JOINT": {"decision": "TRADE", "pnl": {"net": 5.0}},
                                                "C_DIAG": {"decision": "WAIT"}}},
                 {"session": "d1", "variants": {"JOINT": {"decision": "WAIT"},
                                                "C_DIAG": {"decision": "TRADE", "pnl": {"net": -3.0}}}}]
        ej, ec = ATR.economics(scans, "JOINT", draws=60), ATR.economics(scans, "C_DIAG", draws=60)
        assert ej["primary"]["n"] == ec["primary"]["n"] == 2                # the scan never leaves the population
        assert "may be positive or negative" in ej["refusal_note"]
        rows = [{"session": "d1", "contract": "a", "realized": {"bid": 1.0, "executable": True},
                 "samples": {"JOINT": np.array([1.0, 1.1]), "C_DIAG": np.array([0.9, 1.2])}},
                {"session": "d1", "contract": "b", "realized": {"bid": 2.0, "executable": True},
                 "samples": {"JOINT": np.array([2.0, 2.1]), "C_DIAG": None}}]
        fq = ATR.forecast_quality(rows, ["JOINT", "C_DIAG"], draws=60)
        assert fq["n_scored"] == 1 and fq["scored_coverage"] == 0.5
        assert fq["population_label"].startswith("SCORED_POPULATION_CONDITIONAL")
        assert "not eliminate selection bias" in fq["population_label"]
        assert fq["per_comparator"]["JOINT"]["exclusion_sensitivity_observed_worst"]["label"].startswith("EXCLUSION_SENSITIVITY_OBSERVED_WORST")
        assert "not a bound" in fq["per_comparator"]["JOINT"]["exclusion_sensitivity_observed_worst"]["label"]

    def test_scoring_contracts(self):
        s = np.array([0.0, 1.0, 2.0, 3.0])
        brute = float(np.abs(s - 1.5).mean() - 0.5 * np.abs(s[:, None] - s[None, :]).mean())
        assert ATR.crps(s, 1.5) == pytest.approx(brute, abs=1e-12)
        ru = ATR.rank_uniformity([1, 2, 3, 4, 5] * 20, n_ensemble=4)
        assert ru["reference"].startswith("DISCRETE uniform") and ru["bins"] == 5
        b = ATR.brier([0.9, 0.1], [1.0, 0.0])
        assert b["brier"] == pytest.approx(0.01) and "NOT a fill probability" in b["note"]
        v, k = ATR.per_scan_value({"decision": "TRADE_UNRESOLVED", "entry_ask": 2.0, "fees_in": 0.97})
        assert k == "UNRESOLVED_CONSERVATIVE" and v == pytest.approx(-200.97)
        assert ATR.per_scan_value({"decision": "WAIT"}) == (0.0, "WAIT")


# ------------------------------------------------------------------ §2.3 inference
class TestInference:
    def _design(self, seed=1, n_sessions=20, per=12, b1=0.5):
        rng = np.random.default_rng(seed)
        Z, y, sess = [], [], []
        for g in range(n_sessions):
            u = rng.standard_normal() * 0.4
            for i in range(per):
                x = rng.standard_normal()
                Z.append([1.0, x]); y.append(b1 * x + u + 0.3 * rng.standard_normal()); sess.append("d%02d" % g)
        return np.array(Z), np.array(y), sess

    def test_T30_restricted_null_adds_the_offset_back_and_restricts_one_equation(self):
        Z, y, sess = self._design()
        mu0, e0 = INF._restricted(Z, y, 1, 0.9)
        b_res = np.linalg.lstsq(Z, mu0, rcond=None)[0]
        assert b_res[1] == pytest.approx(0.9, abs=1e-10), "the null mean must sit at the tested value"
        assert float(np.max(np.abs(mu0 - y))) > 0 and float(np.mean(e0)) == pytest.approx(0.0, abs=1e-8)

    def test_T33_ci_by_inversion(self):
        Z, y, sess = self._design()
        ci = INF.ci_by_inversion(Z=Z, y=y, sessions=sess, j=1, B=199, seed=11)
        assert ci["lower"] < ci["b_hat"] < ci["upper"] and ci["G"] == 20 and ci["reference"] == "t_{G-1}"
        assert any("NUMERIC_TEST_INVERSION_APPROXIMATION" in l for l in ci["labels"])
        assert any("CLUSTER_INDEPENDENCE_ASSUMED" in l for l in ci["labels"])
        assert "REPRODUCIBILITY, not inferential correctness" in ci["reproducibility_note"]
        again = INF.ci_by_inversion(Z=Z, y=y, sessions=sess, j=1, B=199, seed=11)
        assert (again["lower"], again["upper"]) == (ci["lower"], ci["upper"])
        p_in = ci["tested_points"][str(round(min(k for k in map(float, ci["tested_points"])
                                                 if abs(k - ci["b_hat"]) == min(abs(float(x) - ci["b_hat"]) for x in ci["tested_points"])), 12))]
        assert p_in > 0.05
        cr = INF.cr1(Z, y - Z @ np.linalg.lstsq(Z, y, rcond=None)[0], INF._cluster_index(sess))
        assert cr.shape == (2, 2) and cr[1, 1] > 0
        hc = INF.hc1_descriptive(Z, y - Z @ np.linalg.lstsq(Z, y, rcond=None)[0])
        assert hc[1, 1] > 0 and hc[1, 1] != cr[1, 1]                       # HC1 differs; it is descriptive only

    def test_T31_budget_separation(self):
        e = _engine(n_paths=60)
        r = _decide(e)
        assert "bootstrap" not in json.dumps(r["trace"]).lower()           # no resampling inside a decision
        assert r["trace"]["fit"]["status"] == "READY"


# ------------------------------------------------------------------ §5.3 decision rule
def _acct(mean, *, n=400, spread=1.0, u=0.0, avail=0.0):
    rng = np.random.default_rng(int(abs(mean) * 1000) + 7)
    s1 = rng.normal(mean, spread, n)
    s2 = s1 + u
    return {"S1": s1, "S2": s2, "mean_S1": float(s1.mean()), "mean_S2": float(s2.mean()),
            "E_sel": min(float(s1.mean()), float(s2.mean())), "U": abs(float(s1.mean() - s2.mean())),
            "availability_failure_rate": avail, "refused": None, "size_policy": "ASSUME_AVAILABLE",
            "counters": {}, "selected_scenario": "S1"}


class TestDecisionRule:
    def test_T18_rule_zero_sole_candidate_and_tie(self):
        r0 = DR.decide(ranked=[], eligibility_census={"RISK_ENVELOPE": 3})
        assert r0["decision"] == "WAIT" and r0["why"] == "NO_ELIGIBLE_CANDIDATE"
        assert r0["trace"]["rules"]["0"]["census"] == {"RISK_ENVELOPE": 3}
        one = DR.decide(ranked=[{"label": "a", "acct": _acct(20.0)}], comparator="C_IV")
        assert one["decision"] == "TRADE" and one["trace"]["rules"]["2"]["why"] == "SOLE_CANDIDATE"
        assert one["trace"]["multiplicity"]["family"] == 2 and one["trace"]["multiplicity"]["z"] > 2.0
        a = _acct(20.0)
        tie = DR.decide(ranked=[{"label": "a", "acct": a}, {"label": "b", "acct": a}], comparator="C_IV")
        assert tie["decision"] == "WAIT" and tie["why"] == "RANK_TIED"
        close = DR.decide(ranked=[{"label": "a", "acct": _acct(20.0)}, {"label": "b", "acct": _acct(19.999)}], comparator="C_IV")
        assert close["decision"] == "WAIT" and close["why"] == "RANK_UNCERTAIN"
        assert close["trace"]["rules"]["2"]["label"].startswith("HEURISTIC_SCREEN_NO_CONFIDENCE_CLAIM")

    def test_T34_simultaneous_scenario_gate(self):
        near = {"S1": np.full(400, 5.0), "S2": np.concatenate([np.full(396, 5.0), np.full(4, -300.0)]),
                "mean_S1": 5.0, "mean_S2": float(np.concatenate([np.full(396, 5.0), np.full(4, -300.0)]).mean()),
                "availability_failure_rate": 0.0, "refused": None, "counters": {}}
        near["E_sel"] = min(near["mean_S1"], near["mean_S2"]); near["U"] = abs(near["mean_S1"] - near["mean_S2"])
        r = DR.decide(ranked=[{"label": "a", "acct": near}], comparator="C_IV")
        assert r["decision"] == "WAIT" and r["why"].startswith("MC_NOT_DISTINGUISHED_FROM_WAIT:S2")
        assert r["trace"]["rules"]["1"]["by_scenario"]["S1"]["pass"] is True
        assert r["trace"]["rules"]["1"]["by_scenario"]["S2"]["pass"] is False
        assert "naive_2se_lower" in r["trace"]["rules"]["1"]["by_scenario"]["S1"]
        assert any("GATES_INTERSECTION_NOT_SIMULTANEOUS_COVERAGE" in l for l in r["trace"]["labels"])

    def test_T34_pathwise_minimum_is_a_different_quantity(self):
        s1, s2 = np.array([3.0, -1.0]), np.array([-1.0, 3.0])
        assert min(s1.mean(), s2.mean()) == 1.0 and float(np.minimum(s1, s2).mean()) == -1.0

    def test_T36_size_can_only_veto_never_substitute(self):
        strong, weak = _acct(30.0), _acct(10.0)
        calls = []

        def veto(label):
            calls.append(label)
            arr = np.concatenate([np.full(396, 1.0), np.full(4, -245.0)])   # 4 % illiquidity, negative economics
            return {"S1": arr, "S2": arr, "mean_S1": float(arr.mean()), "mean_S2": float(arr.mean()),
                    "E_sel": float(arr.mean()), "U": 0.0, "availability_failure_rate": 0.04, "refused": None}
        r = DR.decide(ranked=[{"label": "strong", "acct": strong}, {"label": "weak", "acct": weak}],
                      veto_eval=veto, comparator="JOINT")
        assert r["decision"] == "WAIT" and r["why"].startswith("SIZE_VETO_NOT_DISTINGUISHED_FROM_WAIT")
        assert calls == ["strong"], "only the SELECTED candidate is re-evaluated"
        assert r["selected"] == "strong", "no substitution with the runner-up"
        assert r["trace"]["rules"]["4"]["veto"]["policy"].startswith("SIZE_PROXY_V2 SELECT_THEN_VETO")
        und = DR.decide(ranked=[{"label": "s", "acct": strong}], veto_eval=lambda l: None, comparator="JOINT")
        assert und["decision"] == "WAIT" and und["why"] == "EXIT_LIQUIDITY_RISK"
        no_veto = DR.decide(ranked=[{"label": "s", "acct": strong}], veto_eval=veto, comparator="C_IV")
        assert no_veto["decision"] == "TRADE" and no_veto["trace"]["rules"]["4"]["veto"]["applied"] is False

    def test_T36_ranking_is_invariant_to_the_size_state(self):
        e = _engine(n_paths=400, seed=5)
        base = _state()
        big = dict(base); big["x_sz"] = math.log(1 + 9999)
        small = dict(base); small["x_sz"] = math.log(1 + 1)
        ra = _decide(e, ms=big); e.decisions -= 1
        rb = _decide(e, ms=small)
        la = [c["label"] for c in ra["trace"]["candidates"]["table"] if c["status"] == "ELIGIBLE"]
        lb = [c["label"] for c in rb["trace"]["candidates"]["table"] if c["status"] == "ELIGIBLE"]
        assert la == lb and la, "size must play no part in the ranking"
        assert ra["trace"]["candidates"]["ranking_policy"].startswith("ASSUME_AVAILABLE")


# ------------------------------------------------------------------ §6.1 engine identities
class TestEngineIdentities:
    def test_T12_T29_candidate_order_cannot_change_any_path(self):
        e = _engine(n_paths=300, seed=9)
        ms = _state()
        a = _decide(e, ms=ms)
        e2 = _engine(n_paths=300, seed=9)
        ms2 = _state()
        ms2["valid_quotes"] = dict(reversed(list(ms2["valid_quotes"].items())))
        b = _decide(e2, ms=ms2)
        assert a["trace"]["underlying"]["seed"] == b["trace"]["underlying"]["seed"]
        assert a["trace"]["sampler"]["seed"] == b["trace"]["sampler"]["seed"]
        ta = {c["label"]: c.get("E_sel_rank") for c in a["trace"]["candidates"]["table"]}
        tb = {c["label"]: c.get("E_sel_rank") for c in b["trace"]["candidates"]["table"]}
        assert ta == tb and a["trace"]["selected"] == b["trace"]["selected"] if a["decision"] == "TRADE" else ta == tb

    def test_T11_contract_conflict_sigma_exactly_zero_is_unreachable(self):
        """CONTRACT CONFLICT (recorded, not worked around). §6.1 T11a/T11b require `A = 0, Sigma = 0` to produce
        bitwise-identical paths, but §2.3/§2.4 require Sigma positive definite (`COVARIANCE_NOT_PD`). Both cannot
        hold. Smallest reproducing fixture:"""
        with pytest.raises(SMP.SamplerRefused, match="COVARIANCE_NOT_PD:S11"):
            SMP.pregenerate(sigma=np.zeros((4, 4)), n_paths=4, seed=1)
        with pytest.raises(MDL.ModelRefusedR4, match="DEGENERATE_STATE"):        # a zero-variance world cannot be fitted either
            flat = SW.make_rows(n_sessions=30, A_true=None, Sigma_true=np.eye(4) * 1e-14, seed=11)
            for r in flat:
                r["end"] = dict(r["start"])
            MDL.fit(MDL.build_rows(flat), cutoff_epoch=1e12)

    def test_T11a_zero_dynamics_compatible_states_converges(self):
        """The achievable form: A = 0 and Sigma -> 0. With every eligible contract starting at size >= 1, JOINT and
        MATCHED_FROZEN agree, and the gap SHRINKS with Sigma (it is exactly 0 only at the unreachable Sigma = 0)."""
        f = _fitted()
        gaps = {}
        for eps in (1e-10, 1e-14):
            vals = {}
            for comp in ("JOINT", "MATCHED_FROZEN"):
                e = ENG.JointEngine(n_paths=200, seed=4, comparator=comp)
                e.attach({**f, "A": np.zeros((4, 4)), "Sigma": np.eye(4) * eps}, permission=SW.permission())
                r = _decide(e, ms=_state(quotes=_quotes(size=50)))
                vals[comp] = {c["label"]: c.get("E_sel_rank") for c in r["trace"]["candidates"]["table"] if c["status"] == "ELIGIBLE"}
            assert set(vals["JOINT"]) == set(vals["MATCHED_FROZEN"]) and vals["JOINT"]
            gaps[eps] = max(abs(vals["JOINT"][k] - vals["MATCHED_FROZEN"][k]) for k in vals["JOINT"])
        assert gaps[1e-14] < gaps[1e-10], "the gap must shrink with Sigma"
        assert gaps[1e-14] < 1e-3

    def test_T11b_matched_size_policy_agrees_at_any_starting_size(self):
        """With A = 0, Sigma -> 0 and the SAME size policy, comparators agree even when the starting size is < 1 —
        the case that would break a cross-policy identity."""
        f0 = {**_fitted(), "A": np.zeros((4, 4)), "Sigma": np.eye(4) * 1e-14}
        vals = {}
        for comp in ("JOINT", "C_DIAG"):
            e = ENG.JointEngine(n_paths=200, seed=4, comparator=comp)
            e.attach(f0, permission=SW.permission())
            ms = _state(quotes=_quotes(size=25))
            ms["x_sz"] = math.log(1 + 0.4)                                    # starting size < 1
            ms["size_atm"] = 0.4
            r = _decide(e, ms=ms)
            vals[comp] = {c["label"]: c.get("E_sel_rank") for c in r["trace"]["candidates"]["table"] if c["status"] == "ELIGIBLE"}
        assert vals["JOINT"] and vals["JOINT"].keys() == vals["C_DIAG"].keys()
        assert max(abs(vals["JOINT"][k] - vals["C_DIAG"][k]) for k in vals["JOINT"]) < 1e-3

    def test_T17_deterministic_reconstruction(self):
        a = _decide(_engine(n_paths=200, seed=3))
        b = _decide(_engine(n_paths=200, seed=3))
        assert a["trace"]["selected"]["trace_digest"] == b["trace"]["selected"]["trace_digest"] if a["decision"] == "TRADE" else a["why"] == b["why"]
        assert json.dumps(a["trace"], default=str) == json.dumps(b["trace"], default=str)

    def test_T21_separation_block_is_present_with_two_distinct_digests(self):
        r = _decide(_engine(n_paths=100))
        sep = r["trace"]["separation"]
        assert sep["forecast_model"]["produces"] == "future STATES"
        assert sep["pricing_model"]["produces"] == "price of a contract GIVEN a state"
        assert sep["forecast_model"]["parameters_digest"] != sep["pricing_model"]["digest"]
        assert "not a calibrated probability" in sep["statement"] and "not a fill probability" in sep["statement"]

    def test_T20_mandatory_wait_cases(self):
        e = _engine(n_paths=100)
        assert _decide(e, book=None)["why"].startswith("PRIME_ABSTAIN: PREREQUISITE_MISSING: book summary")
        assert "BOOK_INTEGRITY" in _decide(e, book={"integrity_problems": ["CASH"]})["why"]
        ms = _state(); ms["x_sk"] = None; ms["skew_why"] = "SKEW_LEG_MISSING:minus"
        assert "skew MISSING" in _decide(e, ms=ms)["why"]
        cold = ENG.JointEngine(n_paths=50)
        assert _decide(cold)["why"].startswith("PRIME_ABSTAIN: UNSUPPORTED_STATE: NOT_FITTED")
        spy = _engine(n_paths=100)
        ks = [640.0, 645.0, 650.0]
        bars, unders = SW.bars_and_underlyings(t_d=T_D, spot=645.0)
        big = ST.compose(symbol="SPY", t_d=T_D, bars=bars, underlyings=unders,
                         chain=[{"expiration": EXPIRY, "strike": k, "right": rr} for k in ks for rr in ("CALL", "PUT")],
                         raw_quotes=SW.quotes_for_state(expiration=EXPIRY, strikes=ks, spot=645.0, iv=0.18, skew=-0.35,
                                                        spread_rel=0.02, size=25, t=T_D - 1.0, T_years=_T()))
        r = _decide(spy, ms=big)
        assert r["decision"] == "WAIT" and r["why"] == "NO_ELIGIBLE_CANDIDATE"
        assert r["trace"]["candidates"]["census"]["RISK_ENVELOPE"] >= 1


# ------------------------------------------------------------------ T19: the complete synthetic path through the boundary
REG = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc).timestamp() + 1.0


E2E_DRIFT = 0.0005              # 0.75 % up over the horizon: a planted mechanism, still inside the training support
E2E_H = 4e-7
E2E_VHAT = 15.0 * (E2E_DRIFT ** 2 + E2E_H)      # v_hat = E[q] CONSISTENT with the simulated path variance


def _e2e_quotes(t):
    return SW.quotes_for_state(expiration=EXPIRY, strikes=[195.0, 200.0, 205.0], spot=SPOT, iv=0.18, skew=-0.35,
                               spread_rel=0.02, size=40, t=t - 1.0,
                               T_years=(ST.expiry_epoch_of(EXPIRY) - t) / ST.CALENDAR_YEAR_S)


def _joint_context(spot=SPOT, drift=E2E_DRIFT, strikes=(195.0, 200.0, 205.0)):
    def ctx(symbol, as_of, forecast):
        t = as_of
        q = SW.quotes_for_state(expiration=EXPIRY, strikes=list(strikes), spot=spot, iv=0.18, skew=-0.35,
                                spread_rel=0.02, size=40, t=t - 1.0,
                                T_years=(ST.expiry_epoch_of(EXPIRY) - t) / ST.CALENDAR_YEAR_S)
        bars, unders = SW.bars_and_underlyings(t_d=t, spot=spot)
        chain = [{"expiration": EXPIRY, "strike": k, "right": r} for k in strikes for r in ("CALL", "PUT")]
        ms = ST.compose(symbol=symbol, t_d=t, bars=bars, underlyings=unders, chain=chain, raw_quotes=q)
        return {"market_state": ms, "variance_state": {"kind": "FLAT", "h": E2E_H}, "v_hat": E2E_VHAT, "nu": None,
                "drift_per_bar": drift}
    return ctx


def _coherent_execution(h):
    """The boundary's execution quotes agree with the quotes the engine ranked (entry), and the exit reflects the
    planted drift, so the ranking value and the executed price are the same object."""
    def entry(c):
        q = _e2e_quotes(h.now())[(c["expiration"], float(c["strike"]), c["right"])]
        return {"symbol": c["symbol"], "expiration": c["expiration"], "strike": c["strike"], "right": c["right"],
                "bid": q["bid"], "ask": q["ask"], "bid_size": 40, "ask_size": 40, "timestamp_epoch": h.now() - 1.0}

    def exit_(c):
        moved = SW.quotes_for_state(expiration=EXPIRY, strikes=[195.0, 200.0, 205.0],
                                    spot=SPOT * math.exp(E2E_DRIFT * 15), iv=0.18, skew=-0.35, spread_rel=0.02,
                                    size=40, t=h.now() - 1.0,
                                    T_years=(ST.expiry_epoch_of(EXPIRY) - h.now()) / ST.CALENDAR_YEAR_S)
        q = moved[(c["expiration"], float(c["strike"]), c["right"])]
        return {"symbol": c["symbol"], "expiration": c["expiration"], "strike": c["strike"], "right": c["right"],
                "bid": q["bid"], "ask": q["ask"], "bid_size": 40, "ask_size": 40, "timestamp_epoch": h.now() - 1.0}
    return entry, exit_


def test_T19_full_synthetic_path_state_to_reconciled_book(tmp_path):
    """UNCONDITIONAL: state -> forecast -> ranking -> persisted intent -> certified reservation -> fill -> exit -> reconciled book."""
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="R4-E2E", t0=REG)
    engine = ENG.JointEngine(n_paths=800, seed=7, comparator="JOINT")
    engine.attach(_fitted(), permission=SW.permission())
    entry, exit_ = _coherent_execution(h)
    h.quotes.override = entry
    h.exit_quotes.override = exit_
    from apex.pulse_options.sources import synthetic_twin_sources
    twin = synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn,
                                  sleep_fn=h.advance, selection_policy="JOINT_FUNNEL_V1", joint_engine=engine,
                                  joint_context_fn=_joint_context())
    rep = PEP.run_pilot(ledger=led, out=tmp_path / "out.json", symbols=["SPY"], provider=PEP.TwinProvider(twin),
                        session_id="R4-E2E", release="synthetic-release", cycles=1)
    rows = L.read_all(led); kinds = [r["kind"] for r in rows]
    assert rep["selection_policy"] == "JOINT_FUNNEL_V1"
    fn = next(r for r in rows if r["kind"] == "pilot_funnel")
    assert fn["decision"] == "TRADE", fn.get("why")
    assert fn["trace"]["contract_pin"] == CONTRACT_BLOB and fn["trace"]["engine"] == "JOINT_FUNNEL_V1"
    assert fn["trace"]["separation"]["statement"].startswith("a model-conditioned")
    assert fn["trace"]["candidates"]["ranking_policy"].startswith("ASSUME_AVAILABLE")
    assert fn["trace"]["decision_rule"]["rules"]["4"]["veto"]["applied"] is True
    it = next(r for r in rows if r["kind"] == "pilot_intent")
    assert it["funnel_ref"]["seq"] == kinds.index("pilot_funnel") + 1
    assert it["funnel_ref"]["proposal_digest"] == B.Boundary.proposal_digest(fn["proposal"])
    assert it["reference_ask"] == fn["proposal"]["reference_ask"]
    assert it["risk"]["risk_provenance"] == "CERTIFIED_KERNEL" and it["risk"]["kernel_check_at_commit"]["approved"] is True
    fill = next(r for r in rows if r["kind"] == "pilot_fill")
    assert fill["status"] == "FILLED"
    d = rep["decisions"][0]
    assert d["decision"] == "TRADE" and d["decision_persisted"] is True and d["fill_id"] == fill["fill_id"]
    assert len(rep["outcomes"]) == 1 and rep["outcomes"][0]["final"] == "RESOLVED"
    out = next(r for r in rows if r["kind"] == "pilot_outcome")
    assert out["status"] == "RESOLVED" and out["discharges_position"] is True
    assert rep["unresolved_positions"] == [] and not rep["outstanding_obligations"]
    assert rep["book"]["n_positions"] == 0 and rep["book"]["n_closed"] == 1 and rep["book"]["integrity_problems"] == []
    dec = next(r for r in rows if r["kind"] == "pilot_decision")
    assert dec["funnel_trace"]["contract"].startswith("FUNNEL_TRACE_V2")
    L.verify_chain(led, rows=rows)
    json.dumps(rep, allow_nan=False, default=str)


def test_T19_wait_case_persists_the_trace_and_creates_no_intent(tmp_path):
    """UNCONDITIONAL WAIT: same engine and path, but every near-ATM ask is above the kernel envelope."""
    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="R4-E2E-WAIT", t0=REG)
    engine = ENG.JointEngine(n_paths=400, seed=7, comparator="JOINT")
    engine.attach(_fitted(), permission=SW.permission())

    def ctx(symbol, as_of, forecast):
        t = as_of
        strikes = [640.0, 645.0, 650.0]
        q = SW.quotes_for_state(expiration=EXPIRY, strikes=strikes, spot=645.0, iv=0.18, skew=-0.35, spread_rel=0.02,
                                size=40, t=t - 1.0, T_years=(ST.expiry_epoch_of(EXPIRY) - t) / ST.CALENDAR_YEAR_S)  # SPY-scale asks exceed the envelope
        bars, unders = SW.bars_and_underlyings(t_d=t, spot=645.0)
        chain = [{"expiration": EXPIRY, "strike": k, "right": r} for k in strikes for r in ("CALL", "PUT")]
        return {"market_state": ST.compose(symbol=symbol, t_d=t, bars=bars, underlyings=unders, chain=chain, raw_quotes=q),
                "variance_state": {"kind": "FLAT", "h": E2E_H}, "v_hat": 15.0 * E2E_H, "nu": None, "drift_per_bar": 0.0}
    from apex.pulse_options.sources import synthetic_twin_sources
    twin = synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn,
                                  sleep_fn=h.advance, selection_policy="JOINT_FUNNEL_V1", joint_engine=engine, joint_context_fn=ctx)
    rep = PEP.run_pilot(ledger=led, out=tmp_path / "out.json", symbols=["SPY"], provider=PEP.TwinProvider(twin),
                        session_id="R4-E2E-WAIT", release="synthetic-release", cycles=1)
    rows = L.read_all(led); kinds = [r["kind"] for r in rows]
    fn = next(r for r in rows if r["kind"] == "pilot_funnel")
    assert fn["decision"] == "WAIT" and fn["why"] == "NO_ELIGIBLE_CANDIDATE"
    assert fn["trace"]["candidates"]["census"]["RISK_ENVELOPE"] >= 1
    assert "pilot_intent" not in kinds and "pilot_fill" not in kinds and rep["outcomes"] == []
    assert rep["decisions"][0]["decision"] == "WAIT" and rep["decisions"][0]["decision_persisted"] is True
    L.verify_chain(led, rows=rows)
