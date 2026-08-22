#!/usr/bin/env python
"""FRONTIER2_SHADOW_RUNTIME -- the first live process consuming
apex.frontier2. A parallel, read-only, observation-only cycle: reads
ONLY canonical already-persisted production artifacts (Alpaca's own
persisted bar files, the Alpaca daemon's own health/coverage JSON,
Hunter's own forward_ledger watchlist), computes the Frontier-2 organs
in dependency order, and writes EXCLUSIVELY under results/frontier2/.

    python scripts/frontier2_shadow_runtime.py [--minutes 390] [--cadence 20]

THE LAW THIS SCRIPT ENFORCES, not just states: the apex.frontier2
PACKAGE never imports apex.hunter, apex.captain, apex.execution, or
apex.frontier (Desk B) -- verified by tests/test_frontier2_firewall.py.
This SCRIPT is the sanctioned orchestrator ABOVE the firewall: it reads
apex.hunter.session_coverage (canonical coverage) and -- since Profit
Predator v1, 2026-08-20 -- invokes apex.hunter.capital at CP11 and
apex.options_research at CP12/CP13, because the funnel Captain ->
Capital -> Expression -> BEFORE card must flow through SOMETHING and
the organs themselves may not import each other. Capital remains
sovereign and fail-closed; broker execution is not imported by anything
on this path. It never recomputes VWAP/gap/opening-range/
RVOL/minutes_into_session independently -- ParticipantPressure's
Hunter-specific inputs (or_break_up/down/failure, vwap_reclaim/
rejection, rvol_tod) stay None/UNKNOWN in this version because no
canonical PER-SYMBOL ChartState feed is readable from outside
apex.hunter yet; that is an honest gap, not a shortcut, and is reported
as such rather than reimplemented.

decision_power = NONE_FRONTIER_SHADOW everywhere. This process cannot
write to Hunter, Captain, Capital, Shadow Paper, Execution, or DATA-2
artifacts -- it does not even import the modules that could.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

import pandas as pd  # noqa: E402

from apex.governance.service_progress import (  # noqa: E402
    ServiceProgressState, is_pid_alive, start as sp_start, write as sp_write,
)
from apex.hunter.session_coverage import compute_session_coverage  # noqa: E402
from apex.intraday.alpaca_fabric import load_live_bars  # noqa: E402
from apex.intraday.universe_coverage import UniverseCoverageState  # noqa: E402

from apex.intraday import feature_sufficiency as fsmod  # noqa: E402
from apex.market_state import cross_section as msx  # noqa: E402

from apex.frontier2 import FRONTIER2_POWER  # noqa: E402
from apex.frontier2 import event_bus2 as eb2  # noqa: E402
from apex.frontier2 import assassin2, captain_shadow, curve  # noqa: E402
from apex.frontier2 import expectation_violation as evmod  # noqa: E402
from apex.frontier2 import leading_edge_map as lemod  # noqa: E402
from apex.frontier2 import model_market as mmod  # noqa: E402
from apex.frontier2 import observation_integrity as oimod  # noqa: E402
from apex.frontier2 import opportunity_graph as ogmod  # noqa: E402
from apex.frontier2 import participant_pressure as ppmod  # noqa: E402
from apex.frontier2 import propagation as propmod  # noqa: E402
from apex.frontier2 import reunderwrite_ledger as rlmod  # noqa: E402
from apex.frontier2 import reunderwrite_trigger as rumod  # noqa: E402
from apex.frontier2 import system_cognition as sysc  # noqa: E402
from apex.frontier2.compute_router2 import route as compute_route  # noqa: E402
from apex.frontier2.learning_registry2 import preregister  # noqa: E402

SERVICE_NAME = "frontier2_shadow_runtime"
RUNTIME_STATE_PATH = Path("results/frontier2/runtime/service_progress.json")
ERRORS_LEDGER = Path("results/frontier2/errors/error_ledger.jsonl")
BIRTH_LEDGER = Path("results/frontier2/runtime_birth.jsonl")
COVERAGE_ARTIFACT = Path("results/intraday/universe_coverage.json")

MARKET_PROXY = "SPY"
INDEX_ETFS = ("SPY", "QQQ", "IWM")
# V2 (2026-08-20): SIGMA_MAX_RETURNS(30) trailing returns for the
# curvature null + the newest bar = 31 points. Early-session cycles with
# fewer than MIN_POINTS_FOR_CURVATURE(10) bars are INSUFFICIENT_HISTORY
# by design, never a guess. Velocity keeps its own 6-point sub-window
# inside curve.compute_dimension.
CURVE_WINDOW = 31
FUNNEL_LEDGER = Path("results/frontier2/expression_funnel_ledger.jsonl")
RUNTIME_VERSION = "frontier2_shadow_runtime_v1"
SCHEMA_VERSIONS = {
    "curve": "frontier2_curve_v1", "observation_integrity": "frontier2_oi_v1",
    "captain_shadow": "frontier2_captain_shadow_v1",
}


class RuntimeState:
    """In-process memory across cycles -- NOT persisted as a single blob
    (every organ's own persist() already chains its own ledger); this
    just holds enough to diff against for typed event emission and to
    avoid recomputing what hasn't changed."""

    def __init__(self):
        self.captain_state = {}          # subject -> CaptainFrontierShadowState
        self.graph = {}                  # subject -> OpportunityIntelligenceGraph
        self.last_curve_state = {}       # subject -> high_level_state
        self.leading_edge = {}           # subject -> {rank, entry_quality}
        self.first_canonical_input = None
        self.first_regular_session_input = None
        self.first_successful_cycle = None
        self.birth_minted = False
        # --- re-underwriting bookkeeping (Phase 1.0, 2026-08-18) ---
        self.captain_inputs = {}         # subject -> last input snapshot dict
        self.last_review_time = {}       # subject -> pd.Timestamp of last review
        self.review_number = {}          # subject -> int, monotone per candidate
        self.candidate_id = {}           # subject -> current thesis lineage id
        self.thesis_generation = {}      # subject -> int, bumped past INVALIDATE
        self.last_assassin = {}          # subject -> Assassin2 state
        # TIER-OSCILLATION GUARD (audit finding, 2026-08-18). EV/PP/
        # Propagation only compute at route.tier >= 2. When a subject
        # falls back to tier 1 they stop being computed, and substituting
        # "UNKNOWN" into the trigger snapshot reads as a material change
        # even though the market did not move -- a self-sustaining
        # review loop driven by our own compute budget. Same class as the
        # assassin phantom fixed in Phase 1.0. Carry the LAST COMPUTED
        # value instead, so "not computed this cycle" never masquerades
        # as "changed to unknown".
        self.last_ev = {}                # subject -> ExpectationViolation
        self.last_pp = {}                # subject -> ParticipantPressure
        self.last_edge = {}              # subject -> PropagationEdge


def _ledger_error(operation: str, exc: BaseException, ledger: str) -> None:
    """Durable record for a NON-FATAL swallowed failure. The loop still
    continues -- but the failure no longer exists only in stdout."""
    try:
        from apex.governance.ledger_error import record
        record(service=SERVICE_NAME, operation=operation, exc=exc,
               ledger=ledger,
               recovery_action="cycle continues; this input reads UNKNOWN")
    except Exception:                                       # noqa: BLE001
        pass


def _run_expression_funnel(*, symbol: str, candidate_id: str, cs, c,
                           price_pts: list, now, known_from) -> dict:
    """CP11 CAPITAL -> CP12 EXPRESSION -> CP13 BEFORE CARD, shadow-only.

    Every stage's verdict is persisted, including refusals -- the point
    is that an escalated opportunity's fate is always attributable to a
    NAMED checkpoint decision, never to silence. Broker execution does
    not exist on this path (nothing here can place anything anywhere).
    """
    from apex.hunter.capital import (
        ForecastSlot, PortfolioState, evaluate_candidate,
    )
    from apex.options_research import before_card as bcmod
    from apex.options_research import expression_engine as exmod

    # ---- CP11: CAPITAL (sovereign, fail-closed). A frontier2
    # opportunity is not a playbook candidate: no entry/stop/target, no
    # FORWARD_ELIGIBLE forecast. Capital's honest verdict on it TODAY is
    # REFUSED, with the governance reasons in the record. Reachability
    # proven; authority never fabricated.
    # ---- FORECAST LAYER (living-organism diagnostic, 2026-08-21).
    # The empirical ForwardDistribution is computed for VISIBILITY on
    # every escalation -- its blockers become part of the terminal
    # record, so "why did Capital refuse" is answered by evidence, not
    # by an empty default slot. THE AUTHORITY GUARD: only a
    # FORECAST_CALIBRATED distribution may ever fill the ForecastSlot,
    # and calibration requires demonstrated out-of-sample Brier skill --
    # structurally impossible until prediction/outcome pairs accumulate.
    # Anything less keeps the slot at NOT_YET_AVAILABLE, so no
    # Observatory-derived number can influence Capital before it has
    # EARNED calibration.
    forecast_rec = None
    slot = ForecastSlot()
    try:
        from apex.forecast import FORECAST_CALIBRATED
        from apex.forecast import forward_distribution as fdmod
        from apex.pattern_observatory import memory as pomem
        from apex.pattern_observatory import resolution as pores
        from apex.pattern_observatory import support as posup
        prows = pomem.read(pomem.PATTERN_LEDGER)
        fams = sorted({r.get("family_id") for r in prows
                       if r.get("subject") == symbol
                       and r.get("family_id")})
        if fams:
            orows = pomem.read(pomem.OUTCOME_LEDGER)
            fam = fams[-1]
            fd = fdmod.build(
                family_id=fam, subject=symbol,
                horizon_minutes=pores.LEAD_HORIZON_MIN,
                corpus=pores.outcome_corpus(
                    orows, family_id=fam,
                    horizon_minutes=pores.LEAD_HORIZON_MIN, as_of=now),
                support=posup.aggregate(prows, family_id=fam,
                                        as_of=now),
                as_of=now, known_from=known_from)
        else:
            fd = fdmod.build(
                family_id="SUBJECT_LEVEL_FAMILY_NOT_YET_DEFINED",
                subject=symbol, horizon_minutes=30,
                corpus={"returns": []}, support={},
                as_of=now, known_from=known_from)
        forecast_rec = fd.as_record()
        if fd.status == FORECAST_CALIBRATED:
            # future path; unreachable until calibration is earned
            slot = ForecastSlot(status="AVAILABLE", estimate=forecast_rec)
    except Exception as e:  # noqa: BLE001
        _record_error(0, "forecast_layer", e, input_refs=(symbol,),
                     known_from=known_from)

    portfolio = PortfolioState(nav=0.0, positions={}, sector_weights={},
                               heat=0.0, drawdown_budget_left=1.0,
                               sleeve_correlations={})
    cap = evaluate_candidate(
        {"decision_id": f"{candidate_id}@{now}", "symbol": symbol,
         "playbook_id": "FRONTIER2_SHADOW",
         "forward_eligibility": "SHADOW_NOT_FORWARD_ELIGIBLE"},
        sector=None, median_dollar_volume=None, ann_vol=None,
        market_uncertain=False, forecast=slot,
        portfolio=portfolio)

    # ---- CP12: EXPRESSION. NO_TRADE is a first-class always-present
    # candidate inside run(). Since 2026-08-21 the CANONICAL option
    # chain feeds real candidates through chain_adapter (one feed,
    # multiple consumers) -- when the feed is fresh, a real directional
    # option structure competes against EQUITY and NO_TRADE through
    # every eligibility gate; when it is stale or empty, the adapter
    # refuses and the engine records why no option was offered.
    from apex.options_research import chain_adapter as camod
    entry_px = float(price_pts[-1][1]) if price_pts else None
    opt_cands, surface_state, cand_dte = (), None, None
    try:
        direction = getattr(c, "transition_direction", "UNKNOWN")
        if direction in ("UP", "DOWN"):
            chain = camod.load_chain(symbol, now=now)
            cand = camod.build_candidate(
                symbol, direction, thesis_id=f"{candidate_id}@{now}",
                now=now, known_from=known_from, chain=chain)
            if cand is not None:
                opt_cands = (cand,)
                import pandas as pd
                cand_dte = (pd.Timestamp(cand.expiry).date()
                            - pd.Timestamp(now).tz_convert("UTC").date()
                            ).days
                pick = camod.select_directional(chain, direction, now=now)
                if pick is not None:
                    surface_state = camod.build_surface_for(
                        symbol, pick, chain, now=now, known_from=known_from)
    except Exception as e:  # noqa: BLE001
        _record_error(0, "chain_adapter", e, input_refs=(symbol,),
                     known_from=known_from)

    dec = exmod.run(subject=symbol, now=now, known_from=known_from,
                    hunter_present=False, frontier_present=True,
                    stock_entry_price=entry_px,
                    option_candidates=opt_cands,
                    surface_state=surface_state,
                    candidate_dte=cand_dte,
                    expected_realization_minutes=30.0,
                    timing_uncertainty_minutes=30.0)

    # ---- CP13: BEFORE CARD, sealed outcome-blind.
    eligible = tuple(cand["expression_type"] for cand in dec.candidates)
    rejected = tuple({"expression_type": r.get("candidate_expression_type"),
                      "gate": r.get("gate"), "reason": r.get("reason")}
                     for r in dec.refusals)
    card = bcmod.seal(
        opportunity_id=f"{candidate_id}@{now}", subject=symbol,
        known_from=known_from, underlying_thesis=dec.thesis,
        direction_quality=cs.direction_quality,
        transition_quality=cs.transition_quality,
        horizon=(dec.horizon_check or {"status": "NOT_OFFERED"}),
        surface_snapshot={"status": "NOT_SUPPLIED_SHADOW_V1"},
        cohort=dec.cohort, eligible_structures=eligible,
        rejected_structures=rejected,
        # STRUCTURAL ranking, outcome-blind: without a calibrated
        # forecast NO_TRADE outranks every position regardless of which
        # structures survived the eligibility gates -- surviving a gate
        # earns a place in the comparison, never an authorization.
        shadow_expression_ranking=("NO_TRADE",) + tuple(
            e for e in eligible if e != "NO_TRADE"),
        ranking_rationale=(f"no calibrated forecast: NO_TRADE outranks "
                          f"all {len(eligible) - 1} surviving "
                          f"structure(s); option candidates offered: "
                          f"{len(opt_cands)}"),
        now=now)

    # CP14: the terminal decision, EXPLICIT. Distinguishes
    # NO_TRADE_DECISION from PIPELINE_NEVER_REACHED_EXPRESSION forever.
    rec = {"kind": "expression_funnel_terminal", "subject": symbol,
           "opportunity_id": f"{candidate_id}@{now}",
           "captain_state": cs.state,
           "capital_verdict": cap.final_state,
           "capital_reasons": list(cap.reason_codes),
           "forecast": forecast_rec,
           "terminal_decision": "NO_TRADE_DECISION",
           "before_card_sealed": True,
           "as_of": str(now), "known_from": str(known_from),
           "decision_power": FRONTIER2_POWER}
    with open(FUNNEL_LEDGER, "a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return rec


def build_observed_inputs(*, curve, ev, pp, edge, oi, sc, a2,
                          leading_edge=None) -> dict:
    """THE TRIGGER COMPARISON SNAPSHOT -- module-level and pure so the
    phantom-trigger law can be proven BEHAVIOURALLY, not by scanning
    source text for a comment.

    Two phantom classes have already been caught here, and both were the
    same bug: a key whose value depended on whether APEX chose to compute
    something this cycle, rather than on what the market did.

      * ASSASSIN_WOUND_CHANGE fired every cycle because the assassin keys
        were absent from the new snapshot while present in the stored
        prior one -- absence masqueraded as SEVERE -> None.
      * EV / PARTICIPANT / PROPAGATION would fire on a compute-tier drop,
        because those organs only run at route.tier >= 2 and "not computed"
        was being written as "UNKNOWN".

    THE LAW: every key is always present, and a value is only ever
    "UNKNOWN"/"NONE" when it is genuinely unknown -- never merely
    not-recomputed-this-cycle. The caller is responsible for carrying
    forward the last computed ev/pp/edge before calling this (see the
    TIER-OSCILLATION GUARD in RuntimeState); this function then has no way
    to tell a carried value from a fresh one, which is the point.
    """
    return {
        "curve_state": curve.high_level_state,
        "curve_direction": curve.transition_direction,
        "curve_expression": curve.expression,
        "curve_likelihood": curve.transition_likelihood,
        "expectation_violation_state": ev.state if ev else "UNKNOWN",
        "participant_trap": pp.trap_state if pp else "NONE",
        "participant_direction": pp.pressure_direction if pp else "UNKNOWN",
        "propagation_state": edge.status if edge else "UNKNOWN",
        # Phase 8 (2026-08-20): no longer a hardcoded "UNKNOWN" -- fed
        # from the PRIOR cycle's LeadingEdgeMap rank (no lookahead:
        # ranking runs after the symbol loop, so this cycle's rank can
        # only inform the next). UNKNOWN remains the honest value when
        # the symbol was not in any ranked transition.
        "leading_edge_rank": (leading_edge or {}).get("rank", "UNKNOWN"),
        "leading_edge_entry_quality": (leading_edge or {}).get(
            "entry_quality", "UNKNOWN"),
        "observation_quality": oi.quality,
        "system_cognition_state": sc.overall_quality,
        "model_market_tally_agrees": None,
        "assassin2_familiarity": (a2.familiarity if a2 else "UNKNOWN"),
        "assassin2_caution_label": (a2.caution_label if a2 else "NONE"),
    }


def _record_error(cycle: int, module: str, exc: Exception, *, input_refs: tuple,
                  known_from) -> dict:
    rec = {"kind": "frontier2_runtime_error", "cycle": cycle, "module": module,
          "input_references": list(input_refs),
          "exception": f"{type(exc).__name__}: {exc}",
          "traceback": traceback.format_exc(), "known_from": str(known_from),
          "recovery_action": "cycle continues; this module's output for this "
          "subject is skipped this cycle only", "decision_power": FRONTIER2_POWER}
    ERRORS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with ERRORS_LEDGER.open("a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return rec


def _mint_birth(now, first_input_ref: str) -> None:
    BIRTH_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    entry = {
        "kind": "frontier2_live_runtime_birth",
        "runtime_version": RUNTIME_VERSION,
        "code_lineage": "apex/frontier2/* as built 2026-08-17/18 (16 modules, "
                        "270 offline tests, 3 synthetic movies -- all SYNTHETIC, "
                        "none of which validate this live runtime)",
        "runtime_start": str(now), "first_canonical_input": first_input_ref,
        "first_successful_cycle": str(now),
        "known_from": str(now),
        "data_provider_lineage": "ALPACA_WEBSOCKET_SIP_V1 (PRIMARY_BROAD_SENSOR) "
                                 "via apex.intraday.alpaca_fabric's persisted bar "
                                 "files -- this runtime reads no raw websocket "
                                 "message directly",
        "schema_versions": SCHEMA_VERSIONS,
        "decision_power": FRONTIER2_POWER, "capital_authority": "NONE",
        "broker_authority": "NONE",
        "retroactive_validity": False,
        "retroactive_validity_note": ("this birth does NOT validate any "
                                      "observation before runtime_start -- "
                                      "premarket and 09:30 are NOT backfilled"),
    }
    _chain_append(BIRTH_LEDGER, entry)


SESSION_TRANSITION_LEDGER = Path("results/frontier2/session_transition.jsonl")


def _append_session_transition(state, now) -> None:
    """One durable record of the premarket -> regular-session handover,
    written the first time the runtime observes a REGULAR-session cycle.
    Proves (or refutes) that the 09:00 premarket lineage carried into the
    session cleanly instead of stale premarket state surviving the bell."""
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    SESSION_TRANSITION_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(SESSION_TRANSITION_LEDGER, {
        "kind": "frontier2_session_transition",
        "first_regular_session_input": state.first_regular_session_input,
        "premarket_lineage_start": state.first_canonical_input,
        "captain_states_carried_in": {
            k: v.state for k, v in state.captain_state.items()},
        "observed_at": str(now),
        "note": ("captain_states_carried_in are the PREMARKET verdicts alive "
                "at the bell -- each must still be re-underwritten on its own "
                "trigger during the regular session, never trusted as-is"),
        "decision_power": FRONTIER2_POWER,
    })


def _watchlist(today: str) -> tuple:
    """Hunter's own current watchlist, read from the canonical
    forward_ledger -- never re-derived. Absent -> just the index proxies."""
    path = Path("results/hunter/forward_ledger.jsonl")
    watch = set()
    if path.exists():
        try:
            size = path.stat().st_size
            with path.open("rb") as fh:
                fh.seek(max(0, size - 65536))
                tail = fh.read().decode("utf-8", errors="replace")
            for line in reversed(tail.splitlines()):
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("kind") == "scan":
                    for w in d.get("watchlist", []):
                        sym = w.get("symbol") if isinstance(w, dict) else w
                        if sym:
                            watch.add(str(sym).replace(".US", ""))
                    break
        except OSError:
            pass
    return tuple(sorted(set(INDEX_ETFS) | watch))


def _read_observation_integrity(now, known_from) -> "oimod.ObservationIntegrityState":
    spy_bars = load_live_bars(MARKET_PROXY, str(now.date()))
    session_cov = None
    if spy_bars is not None and len(spy_bars):
        try:
            session_cov = compute_session_coverage(
                spy_bars.rename(columns={"event_time_utc": "event_time_utc"}),
                str(now.date()), now, transport_source="ALPACA_WEBSOCKET_SIP_V1",
                known_from=str(known_from))
        except Exception:  # noqa: BLE001
            session_cov = None

    uc = None
    if COVERAGE_ARTIFACT.exists():
        try:
            raw = json.loads(COVERAGE_ARTIFACT.read_text())
            fields = {f: raw.get(f) for f in UniverseCoverageState.__dataclass_fields__}
            for tf in ("intended_universe", "authorized_universe",
                      "streamed_universe", "continuous_universe",
                      "rotated_universe", "never_observed"):
                if fields.get(tf) is not None:
                    fields[tf] = tuple(fields[tf])
            uc = UniverseCoverageState(**fields)
        except Exception:  # noqa: BLE001
            uc = None

    return oimod.compute(session_coverage=session_cov, universe_coverage=uc,
                         as_of=now, known_from=known_from)


def _read_system_cognition(oi, now, known_from) -> "sysc.SystemCognitionState":
    provider_health = trade_cov = quote_cov = None
    health_path = Path("results/intraday/alpaca_fabric_health.json")
    if health_path.exists():
        try:
            h = json.loads(health_path.read_text())
            provider_health = h.get("status")
            n = h.get("symbol_count") or 1
            trade_cov = ("FULL" if (h.get("trade_symbols_accepted") or 0) >= n
                        else "PARTIAL")
            quote_cov = ("FULL" if (h.get("quote_symbols_accepted") or 0) >= n
                        else "PARTIAL")
        except Exception as _e:  # noqa: BLE001
            _ledger_error("HEALTH_READ", _e, "alpaca_fabric_health.json")
    service_progress = None
    sp_path = Path("results/frontier/service_progress.json")
    if sp_path.exists():
        try:
            service_progress = json.loads(sp_path.read_text()).get("progress_status")
        except Exception as _e:  # noqa: BLE001
            _ledger_error("ARTIFACT_READ", _e, "frontier/service_progress.json")
    return sysc.assess(observation_integrity=oi, subject="SYSTEM",
                       provider_health=provider_health, trade_coverage=trade_cov,
                       quote_coverage=quote_cov, service_progress=service_progress,
                       known_from=known_from, now=now)


def _price_points(symbol: str, today: str, now) -> list:
    bars = load_live_bars(symbol, today)
    if bars is None or not len(bars):
        return []
    recent = bars.tail(CURVE_WINDOW)
    return [(row["event_time_utc"], float(row["close"]))
           for _, row in recent.iterrows()]


def _excess_points(symbol: str, market: str, today: str, now) -> list:
    sym_bars, mkt_bars = load_live_bars(symbol, today), load_live_bars(market, today)
    if sym_bars is None or mkt_bars is None or not len(sym_bars) or not len(mkt_bars):
        return []
    merged = pd.merge(sym_bars[["event_time_utc", "close"]],
                      mkt_bars[["event_time_utc", "close"]],
                      on="event_time_utc", suffixes=("_sym", "_mkt")).tail(CURVE_WINDOW)
    if merged.empty:
        return []
    sym0, mkt0 = merged["close_sym"].iloc[0], merged["close_mkt"].iloc[0]
    out = []
    for _, row in merged.iterrows():
        excess = (row["close_sym"] / sym0 - 1) - (row["close_mkt"] / mkt0 - 1)
        out.append((row["event_time_utc"], float(excess)))
    return out


def _returns(symbol: str, today: str) -> list:
    bars = load_live_bars(symbol, today)
    if bars is None or len(bars) < 2:
        return []
    closes = bars["close"].astype(float).to_numpy()
    return list((closes[1:] - closes[:-1]) / closes[:-1])


def run_cycle(state: RuntimeState, cycle: int, now) -> dict:
    known_from = now
    # ET session date, NOT the UTC date (2026-08-21 living-organism
    # diagnostic): str(now.date()) on a UTC clock rolls to tomorrow at
    # 20:00 ET, so any post-8pm cycle looked for bar files that do not
    # exist yet. The Observatory runtime already did this correctly.
    today = str(now.tz_convert("America/New_York").date())
    out = {"subjects": {}, "errors": 0}

    oi = _read_observation_integrity(now, known_from)
    if state.first_canonical_input is None and oi.quality != "UNKNOWN":
        state.first_canonical_input = f"observation_integrity@{now}"

    # FIRST REGULAR-SESSION INPUT (Phase 1.1, operator request #2).
    # With a 09:00 ET premarket start, first_canonical_input is now a
    # PREMARKET observation. Tomorrow we also need to know the exact
    # first REGULAR-session canonical input, to confirm the premarket
    # lineage transitions cleanly through the bell rather than carrying
    # stale premarket assumptions into the session.
    if state.first_regular_session_input is None:
        try:
            from apex.intraday.sessions import Session, classify
            if classify(now) is Session.REGULAR and oi.quality != "UNKNOWN":
                state.first_regular_session_input = {
                    "observed_at": str(now),
                    "observation_quality": oi.quality,
                    "premarket_lineage_start": state.first_canonical_input,
                }
                _append_session_transition(state, now)
        except Exception as e:  # noqa: BLE001
            _record_error(cycle, "first_regular_session_input", e,
                         input_refs=(), known_from=known_from)
    sc = _read_system_cognition(oi, now, known_from)
    try:
        sysc.persist(sc)
    except Exception as e:  # noqa: BLE001
        _record_error(cycle, "system_cognition_persist", e, input_refs=(),
                     known_from=known_from)

    # CANONICAL CROSS-SECTIONAL DIMENSIONS (Phase 3/4, 2026-08-20).
    # Built ONCE per cycle from apex.market_state -- the shared sensory
    # layer both this runtime and Pattern Observatory may read -- and
    # fed to every subject's Curve as the sector_leadership and breadth
    # dimensions. An insufficient series yields [] and the dimension
    # lands NO_SUPPORT: support is never fabricated.
    try:
        _msx = msx.build(today, now=now)
        slead_pts = msx.curve_points(_msx["sector_leadership"],
                                     window=CURVE_WINDOW)
        breadth_pts = msx.curve_points(_msx["breadth"], window=CURVE_WINDOW)
        msx_reasons = {
            "sector_leadership": (None if slead_pts else
                                  f"market_state insufficient: "
                                  f"{_msx['sector_leadership'].quality}"),
            "breadth": (None if breadth_pts else
                        f"market_state insufficient: "
                        f"{_msx['breadth'].quality}")}
    except Exception as e:  # noqa: BLE001
        _record_error(cycle, "market_state", e, input_refs=(),
                     known_from=known_from)
        slead_pts, breadth_pts = [], []
        msx_reasons = {"sector_leadership": "market_state build failed",
                       "breadth": "market_state build failed"}

    watchlist = _watchlist(today)
    sufficiency_refused: dict = {}      # feature -> refusal count this cycle
    le_candidates: dict = {}            # transition -> candidate dicts
    for symbol in watchlist:
        try:
            price_pts = _price_points(symbol, today, now)
            # THE REAL UPSTREAM EVENT INSTANT: the newest underlying bar
            # this Curve was computed from. Using the Curve's own compute
            # timestamp instead would measure intra-cycle latency (~0 by
            # construction, since Curve/Assassin/Captain all run in one
            # cycle off the same `now`) and would report "instant
            # adaptation" no matter how stale the data actually was.
            newest_bar_time = price_pts[-1][0] if price_pts else None
            rs_pts = (_excess_points(symbol, MARKET_PROXY, today, now)
                     if symbol != MARKET_PROXY else [])

            # CP04: FEATURE -> SUFFICIENCY (Phase 7). Each feature gets
            # its OWN verdict against its OWN requirement; a feature
            # that may not speak feeds [] and the Curve dimension lands
            # NO_SUPPORT with the refusal named -- never a global
            # quality bit, never unknown-as-zero.
            feed, refusals = {}, dict(msx_reasons)
            for fname, fpts in (("price", price_pts),
                                ("relative_strength", rs_pts),
                                ("sector_leadership", slead_pts),
                                ("breadth", breadth_pts)):
                if not fpts:
                    feed[fname] = []
                    continue
                suff = fsmod.assess_points(
                    fname, symbol, fpts,
                    required_points=curve.MIN_POINTS_FOR_CURVATURE,
                    expected_spacing_s=60.0, now=now, known_from=known_from)
                if suff.may_speak(consumer_accepts_degraded=False):
                    feed[fname] = fpts
                else:
                    feed[fname] = []
                    refusals[fname] = (f"SUFFICIENCY_{suff.verdict}: "
                                       + "; ".join(suff.reasoning))
                    sufficiency_refused[fname] = \
                        sufficiency_refused.get(fname, 0) + 1

            c = curve.compute(
                symbol, feed,
                observation_integrity=oi, now=now, known_from=known_from,
                unsupported_reasons={k: v for k, v in refusals.items()
                                     if v})
            curve.persist(c)
            prior = state.last_curve_state.get(symbol)
            if prior != c.high_level_state:
                eb2.emit("CURVATURE_CHANGE", symbol, event_time=c.as_of,
                        known_from=c.as_of, source="frontier2_shadow_runtime",
                        prior_state=prior, new_state=c.high_level_state,
                        quality=c.observation_quality)
                state.last_curve_state[symbol] = c.high_level_state
        except Exception as e:  # noqa: BLE001
            _record_error(cycle, "curve", e, input_refs=(symbol,), known_from=known_from)
            out["errors"] += 1
            continue

        seriousness = (state.captain_state.get(symbol).state
                      if symbol in state.captain_state else "IGNORE")
        route = compute_route(symbol, material_change=(prior != c.high_level_state),
                              opportunity_seriousness=seriousness,
                              uncertainty=("HIGH" if c.transition_likelihood == "UNKNOWN"
                                          else "MODERATE"),
                              known_from=known_from, now=now)

        ev = pp = edge = None
        if route.tier >= 2 and symbol != MARKET_PROXY:
            try:
                mkt_bars = load_live_bars(MARKET_PROXY, today)
                sym_bars = load_live_bars(symbol, today)
                market_ret = (float(mkt_bars["close"].iloc[-1] / mkt_bars["close"].iloc[0] - 1)
                             if mkt_bars is not None and len(mkt_bars) else None)
                sym_ret = (float(sym_bars["close"].iloc[-1] / sym_bars["close"].iloc[0] - 1)
                          if sym_bars is not None and len(sym_bars) else None)
                excess60 = rs_pts[-1][1] if rs_pts else None
                ev = evmod.evaluate_index_move_high_beta_refusal(
                    symbol, market_day_return=market_ret, symbol_day_return=sym_ret,
                    excess_market_60m=excess60, event_time=now, known_from=known_from,
                    now=now, quality=oi.quality)
                evmod.persist(ev)
                state.last_ev[symbol] = ev
            except Exception as e:  # noqa: BLE001
                _record_error(cycle, "expectation_violation", e, input_refs=(symbol,),
                             known_from=known_from)
                out["errors"] += 1

            try:
                pp = ppmod.infer(symbol, trend_slope=c.dimensions["price"].get("velocity"),
                                 quality=oi.quality, event_time=now,
                                 known_from=known_from, now=now)
                ppmod.persist(pp)
                state.last_pp[symbol] = pp
            except Exception as e:  # noqa: BLE001
                _record_error(cycle, "participant_pressure", e, input_refs=(symbol,),
                             known_from=known_from)
                out["errors"] += 1

            try:
                src, tgt = _returns(MARKET_PROXY, today), _returns(symbol, today)
                edge = propmod.estimate_edge(MARKET_PROXY, symbol, src, tgt,
                                            known_from=known_from, now=now,
                                            quality=oi.quality)
                propmod.persist_edge(edge)
                state.last_edge[symbol] = edge
            except Exception as e:  # noqa: BLE001
                _record_error(cycle, "propagation", e, input_refs=(symbol,),
                             known_from=known_from)
                out["errors"] += 1

        # --- RE-UNDERWRITING (Phase 1.0, 2026-08-18) -------------------
        # The prior gate was `route.tier >= 4 or symbol not in
        # state.captain_state`, which deadlocked: compute_router2 only
        # grants tier 4 to SERIOUS/WAIT_FOR_ENTRY, and Captain could only
        # reach SERIOUS by running. Every subject that entered at WATCH or
        # DEVELOP froze for the whole 2026-08-18 session. Eligibility is
        # now decided by MATERIAL INPUT CHANGE (or a staleness heartbeat),
        # never by the prior state's own seriousness. Compute tier is still
        # computed and logged as an attention budget -- it just no longer
        # holds a veto over re-underwriting.
        a2 = state.last_assassin.get(symbol)
        # tier gate skipped these this cycle -> reuse last computed, never
        # substitute UNKNOWN (see TIER-OSCILLATION GUARD above)
        if ev is None:
            ev = state.last_ev.get(symbol)
        if pp is None:
            pp = state.last_pp.get(symbol)
        if edge is None:
            edge = state.last_edge.get(symbol)
        prior_cs = state.captain_state.get(symbol)
        prior_inputs = state.captain_inputs.get(symbol)
        candidate_id = state.candidate_id.get(symbol, f"{symbol}-LIVE")

        observed_inputs = build_observed_inputs(
            curve=c, ev=ev, pp=pp, edge=edge, oi=oi, sc=sc, a2=a2,
            leading_edge=state.leading_edge.get(symbol))

        last_rev = state.last_review_time.get(symbol)
        secs_since = ((now - last_rev).total_seconds()
                     if last_rev is not None else None)

        try:
            decision = rumod.evaluate(
                subject=symbol, candidate_id=candidate_id,
                prior_inputs=prior_inputs, current_inputs=observed_inputs,
                prior_state=(prior_cs.state if prior_cs else None),
                seconds_since_last_review=secs_since,
                known_from=known_from, now=now)
            rumod.persist(decision)
        except Exception as e:  # noqa: BLE001
            _record_error(cycle, "reunderwrite_trigger", e, input_refs=(symbol,),
                         known_from=known_from)
            out["errors"] += 1
            decision = None

        if decision is not None and decision.should_review:
            # ASSASSIN FIRST: never hand Captain a stale verdict when the
            # evidence Assassin reasons over has changed.
            assassin_refreshed = False
            assassin_review_at = None
            if rumod.requires_fresh_assassin(decision):
                try:
                    a2 = assassin2.assess(subject=symbol, observation_integrity=oi,
                                          curve=c, expectation_violation=ev,
                                          propagation_edge=edge, quality=oi.quality,
                                          known_from=known_from, now=now)
                    assassin2.persist(a2)
                    state.last_assassin[symbol] = a2
                    assassin_refreshed = True
                    assassin_review_at = a2.as_of
                except Exception as e:  # noqa: BLE001
                    _record_error(cycle, "assassin2", e, input_refs=(symbol,),
                                 known_from=known_from)
                    out["errors"] += 1

            try:
                # refresh the assassin fields to the POST-refresh verdict
                # (observed_inputs carried the pre-refresh one for the
                # change comparison above); same key set either way.
                current_inputs = dict(observed_inputs)
                current_inputs["assassin2_familiarity"] = (
                    a2.familiarity if a2 else "UNKNOWN")
                current_inputs["assassin2_caution_label"] = (
                    a2.caution_label if a2 else "NONE")

                cs = captain_shadow.review(
                    prior_cs, candidate_id=candidate_id, subject=symbol,
                    current_inputs=current_inputs, now=now, known_from=known_from)
                captain_shadow.persist(cs)

                rev_n = state.review_number.get(symbol, 0) + 1
                state.review_number[symbol] = rev_n
                rlmod.persist(rlmod.record(
                    candidate_id=candidate_id, subject=symbol, review_number=rev_n,
                    review_time=now, trigger=decision.triggers,
                    previous_captain_state=(prior_cs.state if prior_cs else None),
                    current_captain_state=cs.state,
                    changed_inputs=decision.changed_inputs,
                    unchanged_inputs=decision.unchanged_inputs,
                    current_curve=c.high_level_state,
                    current_ev=(ev.state if ev else None),
                    current_pressure=(pp.trap_state if pp else None),
                    current_propagation=(edge.status if edge else None),
                    current_assassin=(a2.familiarity if a2 else None),
                    current_system_cognition=observed_inputs["system_cognition_state"],
                    # CaptainFrontierShadowState carries `reasoning` (its
                    # supporting trace) and `what_changed`; it has no
                    # separate support/objections fields, so map the real
                    # ones rather than inventing empties.
                    support=cs.reasoning,
                    objections=((cs.competing_explanation,)
                                if cs.competing_explanation else ()),
                    direction_quality=cs.direction_quality,
                    transition_quality=cs.transition_quality,
                    entry_quality=cs.entry_quality, data_quality=cs.data_quality,
                    assassin_refreshed=assassin_refreshed, known_from=known_from,
                    artifact_refs=(f"curve@{c.as_of}", f"captain@{cs.as_of}"),
                    # DECISION ADAPTATION LATENCY: the upstream material
                    # event is the Curve observation that tripped the
                    # trigger; Assassin's own as_of is recorded only when
                    # it actually re-ran this cycle.
                    upstream_event_time=(newest_bar_time or c.as_of),
                    assassin_review_time=assassin_review_at))

                if prior_cs is None or prior_cs.state != cs.state:
                    eb2.emit("CAPTAIN_STATE_CHANGE", symbol, event_time=cs.as_of,
                            known_from=cs.as_of, source="frontier2_shadow_runtime",
                            prior_state=(prior_cs.state if prior_cs else None),
                            new_state=cs.state, quality=oi.quality)

                state.captain_state[symbol] = cs
                state.captain_inputs[symbol] = current_inputs
                state.last_review_time[symbol] = now

                # CP10 -> CP11 -> CP12 -> CP13 (Phases 13-15,
                # 2026-08-20): a Captain escalation now flows to
                # Capital, Expression and a BEFORE card instead of
                # dying in a ledger row. SHADOW ONLY -- Capital is
                # sovereign and fail-closed (a frontier2 opportunity
                # has no calibrated forecast, so today its honest
                # verdict is REFUSED with named reasons -- that is a
                # REACHED checkpoint, not a failure); execution stays
                # SEALED; NO_TRADE is a persisted positive decision.
                if cs.state in ("SERIOUS", "WAIT_FOR_ENTRY"):
                    try:
                        _run_expression_funnel(
                            symbol=symbol, candidate_id=candidate_id,
                            cs=cs, c=c, price_pts=price_pts,
                            now=now, known_from=known_from)
                    except Exception as e:  # noqa: BLE001
                        _record_error(cycle, "expression_funnel", e,
                                     input_refs=(symbol,),
                                     known_from=known_from)
                        out["errors"] += 1

                # TERMINAL STATE LAW: once INVALIDATE-d, this lineage is
                # closed. Any future thesis for this subject must be minted
                # under a NEW_THESIS_LINEAGE id -- never a mutation of the
                # invalidated one.
                if cs.state in rumod.TERMINAL_STATES:
                    gen = state.thesis_generation.get(symbol, 1) + 1
                    state.thesis_generation[symbol] = gen
                    state.candidate_id[symbol] = rumod.new_thesis_lineage_id(
                        symbol, generation=gen)
                    state.captain_state.pop(symbol, None)
                    state.captain_inputs.pop(symbol, None)
                    state.review_number.pop(symbol, None)

                if cs.state not in ("IGNORE",) and symbol not in state.graph:
                    g = ogmod.new_graph(candidate_id, symbol, known_from=known_from, now=now)
                    g = ogmod.add_node(g, f"curve:{now}", "CURVE",
                                       artifact_hash=None, summary=c.high_level_state, now=now)
                    g = ogmod.add_node(g, "root", "CAPTAIN_SHADOW", artifact_hash=None,
                                       summary="live opportunity entry", now=now)
                    g = ogmod.add_edge(g, "CAUSED_ATTENTION", f"curve:{now}", "root",
                                       reason="first non-IGNORE CaptainShadow state", now=now)
                    ogmod.persist(g)
                    state.graph[symbol] = g
            except Exception as e:  # noqa: BLE001
                _record_error(cycle, "captain_shadow", e, input_refs=(symbol,),
                             known_from=known_from)
                out["errors"] += 1

        out["subjects"][symbol] = {
            "curve": c.high_level_state, "tier": route.tier,
            "ev": ev.state if ev else None, "pp": pp.trap_state if pp else None,
            "propagation": edge.status if edge else None,
            "assassin2": a2.familiarity if a2 else None,
            "captain": state.captain_state.get(symbol).state
            if symbol in state.captain_state else None,
        }

        # LEADING EDGE CANDIDATE COLLECTION (Phase 8, 2026-08-20 -- the
        # caller lemod.rank() never had). Directional transitions only;
        # missing dimensions stay UNKNOWN, never fabricated.
        if c.high_level_state in ("POSITIVE_TRANSITION",
                                  "NEGATIVE_TRANSITION",
                                  "EARLY_POSITIVE_CURVATURE",
                                  "EARLY_NEGATIVE_CURVATURE"):
            le_candidates.setdefault(c.high_level_state, []).append({
                "symbol": symbol,
                "curve_expression": c.expression,
                "propagation_position": (edge.status if edge else "UNKNOWN"),
                "participant_pressure_potential": (
                    pp.forced_action_potential
                    if pp is not None and hasattr(pp, "forced_action_potential")
                    else "UNKNOWN"),
                "expectation_violation": (ev.state if ev else "UNKNOWN"),
                "data_quality": oi.quality,
                "contradictions": ()})

    # CP07: CURVE -> LEADING EDGE (Phase 8). rank() finally has a live
    # caller -- entry_quality is no longer permanently UNKNOWN because
    # nothing ever asked. UNKNOWN remains allowed where evidence is
    # genuinely insufficient; what is no longer allowed is silence.
    out["leading_edge"] = {}
    for transition, cands in le_candidates.items():
        try:
            lem = lemod.rank(transition, cands, known_from=known_from,
                             now=now)
            lemod.persist(lem)
            for r in lem.rows:
                state.leading_edge[r["symbol"]] = {
                    "rank": r["rank"], "entry_quality": r["entry_quality"]}
            out["leading_edge"][transition] = [
                r["symbol"] for r in lem.rows[:3]]
        except Exception as e:  # noqa: BLE001
            _record_error(cycle, "leading_edge", e,
                         input_refs=(transition,), known_from=known_from)
            out["errors"] += 1

    # CP04 audit trail: sufficiency refusals this cycle, persisted so a
    # missing dimension is always attributable to a NAMED gate decision
    # (NO_TRADE-style positive refusal), never a silent absence.
    out["sufficiency_refused"] = sufficiency_refused
    if sufficiency_refused:
        try:
            with open("results/frontier2/feature_sufficiency_refusals.jsonl",
                      "a") as fh:
                fh.write(json.dumps({
                    "kind": "feature_sufficiency_cycle_summary",
                    "cycle": cycle, "as_of": str(now),
                    "known_from": str(known_from),
                    "refusals_by_feature": sufficiency_refused,
                    "decision_power": FRONTIER2_POWER}) + "\n")
        except OSError as e:
            _record_error(cycle, "sufficiency_persist", e, input_refs=(),
                         known_from=known_from)

    if not state.birth_minted and state.first_canonical_input is not None:
        _mint_birth(now, state.first_canonical_input)
        state.birth_minted = True
    if state.first_successful_cycle is None:
        state.first_successful_cycle = str(now)

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=390)
    ap.add_argument("--cadence", type=float, default=20.0)
    a = ap.parse_args()

    preregister()

    sp = sp_start(SERVICE_NAME, expected_cadence_s=a.cadence)
    state = RuntimeState()
    print(f"FRONTIER2_SHADOW_RUNTIME starting pid={sp.pid}", flush=True)

    t_end = time.time() + a.minutes * 60
    cycle = 0
    while time.time() < t_end:
        cycle += 1
        now = pd.Timestamp.now(tz="UTC")
        sp.cycle_number = cycle
        sp.last_cycle_start = str(now)
        sp.heartbeat_time = str(now)
        try:
            result = run_cycle(state, cycle, now)
            sp.last_cycle_complete = str(pd.Timestamp.now(tz="UTC"))
            sp.last_successful_cycle = sp.last_cycle_complete
            sp.cycle_duration_s = (pd.Timestamp(sp.last_cycle_complete)
                                   - now).total_seconds()
            sp.consecutive_failures = 0
            sp.last_state_write = sp.last_cycle_complete
            sp.backlog_count = result["errors"]
            print(f"{now:%H:%M:%S} cycle={cycle} subjects={len(result['subjects'])} "
                 f"errors={result['errors']}", flush=True)
        except Exception as e:  # noqa: BLE001
            sp.consecutive_failures += 1
            sp.total_failures += 1
            sp.error_reference = f"cycle_{cycle}_{type(e).__name__}"
            _record_error(cycle, "run_cycle", e, input_refs=(), known_from=now)
            print(f"{now:%H:%M:%S} cycle={cycle} FAILED: {type(e).__name__}: {e}",
                 flush=True)
        sp_write(sp, RUNTIME_STATE_PATH)
        time.sleep(max(1.0, a.cadence))

    sp_write(sp, RUNTIME_STATE_PATH)
    print("FRONTIER2_SHADOW_RUNTIME stopped (budget reached)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
