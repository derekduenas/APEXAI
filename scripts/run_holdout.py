#!/usr/bin/env python
"""A-010: the standalone APEX-004 holdout evaluation. ONE look, ever.

    python scripts/run_holdout.py --snapshot data/snapshots/sharadar/current \
        --out results/holdout_APEX-004.json

Exists under CONVENTIONS amendment A-010 (SIGNED 2026-08-15). This runner did
not exist before that signature -- run_validation.py deliberately cannot open
the holdout, and this script deliberately cannot open anything else.

Preconditions, enforced by code:
  * signed registration; protocol pin matches
  * results/_unlocks/holdout.unlock exists, HAND-CREATED BY THE OPERATOR
    (A-010 section 4.5: never automated, delegated, scripted, or scheduled)
  * APEX-004 validation PASS on the ledger; no prior holdout entry
  * registered holdout bar t >= 2.88 read from config, never supplied here

Memory: uses the SLIM source (high/low never parsed), proven to change
nothing by full reproduction of the recorded validation at 1e-12
(results/slim_source_proof.json) and probed at holdout length with 3.9GB
headroom (results/slim_probe.json). Runs whatever it records; the Class I
holdout burns programme-wide on completion.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.config import git_sha, load_config  # noqa: E402
from apex.data.production_source import ProductionSource  # noqa: E402
from apex.evaluate.reference import simulate_null_tstats  # noqa: E402
from apex.evaluate.criteria import SuccessCriteria  # noqa: E402
from apex.evaluate.verdict import full_report, interpret  # noqa: E402
from apex.pipeline import run_period  # noqa: E402
from apex.registration import open_ledger, signature_status  # noqa: E402
from apex.report.attribution import attribute  # noqa: E402

PERIOD = "holdout"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path,
                        default=Path("results/holdout_APEX-004.json"))
    args = parser.parse_args()

    config = load_config("experiment", "costs", "synthetic", "sharadar")
    experiment = config.get("experiment.id")
    if experiment != "APEX-004":
        print(f"REFUSED: A-010 authorises the APEX-004 holdout only; config "
              f"names {experiment!r}.", file=sys.stderr)
        return 2

    # A-010 pre-flight evidence must exist and be clean.
    proof = Path("results/slim_source_proof.json")
    if not proof.exists() or json.loads(proof.read_text())["verdict"] != "MATCH":
        print("REFUSED: slim-source reproduction proof missing or not MATCH.",
              file=sys.stderr)
        return 2
    probe = Path("results/slim_probe.json")
    if not probe.exists() or "OK" not in json.loads(probe.read_text())["verdict"]:
        print("REFUSED: holdout-length memory probe missing or without headroom.",
              file=sys.stderr)
        return 2

    source = ProductionSource(
        args.snapshot, config, config.get("calendar.lake_start"),
        config.period(PERIOD)["end"], slim_high_low=True,
    )

    # run_period enforces signature, protocol pin, the HAND-MADE holdout
    # token, the validation-PASS precondition and write-once semantics.
    output, evaluation = run_period(source, config, PERIOD)

    spec = config.period(PERIOD)
    attribution = attribute(output, config, spec["start"], spec["end"])
    ic = evaluation.ic_daily
    robustness = evaluation.ic_non_overlapping
    deciles = evaluation.deciles

    criteria = SuccessCriteria.from_config(config, PERIOD)   # t >= 2.88
    verdict = criteria.evaluate(
        mean_ic=ic.mean, t_stat=ic.t_stat, robustness_t=robustness.t_stat
    )
    reference = simulate_null_tstats(
        n_obs=ic.n_periods, overlap=20, lag=25, kernel="bartlett",
        n_replications=20000, seed=int(config.get("null_rig.reference_seed")),
    )

    ledger = open_ledger(config)
    ledger.record_result(
        experiment, PERIOD,
        p_value=ic.p_value, t_stat=ic.t_stat, verdict=verdict.verdict,
        dataset_hash=source.dataset_fingerprint,
    )

    payload = full_report(
        verdict,
        interpret(ic.t_stat, criteria.t_stat.threshold, reference),
        ledger.report(family_alpha=float(config.get("governance.family_alpha"))),
    )
    payload["a010"] = {
        "amendment": "A-010 (signed 2026-08-15)",
        "holdout_class": "I -- primary (US small-cap 2022-01-01..2026-06-30)",
        "burned_programme_wide": True,
        "slim_source": {"reproduction": "MATCH at 1e-12",
                        "probe_headroom_gb": json.loads(probe.read_text())["headroom_gb"]},
    }
    payload["raw"] = {
        "experiment_id": experiment, "period": PERIOD,
        "dataset_manifest_hash": source.dataset_fingerprint,
        "snapshot_root": str(args.snapshot),
        "protocol_hash": signature_status(config)["protocol_hash"],
        "conventions_hash": signature_status(config)["conventions_hash"],
        "config_hash": config.hash, "git_sha": git_sha(),
        "ic_daily_newey_west": ic.as_dict(),
        "ic_non_overlapping": robustness.as_dict(),
        "deciles_gross": deciles.as_dict(),
        "exclusions": source.exclusions().as_dict(),
        "estimator_disclosure": reference.disclosure(),
    }
    payload["attribution"] = attribution.as_dict()
    payload["success_criteria"] = criteria.as_dict()
    payload["criteria_evaluation"] = verdict.as_dict()
    payload["threshold_disclosure"] = {
        "registered_t_threshold": criteria.t_stat.threshold,
        "simulated_null_one_percent_quantile": reference.quantile(0.99),
        "n_obs": ic.n_periods,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload["raw"], indent=2, default=str))
    print(f"\nVERDICT: {verdict.verdict}")
    for failure in verdict.failures:
        print(f"  - {failure}")
    print(f"\nwritten to {args.out}")
    print("The Class I holdout is now BURNED programme-wide (A-010 section 4.3).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
