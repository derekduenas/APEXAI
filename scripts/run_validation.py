#!/usr/bin/env python
"""Ruling 3 -- the validation pass. ONE evaluation. No iteration. No reruns.

    python scripts/run_validation.py --snapshot /path/to/sharadar-export \
        --reason "pre-registered validation of APEX-001"

Preconditions, all enforced by the code rather than by this docstring:
  * the pre-registration is SIGNED
  * the protocol still hashes to the value CONVENTIONS pins
  * results/_unlocks/validation.unlock exists, hand-created
  * a research credit is available
  * the in-sample smoke run has been completed and passed

The result is written to the ledger with the experiment id, protocol hash,
DATASET MANIFEST HASH and timestamp (ruling 1: a result without a dataset
fingerprint is not a result).

This script cannot open the holdout. There is no flag for it.
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


def spec_end(config):
    """Lake must extend to the end of the period being evaluated."""
    return config.period(PERIOD)["end"]

PERIOD = "validation"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("results/validation_APEX-001.json"))
    args = parser.parse_args()

    config = load_config("experiment", "costs", "synthetic", "sharadar")

    # Cheapest precondition first: refuse before touching the vendor snapshot.
    # The smoke evidence is PER EXPERIMENT. The original check read the
    # APEX-001-era production_smoke.txt for every experiment, so a stale
    # artifact from one experiment would wave a DIFFERENT experiment through --
    # the same per-experiment-binding lesson as the unlock token.
    SMOKE_EVIDENCE = {
        "APEX-001": (Path("results/production_smoke.txt"), "CLEAR TO PROCEED"),
        "APEX-002": (Path("results/production_smoke.txt"), "CLEAR TO PROCEED"),
        "APEX-003": (Path("results/003_dry_run_A.txt"),
                     "STATUS: PASS -- every mechanical check green"),
        "APEX-004": (Path("results/004_dry_run_A.txt"),
                     "STATUS: PASS -- every mechanical check green"),
    }
    experiment = config.get("experiment.id")
    if experiment not in SMOKE_EVIDENCE:
        print(f"REFUSED: no smoke-run evidence is registered for {experiment!r}.",
              file=sys.stderr)
        return 2
    smoke, marker = SMOKE_EVIDENCE[experiment]
    if not smoke.exists():
        print(
            f"REFUSED: the mandatory in-sample smoke/dry run for {experiment} "
            f"has not been completed ({smoke} missing). Ruling 2: no exceptions.",
            file=sys.stderr,
        )
        return 2
    if marker not in smoke.read_text():
        print(
            f"REFUSED: {experiment}'s smoke/dry-run evidence at {smoke} does "
            f"not show a clean pass. Ruling 2: no partial fixes carried into "
            f"validation.",
            file=sys.stderr,
        )
        return 2

    # Slice-aware, universe-first -- the SAME path the production smoke test
    # exercised. The monolithic SharadarSnapshot adapter cannot read a
    # chunked snapshot and is not used here.
    source = ProductionSource(
        args.snapshot, config, config.get("calendar.lake_start"), spec_end(config)
    )

    # run_period enforces signature, protocol pin, unlock token and credit.
    output, evaluation = run_period(source, config, PERIOD)

    spec = config.period(PERIOD)
    attribution = attribute(output, config, spec["start"], spec["end"])

    ic = evaluation.ic_daily
    robustness = evaluation.ic_non_overlapping
    deciles = evaluation.deciles

    # INCIDENT-001 D3. The criteria are READ from the registered experiment,
    # never supplied here. The previous literals -- 0.015 / 2.5 / 2.0 -- are
    # APEX-001's, and would have been applied to APEX-002.
    criteria = SuccessCriteria.from_config(config, PERIOD)
    verdict = criteria.evaluate(
        mean_ic=ic.mean, t_stat=ic.t_stat, robustness_t=robustness.t_stat
    )

    # Disclosure only. CONVENTIONS A-001 bars the simulated null from the
    # decision path, and `criteria.evaluate` above takes no reference argument,
    # so this cannot influence the verdict. It is computed AFTER the decision
    # so that ordering makes the independence visible.
    reference = simulate_null_tstats(
        n_obs=ic.n_periods, overlap=20, lag=25, kernel="bartlett",
        n_replications=20000, seed=int(config.get("null_rig.reference_seed")),
    )

    ledger = open_ledger(config)
    ledger.record_result(
        config.get("experiment.id"),
        PERIOD,
        p_value=ic.p_value,
        t_stat=ic.t_stat,
        verdict=verdict.verdict,
        dataset_hash=source.dataset_fingerprint,
    )

    payload = full_report(
        verdict,
        # The registered threshold, not a literal. This line also carried
        # APEX-001's 2.5 (INCIDENT-001 D3).
        interpret(ic.t_stat, criteria.t_stat.threshold, reference),
        ledger.report(family_alpha=float(config.get("governance.family_alpha"))),
    )
    payload["raw"] = {
        "experiment_id": config.get("experiment.id"),
        "period": PERIOD,
        "dataset_manifest_hash": source.dataset_fingerprint,
        "snapshot_root": str(args.snapshot),
        "protocol_hash": signature_status(config)["protocol_hash"],
        "conventions_hash": signature_status(config)["conventions_hash"],
        "config_hash": config.hash,
        "git_sha": git_sha(),
        "ic_daily_newey_west": ic.as_dict(),
        "ic_non_overlapping": robustness.as_dict(),
        "deciles_gross": deciles.as_dict(),
        "exclusions": source.exclusions().as_dict(),
        "estimator_disclosure": reference.disclosure(),
    }
    payload["attribution"] = attribution.as_dict()
    payload["success_criteria"] = criteria.as_dict()
    payload["criteria_evaluation"] = verdict.as_dict()
    # The registered constant beside the null at the ACTUAL observation count,
    # so a divergence is visible rather than silently absorbed.
    payload["threshold_disclosure"] = {
        "registered_t_threshold": criteria.t_stat.threshold,
        "simulated_null_one_percent_quantile": reference.quantile(0.99),
        "n_obs": ic.n_periods,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print(json.dumps(payload["raw"], indent=2, default=str))
    print("\n--- ATTRIBUTION (protocol section 9) ---")
    print(attribution.render())
    print(f"\nVERDICT: {verdict.verdict}")
    for failure in verdict.failures:
        print(f"  - {failure}")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
