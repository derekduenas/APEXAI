"""EARNINGS_SESSION_PM_FADE_V1 -- Monster event expert A1. SHADOW.

Hypothesis (mechanism UNKNOWN -- behavioral/flow event effect):
    the regular session AFTER an after-market-close earnings report
    has a systematic intraday fade tendency, regardless of the
    surprise sign.

Formation information: ONLY that a PM earnings report occurred for
this symbol (calendar knowledge sealed in advance). The actual EPS is
NOT required and NOT consulted -- this expert must never quietly
become a surprise expert.

Authority: HISTORICAL=NOMINATED_FROM_AUDIT (born from the Alpha #1
validity audit, aggregate seen once, multiplicity-disclosed),
PROSPECTIVE=NONE, CAPITAL=NONE. decision_power: NONE_PREDATOR.
"""
from __future__ import annotations

from apex.predators.core.opportunity import PredatorOpportunity

ALPHA_ID = "EARNINGS_SESSION_PM_FADE_V1"
BIRTH_UTC = "2026-08-30T20:45:00Z"

# SEALED HISTORY (pm_fade_history.json, +5m entry, SPY-residualized)
SEALED = {
    "n": 1533, "gross_bps_at_5m": 19.6, "median_bps": 15.5,
    "win": 0.532, "pos_years": "7/9",
    "neg_years": {"2018": -14.0, "2019": -11.4},
    "clustered_95ci_bps": (1.8, 37.3), "frac_boot_le0": 0.0155,
    "honesty": "thin vs ~10bps event-time RT: net BASE ~ +10, "
               "STRESS-negative. Economic survival likely requires "
               "the A2 increment to be real.",
}


def evaluate(*, symbol: str, report_date: str, timing: str,
             known_from: str, reaction_session: str,
             rt_cost_bps=None):
    """(PredatorOpportunity | None, opinion record)."""
    base = {"kind": "pm_fade_opinion", "alpha_id": ALPHA_ID,
            "symbol": symbol, "report_date": report_date,
            "reaction_session": reaction_session, "timing": timing,
            "known_from": known_from}
    if timing != "pm":
        return None, {**base, "refusal": "NOT_PM_EVENT"}
    gross = SEALED["gross_bps_at_5m"]
    net = (gross - rt_cost_bps) if isinstance(rt_cost_bps, (int, float)) \
        else "NOT_ESTIMABLE"
    opp = PredatorOpportunity(
        opportunity_id=f"{ALPHA_ID}:{symbol}:{reaction_session}",
        sleeve="EVENT", subject=symbol,
        mechanism="POST_AMC_EARNINGS_SESSION_INTRADAY_FADE "
                  "(MECHANISM_UNKNOWN)",
        first_known_from=known_from, state="WATCH", direction="SHORT",
        domain_evidence=("PM earnings report occurred; actual EPS "
                         "deliberately not consulted",),
        thesis_quality="HISTORICALLY_NOMINATED",
        forecast_status="REPLAY_ONLY",
        forecast_pedigree={"sealed": SEALED,
                           "claim_type": "BASE_EVENT_SESSION_EFFECT",
                           "expected_gross_bps": gross,
                           "rt_cost_bps": rt_cost_bps
                           if rt_cost_bps is not None
                           else "NOT_ESTIMABLE",
                           "expected_net_bps": net,
                           "calibration":
                               "UNCALIBRATED_HISTORICAL_ONLY"},
        expected_return=round(gross / 1e4, 6),
        uncertainty="MODERATE_TWO_NEGATIVE_YEARS",
        historical_support="NOMINATED_FROM_AUDIT_BASELINE",
        n_raw=SEALED["n"],
        execution_feasibility="DEGRADED_VS_OPEN_PRINT",
        attack_class="NO_TRADE", data_quality="CALENDAR_ONLY",
        authority_eligibility="OBSERVE_ONLY")
    return opp, {**base, "emitted": True,
                 "opportunity_id": opp.opportunity_id}
