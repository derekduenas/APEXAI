"""Reproduce each reviewer finding against candidate 1ffd217b BEFORE any repair. Read-only probes, synthetic only."""
import sys, json, math, inspect; sys.path.insert(0, '.')
import numpy as np
import tests.test_joint_wb as T
from apex.joint_wb import accounting as ACC, attribution as ATR, endpoint as EP, engine as ENG, sampler as SMP, state as ST, synthetic_world as SW
from apex.options_pilot.fees import SYNTHETIC_FEES

F = {}

def rec(k, reproduced, detail):
    F[k] = {"reproduced": bool(reproduced), "detail": detail}

e = T._engine(n_paths=300, seed=11)
ms = T._state()
r = T._decide(e, ms=ms, drift=0.0005)
ADV = r["trace"]["decision_rule"]["rules"]["3"]

# 1 rule-3 stub -- SET EQUALITY against the registry itself, so a rename cannot drift the probe and the code apart
adv = ADV["scenarios"]
REGISTERED = set(ENG.ADVERSE_SCENARIOS)                       # sourced from the code, never retyped
produced = set(adv) - {"BASE"}
missing, extra = sorted(REGISTERED - produced), sorted(produced - REGISTERED)
rec("F1_rule3_stub", bool(missing or extra or not ADV.get("complete")),
    {"registered": sorted(REGISTERED), "produced_excluding_BASE": sorted(produced),
     "missing": missing, "unregistered_extra": extra, "complete_flag": ADV.get("complete"),
     "all_values_positive": all(v is not None and v > 0 for k, v in adv.items()),
     "parameters_recorded_for_each": sorted(set(ADV.get("parameters", {})) - {"BASE"}) == sorted(REGISTERED),
     "assertion": "set equality of produced-minus-BASE against ENG.ADVERSE_SCENARIOS, plus the complete flag"})

# 2 self-attested risk
src = inspect.getsource(ENG.JointEngine.decide)
rec("F2_self_attested_risk", '"approved": True' in src, {"line": [l.strip() for l in src.splitlines() if '"approved": True' in l]})

# 3 fabricated Gaussian density
rec("F3_gaussian_claim", '"family": "GAUSSIAN"' in src,
    {"line": [l.strip() for l in src.splitlines() if 'GAUSSIAN' in l], "underlying": "truncated-t / GARCH ensemble"})

# 4 endpoint look-ahead
tgt = T.T_D + 900.0
keys = [(T.EXPIRY, 200.0, "CALL"), (T.EXPIRY, 200.0, "PUT")]
q = T._quotes(t=tgt)
la = {k: [{**q[k], "timestamp_epoch": tgt, "available_time": tgt + 30.0}] for k in keys}   # available AFTER t, before t+60
sel = EP.select_endpoint(la, target_epoch=tgt, keys_required=tuple(keys))
rec("F4_endpoint_lookahead", sel["t_e"] == tgt, {"t_e": sel["t_e"], "available_time": tgt + 30.0,
    "why": "a quote available only after the selected instant was used to select it"})

# 5 rows[-1] instead of lookup_at
esrc = inspect.getsource(EP.select_endpoint)
rec("F5_not_using_lookup_at", "rows[-1]" in esrc and "lookup_at(" not in esrc, {"uses": "rows[-1]", "registered": "lookup_at"})

# 6 execution quote freshness 120 s not 15 s
old_q = T._quotes(t=T.T_D - 100.0)                       # 100 s old: indicative-fresh, execution-stale
_b, _u = SW.bars_and_underlyings(t_d=T.T_D, spot=T.SPOT)
_u = _u + [{"event_time": T.T_D - 102.0 + 2.0 * i, "available_time": T.T_D - 101.5 + 2.0 * i, "value": T.SPOT,
            "kind": "NBBO", "source": "SYNTHETIC", "revision_policy": "superseded by newer", "max_age_s": 1e9,
            "quality": "VALID"} for i in range(3)]
ms_old = ST.compose(symbol="SPY", t_d=T.T_D, bars=_b, underlyings=_u, chain=T._chain(), raw_quotes=old_q)
e2 = T._engine(n_paths=300, seed=11)
r_old = T._decide(e2, ms=ms_old, drift=0.0005)
elig = [c for c in r_old["trace"]["candidates"]["table"] if c["status"] == "ELIGIBLE"]
rec("F6_execution_quote_age", r_old["decision"] == "TRADE" and bool(elig),
    {"quote_age_s": 100.0, "execution_limit_s": 15.0, "decision": r_old["decision"], "eligible": len(elig)})

# 7 slice_skew ignores the frozen IV source
ident = ST.frozen_identity(symbol="SPY", t_d=T.T_D, spot=T.SPOT, chain=T._chain())
qq = {k: v for k, v in T._quotes().items()}
valid = {}
from apex.multiverse_wb.pricing import sanitize_quote
for k, v in qq.items():
    valid[(k[0], float(k[1]), k[2])] = {**sanitize_quote(v, now=T.T_D, max_age_s=120.0), "timestamp_epoch": v["timestamp_epoch"]}
del valid[(T.EXPIRY, 195.0, "CALL")]                      # K_- now has only a PUT while ATM used BOTH
bars, un = SW.bars_and_underlyings(t_d=T.T_D, spot=T.SPOT)
try:
    sk = ST.slice_skew(quotes=valid, identity=ident, underlyings=un, T_years=T._T(), iv_source="BOTH")
except TypeError:
    sk = ST.slice_skew(quotes=valid, identity=ident, underlyings=un, T_years=T._T())
rec("F7_skew_ignores_frozen_source", sk["x_sk"] is not None,
    {"atm_source": "BOTH", "k_minus_rights_used": "PUT only", "x_sk": sk["x_sk"], "expected": "IV_SOURCE_CHANGED / incomplete"})

# 8 truncated contract pin
rec("F8_truncated_pin", ms.get("contract_pin") == "902256e3",
    {"state_pin": ms.get("contract_pin"), "full": "902256e3c3c5025a450a4bb607410933bb0c4b25"})

# 9 seed depends on mutable self.decisions
e3 = T._engine(n_paths=200, seed=11)
a = T._decide(e3, ms=ms, drift=0.0005); b = T._decide(e3, ms=ms, drift=0.0005)
rec("F9_seed_from_mutable_counter", a["trace"]["underlying"]["seed"] != b["trace"]["underlying"]["seed"],
    {"seed_call1": a["trace"]["underlying"]["seed"], "seed_call2": b["trace"]["underlying"]["seed"],
     "source": "self.decisions increments per call"})

# 10 Brier uses P(sample > 0)
asrc = inspect.getsource(ATR.forecast_quality)
rec("F10_brier_wrong_quantity", "np.mean(np.asarray(r[\"samples\"][c]) > 0)" in asrc,
    {"used": "P(simulated exit bid > 0)", "required": "modelled availability under the path-accounting rule"})

# 11 attach accepts any truthy permission
e4 = ENG.JointEngine(n_paths=10)
try:
    info = e4.attach(T._fitted(), permission={"anything": True})
    rec("F11_attach_accepts_any_permission", info["status"] == "READY",
        {"permission_passed": {"anything": True}, "status": info["status"]})
except Exception as ex:
    rec("F11_attach_accepts_any_permission", False, {"permission_passed": {"anything": True}, "refused": str(ex)[:120]})

# 12 T11 conflict still open
try:
    SMP.pregenerate(sigma=np.zeros((4, 4)), n_paths=4, seed=1); conflict = False
except SMP.SamplerRefused as ex:
    conflict = "COVARIANCE_NOT_PD" in str(ex)
rec("F12_T11_conflict_open", False, {"resolved_by": "Amendment A1 (2026-09-11): T11a/T11b are declared-limit identities and T11c makes the "
     "COVARIANCE_NOT_PD / DEGENERATE_STATE refusals the contract's behaviour at the limit point", "refusal_still_fires": conflict})

print(json.dumps({"candidate": "1ffd217b314d8bae68d3ae6f486258b240d69187",
                  "contract_blob": "902256e3c3c5025a450a4bb607410933bb0c4b25",
                  "reproduced": sum(1 for v in F.values() if v["reproduced"]), "total": len(F), "findings": F}, indent=1, default=str))
