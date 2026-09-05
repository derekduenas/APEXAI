"""WM-0E-R5 development run: N0/N1/N2/N3-V1/N4 at E=1860, 100 paired seeds,
frozen court, explicit executed split. Contained.
Usage: wm0e_r5_develop.py <predeclaration_sha256> <out.json>"""
import json, sys, time, resource, statistics as st
import numpy as np
from apex.world_model import bootstrap as BS, controls_r3 as R3, controls_r4 as R4, controls_r5 as R5, teststand as TS
from apex.world_model.features import FEATURE_NAMES
from apex.world_model.grader import null_rule
from apex.world_model.inference import dm_hac_rule, non_overlap_rule, paired_differentials
from apex.world_model.models import NullBaseline

PRE_SHA, OUT = sys.argv[1], sys.argv[2]
ZI = FEATURE_NAMES.index("declared_observable_state")
q = lambda xs, k: float(np.quantile(xs, k))
def acf1(x):
    x = np.asarray(x, float); c = x - x.mean(); return float((c[1:] * c[:-1]).sum() / (c * c).sum()) if (c * c).sum() > 0 else 0.0
def runs_med(z):
    r, cur = [], 1
    for a, b in zip(z[:-1], z[1:]):
        if a == b: cur += 1
        else: r.append(cur); cur = 1
    r.append(cur); return float(st.median(r))

t0 = time.time(); cells = {c: [] for c in R5.R5_CONTROLS}; n3diag = []; per_ctl_time = {c: 0.0 for c in R5.R5_CONTROLS}
exec_split_hashes = set()
for i, s in enumerate(R5.R5_DEV_SEEDS):
    w = R4.r4_world(s); line = []
    for ctl in R5.R5_CONTROLS:
        tc = time.time()
        ds = R5.r5_dataset(ctl, s); model = R5.r5_model(ctl, s)
        m = TS.run_pipeline(w, model, dataset=ds, split=R4.R4_SPLIT, code_commit="R5_E1860")
        n = TS.run_pipeline(w, NullBaseline(), dataset=ds, split=R4.R4_SPLIT, code_commit="R5_E1860")
        es = m["executed_split"]; exec_split_hashes.add(es["executed_split_hash"])
        assert es["boundary"] == 720 and es["training_count"] == 701 and m["run"].training_configuration["executed_split"]["executed_split_hash"] == es["executed_split_hash"]
        assert m["n_eval"] == R5.EXPECTED_USABLE[ctl] and m["n_train"] == R5.EXPECTED_TRAIN[ctl], (ctl, m["n_eval"], m["n_train"])
        d = np.array(paired_differentials(m["grades"], n["grades"]))
        b = BS.bootstrap_test(d.tolist(), court_id=R5.COURT_ID, control=ctl, seed=s)
        h = dm_hac_rule(m["grades"], n["grades"]); nov = non_overlap_rule(m["grades"], n["grades"]); z = null_rule(m["grades"], n["grades"])
        cell = {"seed": s, "control": ctl, "verdict": b["verdict"], "p": b["p_bootstrap"], "t_obs": b["t_obs"],
                "block_length": b["block"]["block_length"], "t_star_q975": b["t_star_q"]["q975"],
                "mean_d": float(d.mean()), "sd_d": float(d.std(ddof=1)), "acf1_d": acf1(d), "acf5_d": float(np.corrcoef(d[5:], d[:-5])[0, 1]),
                "n_eval": int(len(d)), "eval_over_block": len(d) / b["block"]["block_length"],
                "hac_t": h["t"], "hac_verdict": h["verdict"], "nonoverlap_z": nov["z"], "nonoverlap_verdict": nov["verdict"],
                "legacy_iid_z": z["z"], "executed_split_hash": es["executed_split_hash"]}
        cells[ctl].append(cell); per_ctl_time[ctl] += time.time() - tc
        line.append("%s:%s p=%.3f t=%+.2f bl=%d" % (ctl[:5], "DET" if cell["verdict"] == "SIGNAL_DETECTED" else "no ", cell["p"], cell["t_obs"], cell["block_length"]))
        if ctl == "N3_SHADOW_V1":
            Xtr_t, _, Xev_t, _, *_ = TS.default_dataset(w, "SYN_A", R4.R4_SPLIT)
            Xtr_s, _, Xev_s, _, *_ = ds(w, "SYN_A", R4.R4_SPLIT)
            zt = [x[ZI] for x in Xtr_t + Xev_t]; zs = [x[ZI] for x in Xtr_s + Xev_s]
            n3diag.append({"seed": s, "acf1_z_target": acf1(zt), "acf1_z_shadow": acf1(zs),
                           "acf1_ret1_target": acf1([x[0] for x in Xtr_t + Xev_t]), "acf1_ret1_shadow": acf1([x[0] for x in Xtr_s + Xev_s]),
                           "run_med_target": runs_med(zt), "run_med_shadow": runs_med(zs),
                           "corr_z": float(np.corrcoef(zt, zs)[0, 1]),
                           "shift_target": abs(st.mean(x[ZI] for x in Xev_t) - st.mean(x[ZI] for x in Xtr_t)),
                           "shift_shadow": abs(st.mean(x[ZI] for x in Xev_s) - st.mean(x[ZI] for x in Xtr_s))})
    print("seed %3d/100 %10d | " % (i + 1, s) + " | ".join(line), flush=True)

summary = {}
for ctl in R5.R5_CONTROLS:
    cs = cells[ctl]; n = len(cs); det = sum(1 for c in cs if c["verdict"] == "SIGNAL_DETECTED")
    ps = [c["p"] for c in cs]; ts = [c["t_obs"] for c in cs]; bl = [c["block_length"] for c in cs]
    summary[ctl] = {"n": n, "false_detections": det, "rate": det / n, "max_allowed": R5.R5_MAX_FP,
                    "verdict": "PASS" if det <= R5.R5_MAX_FP else "FAIL",
                    "p": {"min": min(ps), "q10": q(ps, .1), "med": q(ps, .5), "q90": q(ps, .9), "max": max(ps),
                          "frac_le_025": float(np.mean(np.array(ps) <= 0.025)), "frac_le_05": float(np.mean(np.array(ps) <= 0.05)), "frac_le_10": float(np.mean(np.array(ps) <= 0.10))},
                    "t_obs": {"min": min(ts), "q10": q(ts, .1), "med": q(ts, .5), "q90": q(ts, .9), "max": max(ts), "abs_gt_2.5": sum(1 for t in ts if abs(t) > 2.5)},
                    "block_length": {"min": min(bl), "q25": q(bl, .25), "med": q(bl, .5), "q75": q(bl, .75), "max": max(bl)},
                    "eval_over_block_med": q([c["eval_over_block"] for c in cs], .5), "n_eval": cs[0]["n_eval"],
                    "acf1_d_med": q([c["acf1_d"] for c in cs], .5), "acf5_d_med": q([c["acf5_d"] for c in cs], .5),
                    "t_star_q975_med": q([c["t_star_q975"] for c in cs], .5),
                    "hac_secondary_detections": sum(1 for c in cs if c["hac_verdict"] == "SIGNAL_DETECTED"),
                    "nonoverlap_secondary_detections": sum(1 for c in cs if c["nonoverlap_verdict"] == "SIGNAL_DETECTED"),
                    "legacy_iid_z_med": q([c["legacy_iid_z"] for c in cs], .5),
                    "elapsed_s": round(per_ctl_time[ctl], 1)}
    print("%-13s det %2d/100 %s | p min/med %.4f/%.3f frac<=.025 %.2f | t min/med/max %+.2f/%+.2f/%+.2f | bl med %d eval/bl %.1f | acf1(d) %.2f | HAC %d NOV %d | %.0fs" % (
        ctl, det, summary[ctl]["verdict"], min(ps), q(ps, .5), summary[ctl]["p"]["frac_le_025"], min(ts), q(ts, .5), max(ts), q(bl, .5), summary[ctl]["eval_over_block_med"], summary[ctl]["acf1_d_med"], summary[ctl]["hac_secondary_detections"], summary[ctl]["nonoverlap_secondary_detections"], per_ctl_time[ctl]), flush=True)
det_seeds = {ctl: {c["seed"] for c in cells[ctl] if c["verdict"] == "SIGNAL_DETECTED"} for ctl in R5.R5_CONTROLS}
all_det = sum(len(v) for v in det_seeds.values())
overlap = {"%s&%s" % (a, b): len(det_seeds[a] & det_seeds[b]) for i, a in enumerate(R5.R5_CONTROLS) for b in R5.R5_CONTROLS[i + 1:] if det_seeds[a] & det_seeds[b]}
n3s = {k: {"med": q([d[k] for d in n3diag], .5), "min": min(d[k] for d in n3diag), "max": max(d[k] for d in n3diag)} for k in n3diag[0] if k != "seed"}
out = {"version": R5.R5_VERSION, "predeclaration_sha256": PRE_SHA, "predeclaration_hash": R5.predeclaration_hash(),
       "bootstrap_contract_hash": BS.content_identity(), "geometry": R5.predeclaration()["geometry"],
       "executed_split_hashes_seen": sorted(exec_split_hashes), "controls": summary, "cells": cells,
       "N3_V1_target_vs_shadow": n3s,
       "pooled_descriptive": {"total_detections": all_det, "of": 500, "pooled_rate": all_det / 500,
                              "per_control_rates": {c: summary[c]["rate"] for c in R5.R5_CONTROLS},
                              "cross_control_overlap_by_seed": overlap, "note": "controls share seeds; not independent; no rescue"},
       "ALL_NEGATIVE_CONTROLS_E1860": "PASS" if all(summary[c]["verdict"] == "PASS" for c in R5.R5_CONTROLS) else "FAIL",
       "elapsed_s": round(time.time() - t0, 1),
       "resource_truth": {"ru_maxrss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                          "cgroup": open("/proc/self/cgroup").read().strip(), "cells": 500, "per_control_elapsed_s": {c: round(per_ctl_time[c], 1) for c in R5.R5_CONTROLS}}}
json.dump(out, open(OUT, "w"), indent=1, default=str)
print("executed split hashes seen:", len(exec_split_hashes), "| pooled %d/500 | overlap %s" % (all_det, overlap))
print("R5_VERDICT:", out["ALL_NEGATIVE_CONTROLS_E1860"], "elapsed %.0fs rss %.0fMiB" % (out["elapsed_s"], out["resource_truth"]["ru_maxrss_MiB"]))
