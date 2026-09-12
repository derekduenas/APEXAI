"""WM-0E-R4 development run. Contained. Frozen engine, frozen M0, original mu.
Per seed: one T_MAX world, M0 fit ONCE, forecasts over the whole path, four
nested prefixes graded. Selection applied only after ALL levels ran.
Usage: wm0e_r4_develop.py <predeclaration_sha256> <out.json>"""
import json, math, sys, time, resource, statistics as st
import numpy as np
from apex.world_model import bootstrap as BS, controls_r4 as R4, teststand as TS
from apex.world_model.canonical import content_hash
from apex.world_model.inference import dm_hac_rule, paired_differentials, hac_long_run_variance
from apex.world_model.models import M0SyntheticBaseline, NullBaseline

PRE_SHA, OUT = sys.argv[1], sys.argv[2]
t0 = time.time()
def wilson_low(k, n, z=1.96):
    p = k / n; den = 1 + z * z / n
    return (p + z * z / (2 * n)) / den - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
q = lambda xs, k: float(np.quantile(xs, k))

levels = {L: [] for L in R4.EVAL_LADDER}
seed_records = []
prefix_identity_ok = training_identity_ok = True
for i, s in enumerate(R4.DEV_SEEDS):
    w = R4.r4_world(s)
    m0 = M0SyntheticBaseline(); nl = NullBaseline()
    m = TS.run_pipeline(w, m0, dataset=R4.r4_dataset, code_commit="R4_DEV")
    n = TS.run_pipeline(w, nl, dataset=R4.r4_dataset, code_commit="R4_DEV")
    Xtr, ytr, Xev, yev, iev, _ = R4.r4_dataset(w, "SYN_A", None)
    th = R4.training_hash(Xtr, ytr); beta_h = content_hash(list(m0._beta)); sig = m0._sigma
    scaler_h = content_hash(m["run"].training_configuration["scaler"])
    d_full = np.array(paired_differentials(m["grades"], n["grades"]))
    oh_full = [g.outcome_hash for g in m["grades"]]
    assert len(d_full) == max(R4.EVAL_LADDER)
    rec = {"seed": s, "world_hash": w.world_hash, "training_hash": th, "beta_hash": beta_h,
           "sigma_M0": sig, "scaler_hash": scaler_h, "n_train": len(ytr), "levels": {}}
    for L in R4.EVAL_LADDER:
        d = d_full[:L]
        # nested-prefix identity: the level's data IS the prefix of the full graded path
        pid = bool(np.array_equal(d, d_full[:L]) and oh_full[:L] == [g.outcome_hash for g in m["grades"][:L]]
                   and iev[:L] == list(R4.R4_SPLIT.eval_steps)[:L])
        prefix_identity_ok &= pid
        b = BS.bootstrap_test(d.tolist(), court_id="P0_V2_DEV", control="P0_V2_%d" % L, seed=s)
        h = dm_hac_rule(m["grades"][:L], n["grades"][:L])
        cell = {"seed": s, "L": L, "verdict": b["verdict"], "p": b["p_bootstrap"], "t_obs": b["t_obs"],
                "block_length": b["block"]["block_length"], "t_star_q975": b["t_star_q"]["q975"],
                "mean_d": float(d.mean()), "sd_d": float(d.std(ddof=1)),
                "lrv_over_n": hac_long_run_variance(d.tolist(), 14) / L,
                "eval_over_block": L / b["block"]["block_length"],
                "positive": bool(d.mean() > 0), "hac_t": h["t"],
                "training_hash": th, "beta_hash": beta_h, "scaler_hash": scaler_h,
                "prefix_identity": pid}
        levels[L].append(cell); rec["levels"][str(L)] = {k: cell[k] for k in ("verdict", "p", "t_obs", "block_length")}
    # training identity across levels: every level of this seed references the same fitted state
    training_identity_ok &= all(c["training_hash"] == th and c["beta_hash"] == beta_h and c["scaler_hash"] == scaler_h
                                for L in R4.EVAL_LADDER for c in levels[L] if c["seed"] == s)
    seed_records.append(rec)
    print("seed %2d/50 %10d  " % (i + 1, s) + "  ".join("L%d:%s p=%.3f t=%+.2f bl=%d" % (
        L, "DET" if levels[L][-1]["verdict"] == "SIGNAL_DETECTED" else "no ", levels[L][-1]["p"], levels[L][-1]["t_obs"], levels[L][-1]["block_length"]) for L in R4.EVAL_LADDER), flush=True)

summary = {}
for L in R4.EVAL_LADDER:
    cs = levels[L]; n = len(cs); det = sum(1 for c in cs if c["verdict"] == "SIGNAL_DETECTED"); pos = sum(1 for c in cs if c["positive"])
    ps = [c["p"] for c in cs]; ts = [c["t_obs"] for c in cs]; bl = [c["block_length"] for c in cs]
    summary[str(L)] = {"usable_eval_obs": L, "n": n, "detections": det, "detection_rate": det / n,
                       "wilson95_lower": wilson_low(det, n), "positive_direction": pos, "direction_rate": pos / n,
                       "p": {"q10": q(ps, .1), "q25": q(ps, .25), "med": q(ps, .5), "q75": q(ps, .75), "q90": q(ps, .9)},
                       "t_obs": {"min": min(ts), "q10": q(ts, .1), "med": q(ts, .5), "q90": q(ts, .9), "max": max(ts)},
                       "block_length": {"min": min(bl), "q25": q(bl, .25), "med": q(bl, .5), "q75": q(bl, .75), "max": max(bl)},
                       "eval_over_block_med": q([c["eval_over_block"] for c in cs], .5),
                       "mean_d": {"med": q([c["mean_d"] for c in cs], .5), "q10": q([c["mean_d"] for c in cs], .1), "q90": q([c["mean_d"] for c in cs], .9)},
                       "sd_d_med": q([c["sd_d"] for c in cs], .5), "lrv_over_n_med": q([c["lrv_over_n"] for c in cs], .5),
                       "t_star_q975_med": q([c["t_star_q975"] for c in cs], .5),
                       "hac_secondary_detections": sum(1 for c in cs if c["hac_t"] > 2.0 and c["positive"]),
                       "qualifies": bool(det / n >= R4.QUALIFICATION["min_detection_rate"] and wilson_low(det, n) >= R4.QUALIFICATION["min_wilson95_lower"] and pos / n >= R4.QUALIFICATION["min_direction_rate"])}
    print("L=%4d det %2d/50 rate %.2f wilson %.3f dir %.2f p_med %.4f t_med %+.2f bl_med %d eval/bl %.1f t*q975 %.2f -> %s" % (
        L, det, det / n, wilson_low(det, n), pos / n, q(ps, .5), q(ts, .5), q(bl, .5), summary[str(L)]["eval_over_block_med"], summary[str(L)]["t_star_q975_med"], "QUALIFIES" if summary[str(L)]["qualifies"] else "no"), flush=True)
chosen = next((L for L in R4.EVAL_LADDER if summary[str(L)]["qualifies"]), None)   # smallest, after ALL ran
out = {"version": R4.R4_VERSION, "predeclaration_sha256": PRE_SHA, "predeclaration_hash": R4.predeclaration_hash(),
       "bootstrap_contract_hash": BS.content_identity(), "mu_multiplier": R4.P0_MU_MULTIPLIER,
       "ladder": list(R4.EVAL_LADDER), "T_max": R4.T_MAX, "split_used": R4.R4_SPLIT.canonical() if hasattr(R4.R4_SPLIT, "canonical") else {"n_steps": R4.T_MAX, "boundary": R4.V0_BOUNDARY},
       "NESTED_EVALUATION_PREFIX_IDENTITY": "PASS" if prefix_identity_ok else "FAIL",
       "TRAINING_IDENTITY_ACROSS_LENGTHS": "PASS" if training_identity_ok else "FAIL",
       "n_train_all_seeds": sorted({r["n_train"] for r in seed_records}),
       "levels": summary, "cells": {str(L): levels[L] for L in R4.EVAL_LADDER}, "seeds": seed_records,
       "selected_evaluation_length": chosen,
       "power_validity": "PASS" if chosen is not None else "FAIL",
       "identity": "P0_CAUSAL_TREND_POWERED_V2" if chosen else None,
       "elapsed_s": round(time.time() - t0, 1),
       "resource_truth": {"ru_maxrss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                          "cgroup": open("/proc/self/cgroup").read().strip(), "seeds": 50, "cells": 200}}
out["R4_VERDICT"] = out["power_validity"] if (prefix_identity_ok and training_identity_ok) else "FAIL"
json.dump(out, open(OUT, "w"), indent=1, default=str)
print("selected:", chosen, "| prefix identity", out["NESTED_EVALUATION_PREFIX_IDENTITY"], "| training identity", out["TRAINING_IDENTITY_ACROSS_LENGTHS"])
print("R4_VERDICT:", out["R4_VERDICT"], "elapsed %.0fs rss %.0fMiB" % (out["elapsed_s"], out["resource_truth"]["ru_maxrss_MiB"]))
