"""Reference comparison: the workbench GARCH(1,1)-t against the `arch` library on ONE synthetic world.
Run with an interpreter that has `arch` (the Mac system python3 8.0.0); the frozen runner venv has none.
Evidence only: agreement on a synthetic series says the likelihood and recursion are implemented
consistently; it says nothing about market data."""
import json, sys, time, platform
import numpy as np
sys.path.insert(0, ".")
from apex.worldmodel_wb import vol_models as VM
import arch
from arch import arch_model

x = VM.simulate_garch(n=6000, omega=2e-8, alpha=0.08, beta=0.90, nu=7.0, seed=3)
rows = [{"event_time": i * 60.0, "available": i * 60.0 + 60, "ret_1": float(v)} for i, v in enumerate(x)]
m = VM.GARCH(); ours = m.fit(rows, cutoff_epoch=1e9)
# arch works in percent for conditioning: scale returns by 100 -> omega scales by 1e4
am = arch_model(x * 100.0, mean="Zero", vol="GARCH", p=1, q=1, dist="t")
res = am.fit(disp="off")
theirs = {"omega": float(res.params["omega"]) / 1e4, "alpha": float(res.params["alpha[1]"]), "beta": float(res.params["beta[1]"]),
          "nu": float(res.params["nu"]), "loglik_percent_units": float(res.loglikelihood)}
# our NLL is in raw units; arch fitted 100*x, so f_raw(x) = 100 f_pct(100 x): log-likelihood shifts by +N*log(100)
theirs["loglik_raw_units"] = theirs["loglik_percent_units"] + len(x) * np.log(100.0)
out = {"world": {"n": 6000, "omega": 2e-8, "alpha": 0.08, "beta": 0.90, "nu": 7.0, "seed": 3},
       "workbench": {k: ours[k] for k in ("omega", "alpha", "beta", "nu")}, "workbench_loglik": -ours["nll"],
       "arch": theirs, "arch_version": arch.__version__, "python": platform.python_version(),
       "abs_diff": {k: abs(ours[k] - theirs[k]) for k in ("omega", "alpha", "beta", "nu")},
       "loglik_diff": (-ours["nll"]) - theirs["loglik_raw_units"], "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
print(json.dumps(out, indent=1))
json.dump(out, open("docs/evidence/garch_reference_vs_arch_OUTPUT.json", "w"), indent=1)
