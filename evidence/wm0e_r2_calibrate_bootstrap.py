"""WM-0E-R2 §7 CALIBRATION EXERCISE -- runs BEFORE any acceptance seed.

Development statistical fixtures in their own PRNG namespace (9_500_xxx):
never a court seed. The envelope was written into bootstrap.py before
this script existed; this script only measures and compares.
Usage: calibrate_bootstrap.py <out.json>
"""
import json, math, random, sys, time
import numpy as np
from apex.world_model import bootstrap as BS

OUT = sys.argv[1]
ENV = BS.CALIBRATION_ENVELOPE
R = ENV["replications_per_fixture"]
H = 15

def ma(rng, n, mu=0.0):
    e = [rng.gauss(0, 1) for _ in range(n + H)]
    return [mu + sum(e[t:t + H]) for t in range(n)]
def ar1(rng, n, phi, mu=0.0):
    x, out = 0.0, []
    for _ in range(n):
        x = phi * x + rng.gauss(0, 1); out.append(mu + x)
    return out
def wilson(k, n, z=1.96):
    p = k / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [c - h, c + h]

FIXTURES = [
    ("NULL_iid_n465",        True,  lambda r: [r.gauss(0, 1) for _ in range(465)]),
    ("NULL_MA14_n465",       True,  lambda r: ma(r, 465)),
    ("NULL_MA14_n270",       True,  lambda r: ma(r, 270)),
    ("NULL_AR1_phi0.5_n465", True,  lambda r: ar1(r, 465, 0.5)),
    ("NULL_AR1_phi0.9_n465", True,  lambda r: ar1(r, 465, 0.9)),
    ("POWER_MA14_mu3_n465",  False, lambda r: ma(r, 465, mu=3.0)),
    ("POWER_AR1_phi0.9_mu1.5_n465", False, lambda r: ar1(r, 465, 0.9, mu=1.5)),
]
t0 = time.time(); out = {"bootstrap_contract_hash": BS.content_identity(),
                         "bootstrap_contract": BS.bootstrap_contract(),
                         "envelope": ENV, "replications": R, "fixtures": {}}
pooled_k = pooled_n = 0
for name, is_null, gen in FIXTURES:
    rng = random.Random(9_500_000 + abs(hash(name)) % 1000)
    rng = random.Random(9_500_000 + FIXTURES.index((name, is_null, gen)))
    rej = 0; ps = []; bls = []; ts = []; clamped = {"lower": 0, "none": 0, "upper": 0}
    for rep in range(R):
        d = gen(rng)
        r = BS.bootstrap_test(d, court_id="CALIBRATION", control=name, seed=rep)
        ps.append(r["p_bootstrap"]); bls.append(r["block"]["block_length"]); ts.append(r["t_obs"])
        clamped[r["block"]["clamped"]] += 1
        if r["verdict"] == "SIGNAL_DETECTED": rej += 1
    ps_a = np.array(ps)
    rec = {"is_null": is_null, "reps": R, "n": len(d), "rejection_rate": rej / R,
           "rejections": rej, "ci95": wilson(rej, R),
           "p_quantiles": {q: float(np.quantile(ps_a, float(q))) for q in ("0.05", "0.25", "0.5", "0.75")},
           "frac_p_le_0.05": float((ps_a <= 0.05).mean()), "frac_p_le_0.10": float((ps_a <= 0.10).mean()),
           "block_length": {"min": min(bls), "median": sorted(bls)[R // 2], "max": max(bls)},
           "block_clamped": clamped,
           "t_obs_sd": float(np.std(ts, ddof=1)), "t_obs_mean": float(np.mean(ts))}
    if is_null:
        ok = ENV["null_fixture_type1_min"] <= rec["rejection_rate"] <= ENV["null_fixture_type1_max"]
        rec["envelope_ok"] = bool(ok)
        if "iid" not in name: pooled_k += rej; pooled_n += R
    else:
        rec["envelope_ok"] = bool(rec["rejection_rate"] >= ENV["power_fixture_min"])
    out["fixtures"][name] = rec
    print("%-30s rej=%.4f CI=[%.3f,%.3f] p50=%.3f bl=%d/%d/%d clamp=%s t_sd=%.2f %s"
          % (name, rec["rejection_rate"], *rec["ci95"], rec["p_quantiles"]["0.5"],
             rec["block_length"]["min"], rec["block_length"]["median"], rec["block_length"]["max"],
             clamped, rec["t_obs_sd"], "ok" if rec["envelope_ok"] else "OUTSIDE ENVELOPE"), flush=True)
pooled = pooled_k / pooled_n
out["pooled_dependent_null_rejection"] = pooled
out["pooled_ok"] = bool(pooled <= ENV["pooled_dependent_null_type1_max"])
all_ok = all(f["envelope_ok"] for f in out["fixtures"].values()) and out["pooled_ok"]
out["envelope_verdict"] = "PASS" if all_ok else "FAIL"
out["elapsed_s"] = round(time.time() - t0, 1)
json.dump(out, open(OUT, "w"), indent=1)
print("pooled dependent-null rejection: %.4f (max %.3f) -> %s" % (pooled, ENV["pooled_dependent_null_type1_max"], out["pooled_ok"]))
print("ENVELOPE_VERDICT:", out["envelope_verdict"], " elapsed %.1fs" % out["elapsed_s"])
