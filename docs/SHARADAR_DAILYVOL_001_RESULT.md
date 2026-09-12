# SHARADAR-DAILYVOL-001 — result (HISTORICAL_DEVELOPMENT_STUDY, daily horizon)

**What it is.** A declared, budgeted walk-forward comparison of the M3 variance candidates on SPY
DAILY log returns (Sharadar SFP, split+dividend-adjusted closes, frozen snapshot 2026-08-12), rows
≤ 2021-12-31 only. Folds = calendar years 2013–2021, training on all earlier rows, one fit per candidate
per fold (36 fits, all succeeded), the filter rolled forward through the fold without refit. Scores:
log score of each candidate's predictive density on the realized next-day return; PIT calibration.
Command and output: `scripts/sharadar_daily_vol_001.py`, `docs/evidence/sharadar_daily_vol_001_OUTPUT.json`.

**What it is not.** Evidence about the 15-minute options pilot (different horizon, target and data), and
not an economic result. It is forecast-score evidence for the workbench's volatility layer.

| Candidate | Mean OOF log score | vs ROLLING_VAR(30): mean Δ | year-block bootstrap 95% CI | Conclusion (this sample) |
|---|---|---|---|---|
| ROLLING_VAR(30) — comparator | 3.394 | — | — | — |
| EWMA(0.94) | 3.489 | +0.095 | [+0.041, +0.179] | improves |
| GARCH(1,1)-t | 3.561 | +0.167 | [+0.087, +0.276] | improves |
| GJR-GARCH(1,1)-t | 3.585 | +0.191 | [+0.115, +0.300] | improves |

n = 2,267 common out-of-fold days; every fold-year difference is positive for all three candidates
(largest in 2018 and 2020).

**Calibration, stated plainly.** No candidate is calibrated: PIT KS p-values are all ≈ 0 and mean PIT
≈ 0.535 for all four. The zero-mean assumption meets a positive drift, and the Gaussian candidates
mis-state the tails. GARCH-t improves the *relative* score; it does not yield a distribution you could
act on without a location model and a tail check.

**Limits.** One symbol; one target; zero conditional mean by construction; the standardized-t
convention only for the GARCH family (the comparator and EWMA are Gaussian by their contract);
daily rows treated as independent for the bootstrap blocks by year.

**Registry.** Search budget 4, all four trials recorded SCORED in the study output; the contract
digest is stored beside the results.
