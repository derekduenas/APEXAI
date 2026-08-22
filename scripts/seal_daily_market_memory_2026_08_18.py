"""Seal DailyMarketMemory for 2026-08-18 from the end-of-market
forensic recap. Every value here traces to a real measured artifact or
to today's real REST-fetched session bars -- nothing is a hindsight
rule, and every open question is preserved as an UNKNOWN rather than
resolved into a conclusion.

Idempotent: re-running with identical content is a DUPLICATE.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from apex.memory import daily_market_memory as dmm

SESSION_DATE = "2026-08-18"
# known_from: the close of the session this memory describes. Nothing in
# this record was known before the session ended.
KNOWN_FROM = "2026-08-18T20:00:00+00:00"


def build_fields() -> dict:
    return dict(
        day_classification=(
            "broad risk-off, small-cap-led weakness, mixed sector rotation "
            "(defensive Healthcare + Energy + Financials up; Real Estate, "
            "Utilities, Industrials, Materials down) -- not a clean "
            "single-factor day"),
        regime={
            "SPY": -0.174, "QQQ": -0.376, "IWM": -0.747, "DIA": -0.088,
            "XLV": 0.628, "XLE": 0.315, "XLF": 0.173, "XLP": -0.210,
            "XLY": -0.291, "XLC": -0.343, "XLK": -0.392, "XLB": -0.843,
            "XLU": -0.878, "XLI": -0.885, "XLRE": -1.217,
        },
        leadership=(("XLV", 0.628), ("XLE", 0.315), ("XLF", 0.173)),
        laggards=(("XLRE", -1.217), ("XLI", -0.885), ("XLU", -0.878),
                  ("XLB", -0.843)),
        breadth=("not independently computed; Hunter's own breadth_proxy_crude "
                "read 0.45 at 19:50 UTC with market_above_vwap=false"),
        volatility=("realized 1m stdev 2.05-5.78 bps across the index/sector "
                   "set; XLK 5.78 and XLE 5.58 highest, SPY 2.05 lowest"),
        important_transitions=(
            "SPY/QQQ/IWM Curve oscillated continuously all session (42/58/76 "
            "state changes respectively); no sustained morning convergence",
            "longest sustained NEGATIVE_TRANSITION streak for all three index "
            "ETFs landed in the AFTERNOON (SPY 18:37 UTC, QQQ 18:41 UTC, "
            "IWM 17:29 UTC), not the morning",
            "all of SPY/QQQ/IWM closed BELOW their opening range; DIA closed "
            "INSIDE it",
        ),
        persistent_relative_strength=(
            "not computed this session -- no persistence metric existed yet",),
        persistent_weakness=(
            "XLRE, XLU, XLI negative in both the morning and afternoon windows",),
        failed_breakouts=(
            {"symbol": "HD", "playbook": "HUNTER-001_v1", "direction": "LONG",
             "note": "stopped out intraday; +0.55% at 15m, -1.05% by close"},),
        failed_breakdowns=("not computed this session",),
        traps=("none identified with sufficient evidence",),
        late_day_changes=(
            "XLY afternoon -0.81% after a +0.51% morning",
            "XLU afternoon -0.87% after a flat -0.02% morning",
        ),
        hunter_matches=(
            {"symbol": "HD", "playbook": "HUNTER-001_v1",
             "timestamp_utc": "2026-08-18 14:42:08.839988+00:00",
             "direction": "LONG", "entry": 341.39, "stop": 337.05,
             "target": 350.07,
             "assassin_verdict": "SURVIVED_WOUNDED",
             "assassin_objections": ["SWARM_ADVERSARIAL_TRADER",
                                     "FORECAST_SOURCE_DISAGREEMENT"],
             "capital_final_state": "WATCH",
             "capital_reasons": ["NO_CALIBRATED_FORECAST",
                                 "INSUFFICIENT_EDGE_EVIDENCE", "COST_UNKNOWN"],
             "ret_15m": 0.00554, "ret_30m": 0.003724, "ret_60m": -0.001968,
             "ret_90m": -0.002314, "closing_return": -0.010457,
             "stop_before_target": True,
             "note": "the ONLY non-baseline playbook match of the session; n=1"},
        ),
        fastwatch_observations={
            "events": 3160, "symbols": 29, "errors": 0,
            "first_event_utc": "2026-08-18 13:27:02.653843+00:00",
            "last_event_utc": "2026-08-18 20:06:13.494916+00:00",
            "condition_tags": {"VWAP_RECLAIM_SHAPE": 371,
                               "SESSION_HIGH_TOUCH": 50},
            "converted_to_hunter_match": 0,
            "note": ("live 3 min before Hunter's first tick and 16 min after "
                    "its last; tags are explicitly NOT Hunter matches"),
        },
        frontier2_limitations=(
            "CaptainFrontierShadow produced exactly ONE evaluation per subject "
            "across all 55 subjects and never re-reviewed -- frozen from "
            "13:43 UTC for the rest of the session",
            "Assassin2 likewise one evaluation per subject, never re-run",
            "runtime began 13:43 UTC, 13 minutes after the 13:30 UTC open -- "
            "no Frontier-2 observation exists for the first 13 minutes",
            "ParticipantPressure's Hunter-specific fields (or_break, "
            "vwap_reclaim, rvol_tod) stayed None all session by design",
            "LeadingEdgeMap / WorldLab / ModelMarket live status not "
            "independently verified during the session",
        ),
        data_fabric_limitations=(
            "universe_coverage continuous_coverage_fraction = 0.0 and "
            "broad_discovery_valid = false despite 164/164 nominal coverage",
            "measured bar gap-overlap: SPY 52.5%, QQQ 52.5%, IWM 59.2% "
            "with IWM also 24.5% INCOMPLETE bars -- real, uneven damage",
            "alpaca_fabric_health reconnects counter = 388 with ZERO "
            "corresponding lines in logs/alpaca_fabric.log -- unexplained",
            "first_observed_by_symbol for SPY/QQQ/IWM = 16:03-16:36 UTC, "
            "far later than the 13:30 UTC open",
        ),
        options_limitations=(
            "every sampled contract was 1-2 DTE; nothing observed at longer "
            "maturity",
            "all analytics states capped at LOW quality by the deliberately "
            "stale static rate source",
            "American finite-difference Greeks disagreed with vendor Greeks "
            "~15x more than analytic BSM did (mean abs delta 0.019 vs 0.00125)",
            "zero OPTIONS_BEFORE_CARDs sealed -- the research layer never ran "
            "prospectively against real Hunter/Frontier-2 output",
        ),
        system_blind_spots=(
            "Captain Shadow frozen all session on all 55 subjects",
            "no Morning Prior artifact was locatable at end of day",
            "no session-integrity certification was run for this session",
            "Hunter has no service-progress or watchdog artifact at all",
            "no live loop connects Options Research to real opportunities",
        ),
        important_unknowns=(
            "whether the 16:03-16:36 UTC first_observed pattern is a repeat of "
            "the 2026-08-17 session-anchor bug class or a different cause",
            "why reconnects=388 has no corresponding log evidence",
            "whether Captain Shadow's freeze is tier-gating by design or a "
            "live-wiring defect",
            "whether Curve's afternoon-weighted negative conviction recurs or "
            "was specific to this session",
            "whether FastWatch condition tags carry information -- 421 fired, "
            "0 converted, single session",
        ),
    )


def main() -> dict:
    now = pd.Timestamp.now(tz="UTC")
    mem, verdict = dmm.seal(session_date=SESSION_DATE, known_from=KNOWN_FROM,
                            now=now, **build_fields())
    return {"verdict": verdict, "session_date": mem.session_date,
           "version": mem.version, "content_hash": mem.content_hash[:16],
           "positions_carried_overnight": mem.positions_carried_overnight}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
