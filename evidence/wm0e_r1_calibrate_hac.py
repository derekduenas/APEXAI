"""CALIBRATION EXERCISE (not acceptance). Measures what the corrected
statistic actually does under a zero-mean dependent null, so the §10
question -- does it legitimately have alpha ~ 0.02275 at 2.0? -- is
answered by measurement before any acceptance seed is executed.

Part A: artificial fixtures (own PRNG namespace).
Part B: the DEVELOPMENT set (observed V0 seeds), N1 and P0 -- allowed
        for diagnosis, explicitly NOT acceptance evidence."""
import json, math, random, sys, time
sys.path.insert(0, "/opt/apex-research/world-model-shadow")
from apex.world_model import inference as I, court_v1 as V1
from apex.world_model.holdout import WM_0E_DEVELOPMENT_NULL_SET_V0

H = 15
def ma_overlap(rng, n, mu=0.0):
    e = [rng.gauss(0, 1) for _ in range(n + H)]
    return [mu + sum(e[t:t + H]) for t in range(n)]
def ar1(rng, n, phi):
    x, out = 0.0, []
    for _ in range(n):
        x = phi * x + rng.gauss(0, 1); out.append(x)
    return out
def iid_z(d):
    n = len(d); m = sum(d) / n
    v = sum((x - m) ** 2 for x in d) / (n - 1); return m / math.sqrt(v / n)
def wilson(k, n, z=1.96):
    p = k / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)

out = {"part_A_fixtures": {}, "part_B_development_set": {}}
R, n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000, 465
t0 = time.time()
# analytic Bartlett recovery for pure MA(14): LRV_true = H^2 ; LRV_bartlett = H + (2/(L+1)) * sum_{j=1}^{L} j^2
L = H - 1
lrv_true = H * H
lrv_bart = H + 2.0 * sum((1 - k / (L + 1)) * (H - k) for k in range(1, L + 1))
out["part_A_fixtures"]["analytic_MA14"] = {
    "lrv_true": lrv_true, "lrv_bartlett_L14_expected": lrv_bart,
    "variance_recovery_ratio": lrv_bart / lrv_true,
    "t_inflation_expected": math.sqrt(lrv_true / lrv_bart),
    "implied_one_sided_alpha_at_2.0": None}
from statistics import NormalDist
out["part_A_fixtures"]["analytic_MA14"]["implied_one_sided_alpha_at_2.0"] = \
    1 - NormalDist().cdf(2.0 / math.sqrt(lrv_true / lrv_bart))

for name, gen in (("MA14_overlap_zero_mean", lambda r: ma_overlap(r, n)),
                  ("AR1_phi0.9_zero_mean_(dependence_beyond_L)", lambda r: ar1(r, n, 0.9)),
                  ("AR1_phi0.5_zero_mean", lambda r: ar1(r, n, 0.5)),
                  ("iid_zero_mean", lambda r: [r.gauss(0, 1) for _ in range(n)])):
    rng = random.Random(9_400_001)
    iid_rej = hac_rej = 0; ts = []; infl = []
    for _ in range(R):
        d = gen(rng); m = sum(d) / n
        if m > 0 and iid_z(d) > 2.0: iid_rej += 1
        s = I.dm_hac_statistic(d); ts.append(s["t"]); infl.append(s["se_inflation_vs_iid"])
        if m > 0 and s["t"] > 2.0: hac_rej += 1
    mt = sum(ts) / R; sdt = math.sqrt(sum((t - mt) ** 2 for t in ts) / (R - 1))
    out["part_A_fixtures"][name] = {
        "reps": R, "n": n,
        "iid_rejection_rate": iid_rej / R, "iid_ci95": wilson(iid_rej, R),
        "hac_rejection_rate": hac_rej / R, "hac_ci95": wilson(hac_rej, R),
        "nominal_alpha": I.NOMINAL_ALPHA_ONE_SIDED,
        "hac_t_mean": mt, "hac_t_sd": sdt,
        "median_se_inflation_vs_iid": sorted(infl)[R // 2]}
    print("%-46s iid_rej=%.4f  hac_rej=%.4f  CI=[%.4f,%.4f]  t_mean=%+.3f t_sd=%.3f infl=%.2f"
          % (name, iid_rej / R, hac_rej / R, *wilson(hac_rej, R), mt, sdt, sorted(infl)[R // 2]))
# power
rng = random.Random(9_400_002); det = 0
for _ in range(500):
    d = ma_overlap(rng, n, mu=3.0); s = I.dm_hac_statistic(d)
    if s["mean"] > 0 and s["t"] > 2.0: det += 1
out["part_A_fixtures"]["MA14_positive_mean_mu3_power"] = {"reps": 500, "detection_rate": det / 500}
print("power (mu=3, MA14): %.3f" % (det / 500))
print("analytic:", json.dumps(out["part_A_fixtures"]["analytic_MA14"]))
print("elapsed A: %.1fs" % (time.time() - t0))

# ---- Part B: development set, N1 and P0
defn = V1.define_v1("DEV-DIAG", 0.0)
for ctl in ("N1", "P0"):
    cells = [V1.run_control_v1(defn, ctl, s) for s in WM_0E_DEVELOPMENT_NULL_SET_V0]
    j = V1.judge_control_v1(cells, ctl)
    out["part_B_development_set"][ctl] = {
        "role": "DEVELOPMENT DIAGNOSTIC -- observed seeds; not acceptance",
        "judgement": j,
        "cells": [{k: c[k] for k in ("seed", "verdict", "t_hac", "se_inflation_vs_iid",
                                     "legacy_iid_z_reference_only")} | {"non_overlap_z": c["non_overlap"]["z"]}
                  for c in cells]}
    print("%s dev-set: det=%d/%d  t_hac[min/med/max]=%+.2f/%+.2f/%+.2f  infl med=%.2f  iid_z med=%+.2f  nonoverlap det=%d"
          % (ctl, j["detections"], j["n"], j["primary_t_hac"]["min"], j["primary_t_hac"]["median"],
             j["primary_t_hac"]["max"], j["se_inflation_vs_iid"]["median"],
             j["legacy_iid_z_reference_only"]["median"], j["non_overlap_robustness"]["detections"]))
print("elapsed total: %.1fs" % (time.time() - t0))
json.dump(out, open("/tmp/wm0e_r1_calibration.json", "w"), indent=1, default=str)
