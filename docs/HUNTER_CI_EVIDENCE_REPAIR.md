# Hunter CI evidence repair

Base: a0af2b83e3132cf69357801f3137a06eafcf3a6f (Claude review of PR #7).

The synthetic smoke world used initial market caps of $150M–$500B while the active registered universe is $100M–$2B. The baseline command failed its unchanged 100-name median requirement: min 11, median 36, max 60 across 1,004 dates.

The smoke-only generator now spans half the registered minimum to twice the registered maximum ($50M–$4B), retaining out-of-band examples on both sides. No experiment configuration, protocol, ranking requirement, seed, return drift, or alpha changed. This is explicitly a fixture correction, not independent research evidence. After: min 159, median 178, max 199; every smoke check passed and command exit was zero. Reports are preserved in docs/evidence/hunter_ci_repair.

The workflow runs four Hunter contract files before smoke. Test steps explicitly continue after earlier failures if installation succeeded and the run was not cancelled. No continue-on-error or swallowed exit status is used; a failed step still fails the job. JUnit and smoke output are uploaded after failures. A runner timeout or cancellation can still prevent completion; this does not promise otherwise.

Local verification: the exact four-file Hunter command passed 53 tests. Full suite not run locally; GitHub workflow execution remains separate evidence.

## Operating status and next acceptance

This repair enables evidence collection, not paper execution. In this code line capital.evaluate_candidate rejects every non-default ForecastSlot status as uncommissioned; a calibrated DistributionEstimate alone does not unlock it. The paper full-stack fixture uses SyntheticTestAuthorization and does not prove a production-authorized round trip or numeric P&L reconciliation.

Next bounded work must explicitly commission the forecast-to-capital contract and prove an authorized synthetic entry, fill, exit, fees, P&L and ledger reconstruction, while a SIMULATED_UNCALIBRATED production forecast remains refused. Forecast calibration requires chronological forecast-before-outcome evidence. The current retrospective GARCH convergence run supplies no such calibration.

No deployment, host changes, calibration promotion, account permission changes or order submission performed here. Existing basic live observation and undeployed full-model observation are different capabilities.
