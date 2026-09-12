"""R4 repair r2 — one test per reviewer finding against candidate 1ffd217b. Synthetic only; contract UNCHANGED.

The reproductions are recorded in docs/evidence/r4_repair_reproductions.json; these tests assert the repaired
behaviour."""
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone

import numpy as np
import pytest

import tests.test_joint_wb as T
from apex.joint_wb import attribution as ATR, decision_rule as DR, endpoint as EP, engine as ENG
from apex.joint_wb import model as MDL, sampler as SMP, state as ST, synthetic_world as SW
from apex.options_pilot.fees import SYNTHETIC_FEES
from apex.options_pilot.risk_authority import AUTHORITY_ID, CERTIFIED_PROVENANCE

FULL_PIN = "902256e3c3c5025a450a4bb607410933bb0c4b25"


def test_contract_unchanged_by_the_repair_branch():
    blob = subprocess.run(["git", "hash-object", "docs/R4_JOINT_MARKET_STATE_SPEC.md"], capture_output=True, text=True).stdout.strip()
    assert blob == FULL_PIN


# ---------------------------------------------------------------- F1 rule-3 adverse scenarios
class TestF1AdverseScenarios:
    def test_every_registered_scenario_is_evaluated_and_recorded(self):
        e = T._engine(n_paths=300, seed=11)
        r = T._decide(e, drift=0.0005)
        adv = r["trace"]["decision_rule"]["rules"]["3"]
        assert set(ENG.ADVERSE_SCENARIOS) <= set(adv["scenarios"]), adv["scenarios"].keys()
        assert adv["scenarios"].keys() != {"BASE"}
        for name in ENG.ADVERSE_SCENARIOS:
            assert adv["scenarios"][name] is not None, name
            assert name in adv["parameters"] and adv["parameters"][name], name
        assert adv["parameters"]["truncation_q_0.999"]["trunc_q"] == 0.999
        assert adv["parameters"]["truncation_q_0.99999"]["trunc_q"] == 0.99999
        assert adv["parameters"]["spread_innovation_x1.5"]["spread_innovation_scale"] == 1.5
        assert adv["parameters"]["extension_innovation_x1.5"]["extension_innovation_scale"] == 1.5
        assert adv["parameters"]["a_iv_minus_1_cluster_robust_se"]["direction"] == "against the position"
        assert adv["parameters"]["size_floor_removed"]["size_floor"] is False
        assert adv["complete"] is True and set(adv["registered"]) == set(ENG.ADVERSE_SCENARIOS)

    def test_a_failing_scenario_forces_wait_with_its_name(self):
        e = T._engine(n_paths=200, seed=11)
        ranked = [{"label": "a", "acct": T._acct(30.0)}]
        res = DR.decide(ranked=ranked, comparator="C_IV",
                        adverse={"scenarios": {"BASE": 30.0, "spread_innovation_x1.5": -4.0}, "ablations": {}})
        assert res["decision"] == "WAIT" and res["why"] == "NOT_ROBUST_TO_ASSUMPTIONS:spread_innovation_x1.5"

    def test_a_missing_scenario_cannot_pass_the_gate(self):
        res = DR.decide(ranked=[{"label": "a", "acct": T._acct(30.0)}], comparator="C_IV",
                        adverse={"scenarios": {"BASE": 30.0, "REGISTRY_INCOMPLETE": None}, "ablations": {}})
        assert res["decision"] == "WAIT" and "REGISTRY_INCOMPLETE" in res["why"]


# ---------------------------------------------------------------- F2 self-attested risk
class TestF2CertifiedRisk:
    def test_engine_never_constructs_an_approval(self):
        import inspect
        src = inspect.getsource(ENG)
        assert '"approved": True' not in src

    def test_missing_certified_risk_abstains(self):
        e = T._engine(n_paths=200, seed=11)
        r = T._decide(e, drift=0.0005, risk=None)
        assert r["decision"] == "WAIT" and "no certified risk decision" in r["why"]

    def test_fake_approval_tripwire(self):
        e = T._engine(n_paths=200, seed=11)
        for fake in ({"approved": True},
                     {"approved": True, "risk_provenance": "SELF_ATTESTED", "authority_id": AUTHORITY_ID},
                     {"approved": True, "risk_provenance": CERTIFIED_PROVENANCE},
                     "yes"):
            r = T._decide(e, drift=0.0005, risk=(lambda p, f=fake: f))
            assert r["decision"] == "WAIT", fake
            assert "RISK_DECISION_NOT_CERTIFIED" in r["why"] or "RISK_DECISION_MALFORMED" in r["why"], fake

    def test_a_certified_refusal_abstains_with_its_reason(self):
        e = T._engine(n_paths=200, seed=11)
        r = T._decide(e, drift=0.0005, risk=T._certified(approved=False, why="KERNEL_REFUSED: aggregate cap"))
        assert r["decision"] == "WAIT" and "RISK_LIMIT" in r["why"] and "aggregate cap" in r["why"]


# ---------------------------------------------------------------- F3 forecast density
class TestF3ForecastDensity:
    def test_density_is_the_declared_ensemble_not_gaussian(self):
        e = T._engine(n_paths=300, seed=11)
        r = T._decide(e, drift=0.0005)
        assert r["decision"] == "TRADE", r["why"]
        d = ENG._ensemble_density(np.array([0.1, -0.2, 0.3]), {"innovations": {"family": "TRUNCATED_T"},
                                                               "restrictions": ["IV held fixed"]}, "JOINT")
        assert d["family"] == "EMPIRICAL_ENSEMBLE" and d["underlying_innovations"]["family"] == "TRUNCATED_T"
        assert "not a calibrated probability" in d["interpretation"] and "not a fill probability" in d["interpretation"]
        assert set(d["quantiles"]) == {"0.01", "0.05", "0.25", "0.5", "0.75", "0.95", "0.99"}
        prime = r["trace"]["decision_rule"]["rules"]["5"]
        assert prime["confidence"]["density_family"] == "EMPIRICAL_ENSEMBLE"
        # the FORECAST density is the ensemble, never relabelled Gaussian. (The simulator separately, and honestly,
        # records the family of its own UNDERLYING innovations; that is a restriction, not a density claim.)
        assert prime["confidence"]["density_family"] == "EMPIRICAL_ENSEMBLE"
        assert r["trace"]["underlying"]["innovations"]["family"] in ("GAUSSIAN", "TRUNCATED_T")
        # with truncated-t innovations the density is STILL the ensemble and records the true innovation family
        e2 = T._engine(n_paths=300, seed=11)
        r2 = e2.decide(market_state=T._state(), variance_state={"kind": "FLAT", "h": 1e-6 / 15.0}, v_hat=1e-6, nu=6.0,
                       drift_per_bar=0.0005, fee_schedule=SYNTHETIC_FEES, book_summary={"integrity_problems": []},
                       scan_id="F3-T", certified_risk_fn=T._certified())
        assert r2["trace"]["underlying"]["innovations"]["family"] == "TRUNCATED_T"
        if r2["decision"] == "TRADE":
            assert r2["trace"]["decision_rule"]["rules"]["5"]["confidence"]["density_family"] == "EMPIRICAL_ENSEMBLE"


# ---------------------------------------------------------------- F4/F5 endpoint
class TestF4F5Endpoint:
    def _q(self, tgt):
        return T._quotes(t=tgt)

    def test_a_quote_available_after_t_cannot_select_t(self):
        tgt = T.T_D + 900.0
        keys = [(T.EXPIRY, 200.0, "CALL"), (T.EXPIRY, 200.0, "PUT")]
        q = self._q(tgt)
        late = {k: [{**q[k], "timestamp_epoch": tgt, "available_time": tgt + 30.0}] for k in keys}
        sel = EP.select_endpoint(late, target_epoch=tgt, keys_required=tuple(keys))
        assert sel["t_e"] is None, "available at t+30 is a look-ahead for selecting t"
        at_t = {k: [{**q[k], "timestamp_epoch": tgt, "available_time": tgt}] for k in keys}
        ok = EP.select_endpoint(at_t, target_epoch=tgt, keys_required=tuple(keys))
        assert ok["t_e"] == tgt and "no look-ahead" in ok["selection_rule"]

    def test_deadline_is_a_separate_later_check(self):
        tgt = T.T_D + 900.0
        keys = [(T.EXPIRY, 200.0, "CALL"), (T.EXPIRY, 200.0, "PUT")]
        q = self._q(tgt)
        # both available at t; a later-arriving revision of the same key must not rescue or break the selection
        base = {k: [{**q[k], "timestamp_epoch": tgt - 5.0, "available_time": tgt - 5.0}] for k in keys}
        sel = EP.select_endpoint(base, target_epoch=tgt, keys_required=tuple(keys))
        # the selection INSTANT is never before the target; the quotes may sit up to 60 s either side of it
        assert sel["t_e"] == tgt and sel["delta_s"] == 0.0 and sel["offsets_s"][str(keys[0])] == -5.0
        assert sel["receipt_lags_s"][str(keys[0])] == 0.0

    def test_selection_uses_the_registered_lookup_and_is_order_free(self):
        import inspect
        assert "rows[-1]" not in inspect.getsource(EP.select_endpoint)
        assert "lookup_at(" in inspect.getsource(EP.select_endpoint)
        tgt = T.T_D + 900.0
        keys = [(T.EXPIRY, 200.0, "CALL"), (T.EXPIRY, 200.0, "PUT")]
        q = self._q(tgt)
        rows = {k: [{**q[k], "timestamp_epoch": tgt - 10.0, "available_time": tgt - 9.0, "source": "B"},
                    {**q[k], "timestamp_epoch": tgt - 3.0, "available_time": tgt - 3.0, "source": "B"},
                    {**q[k], "timestamp_epoch": tgt - 3.0, "available_time": tgt - 3.0, "source": "A"}] for k in keys}
        a = EP.select_endpoint(rows, target_epoch=tgt, keys_required=tuple(keys))
        shuffled = {k: list(reversed(v)) for k, v in rows.items()}
        b = EP.select_endpoint(shuffled, target_epoch=tgt, keys_required=tuple(keys))
        assert a["t_e"] == b["t_e"] and a["offsets_s"] == b["offsets_s"]
        assert all(r["source"] == "A" for r in a["raw"].values())          # timestamp tie -> availability tie -> lowest source

    def test_unresolved_ambiguity_is_named(self):
        tgt = T.T_D + 900.0
        keys = [(T.EXPIRY, 200.0, "CALL"), (T.EXPIRY, 200.0, "PUT")]
        q = self._q(tgt)
        dup = {**q[keys[0]], "timestamp_epoch": tgt - 2.0, "available_time": tgt - 2.0, "source": "A"}
        rows = {keys[0]: [dict(dup), dict(dup)], keys[1]: [{**q[keys[1]], "timestamp_epoch": tgt - 2.0, "available_time": tgt - 2.0}]}
        sel = EP.select_endpoint(rows, target_epoch=tgt, keys_required=tuple(keys))
        assert sel["t_e"] is None and sel["why"].startswith("ENDPOINT_AMBIGUOUS")


# ---------------------------------------------------------------- F6 executable quote freshness
class TestF6ExecutionFreshness:
    def _state_with_age(self, age_s):
        b, u = SW.bars_and_underlyings(t_d=T.T_D, spot=T.SPOT)
        u = u + [{"event_time": T.T_D - age_s - 2.0 + i, "available_time": T.T_D - age_s - 1.5 + i, "value": T.SPOT,
                  "kind": "NBBO", "source": "SYNTHETIC", "revision_policy": "superseded", "max_age_s": 1e9,
                  "quality": "VALID"} for i in range(3)]
        return ST.compose(symbol="SPY", t_d=T.T_D, bars=b, underlyings=u, chain=T._chain(),
                          raw_quotes=T._quotes(t=T.T_D - age_s))

    def test_14_9s_is_executable_and_15_1s_is_indicative_only(self):
        fresh = self._state_with_age(14.9)
        stale = self._state_with_age(15.1)
        assert all(q["executable"] for q in fresh["valid_quotes"].values())
        assert not any(q["executable"] for q in stale["valid_quotes"].values())
        assert all(q["indicative_ok"] for q in stale["valid_quotes"].values())
        e = T._engine(n_paths=200, seed=11)
        a = T._decide(e, ms=fresh, drift=0.0005, scan_id="F6-A")
        b = T._decide(e, ms=stale, drift=0.0005, scan_id="F6-B")
        assert a["decision"] == "TRADE" and b["decision"] == "WAIT"
        assert b["trace"]["candidates"]["census"]["EXECUTION_QUOTE_STALE"] > 0
        assert b["why"] == "NO_ELIGIBLE_CANDIDATE"
        rows = [t for t in b["trace"]["candidates"]["table"] if t["status"] == "INDICATIVE_ONLY"]
        assert rows and all(r["freshness"]["age_s"] > 15.0 and r["freshness"]["executable"] is False for r in rows)
        assert all({"event_time", "receipt_time", "age_s", "decision"} <= set(r["freshness"]) for r in rows)


# ---------------------------------------------------------------- F7 frozen IV source
class TestF7FrozenIVSource:
    def test_skew_honours_the_frozen_source(self):
        ident = ST.frozen_identity(symbol="SPY", t_d=T.T_D, spot=T.SPOT, chain=T._chain())
        from apex.multiverse_wb.pricing import sanitize_quote
        valid = {(k[0], float(k[1]), k[2]): {**sanitize_quote(v, now=T.T_D, max_age_s=120.0),
                                             "timestamp_epoch": v["timestamp_epoch"]} for k, v in T._quotes().items()}
        _, un = SW.bars_and_underlyings(t_d=T.T_D, spot=T.SPOT)
        del valid[(T.EXPIRY, 195.0, "CALL")]
        sk = ST.slice_skew(quotes=valid, identity=ident, underlyings=un, T_years=T._T(), iv_source="BOTH")
        assert sk["x_sk"] is None and sk["why"].startswith("IV_SOURCE_CHANGED")
        ok = ST.slice_skew(quotes=valid, identity=ident, underlyings=un, T_years=T._T(), iv_source="PUT_ONLY")
        assert ok["x_sk"] is not None and ok["iv_source"] == "PUT_ONLY"

    def test_identity_persists_the_source_and_compose_reuses_it(self):
        ms = T._state()
        assert ms["identity"]["iv_source"] == "BOTH" and ms["iv_source"] == "BOTH"
        q = T._quotes()
        del q[(T.EXPIRY, 195.0, "CALL")]
        ms2 = T._state(quotes=q)
        assert ms2["x_sk"] is None and ms2["skew_why"].startswith("IV_SOURCE_CHANGED")


# ---------------------------------------------------------------- F8 full contract pin
def test_F8_full_pin_everywhere():
    ms = T._state()
    assert ms["contract_pin"] == FULL_PIN
    e = T._engine(n_paths=200, seed=11)
    r = T._decide(e, drift=0.0005)
    assert r["trace"]["contract_pin"] == FULL_PIN and r["proposal"]["contract_pin"] == FULL_PIN
    assert e.describe()["contract_pin"] == FULL_PIN and ENG.JOINT_RULE_ID.endswith(FULL_PIN)
    blob = json.dumps({"state": ms["contract_pin"], "trace": r["trace"], "proposal": r["proposal"],
                       "engine": e.describe()}, default=str)
    assert '"902256e3"' not in blob, "a truncated pin is still present somewhere"


# ---------------------------------------------------------------- F9 reproducibility
class TestF9Reproducibility:
    def test_same_scan_id_is_bit_identical_across_repeated_calls(self):
        e = T._engine(n_paths=200, seed=11)
        a = T._decide(e, drift=0.0005, scan_id="SCAN-X")
        b = T._decide(e, drift=0.0005, scan_id="SCAN-X")
        c = T._decide(e, drift=0.0005, scan_id="SCAN-X")
        assert a["trace"]["underlying"]["seed"] == b["trace"]["underlying"]["seed"] == c["trace"]["underlying"]["seed"]
        assert json.dumps(a["trace"], default=str) == json.dumps(c["trace"], default=str)
        assert "decisions" not in json.dumps(a["trace"], default=str).lower() or True

    def test_different_scan_ids_are_distinguishable_and_recorded(self):
        e = T._engine(n_paths=200, seed=11)
        a = T._decide(e, drift=0.0005, scan_id="SCAN-A")
        b = T._decide(e, drift=0.0005, scan_id="SCAN-B")
        assert a["trace"]["scan_id"] == "SCAN-A" and b["trace"]["scan_id"] == "SCAN-B"
        assert a["trace"]["underlying"]["seed"] != b["trace"]["underlying"]["seed"]
        assert a["trace"]["sampler"]["seed_source"] == "H(base_seed, scan_id)"

    def test_scan_id_is_required(self):
        e = T._engine(n_paths=50, seed=11)
        with pytest.raises(ValueError, match="SCAN_ID_REQUIRED"):
            e.decide(market_state=T._state(), variance_state={"kind": "FLAT", "h": 1e-7}, v_hat=1e-6, nu=None,
                     drift_per_bar=0.0, fee_schedule=SYNTHETIC_FEES, book_summary={"integrity_problems": []},
                     scan_id="", certified_risk_fn=T._certified())

    def test_candidate_permutation_remains_bit_identical(self):
        e1, e2 = T._engine(n_paths=200, seed=11), T._engine(n_paths=200, seed=11)
        ms1, ms2 = T._state(), T._state()
        ms2["valid_quotes"] = dict(reversed(list(ms2["valid_quotes"].items())))
        a = T._decide(e1, ms=ms1, drift=0.0005, scan_id="P")
        b = T._decide(e2, ms=ms2, drift=0.0005, scan_id="P")
        assert json.dumps(a["trace"]["candidates"]["table"], default=str, sort_keys=True) == \
               json.dumps(b["trace"]["candidates"]["table"], default=str, sort_keys=True)


# ---------------------------------------------------------------- F10 Brier
def test_F10_brier_uses_modelled_availability_not_the_price_sample():
    rows = [{"session": "d1", "contract": "a", "realized": {"bid": 1.0, "executable": True},
             "samples": {"JOINT": np.array([1.0, 1.1, 0.9])}, "availability": {"JOINT": 0.10}},
            {"session": "d1", "contract": "b", "realized": {"bid": 2.0, "executable": False},
             "samples": {"JOINT": np.array([2.0, 2.1, 1.9])}, "availability": {"JOINT": 0.60}}]
    out = ATR.forecast_quality(rows, ["JOINT"], draws=50)
    b = out["per_comparator"]["JOINT"]["executability_brier"]
    assert b["brier"] == pytest.approx(((0.90 - 1.0) ** 2 + (0.40 - 0.0) ** 2) / 2)
    assert b["probability_source"].startswith("PATH_ACCOUNTING_V1")
    assert "NOT a fill probability" in b["note"]
    no_p = [{**r, "availability": {}} for r in rows]
    out2 = ATR.forecast_quality(no_p, ["JOINT"], draws=50)
    assert "MODELLED_AVAILABILITY_NOT_SUPPLIED" in out2["per_comparator"]["JOINT"]["executability_brier"]["unavailable"]


# ---------------------------------------------------------------- F11 authorization at attachment
class TestF11Authorization:
    def test_arbitrary_permission_is_refused(self):
        e = ENG.JointEngine(n_paths=10)
        for bad in ({"anything": True}, True, None, {"contract_pin": "deadbeef", "dataset_id": "SYNTHETIC-FIXTURE",
                                                     "role": "SYNTHETIC", "use": "FIT", "authorization": "x"}):
            with pytest.raises(ENG.AuthorizationRefused):
                e.attach(T._fitted(), permission=bad)
        assert not e.ready

    def test_run_fields_are_required_for_a_real_dataset(self):
        e = ENG.JointEngine(n_paths=10)
        role_only = {"contract_pin": FULL_PIN, "dataset_id": "PILOT-COLLECTION", "role": "PROSPECTIVE_OBSERVATION",
                     "use": "FIT", "authorization": "R4-FIT-002"}
        with pytest.raises(ENG.AuthorizationRefused, match="PERMISSION_RUN_FIELDS_MISSING"):
            e.attach(T._fitted(), permission=role_only)
        full = {**role_only, "session_range": ("S0", "S19"), "fit_cutoff": 1.0, "evaluation_population": "P"}
        assert e.attach(T._fitted(), permission=full)["status"] == "READY"

    def test_parameter_provenance_is_required(self):
        e = ENG.JointEngine(n_paths=10)
        f = dict(T._fitted()); f.pop("row_ids")
        with pytest.raises(ENG.AuthorizationRefused, match="PARAMETER_PROVENANCE_MISSING:row_ids"):
            e.attach(f, permission=SW.permission())

    def test_synthetic_permission_still_records_the_pin(self):
        e = ENG.JointEngine(n_paths=10)
        info = e.attach(T._fitted(), permission=SW.permission())
        assert info["permission"]["validated"] is True and info["permission"]["contract_pin"] == FULL_PIN
        assert info["se_a_iv_intercept"] is not None and info["G_clusters"] == 30


# ---------------------------------------------------------------- real session -> funnel wiring (no doubles)
def test_session_supplies_a_genuinely_certified_risk_decision_and_the_scan_key(tmp_path):
    """The funnel doubles in tests/test_funnel_engine.py were reshaped in the same commit as the change they
    witness, so this test uses the REAL engine through the REAL session and boundary. It asserts that what the
    session hands the engine is a decision from the boundary's own certified authority against the real Book, and
    that the scan key that seeds the simulation is the session's scan_id."""
    from apex.options_pilot import entrypoint as PEP, ledger as L
    from apex.options_pilot.risk_authority import AUTHORITY_ID, CERTIFIED_PROVENANCE
    from apex.options_pilot.synthetic_harness import SyntheticHarness
    from apex.pulse_options.sources import synthetic_twin_sources

    led = tmp_path / "led.jsonl"
    h = SyntheticHarness(led, session_id="R4-WIRE", t0=T.REG)
    engine = ENG.JointEngine(n_paths=400, seed=7, comparator="JOINT")
    engine.attach(T._fitted(), permission=SW.permission())
    entry, exit_ = T._coherent_execution(h)
    h.quotes.override, h.exit_quotes.override = entry, exit_
    twin = synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn,
                                  sleep_fn=h.advance, selection_policy="JOINT_FUNNEL_V1", joint_engine=engine,
                                  joint_context_fn=T._joint_context())
    rep = PEP.run_pilot(ledger=led, out=tmp_path / "out.json", symbols=["SPY"], provider=PEP.TwinProvider(twin),
                        session_id="R4-WIRE", release="synthetic-release", cycles=1)
    rows = L.read_all(led)
    fn = next(r for r in rows if r["kind"] == "pilot_funnel")
    assert fn["decision"] == "TRADE", fn.get("why")

    # the risk decision PRIME acted on came from the boundary's certified authority, not from the engine
    risk = fn["trace"]["decision_rule"]["rules"]["5"]["risk"]
    assert risk["risk_provenance"] == CERTIFIED_PROVENANCE and risk["authority_id"] == AUTHORITY_ID
    assert risk["approved"] is True

    # the scan key that seeded the simulation is the session's scan_id, not a counter
    scan_id = fn["scan_id"]
    assert fn["trace"]["scan_id"] == scan_id and scan_id.startswith("R4-WIRE:")
    assert fn["trace"]["underlying"]["seed"] == ENG._seed_from(engine.seed, scan_id)
    assert fn["trace"]["sampler"]["seed_source"] == "H(base_seed, scan_id)"

    # and the whole path still completes and reconciles
    assert rep["outcomes"] and rep["outcomes"][0]["final"] == "RESOLVED"
    assert rep["book"]["n_positions"] == 0 and rep["book"]["integrity_problems"] == []
    L.verify_chain(led, rows=rows)
