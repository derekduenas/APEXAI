"""PILOT-REPLAY-002 — the FULL FUNNEL against the deterministic rule and WAIT on the SAME population. Declared before access."""
from __future__ import annotations

from apex.worldmodel_wb.study_contract import HistoricalStudyContract

from .contract import PERIOD_POLICY

CONTRACT = HistoricalStudyContract(
    study_id="PILOT-REPLAY-002",
    primary_target="after-cost net P&L per scan (USD, one contract, exit at +15 minutes) of the FULL_FUNNEL system",
    primary_hypothesis=("the full funnel (twin + artifact location + walk-forward GARCH-t variance + causal regime mixture + ATM implied vol + "
                        "joint simulation + expression comparison over nearest-ATM +/-2 strikes both rights + PRIME supervision) does not "
                        "improve mean net P&L over the deterministic pilot rule on common rows, nor over WAIT (null)"),
    comparator="POLICY (deterministic pilot rule, same execution) and WAIT, on the same eligible scans; RANDOM/REVERSED controls retained from REPLAY-001",
    eligible_rows="identical to PILOT-REPLAY-001 (SPY corpus sessions <= 2021-12-31, regular hours, 15-minute scans); the funnel is additionally WAIT when its fits are unavailable (first sessions) and that is counted as coverage, not excluded",
    null_and_assumptions=("GARCH/regime fitted only on prior sessions (trailing 20, pooled 1-minute returns, session boundaries ignored: declared); "
                          "IV held fixed over 15 minutes (expected values are model-conditional, UNESTABLISHED under the M4 rule; the study policy acts on them "
                          "anyway and says so); European approximation for American SPY options at the exit; r = q = 0; simulation N = 2000 paths per scan"),
    fitting_cadence="one GARCH fit and one regime fit per session on prior sessions only; filters rolled forward within the session; budget 400 fits",
    parameter_budget=400,
    selection_rule="pre-declared: best expected net P&L among eligible candidates if > 0 and PRIME does not abstain, else WAIT; no threshold varied",
    reporting_family="ECONOMIC_OUTCOME",
    horizon_minutes=15,
    information_cutoff_rule="as REPLAY-001; fits use sessions strictly before the day; the regime filter and GARCH recursion see only the day's prefix",
    dependence_inference="session-block bootstrap (2000 draws, seed 11) for FULL_FUNNEL vs WAIT; paired differences on common rows vs POLICY",
    search_budget=1,
    planned_comparisons=["FULL_FUNNEL vs POLICY on common rows (paired mean difference, coverage difference disclosed)",
                         "FULL_FUNNEL vs WAIT (session-block bootstrap CI)", "FULL_FUNNEL abstention-reason census and rights census",
                         "gross vs friction for FULL_FUNNEL"],
    planted_signal_fixture="tests/test_backtest_wb.py::test_full_funnel_on_planted_drift",
    permutation_control="RANDOM_DIRECTION from REPLAY-001 (same rows)",
    notes=PERIOD_POLICY + " The funnel's fits are on exposed development data; this is a development study, not prospective evidence.",
)


def validated() -> dict:
    return CONTRACT.validate()
