"""Reproducers for the decision-path review of b9998d02 (six findings). Run BEFORE and AFTER the repair:

    .venv/bin/python scripts/decision_path_probes.py > docs/evidence/decision_path_reproductions.json   # before
    .venv/bin/python scripts/decision_path_probes.py > docs/evidence/decision_path_after.json           # after

Each probe records `reproduced` (True = the defect is present) and the detail that shows it. Synthetic inputs only."""
import json
import math
import subprocess
import sys

sys.path.insert(0, ".")
import numpy as np  # noqa: E402

from apex.decision_wb import supervision as SV  # noqa: E402
from apex.joint_wb import engine as ENG  # noqa: E402
from apex.options_pilot import expression_rule as ER  # noqa: E402
from apex.pulse_options import sources as SRC  # noqa: E402

OUT = {"review_base": "b9998d02b7c3dc8030e753277fd5fbd1bba9ff8f",
       "head": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(), "findings": {}}


def rec(k, reproduced, detail):
    OUT["findings"][k] = {"reproduced": bool(reproduced), "detail": detail}


# ---------------------------------------------------------------- F1 policy identity
try:
    import re
    cli = open("scripts/options_paper_session.py").read()
    m = re.search(r'--pilot-selection-policy", default="([A-Z0-9_]+)", choices=\(([^)]*)\)', cli)
    cli_default, cli_choices = m.group(1), m.group(2)
    session_default = ER.DEFAULT_RULE
    rec("F1_policy_identity", cli_default != session_default or "PILOT_RULE_V2" not in cli_choices,
        {"cli_default": cli_default, "cli_choices": cli_choices, "session_default_rule": session_default,
         "SELECTION_POLICIES": list(SRC.SELECTION_POLICIES)})
except Exception as ex:                                                  # noqa: BLE001
    rec("F1_policy_identity", True, {"error": str(ex)[:200]})

# ---------------------------------------------------------------- F2 normalization + selector
rows_raw = [{"symbol": "SPY", "expiration": "20261002", "strike": "773.000", "right": "", "timestamp": "2026-09-11 10:53:23",
             "bid": "4.59", "ask": "4.63", "bid_size": "1.7", "ask_size": "True"},
            {"symbol": "SPY", "expiration": "20261002", "strike": "774.000", "right": "C", "timestamp": "2026-09-11 10:53:23",
             "bid": "inf", "ask": "inf", "bid_size": "5", "ask_size": "5"}]
try:
    norm = SRC.live_chain_rows(rows_raw, symbol="SPY", receipt_time=1.0)
    d = {"right_of_empty": norm[0]["right"] if norm else None, "bid_size_of_1.7": norm[0]["bid_size"] if norm else None,
         "ask_size_of_True": norm[0]["ask_size"] if norm else None, "ask_of_inf": (norm[1]["ask"] if len(norm) > 1 else None),
         "n_rows_kept": len(norm)}
    rec("F2a_unknown_right_becomes_put", bool(norm) and norm[0]["right"] == "PUT", d)
    rec("F2b_fractional_or_bool_sizes_coerced", bool(norm) and norm[0]["bid_size"] == 1, d)
    rec("F2c_infinity_survives", len(norm) > 1 and norm[1]["ask"] is not None and math.isinf(norm[1]["ask"]), d)
except Exception as ex:                                                  # noqa: BLE001
    rec("F2a_unknown_right_becomes_put", False, {"refused": str(ex)[:160]})
    rec("F2b_fractional_or_bool_sizes_coerced", False, {"refused": str(ex)[:160]})
    rec("F2c_infinity_survives", False, {"refused": str(ex)[:160]})
SPOT, AS_OF = 763.94, "2026-09-11T14:53:23Z"


def _avail(extra):
    base = [{"expiration": "2026-10-02", "strike": 780.0, "right": "CALL", "ask": 3.0, "bid": 2.9, "bid_size": 5, "ask_size": 5, "timestamp_epoch": 1.0}]
    return base + extra


for name, extra in (("zero_ask", [{"expiration": "2026-10-02", "strike": 770.0, "right": "CALL", "ask": 0.0, "bid": 0.0, "bid_size": 1, "ask_size": 1, "timestamp_epoch": 1.0}]),
                    ("negative_ask", [{"expiration": "2026-10-02", "strike": 770.0, "right": "CALL", "ask": -1.0, "bid": -1.5, "bid_size": 1, "ask_size": 1, "timestamp_epoch": 1.0}]),
                    ("inf_ask", [{"expiration": "2026-10-02", "strike": 770.0, "right": "CALL", "ask": float("-inf"), "bid": 0.1, "bid_size": 1, "ask_size": 1, "timestamp_epoch": 1.0}])):
    try:
        v = ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=_avail(extra), max_entry_price=5.0, **({"as_of_epoch": 2.0} if "as_of_epoch" in ER.choose.__code__.co_varnames else {}))
        rec("F2d_%s_enters_v2" % name, v["contract"]["strike"] == 770.0, {"chosen": v["contract"]["strike"], "reference_ask": v["reference_ask"]})
    except ER.RuleRefused as ex:
        rec("F2d_%s_enters_v2" % name, False, {"refused": str(ex)[:120]})
dup_a = [{"expiration": "2026-10-02", "strike": 770.0, "right": "CALL", "ask": 4.0, "bid": 3.9, "bid_size": 5, "ask_size": 5, "timestamp_epoch": 1.0},
         {"expiration": "2026-10-02", "strike": 770.0, "right": "CALL", "ask": 9.0, "bid": 8.9, "bid_size": 5, "ask_size": 5, "timestamp_epoch": 1.0}]
try:
    kw = {"as_of_epoch": 2.0} if "as_of_epoch" in ER.choose.__code__.co_varnames else {}
    a = ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=_avail(dup_a), max_entry_price=5.0, **kw)
    b = ER.choose(symbol="SPY", direction_signal="LONG", spot=SPOT, as_of=AS_OF, available=_avail(list(reversed(dup_a))), max_entry_price=5.0, **kw)
    rec("F2e_duplicate_order_dependence", a["contract"]["strike"] != b["contract"]["strike"] or a["reference_ask"] != b["reference_ask"],
        {"forward": (a["contract"]["strike"], a["reference_ask"]), "reversed": (b["contract"]["strike"], b["reference_ask"])})
except ER.RuleRefused as ex:
    rec("F2e_duplicate_order_dependence", False, {"refused": str(ex)[:120]})

# ---------------------------------------------------------------- F3 spread bypass
import tests.test_joint_wb as T  # noqa: E402
e = T._engine(n_paths=300, seed=11)
r = T._decide(e, ms=T._state(), drift=0.0005)
p5 = r["trace"]["decision_rule"]["rules"].get("5") or {}
src_sv = open("apex/decision_wb/supervision.py").read()
rec("F3_prime_spread_bypassed", '(cand.get("entry_spread_rel") or 0)' in src_sv or '"entry_spread_rel": None' in open("apex/joint_wb/engine.py").read(),
    {"engine_passes_None": '"entry_spread_rel": None' in open("apex/joint_wb/engine.py").read(),
     "supervision_treats_missing_as_zero": '(cand.get("entry_spread_rel") or 0)' in src_sv, "prime_decision": p5.get("decision")})

# ---------------------------------------------------------------- F4 adverse IV direction
src_e = open("apex/joint_wb/engine.py").read()
rec("F4_put_iv_stress_is_favorable", 'shift = -se_iv if right == "CALL" else +se_iv' in src_e,
    {"mapping_in_source": 'shift = -se_iv if right == "CALL" else +se_iv' in src_e})

# ---------------------------------------------------------------- F5 premature 15 s ranking exclusion
import tests.test_joint_wb_repairs as TR  # noqa: E402
st = TR.TestF6ExecutionFreshness()._state_with_age(30.0)
r30 = T._decide(T._engine(n_paths=200, seed=11), ms=st, drift=0.0005, scan_id="F5")
rec("F5_30s_indicative_quote_excluded_from_ranking", r30["trace"]["candidates"]["n_eligible"] == 0,
    {"n_eligible": r30["trace"]["candidates"]["n_eligible"], "census": r30["trace"]["candidates"]["census"], "decision": r30["decision"]})

# ---------------------------------------------------------------- F6 BEFORE-record timing gap
spec = open("docs/SEAL_SPEC_OBSERVATION_ONE.md").read()
rec("F6_toll_formula_references_fill_quote_at_intent_time", "ask_fill" in spec.split("## 3.")[0] and "not a field" in spec,
    {"intent_time_formula_uses_fill": "ask_fill" in spec.split("## 3.")[0], "expected_toll_is_a_field": "not a field" not in spec})

print(json.dumps(OUT, indent=1, default=str))
