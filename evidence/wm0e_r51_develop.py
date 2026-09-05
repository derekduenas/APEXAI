"""WM-0E-R5.1 development run: N0_SHADOW_TARGET_NULL_V1 and
N1_TIME_DESTRUCTION_E1860_V1, 100 shared dev seeds, frozen court. Contained.
Usage: wm0e_r51_develop.py <predeclaration_sha256> <out.json>"""
import json, sys, time, resource, statistics as st
import numpy as np
from apex.world_model import bootstrap as BS, controls_r4 as R4, controls_r51 as R, teststand as TS
from apex.world_model.features import FEATURE_NAMES
from apex.world_model.grader import null_rule
from apex.world_model.inference import dm_hac_rule, non_overlap_rule, paired_differentials
from apex.world_model.models import M0SyntheticBaseline, NullBaseline

PRE_SHA, OUT = sys.argv[1], sys.argv[2]
ZI = FEATURE_NAMES.index("declared_observable_state")
q = lambda xs, k: float(np.quantile(xs, k))
def acf(x, k=1):
    x = np.asarray(x, float); c = x - x.mean(); return float((c[k:] * c[:-k]).sum() / (c * c).sum()) if (c * c).sum() > 0 else 0.0
def runs_med(z):
    r, cur = [], 1
    for a, b in zip(z[:-1], z[1:]):
        if a == b: cur += 1
        else: r.append(cur); cur = 1
    r.append(cur); return float(st.median(r))

def cell(world, ds, split, ctl, seed, expect_eval, expect_train):
    m = TS.run_pipeline(world, M0SyntheticBaseline(), dataset=ds, split=split, code_commit="R51")
    n = TS.run_pipeline(world, NullBaseline(), dataset=ds, split=split, code_commit="R51")
    es = m["executed_split"]
    if m["n_eval"] != expect_eval or m["n_train"] != expect_train or es["boundary"] != 720:
        return {"seed": seed, "control": ctl, "verdict": "RUN_INVALID",
                "error": "geometry n_eval=%d n_train=%d boundary=%d" % (m["n_eval"], m["n_train"], es["boundary"])}
    d = np.array(paired_differentials(m["grades"], n["grades"]))
    b = BS.bootstrap_test(d.tolist(), court_id=R.COURT_ID, control=ctl, seed=seed)
    h = dm_hac_rule(m["grades"], n["grades"]); nov = non_overlap_rule(m["grades"], n["grades"]); z = null_rule(m["grades"], n["grades"])
    return {"seed": seed, "control": ctl, "verdict": b["verdict"], "p": b["p_bootstrap"], "t_obs": b["t_obs"],
            "block_length": b["block"]["block_length"], "t_star_q975": b["t_star_q"]["q975"],
            "mean_d": float(d.mean()), "sd_d": float(d.std(ddof=1)), "acf1_d": acf(d, 1), "acf5_d": acf(d, 5),
            "n_eval": int(len(d)), "n_train": m["n_train"], "eval_over_block": len(d) / b["block"]["block_length"],
            "hac_t": h["t"], "hac_verdict": h["verdict"], "nonoverlap_z": nov["z"], "nonoverlap_verdict": nov["verdict"],
            "legacy_iid_z": z["z"], "executed_split_hash": es["executed_split_hash"], "usable_evaluation_count": es["usable_evaluation_count"]}

t0 = time.time(); cells = {"N0_V1": [], "N1_E1860": []}; n0diag = []; tm = {"N0_V1": 0.0, "N1_E1860": 0.0}
for i, s in enumerate(R.DEV_SEEDS):
    tc = time.time()
    wa = R4.r4_world(s); wb = R.target_world(wa)
    c0 = cell(wa, R.n0_v1_dataset(s), R4.R4_SPLIT, "N0_V1", s, R.E, 701); c0["identity"] = R.n0_v1_identity(wa)[:16]
    c0["feature_world_hash"] = wa.world_hash[:16]; c0["target_world_hash"] = wb.world_hash[:16]; c0["target_seed"] = wb.config.seed
    cells["N0_V1"].append(c0); tm["N0_V1"] += time.time() - tc
    Xtr_a, _, Xev_a, _, *_ = TS.default_dataset(wa, "SYN_A", R4.R4_SPLIT)
    Xtr_b, ytr_b, Xev_b, yev_b, *_ = TS.default_dataset(wb, "SYN_A", R4.R4_SPLIT)
    za = [x[ZI] for x in Xtr_a + Xev_a]; zb = [x[ZI] for x in Xtr_b + Xev_b]
    n0diag.append({"seed": s, "acf1_z_A": acf(za), "acf1_z_B": acf(zb), "run_med_A": runs_med(za), "run_med_B": runs_med(zb),
                   "corr_z_AB": float(np.corrcoef(za, zb)[0, 1]),
                   "shift_z_A": abs(st.mean(x[ZI] for x in Xev_a) - st.mean(x[ZI] for x in Xtr_a)),
                   "shift_z_B": abs(st.mean(x[ZI] for x in Xev_b) - st.mean(x[ZI] for x in Xtr_b)),
                   "shift_y_B_sd": abs(st.mean(yev_b) - st.mean(ytr_b)) / st.pstdev(ytr_b),
                   "acf1_y_B": acf(ytr_b + yev_b)})
    tc = time.time()
    w1 = R.n1_world(s)
    c1 = cell(w1, R.n1_e1860_dataset(s), R.N1_SPLIT, "N1_E1860", s, R.E, R.N1_EXPECTED_TRAIN)
    cells["N1_E1860"].append(c1); tm["N1_E1860"] += time.time() - tc
    f = lambda c: "INVALID" if c["verdict"] == "RUN_INVALID" else "%s p=%.3f t=%+.2f bl=%d n=%d" % ("DET" if c["verdict"] == "SIGNAL_DETECTED" else "no ", c["p"], c["t_obs"], c["block_length"], c["n_eval"])
    print("seed %3d/100 %10d | N0V1 %s | N1E1860 %s" % (i + 1, s, f(c0), f(c1)), flush=True)

summary = {}
for ctl, cs in cells.items():
    inv = [c for c in cs if c["verdict"] == "RUN_INVALID"]; valid = [c for c in cs if c["verdict"] != "RUN_INVALID"]
    det = sum(1 for c in valid if c["verdict"] == "SIGNAL_DETECTED")
    ps = [c["p"] for c in valid]; ts = [c["t_obs"] for c in valid]; bl = [c["block_length"] for c in valid]
    summary[ctl] = {"n": len(cs), "run_invalid": len(inv), "false_detections": det, "rate": det / max(1, len(valid)), "max_allowed": R.MAX_FP,
                    "verdict": "INVALID" if inv else ("PASS" if det <= R.MAX_FP else "FAIL"),
                    "usable_evaluation_counts": sorted({c["n_eval"] for c in valid}), "n_train": sorted({c["n_train"] for c in valid}),
                    "executed_split_hashes": sorted({c["executed_split_hash"] for c in valid}),
                    "p": {"min": min(ps), "q10": q(ps, .1), "med": q(ps, .5), "q90": q(ps, .9), "max": max(ps),
                          "frac_le_025": float(np.mean(np.array(ps) <= .025)), "frac_le_05": float(np.mean(np.array(ps) <= .05)), "frac_le_10": float(np.mean(np.array(ps) <= .10))},
                    "t_obs": {"min": min(ts), "q10": q(ts, .1), "med": q(ts, .5), "q90": q(ts, .9), "max": max(ts), "abs_gt_2.5": sum(1 for t in ts if abs(t) > 2.5), "pos_gt_2.5": sum(1 for t in ts if t > 2.5)},
                    "block_length": {"min": min(bl), "q25": q(bl, .25), "med": q(bl, .5), "q75": q(bl, .75), "max": max(bl)},
                    "eval_over_block_med": q([c["eval_over_block"] for c in valid], .5),
                    "acf1_d_med": q([c["acf1_d"] for c in valid], .5), "acf5_d_med": q([c["acf5_d"] for c in valid], .5),
                    "t_star_q975_med": q([c["t_star_q975"] for c in valid], .5),
                    "hac_secondary_detections": sum(1 for c in valid if c["hac_verdict"] == "SIGNAL_DETECTED"),
                    "nonoverlap_secondary_detections": sum(1 for c in valid if c["nonoverlap_verdict"] == "SIGNAL_DETECTED"),
                    "legacy_iid_z_med": q([c["legacy_iid_z"] for c in valid], .5), "elapsed_s": round(tm[ctl], 1)}
    print("%-9s det %2d/%d %s invalid %d | usable %s train %s | p min/med %.4f/%.3f frac<=.025 %.2f | t min/med/max %+.2f/%+.2f/%+.2f pos>2.5 %d | bl med %d eval/bl %.1f acf1 %.2f | HAC %d NOV %d | %.0fs" % (
        ctl, det, len(valid), summary[ctl]["verdict"], len(inv), summary[ctl]["usable_evaluation_counts"], summary[ctl]["n_train"], min(ps), q(ps, .5), summary[ctl]["p"]["frac_le_025"], min(ts), q(ts, .5), max(ts), summary[ctl]["t_obs"]["pos_gt_2.5"], q(bl, .5), summary[ctl]["eval_over_block_med"], summary[ctl]["acf1_d_med"], summary[ctl]["hac_secondary_detections"], summary[ctl]["nonoverlap_secondary_detections"], tm[ctl]), flush=True)
n0s = {k: {"med": q([d[k] for d in n0diag], .5), "min": min(d[k] for d in n0diag), "max": max(d[k] for d in n0diag)} for k in n0diag[0] if k != "seed"}
out = {"version": R.R51_VERSION, "predeclaration_sha256": PRE_SHA, "predeclaration_hash": R.predeclaration_hash(),
       "bootstrap_contract_hash": BS.content_identity(), "controls": summary, "cells": cells, "N0_V1_feature_vs_target_world": n0s,
       "N1_FINAL_USABLE_EVALUATION": summary["N1_E1860"]["usable_evaluation_counts"], "N0_V1_FINAL_USABLE_EVALUATION": summary["N0_V1"]["usable_evaluation_counts"],
       "R51_VERDICT": "PASS" if all(summary[c]["verdict"] == "PASS" for c in summary) else "FAIL",
       "elapsed_s": round(time.time() - t0, 1),
       "resource_truth": {"ru_maxrss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), "cgroup": open("/proc/self/cgroup").read().strip(), "cells": 200, "per_control_elapsed_s": {c: round(tm[c], 1) for c in tm}}}
json.dump(out, open(OUT, "w"), indent=1, default=str)
print("N0V1 A-vs-B:", {k: round(v["med"], 3) for k, v in n0s.items()})
print("R51_VERDICT:", out["R51_VERDICT"], "elapsed %.0fs rss %.0fMiB" % (out["elapsed_s"], out["resource_truth"]["ru_maxrss_MiB"]))
