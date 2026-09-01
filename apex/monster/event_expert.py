"""EARNINGS_NEGATIVE_SURPRISE_DRIFT_V1 -- the first Monster event
expert. SHADOW ONLY.

Mechanism (HYPOTHESIZED, NOT PROVEN):
    incomplete intraday incorporation of negative earnings
    information -> bearish drift through the post-information session.

Authority: HISTORICAL=NOMINATED, PROSPECTIVE=UNPROVEN, CAPITAL=NONE.

The expert emits a PredatorOpportunity (the canonical contract) or a
named refusal. It carries the SEALED audit facts verbatim, including
the adverse ones:

  * the cohort effect at the executable +5m entry (PM subset) was
    +38.6 bps gross, n=215, win 59.1% -- but
  * the surprise-direction INCREMENT over the generic PM earnings-day
    fade was +23.4 bps with a date-clustered 95% CI of [-35, +79]:
    INCREMENTAL INFORMATION VALUE UNPROVEN;
  * edge decays ~55% between the open print and the first executable
    minute -- the open itself belongs to faster participants.

Nothing here sizes, orders, or promotes. decision_power: NONE_PREDATOR.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.predators.core.opportunity import PredatorOpportunity

ALPHA_ID = "EARNINGS_NEGATIVE_SURPRISE_DRIFT_V1"
BIRTH_UTC = "2026-08-30T19:55:00Z"      # prospective eligibility gate

# SEALED HISTORY (validity audit 2026-08-30; never edited in place)
SEALED = {
    "cohort_pm_n": 215,
    "cohort_pm_gross_bps_at_5m": 38.6,
    "cohort_pm_win_at_5m": 0.591,
    "cohort_pm_gross_bps_at_open_unexecutable": 84.3,
    "increment_over_event_day_fade_bps": 23.4,
    "increment_95ci_bps": (-35.0, 79.3),
    "increment_status": "UNPROVEN",
    "am_cohort_gross_bps_at_5m": 8.6,
    "loyo_min_bps": 42.5, "lono_min_bps": 49.0,
    "boot_frac_cohort_mean_below_zero": 0.0045,
}

REFUSALS = ("NO_ESTIMATE", "NO_ACTUAL", "NOT_NEGATIVE_SURPRISE",
            "TIMING_UNKNOWN", "TIMING_NOT_CERTIFIABLE_AM",
            "FORMATION_BEFORE_INFORMATION")


@dataclass(frozen=True)
class EventRecord:
    """One earnings event as the prospective feed delivers it."""
    symbol: str
    report_date: str        # YYYY-MM-DD
    timing: str             # "am" | "pm" | "unknown"
    eps_estimate: float | None
    eps_actual: float | None
    consensus_provenance: str
    known_from: str         # when APEX first knew estimate+actual
    reaction_session: str   # first session with formation eligibility


def classify_surprise(ev: EventRecord) -> str:
    if ev.eps_estimate is None:
        return "UNKNOWN_NO_ESTIMATE"
    if ev.eps_actual is None:
        return "UNKNOWN_NO_ACTUAL"
    d = ev.eps_actual - ev.eps_estimate
    if d < 0:
        return "NEGATIVE"
    if d > 0:
        return "POSITIVE"
    return "SMALL_NEUTRAL"


def evaluate(ev: EventRecord, *, rt_cost_bps=None):
    """Return (PredatorOpportunity | None, refusal_record).

    A refusal is evidence, not silence -- callers must persist it.
    """
    surprise = classify_surprise(ev)
    base = {"kind": "event_expert_opinion", "alpha_id": ALPHA_ID,
            "symbol": ev.symbol, "report_date": ev.report_date,
            "reaction_session": ev.reaction_session,
            "timing": ev.timing, "surprise_class": surprise,
            "known_from": ev.known_from,
            "consensus_provenance": ev.consensus_provenance}
    if surprise == "UNKNOWN_NO_ESTIMATE":
        return None, {**base, "refusal": "NO_ESTIMATE"}
    if surprise == "UNKNOWN_NO_ACTUAL":
        return None, {**base, "refusal": "NO_ACTUAL"}
    if surprise != "NEGATIVE":
        return None, {**base, "refusal": "NOT_NEGATIVE_SURPRISE"}
    if ev.timing == "unknown":
        return None, {**base, "refusal": "TIMING_UNKNOWN",
                      "law": "do not assume the open is "
                             "post-information"}
    if ev.timing == "am":
        # same-session open is only PROBABLY post-information; the
        # audit showed the am cohort near zero -- the expert refuses
        # rather than diluting its prospective record.
        return None, {**base, "refusal": "TIMING_NOT_CERTIFIABLE_AM",
                      "sealed_am_gross_bps": SEALED[
                          "am_cohort_gross_bps_at_5m"]}

    gross = SEALED["cohort_pm_gross_bps_at_5m"]
    net = (gross - rt_cost_bps) if isinstance(rt_cost_bps, (int, float)) \
        else "NOT_ESTIMABLE"
    opp = PredatorOpportunity(
        opportunity_id=f"{ALPHA_ID}:{ev.symbol}:{ev.reaction_session}",
        sleeve="EVENT",
        subject=ev.symbol,
        mechanism="INCOMPLETE_INTRADAY_INCORPORATION_OF_NEGATIVE_"
                  "EARNINGS_INFORMATION (HYPOTHESIZED_NOT_PROVEN)",
        first_known_from=ev.known_from,
        state="WATCH",
        direction="SHORT",
        domain_evidence=(f"actual {ev.eps_actual} vs consensus "
                         f"{ev.eps_estimate} ({ev.consensus_provenance})",
                         "timing pm: information out before formation"),
        thesis_quality="HISTORICALLY_NOMINATED",
        entry_quality="UNKNOWN",
        forecast_status="REPLAY_ONLY",
        forecast_pedigree={
            "sealed": SEALED,
            "horizon": "reaction session close",
            "formation": "first executable minute >= 09:35 ET",
            "claim_type": "INCREMENTAL_OVER_PM_FADE",
            "base_expert": "EARNINGS_SESSION_PM_FADE_V1",
            "expected_gross_bps": gross,
            "of_which_base_pm_fade_bps": 19.6,
            "expected_incremental_gross_bps": SEALED[
                "increment_over_event_day_fade_bps"],
            "incremental_95ci_bps": SEALED["increment_95ci_bps"],
            "rt_cost_bps": rt_cost_bps if rt_cost_bps is not None
            else "NOT_ESTIMABLE",
            "expected_net_bps": net,
            "incremental_information_value": "UNPROVEN",
            "credit_law": "this expert may never inherit credit for "
                          "the generic PM-session effect",
            "calibration": "UNCALIBRATED_HISTORICAL_ONLY"},
        expected_return=round(gross / 1e4, 6),
        uncertainty="HIGH_INCREMENT_CI_SPANS_ZERO",
        historical_support="NOMINATED_SURVIVED_VALIDITY_AUDIT",
        n_raw=SEALED["cohort_pm_n"],
        n_effective_lower_bound=149,     # distinct names in cohort
        execution_feasibility="DEGRADED_VS_OPEN_PRINT",
        attack_class="NO_TRADE",
        data_quality="BROKER_REPORTED_CONSENSUS",
        authority_eligibility="OBSERVE_ONLY",
    )
    return opp, {**base, "emitted": True,
                 "opportunity_id": opp.opportunity_id}
