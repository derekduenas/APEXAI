"""Committed generator for docs/evidence/r4_latency_budget.json.

Measures JointEngine.decide() wall time on SYNTHETIC inputs with the tracer OFF, and writes every measurement
condition IN-BAND (tracer state, sample count, host, process, python, generator, git commit). An evidence file
that does not say how it was measured is a number, not evidence. The r1/r2 scale files were produced with
tracemalloc active (about 2.5x inflation on this allocation-heavy path) over 5 samples; this file supersedes them.

    ../apex-equities/.venv/bin/python scripts/r4_latency_measure.py [n_decisions] [n_paths]

No historical data, no collector reads, no broker calls. The deadline written here is DECLARED, not enforced.
"""
import datetime as dt
import json
import os
import platform
import resource
import socket
import statistics
import subprocess
import sys
import time
import tracemalloc

sys.path.insert(0, ".")
import numpy as np  # noqa: E402

import tests.test_joint_wb as T  # noqa: E402
from apex.joint_wb import engine as ENG  # noqa: E402
from apex.joint_wb import state as ST  # noqa: E402

N_DECISIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 35
N_PATHS = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
OUT = "docs/evidence/r4_latency_budget.json"
DECIDE_DEADLINE_S, PER_SCAN_DEADLINE_S = 2.0, 5.0


def _time(engine, n, scan_prefix):
    ms = T._state()
    out = []
    for i in range(n):
        t0 = time.perf_counter()
        r = T._decide(engine, ms=ms, drift=0.0005, scan_id="%s-%d" % (scan_prefix, i))
        out.append(time.perf_counter() - t0)
        assert r["decision"] in ("TRADE", "WAIT")
    return out


def _summ(xs):
    xs = sorted(xs)
    return {"median": round(statistics.median(xs), 4), "p95": round(xs[int(0.95 * (len(xs) - 1))], 4),
            "max": round(xs[-1], 4), "min": round(xs[0], 4), "n": len(xs)}


def main():
    assert not tracemalloc.is_tracing(), "tracer must be OFF for a latency measurement"
    e = T._engine(n_paths=N_PATHS, seed=11)
    _time(e, 3, "WARM")                                  # warm-up excluded
    # time the adverse block DIRECTLY by wrapping it: the six scenarios are hard-coded inside JointEngine._adverse
    # (the ADVERSE_SCENARIOS tuple is the registry the gate checks against, not a switch), so they cannot be
    # "disabled" from outside without changing the decision path
    adverse_times = []
    orig = ENG.JointEngine._adverse

    def timed(self, *a, **k):
        t0 = time.perf_counter()
        try:
            return orig(self, *a, **k)
        finally:
            adverse_times.append(time.perf_counter() - t0)
    ENG.JointEngine._adverse = timed
    try:
        with_adv = _time(e, N_DECISIONS, "ADV")
    finally:
        ENG.JointEngine._adverse = orig
    adverse_times = adverse_times[-N_DECISIONS:]
    # the control: the same code with the tracer ON, 5 samples, to show the inflation the r1/r2 files carried
    tracemalloc.start()
    traced = _time(e, 5, "TRACED")
    tracemalloc.stop()
    worst = max(with_adv)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    rec = {
        "kind": "R4_LATENCY_BUDGET",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "measurement_conditions": {
            "tracer_active_during_timed_decisions": False,
            "sample_count": N_DECISIONS, "warmup_excluded": 3, "n_paths": N_PATHS,
            "inputs": "SYNTHETIC (tests.test_joint_wb fixtures); no market data",
            "host": socket.gethostname(), "cpu": platform.processor() or platform.machine(),
            "platform": platform.platform(), "python": sys.version.split()[0], "numpy": np.__version__,
            "process": "single process, pid %d, this generator only; no other apex service running on the host" % os.getpid(),
            "max_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 2), 1),
            "generator": "scripts/r4_latency_measure.py", "git_commit": commit,
            "attribution": "builder-reported; reproducible by re-running the generator"},
        "measurement": {"decide_total": _summ(with_adv), "adverse_block_inside_decide": _summ(adverse_times),
                        "adverse_share_of_median": round(statistics.median(adverse_times) / statistics.median(with_adv), 3),
                        "note": ("the adverse block is timed by wrapping JointEngine._adverse (the scenarios are hard-coded there; the "
                                 "ADVERSE_SCENARIOS tuple is the registry the gate checks, not a switch, so they cannot be disabled "
                                 "from outside). An earlier uncommitted measurement reported 0.062 s for the block by a method that "
                                 "cannot be reproduced; the direct measurement here replaces it"),
                        "control_tracer_on_5_samples": _summ(traced),
                        "tracer_inflation_factor": round(statistics.median(traced) / statistics.median(with_adv), 2)},
        "supersedes": ["docs/evidence/r4_scale_synthetic.json", "docs/evidence/r4_scale_synthetic_r2.json"],
        "correction_to_earlier_reports": {
            "r1_reported": "median 0.121 s over 5 decisions (tracer ON)",
            "r2_reported": "median 0.447 s over 5 decisions (tracer ON)",
            "defect": "both measured with tracemalloc active; the harness observed itself. 5 samples is too few to be stable.",
            "conclusion": "the r1 -> r2 slowdown claim was not a clean comparison and is withdrawn"},
        "declared_deadline_before_this_record": None,
        "binding_constraint": {"name": "EXECUTION_MAX_AGE_S", "value_s": ST.EXECUTION_MAX_AGE_S,
                               "why": "the quote that produces an intent must be <= 15 s old at the decision boundary; decision time consumes that budget"},
        "declaration": {
            "status": "DECLARED_NOT_ENFORCED", "declared_on": "2026-09-11", "declared_by": "operator (Clock Start Block item 4)",
            "decide_deadline_s": DECIDE_DEADLINE_S, "per_scan_deadline_s": PER_SCAN_DEADLINE_S,
            "measured_margin_s": {"decide_worst_case": round(DECIDE_DEADLINE_S - worst, 4),
                                  "per_scan_worst_case_assuming_one_decision": round(PER_SCAN_DEADLINE_S - worst, 4),
                                  "raw_constraint_worst_case": round(ST.EXECUTION_MAX_AGE_S - worst, 4)},
            "headroom_factor_vs_decide_deadline": round(DECIDE_DEADLINE_S / worst, 1),
            "reasoning": ("decide() <= 2.0 s is 13% of the 15 s freshness window, leaving >= 13 s for state assembly, ledger "
                          "writes, the kernel check and the fill round trip; the 5.0 s per-scan budget leaves 10 s for the "
                          "execution quote itself"),
            "enforcement": "NOT BUILT: enforcing a deadline is capability and the build is frozen; a breach today is invisible"},
    }
    with open(OUT, "w") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    print(json.dumps(rec["measurement"], indent=1))
    print("margin", rec["declaration"]["measured_margin_s"])


if __name__ == "__main__":
    main()
