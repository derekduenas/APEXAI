#!/usr/bin/env python
"""A-010 remediation proof: the slim source changes NOTHING, anywhere.

    python scripts/slim_source_proof.py          # reproduction at 1e-12
    python scripts/slim_source_proof.py --probe  # holdout-length headroom probe

MODE 1 (default): rebuild the APEX-004 validation evaluation through the
slim-high-low source and compare EVERY numeric field of the recorded artifact
-- daily IC block, non-overlapping block, full decile block -- at 1e-12.
Operator requirement: "a memory optimization that changes nothing should
change nothing anywhere." One mismatch = the slim source is refused for the
holdout, whatever the explanation.

MODE 2 (--probe): load the FULL holdout-length panel (2004 -> 2026-06-30)
through the slim source, run the complete GP pipeline, and additionally run
an evaluation-sized allocation on the ALREADY-PAID validation window (never
the holdout -- no holdout statistic is computed or observed). Report peak RSS
against physical memory: the requirement is measured HEADROOM, not survival.
"""
from __future__ import annotations

import json
import resource
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex003  # noqa: E402
from apex.pipeline import evaluate  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
TOL = 1e-12


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}  rss={rss_gb():.2f}GB",
          file=sys.stderr, flush=True)


def compare_block(name, got: dict, want: dict, failures: list):
    # JSON round-trips dict keys to strings; the recomputed evaluation keeps
    # integer decile labels. Normalise so "1" and 1 are the same key.
    got = {str(k): v for k, v in got.items()}
    for k, w in want.items():
        g = got.get(str(k))
        if isinstance(w, (int, float)) and not isinstance(w, bool):
            if g is None or abs(float(g) - float(w)) > TOL:
                failures.append(f"{name}.{k}: got {g!r} want {w!r}")
        elif isinstance(w, dict):
            compare_block(f"{name}.{k}", g or {}, w, failures)
        else:
            if g != w:
                failures.append(f"{name}.{k}: got {g!r} want {w!r}")


def mode_reproduce(cfg) -> int:
    rec = json.loads(Path("results/validation_APEX-004.json").read_text())["raw"]
    val = cfg.period("validation")

    progress("building SLIM panel through validation end")
    panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"),
                                      val["end"], slim_high_low=True)
    assert panel.high_adj is panel.close_adj, "slim mode must share the object"
    progress("running GP pipeline")
    output, _ = apex003.build_gp_output(panel, cfg, ROOT)
    progress("evaluating the (already recorded) validation window")
    ev = evaluate(output, cfg, val["start"], val["end"])

    failures: list[str] = []
    compare_block("ic_daily_newey_west", ev.ic_daily.as_dict(),
                  rec["ic_daily_newey_west"], failures)
    compare_block("ic_non_overlapping", ev.ic_non_overlapping.as_dict(),
                  rec["ic_non_overlapping"], failures)
    compare_block("deciles_gross", ev.deciles.as_dict(),
                  rec["deciles_gross"], failures)

    n_checked = sum(len(rec[b]) + (len(rec[b].get("mean_by_decile", {}))
                                   if isinstance(rec[b], dict) else 0)
                    for b in ("ic_daily_newey_west", "ic_non_overlapping",
                              "deciles_gross"))
    verdict = "MATCH" if not failures else "FAIL"
    out = {"mode": "full_reproduction", "tolerance": TOL,
           "fields_checked_approx": n_checked, "verdict": verdict,
           "failures": failures, "peak_rss_gb": round(rss_gb(), 2)}
    Path("results/slim_source_proof.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"SLIM SOURCE REPRODUCTION: {verdict} "
          f"({n_checked}+ fields at {TOL})")
    for f in failures:
        print(f"  MISMATCH {f}")
    return 0 if not failures else 1


def mode_probe(cfg) -> int:
    phys = int(subprocess.run(["sysctl", "-n", "hw.memsize"],
                              capture_output=True, text=True).stdout) / 1e9
    hold_end = cfg.period("holdout")["end"]
    progress(f"HOLDOUT-LENGTH probe: slim panel through {hold_end} "
             f"(physical {phys:.0f}GB)")
    panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"),
                                      hold_end, slim_high_low=True)
    progress("panel loaded")
    output, _ = apex003.build_gp_output(panel, cfg, ROOT)
    progress("gp output built")
    val = cfg.period("validation")
    # evaluation-SIZED allocation on the PAID window only; no holdout statistic
    evaluate(output, cfg, val["start"], val["end"])
    progress("evaluation-sized allocation exercised (validation window only)")

    peak = rss_gb()
    headroom = phys - peak
    ok = peak < 0.70 * phys
    out = {"mode": "holdout_length_probe", "physical_gb": round(phys, 1),
           "peak_rss_gb": round(peak, 2), "headroom_gb": round(headroom, 2),
           "requirement": "peak < 70% of physical",
           "verdict": "HEADROOM OK" if ok else "INSUFFICIENT HEADROOM"}
    Path("results/slim_probe.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(out, indent=2))
    return 0 if ok else 1


def main() -> int:
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    if "--probe" in sys.argv:
        return mode_probe(cfg)
    return mode_reproduce(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
