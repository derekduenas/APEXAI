#!/usr/bin/env python
"""APEX-004 section 8a: derive the small-cap validation critical value.

    python scripts/recalibrate_004_null.py

WHY DERIVE WHAT MIGHT COME OUT THE SAME
---------------------------------------
The 2.92 registered for APEX-002/003 is the 1% one-sided critical value of the
simulated null t-distribution at the validation period's length. That null
depends on (n_obs, overlap, lag, kernel) -- and on NOTHING else: the
t-statistic is scale invariant, so universe breadth and per-day IC variance
drop out. APEX-004 keeps the same validation window, the same 20-day overlap
and the same lag-25 Bartlett estimator, so the honest expectation is a bar
close to 2.92 again. It is derived here anyway, with a fresh declared seed,
because "the old constant probably carries over" is an assumption, and
registered constants are derived, frozen, and never assumed.

The null model never sees pipeline output (reference.py property 1), this
script reads NO snapshot data, and n_obs is taken from the RECORDED APEX-003
validation artifact -- a date count on the shared trading calendar, which is
structural, not statistical.

The derived value goes into the DRAFT protocol. It becomes binding only when
written into config and signed -- both human acts. The holdout bar is derived
the same way at signing (its exact day count is a calendar fact; nothing else
about holdout is touched, and it only matters after a validation PASS).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.evaluate.reference import simulate_null_tstats  # noqa: E402

SEED = 20260813          # declared here, fresh for 004; frozen at signing
N_REPLICATIONS = 100_000
OVERLAP, LAG = 20, 25    # inherited estimator structure, unchanged


def main() -> int:
    recorded = json.loads(Path("results/validation_APEX-003.json").read_text())
    n_obs = int(recorded["raw"]["estimator_disclosure"]["n_obs"])  # 987 IC days

    ref = simulate_null_tstats(
        n_obs=n_obs, overlap=OVERLAP, lag=LAG,
        n_replications=N_REPLICATIONS, seed=SEED,
    )
    q99 = ref.quantile(0.99)

    # Stability: the declared seed's p99 must not be a Monte-Carlo accident.
    # Four independent seeds, disclosed alongside; they select nothing.
    stability = {
        s: simulate_null_tstats(n_obs=n_obs, overlap=OVERLAP, lag=LAG,
                                n_replications=N_REPLICATIONS, seed=s).quantile(0.99)
        for s in (1, 2, 3, 42)
    }
    out = {
        "purpose": "APEX-004 draft section 8a null recalibration (validation bar)",
        "derived_critical_value_1pct_one_sided": round(q99, 2),
        "raw_quantile_0_99": q99,
        "seed_stability_p99": {str(k): v for k, v in stability.items()},
        "registered_002_003_bar": 2.92,
        "true_size_of_2_92_under_this_null": ref.one_sided_size(2.92),
        "true_size_of_2_85_under_this_null": ref.one_sided_size(2.85),
        "note": (
            "The derived exact-1% bar is LOWER than the registered 2.92 "
            "(which has true size ~0.87%). Deriving a lower bar immediately "
            "after a near-miss FAILURE is exactly when bar-shopping suspicion "
            "is warranted, so the choice between the derived 2.85 and the "
            "stricter legacy 2.92 is reserved to the human gate and recorded "
            "in the protocol at signing. Neither choice affects any closed "
            "experiment; APEX-003's t=2.525 is below both."
        ),
        "n_obs": n_obs,
        "n_obs_source": "recorded validation_APEX-003.json estimator n_obs (calendar fact)",
        "seed": SEED,
        "n_replications": N_REPLICATIONS,
        "disclosure": ref.disclosure(),
        "status": "DERIVED -- becomes binding only via config + signature",
    }
    path = Path("results/004_null_recalibration.json")
    path.write_text(json.dumps(out, indent=2))
    print(f"1% one-sided critical value at n={n_obs}: {q99:.4f}"
          f"  (registered 002/003 bar: 2.92)")
    print(f"written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
