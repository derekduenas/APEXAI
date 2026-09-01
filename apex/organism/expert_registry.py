"""THE ALPHA EXPERT REGISTRY — every alpha family, as data.

The organism should not have to remember who is alive one conversation
at a time. This is the single queryable roster of alpha experts and
families: economic job, lifecycle status, authority, evidence lineage
(sealed board IDs), and the consult surface if one exists.

LAWS (operator, 2026-08-30):
  * ECONOMIC-JOB-FIRST: an expert exists here only with a defined
    economic job. A component whose registered jobs are all KILLED is
    RETIRED; proposing a new job for it requires an INDEPENDENT
    observation (no job-shopping).
  * NO FAKE EXPERTS: a family without an earned mechanism is
    NOT_IMPLEMENTED, and stays visible as such -- honesty about
    absence is part of the roster.
  * Status here mirrors SEALED board verdicts. Changing a status is a
    governance act referencing a seal, never a convenience edit.

decision_power: NONE_DECLARATION.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

JOBS = ("ALPHA_GENERATOR", "SELECTOR", "INCREMENTAL_SPECIALIST",
        "VETO", "SIZER", "EXPRESSION_ADVISOR", "REGIME_COMPATIBILITY",
        "POSITION_MANAGEMENT")

STATUSES = ("ACTIVE_PROSPECTIVE_SHADOW",   # frozen Lane-A combatants
            "ACTIVE_LIVE_PAPER",           # running paper loop
            "ACTIVE_SHADOW",               # running, evidence-only
            "REGISTERED_UNBUILT",          # sealed design, no code
            "ANOMALY_ONLY",                # recorded, no testing rights
            "KILLED",                      # sealed kill verdict
            "RETIRED",                     # all jobs killed
            "NOT_IMPLEMENTED")             # honest absence


@dataclass(frozen=True)
class AlphaExpert:
    expert_id: str
    family: str
    mechanism: str
    economic_job: str
    status: str
    authority: str
    evidence: tuple            # sealed board IDs / ledgers
    consult: str               # module path, or "" if none
    note: str = ""

    def __post_init__(self):
        if self.economic_job not in JOBS:
            raise ValueError(f"{self.expert_id}: bad job")
        if self.status not in STATUSES:
            raise ValueError(f"{self.expert_id}: bad status")

    def as_record(self) -> dict:
        return {"kind": "alpha_expert", **asdict(self)}


ROSTER = (
    # ---------------- ACTIVE (each with real machinery behind it)
    AlphaExpert(
        "EVENT_PM_FADE_A1", "EVENT_INFORMATION",
        "AMC-earnings next-session fade; actual EPS never consulted",
        "ALPHA_GENERATOR", "ACTIVE_PROSPECTIVE_SHADOW",
        "OBSERVE_ONLY -- frozen Lane-A combatant",
        ("EARNINGS_SESSION_PM_FADE_V1", "COMBAT-WEEK-1-FREEZE"),
        "apex.monster.pm_fade_expert",
        "sealed history +19.6 gross at +5m, n=1533, CI (1.8,37.3); "
        "thin vs ~10bps RT -- the future is grading it now"),
    AlphaExpert(
        "EVENT_NEG_SURPRISE_A2", "EVENT_INFORMATION",
        "negative-surprise increment OVER A1; increment-only credit",
        "INCREMENTAL_SPECIALIST", "ACTIVE_PROSPECTIVE_SHADOW",
        "OBSERVE_ONLY -- frozen Lane-A combatant",
        ("EVENT-NEG-DRIFT-VALIDITY-VERDICT", "FIRST-ALPHA-TOURNAMENT"),
        "apex.monster.event_expert",
        "increment +23.4 with CI (-35.0,+79.3): UNPROVEN, on trial"),
    AlphaExpert(
        "BTC_FORCED_ACTION", "FORCED_FLOW",
        "participant-state + forced-action thesis on BTC 15-min "
        "windows", "ALPHA_GENERATOR", "ACTIVE_LIVE_PAPER",
        "PAPER_EXPLORATORY (cohort law; sealed windows)",
        ("BTC-L3", "apex-btc-paper.service"),
        "apex.btc_sleeve.forced_action",
        "prospective combat loop live since 2026-08-24"),
    AlphaExpert(
        "EQUITY_INCUMBENT_HUNTER", "PRICE_FLOW",
        "frozen incumbent intraday hunter over the sealed 46-name "
        "universe", "ALPHA_GENERATOR", "ACTIVE_SHADOW",
        "SHADOW_ONLY (frozen by test)",
        ("apex-equity-shadow.service",),
        "apex.predators.equities.day_trader",
        "incumbent frozen; V2 faculties shadow-scaffolded"),
    AlphaExpert(
        "OPTIONS_VRP_SLEEVE", "VOLATILITY",
        "options paper sleeve; expression via real NBBO only",
        "ALPHA_GENERATOR", "ACTIVE_SHADOW",
        "PAPER via outbox -> allocator",
        ("results/outbox/v1_decisions.jsonl",),
        "apex.predators.options",
        "mid P&L -338 vs friction 15,318: execution IS the alpha"),
    # ---------------- REGISTERED, UNBUILT (future grades the repair)
    AlphaExpert(
        "NEG_SURPRISE_SELECTOR_V2", "EVENT_INFORMATION",
        "successor selector; corpus burned, prospective-only",
        "SELECTOR", "REGISTERED_UNBUILT",
        "NONE until Week-1 acceptance",
        ("EARNINGS_NEGATIVE_SURPRISE_SELECTOR_V2",), "",
        "may not be tested on the corpus that generated it"),
    # ---------------- ANOMALY_ONLY (recorded, no testing rights)
    AlphaExpert(
        "RV_EXTREME_NON_EVENT_FADE", "RELATIVE_VALUE",
        "extreme non-event residual fade t+5",
        "ALPHA_GENERATOR", "ANOMALY_ONLY", "NONE",
        ("RELATIVE-VALUE-LAB-RV1-VERDICT",), "",
        "clustered CI spans zero; MARA 30.6%; recency negative"),
    AlphaExpert(
        "H5_S15_EXTREME_BEARISH_CONTEXT", "STATISTICAL",
        "frozen-H5 s15 extreme-bearish context on PM events",
        "SELECTOR", "ANOMALY_ONLY", "NONE",
        ("H5-SELECTOR-LAB-HS1-VERDICT-2026-08-30",), "",
        "zero-authority prospective tag eligible post-acceptance; "
        "if outcomes do not differ, bury permanently"),
    AlphaExpert(
        "DOWN_GAP_HUMP", "EVENT_INFORMATION",
        "peer down-gap hump (E-P2 prospective-first)",
        "ALPHA_GENERATOR", "ANOMALY_ONLY", "NONE",
        ("PROPAGATION-LAB-E-P2-REGISTRATION",), "",
        "corpus burned; prospective collector is the only path"),
    # ---------------- KILLED / RETIRED (graveyard authority)
    AlphaExpert(
        "H5_STATISTICAL", "STATISTICAL",
        "ridge state-forecaster", "ALPHA_GENERATOR", "RETIRED",
        "NONE -- all jobs killed",
        ("H5-SELECTOR-LAB-HS1-VERDICT-2026-08-30",
         "ECONOMIC-JOB-FIRST-LAW-2026-08-30"), "",
        "ALPHA_GENERATOR killed; SELECTOR killed; no job-shopping"),
    AlphaExpert(
        "PEER_INTRADAY_PROPAGATION", "PEER_PROPAGATION",
        "same-session SIC-peer propagation", "ALPHA_GENERATOR",
        "KILLED", "NONE", ("PROPAGATION-LAB-E-P1-VERDICT",), "",
        "-13.1 net across all 49 cells"),
    AlphaExpert(
        "OPEX_CALENDAR_FLOW", "FORCED_FLOW",
        "post-OPEX drift / OPEX-week / pinning", "ALPHA_GENERATOR",
        "KILLED", "NONE", ("FORCED-FLOW-LAB-F1-VERDICT-2026-08-30",),
        "", "matched-month baseline killed it; no dealer footprint"),
    # ---------------- honest absences
    AlphaExpert(
        "VOLATILITY_RV", "VOLATILITY",
        "vol relative value", "ALPHA_GENERATOR", "NOT_IMPLEMENTED",
        "NONE", (), "",
        "awaits real prospective option-surface history; sparse "
        "historical NBBO breeds imaginary options alpha"),
    AlphaExpert(
        "CONTINUATION", "PRICE_FLOW", "generic continuation",
        "ALPHA_GENERATOR", "NOT_IMPLEMENTED", "NONE", (), "",
        "no earned mechanism"),
    AlphaExpert(
        "REVERSAL", "PRICE_FLOW", "generic reversal",
        "ALPHA_GENERATOR", "NOT_IMPLEMENTED", "NONE", (), "",
        "no earned mechanism"),
    AlphaExpert(
        "BTC_LIQUIDATION_CASCADE", "FORCED_FLOW",
        "crypto liquidation cascades", "ALPHA_GENERATOR",
        "NOT_IMPLEMENTED", "NONE", (), "",
        "factory may research; not earned yet"),
    AlphaExpert(
        "MULTI_SESSION_DIFFUSION", "EVENT_INFORMATION",
        "multi-session information diffusion", "ALPHA_GENERATOR",
        "NOT_IMPLEMENTED", "NONE", (), "",
        "E-P2 collects prospectively first"),
)


def roster() -> tuple:
    return ROSTER


def active() -> tuple:
    return tuple(e for e in ROSTER if e.status.startswith("ACTIVE"))


def graveyard() -> tuple:
    return tuple(e for e in ROSTER
                 if e.status in ("KILLED", "RETIRED"))


def by_family() -> dict:
    out: dict = {}
    for e in ROSTER:
        out.setdefault(e.family, []).append(e.as_record())
    return out


def summary() -> dict:
    counts: dict = {}
    for e in ROSTER:
        counts[e.status] = counts.get(e.status, 0) + 1
    return {"kind": "expert_registry_summary",
            "experts": len(ROSTER), "by_status": counts,
            "active": [e.expert_id for e in active()],
            "law": "no fake experts; graveyard authority is respected",
            "decision_power": "NONE_DECLARATION"}
