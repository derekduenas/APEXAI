"""WM-0E-R3 development run. Contained. Frozen engine. No acceptance seeds.
Usage: wm0e_r3_develop.py <predeclaration_sha256> <out.json>"""
import json, math, sys, time, resource, statistics as st
import numpy as np
from apex.world_model import bootstrap as BS, controls_r3 as R3, teststand as TS
from apex.world_model.court import _world
from apex.world_model.features import FEATURE_NAMES
from apex.world_model.grader import null_rule
from apex.world_model.inference import dm_hac_rule, paired_differentials
from apex.world_model.models import M0SyntheticBaseline, NullBaseline
from apex.world_model.runs import ChronologicalSplit

PRE_SHA, OUT = sys.argv[1], sys.argv[2]
assert R3.predeclaration_hash() and PRE_SHA, "predeclaration required"
ZI = FEATURE_NAMES.index("declared_observable_state")
t0 = time.time()

def wilson_low(k, n, z=1.96):
    p = k / n; den = 1 + z * z / n
    return (p + z * z / (2 * n)) / den - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den

def acf1(x):
    x = np.asarray(x, float); c = x - x.mean()
    return float((c[1:] * c[:-1]).sum() / (c * c).sum()) if (c * c).sum() > 0 else 0.0

def runs_median(z):
    runs, cur = [], 1
    for a, b in zip(z[:-1], z[1:]):
        if a == b: cur += 1
        else: runs.append(cur); cur = 1
    runs.append(cur); return float(st.median(runs))

def cell(world, dataset, court_id, control, seed):
    m = TS.run_pipeline(world, M0SyntheticBaseline(), dataset=dataset, code_commit=court_id)
    n = TS.run_pipeline(world, NullBaseline(), dataset=dataset, code_commit=court_id)
    d = paired_differentials(m["grades"], n["grades"])
    b = BS.bootstrap_test(d, court_id=court_id, control=control, seed=seed)
    h = dm_hac_rule(m["grades"], n["grades"]); z = null_rule(m["grades"], n["grades"])
    return {"seed": seed, "verdict": b["verdict"], "p": b["p_bootstrap"], "t_obs": b["t_obs"],
            "block_length": b["block"]["block_length"], "mean_gain": b["mean_loglik_gain"],
            "n_eval": b["n"], "hac_t": h["t"], "legacy_iid_z": z["z"]}

out = {"version": R3.R3_VERSION, "predeclaration_sha256": PRE_SHA,
       "predeclaration_hash": R3.predeclaration_hash(),
       "bootstrap_contract_hash": BS.content_identity()}

# ---------------- N3 V1 development calibration (100 cells)
cells, diag = [], []
for s in R3.N3_DEV_SEEDS:
    w = _world(s); sh = R3.shadow_world(w)
    T = w.config.n_steps; split = ChronologicalSplit(n_steps=T, boundary=int(T * TS.FIXED_BOUNDARY_FRACTION))
    c = cell(w, R3.n3_v1_dataset(s), "N3_V1_DEV", "N3_V1", s); c["identity"] = R3.n3_v1_identity(w)[:16]
    Xtr_t, ytr, Xev_t, yev, *_ = TS.default_dataset(w, "SYN_A", split)
    Xtr_s, _, Xev_s, _, *_ = R3.n3_v1_dataset(s)(w, "SYN_A", split)
    zt = [x[ZI] for x in Xtr_t + Xev_t]; zs = [x[ZI] for x in Xtr_s + Xev_s]
    rt = [x[0] for x in Xtr_t + Xev_t]; rs = [x[0] for x in Xtr_s + Xev_s]
    diag.append({"seed": s, "shadow_seed": sh.config.seed,
                 "acf1_z_target": acf1(zt), "acf1_z_shadow": acf1(zs),
                 "acf1_ret1_target": acf1(rt), "acf1_ret1_shadow": acf1(rs),
                 "run_median_z_target": runs_median(zt), "run_median_z_shadow": runs_median(zs),
                 "corr_z_target_shadow": float(np.corrcoef(zt, zs)[0, 1]),
                 "shadow_eval_marginal_shift_z": abs(st.mean(x[ZI] for x in Xev_s) - st.mean(x[ZI] for x in Xtr_s)),
                 "target_eval_marginal_shift_z": abs(st.mean(x[ZI] for x in Xev_t) - st.mean(x[ZI] for x in Xtr_t))})
    cells.append(c)
    print("N3V1 %3d/100 seed %10d p=%.4f t=%+.2f bl=%d %s" % (len(cells), s, c["p"], c["t_obs"], c["block_length"], c["verdict"]), flush=True)
det = sum(1 for c in cells if c["verdict"] == "SIGNAL_DETECTED")
ps = [c["p"] for c in cells]; ts = [c["t_obs"] for c in cells]; bl = [c["block_length"] for c in cells]
q = lambda xs, k: float(np.quantile(xs, k))
out["N3_V1"] = {"cells": cells, "diagnostics": diag, "n": len(cells), "detections": det,
                "detection_rate": det / len(cells), "max_allowed": R3.N3_V1_DEV_MAX_FP,
                "control_validity": "PASS" if det <= R3.N3_V1_DEV_MAX_FP else "FAIL",
                "p_quantiles": {"q05": q(ps, .05), "q25": q(ps, .25), "q50": q(ps, .5), "q75": q(ps, .75)},
                "t_obs": {"min": min(ts), "q10": q(ts, .1), "med": q(ts, .5), "q90": q(ts, .9), "max": max(ts),
                          "abs_gt_2.5": sum(1 for t in ts if abs(t) > 2.5)},
                "block_length": {"min": min(bl), "med": q(bl, .5), "max": max(bl)},
                "hac_detections": sum(1 for c in cells if c["hac_t"] > 2.0 and c["mean_gain"] > 0),
                "diag_summary": {k: {"med": q([d[k] for d in diag], .5), "min": min(d[k] for d in diag), "max": max(d[k] for d in diag)}
                                 for k in diag[0] if k not in ("seed", "shadow_seed")}}
print("N3_V1 detections %d/100 -> %s" % (det, out["N3_V1"]["control_validity"]), flush=True)

# ---------------- P0 power ladder (predeclared; every level inspected and recorded)
ladder = {}
for mult in R3.P0_POWER_LADDER:
    cs = []
    for s in R3.P0_DEV_SEEDS:
        w = R3.p0_world(s, mult)
        cs.append(cell(w, TS.default_dataset, "P0_V1_DEV_%.2f" % mult, "P0_V1", s))
    d = sum(1 for c in cs if c["verdict"] == "SIGNAL_DETECTED"); pos = sum(1 for c in cs if c["mean_gain"] > 0)
    n = len(cs); ps = [c["p"] for c in cs]; ts = [c["t_obs"] for c in cs]
    ladder[str(mult)] = {"multiplier": mult, "mu": R3.P0_BASE_MU * mult, "cells": cs, "n": n,
                         "detections": d, "detection_rate": d / n, "wilson95_lower": wilson_low(d, n),
                         "positive_direction": pos, "direction_rate": pos / n,
                         "p_quantiles": {"q25": q(ps, .25), "q50": q(ps, .5), "q75": q(ps, .75)},
                         "t_obs": {"min": min(ts), "q10": q(ts, .1), "med": q(ts, .5), "q90": q(ts, .9), "max": max(ts)},
                         "block_length_med": q([c["block_length"] for c in cs], .5)}
    print("P0 ladder x%.2f: det %d/%d rate %.2f wilson_low %.3f dir %.2f t_med %+.2f" % (
        mult, d, n, d / n, wilson_low(d, n), pos / n, q(ts, .5)), flush=True)
sel = R3.P0_V1_SELECTION; chosen = None
for mult in R3.P0_POWER_LADDER:                       # smallest first
    L = ladder[str(mult)]
    if (L["detection_rate"] >= sel["min_detection_rate"] and L["wilson95_lower"] >= sel["min_wilson95_lower"]
            and L["direction_rate"] >= sel["min_direction_rate"]):
        chosen = mult; break
out["P0_V1"] = {"ladder": ladder, "levels_inspected": list(R3.P0_POWER_LADDER), "selection_rule": sel,
                "selected_multiplier": chosen, "selected_mu": (R3.P0_BASE_MU * chosen) if chosen else None,
                "power_validity": "PASS" if chosen is not None else "FAIL",
                "identity": "P0_CAUSAL_TREND_POWERED_V1" if chosen else None,
                "future_acceptance": R3.P0_V1_FUTURE_ACCEPTANCE}
print("P0_V1 selected:", chosen, "->", out["P0_V1"]["power_validity"], flush=True)
out["elapsed_s"] = round(time.time() - t0, 1)
out["resource_truth"] = {"ru_maxrss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                         "cgroup": open("/proc/self/cgroup").read().strip(), "cells": 100 + 4 * 50}
out["R3_VERDICT"] = "PASS" if (out["N3_V1"]["control_validity"] == "PASS" and out["P0_V1"]["power_validity"] == "PASS") else "FAIL"
json.dump(out, open(OUT, "w"), indent=1, default=str)
print("R3_VERDICT:", out["R3_VERDICT"], "elapsed %.0fs" % out["elapsed_s"])
