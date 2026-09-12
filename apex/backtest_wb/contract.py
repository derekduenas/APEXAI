"""PILOT-REPLAY-001 — the study contract, declared BEFORE any corpus access.

Primary question: over the exposed sessions of the validated SPY options corpus, what is the
after-cost economic outcome of the FROZEN pilot policy per scan, and does it differ from WAIT and
from direction-agnostic controls on the same eligible rows? No parameter is fitted; the search
budget is one policy plus two controls; every planned comparison is listed here."""
from __future__ import annotations

from apex.worldmodel_wb.study_contract import HistoricalStudyContract

PERIOD_POLICY = ("EXPOSED PERIODS ONLY: sessions dated <= 2021-12-31 (EXP-001B train/validation, EXP-002 development/"
                 "observed). 2022-01-01 onward is SEALED (evaluation/reserve) by the EXP-001B registration and is NOT opened "
                 "by this study; corpus days in those years are excluded by date before any file is read.")

CONTRACT = HistoricalStudyContract(
    study_id="PILOT-REPLAY-001",
    primary_target="after-cost net P&L per scan (USD, one contract) of the frozen pilot policy exited at +15 minutes",
    primary_hypothesis=("the frozen pilot policy's mean net P&L per eligible scan is not distinguishable from zero after costs "
                        "(null); secondary: its forecast component is not calibrated on the 15-minute target (PIT)"),
    comparator="WAIT (zero) and two direction controls on the SAME rows: RANDOM_DIRECTION (seeded coin) and REVERSED_DIRECTION",
    eligible_rows=("SPY corpus sessions <= 2021-12-31 with quotes_ and underlying_ files; regular hours; scans at 10:00, 10:15, ... 15:30 ET "
                   "(bar at t complete, 30-bar warm-up satisfied, exit bar at t+15 inside the session); contract = PILOT_RULE_V1 on the "
                   "contracts quoted at the decision minute with ask > 0 and ask_size >= 1; envelope cap applied (policy-as-is) and "
                   "recorded without the cap as a labelled counterfactual"),
    null_and_assumptions=("null: E[net P&L] <= 0 and the direction label carries no information; quotes at the decision minute are "
                          "executable at the ask for one contract (displayed size >= 1); exit at the +15 minute bid; no queue position; "
                          "fees are the SYNTHETIC fixture schedule (labelled, not a provider's); no assignment/early exercise within 15 minutes"),
    fitting_cadence="NONE: the artifact (EXP-002 L, ca04fc6e713e1a5c) and every policy are frozen; no parameter is estimated",
    parameter_budget=1,
    selection_rule="pre-declared: the policy as shipped; no threshold, strike rule, horizon or fee is varied; the counterfactual without the cap is reported, never selected",
    reporting_family="ECONOMIC_OUTCOME",
    horizon_minutes=15,
    information_cutoff_rule="decision at bar_complete of the bar at t; only quote rows with timestamp <= t are visible; the exit uses exactly the row at t+15",
    dependence_inference=("trades are non-overlapping (15-minute scans, 15-minute holds) but cluster within sessions; the session-block "
                          "bootstrap (resample sessions with replacement, 2000 draws, seed 11) is the declared interval method"),
    search_budget=3,
    planned_comparisons=["POLICY vs WAIT (mean net P&L, session-block bootstrap CI)",
                         "POLICY vs RANDOM_DIRECTION on common rows (paired mean difference)",
                         "POLICY vs REVERSED_DIRECTION on common rows (paired mean difference)",
                         "gross P&L vs total friction (fees + spread crossing) — friction share",
                         "artifact PIT histogram + KS on realized 15-minute log returns (forecast skill, separate family: CALIBRATION)",
                         "cap-free counterfactual: coverage difference and paired result on common rows (labelled, not selected)"],
    planted_signal_fixture="tests/test_backtest_wb.py: a synthetic corpus with a planted deterministic drift proves the engine detects P&L when it exists",
    permutation_control="RANDOM_DIRECTION is the permutation of the direction label under the null that the label carries no information; its inferential authority is limited to that null",
    notes=PERIOD_POLICY,
)


def validated() -> dict:
    return CONTRACT.validate()
