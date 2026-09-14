"""The Hunter forward pass: states -> scan -> playbooks -> DECISION records,
and the end-of-day deterministic realization resolver.

Eligibility is mechanical: every DECISION carries the four dependency
birth times (protocol / feature schema / playbook / model) and the computed
FORWARD_ELIGIBLE / NOT_FORWARD_ELIGIBLE verdict. A forecast made before any
dependency's birth can never become forward evidence retroactively — the
ledger refuses it at write time, no human judgment involved.

One DECISION per (symbol, playbook, direction) per session (frozen rule):
the first formation wins; later snapshots of the same setup are not new
evidence, they are the same opportunity observed again.

Realizations are appended, never edited into decisions; each is labeled
MECHANICAL_DETERMINISTIC (protocol §3) — an outcome measurement, computed
identically by anyone from the same bars.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from apex.hunter import birth as birthlib
from apex.hunter.baselines import baseline_decisions
from apex.hunter.capital import (ForecastSlot, evaluate_candidate,
                                 intraday_market_uncertain)
from apex.hunter.chartstate import (BAR, ChartState, DailyContext,
                                    compute_chart_state, visible_bars)
from apex.hunter.contracts import HORIZONS_MINUTES, content_hash
from apex.hunter.evidence import EvidenceClass, stamp
from apex.hunter.playbooks_v1 import match_hunter_001, match_hunter_002
from apex.hunter.relstrength import compute_relative_strength
from apex.hunter.scanner import scan

LEDGER = Path("results/hunter/forward_ledger.jsonl")


def extension_geometry(bars: pd.DataFrame, t_utc) -> dict:
    """Session extremes (LAST touch — the extension was still alive then),
    their ages, and direction-specific leg bases: min/max close in the 60m
    BEFORE the extreme's last touch. From the SAME visible frame ChartState
    uses (as-of inherited)."""
    f = visible_bars(bars, t_utc)
    empty = {"session_high": None, "session_low": None,
             "session_high_age_min": None, "session_low_age_min": None,
             "leg_start_up": None, "leg_start_down": None}
    if f.empty:
        return empty
    t = pd.Timestamp(t_utc)
    hi, lo = f["high"].astype(float), f["low"].astype(float)
    px, times = f["close"].astype(float), f["event_time_utc"]
    sh, sl = float(hi.max()), float(lo.min())
    hi_t = times[hi >= sh * (1 - 1e-9)].iloc[-1]        # last touch
    lo_t = times[lo <= sl * (1 + 1e-9)].iloc[-1]
    pre_hi = px[(times < hi_t) & (times >= hi_t - pd.Timedelta(minutes=60))]
    pre_lo = px[(times < lo_t) & (times >= lo_t - pd.Timedelta(minutes=60))]
    return {
        "session_high": sh, "session_low": sl,
        "session_high_age_min": float((t - (hi_t + BAR)).total_seconds() / 60),
        "session_low_age_min": float((t - (lo_t + BAR)).total_seconds() / 60),
        "leg_start_up": float(pre_hi.min()) if len(pre_hi) else None,
        "leg_start_down": float(pre_lo.max()) if len(pre_lo) else None}


def existing_decision_keys(date: str, ledger: Path = LEDGER) -> tuple:
    """(playbook_keys, baseline_keys) already minted this session. Playbooks
    dedupe on (symbol, playbook, direction); baselines on (symbol, baseline)
    — a baseline's direction input can flip tick to tick, and the first
    formation still wins."""
    pb, base = set(), set()
    if not ledger.exists():
        return pb, base
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)                 # chain entries are FLAT
        except json.JSONDecodeError:
            continue                             # torn line: reader survives
        if r.get("kind") == "decision" and r.get("session_date") == date:
            if r["playbook_id"].startswith("BASELINE-"):
                base.add((r["symbol"], r["playbook_id"]))
            else:
                pb.add((r["symbol"], r["playbook_id"], r["direction"]))
    return pb, base


def realized_decision_ids(ledger: Path = LEDGER) -> set:
    ids = set()
    if not ledger.exists():
        return ids
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)                 # chain entries are FLAT
        except json.JSONDecodeError:
            continue                             # torn line: reader survives
        if r.get("kind") == "realization":
            ids.add(r["decision_id"])
    return ids


def unrealized_decisions(date: str, ledger: Path = LEDGER) -> list:
    done = realized_decision_ids(ledger)
    out = []
    if not ledger.exists():
        return out
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)                 # chain entries are FLAT
        except json.JSONDecodeError:
            continue                             # torn line: reader survives
        if (r.get("kind") == "decision" and r.get("session_date") == date
                and r["decision_id"] not in done):
            out.append(r)
    return out


def decision_pass(t_utc, universe: dict, bars_by_symbol: dict,
                  contexts: dict, market_symbol: str = "SPY.US",
                  enrich: bool = True) -> tuple:
    """-> (scan_record, records). Pure: caller appends to ledger.
    enrich=False returns ONLY scan + decisions so the caller can persist
    them BEFORE any LLM/enrichment runs (the ordering law); it then calls
    enrichment_pass(t, date, decisions, universe) separately."""
    t = pd.Timestamp(t_utc)
    date = str(t.tz_convert("America/New_York").date())
    market_bars = bars_by_symbol.get(market_symbol)
    market_cs = (compute_chart_state(
        market_symbol, market_bars, t,
        contexts.get(market_symbol,
                     DailyContext(symbol=market_symbol, as_of_date=date)))
        if market_bars is not None else None)

    etf_cs = {}
    for sym, b in bars_by_symbol.items():
        if sym.endswith(".US") and sym not in universe["symbols"]:
            cs = compute_chart_state(
                sym, b, t, contexts.get(sym, DailyContext(symbol=sym,
                                                          as_of_date=date)))
            if cs is not None:
                etf_cs[sym] = cs

    # target states
    cs_by_symbol, sector_of = {}, {}
    for sym, meta in universe["symbols"].items():
        b = bars_by_symbol.get(sym)
        if b is None:
            continue
        ctx = contexts.get(sym, DailyContext(symbol=sym, as_of_date=date))
        cs = compute_chart_state(sym, b, t, ctx)
        if cs is not None:
            cs_by_symbol[sym] = cs
            sector_of[sym] = meta.get("sector")

    pairs, rs_by_symbol = [], {}
    if market_cs is not None:
        day_excess = tuple(
            (c.day_return - market_cs.day_return)
            if c.day_return is not None and market_cs.day_return is not None
            else None for c in cs_by_symbol.values())
        for sym, cs in cs_by_symbol.items():
            setf = universe["symbols"][sym].get("sector_etf")
            peers = tuple(c for s2, c in cs_by_symbol.items()
                          if s2 != sym and sector_of.get(s2) == sector_of.get(sym))
            rs = compute_relative_strength(
                cs, market_cs, etf_cs.get(setf), peers, day_excess)
            rs_by_symbol[sym] = rs
            pairs.append((cs, rs))

    result = scan(str(t), len(universe["symbols"]), pairs)
    scan_record = stamp(result.as_record(),
                        EvidenceClass.EODHD_FORWARD_OBSERVATION)
    scan_record["kind"] = "scan"
    # Scout-level universe facets for the DIGITAL WORLD (Twin 2.0):
    # observational aggregates over every computed state, typed absences
    # when the universe is thin OR when session-anchored features are
    # invalid (SESSION INTEGRITY GATE, v1.2) -- an aggregate over zero
    # valid inputs is None + status, never a silent 0.0/NaN.
    if cs_by_symbol:
        import numpy as _np
        _states = list(cs_by_symbol.values())
        _anchor_valid_states = [c for c in _states
                                if c.session_coverage.get("session_anchor_valid")]
        _n_anchor_valid = len(_anchor_valid_states)
        _gaps = [c.gap_frac for c in _states if c.gap_frac is not None]
        _rvols = [c.rvol_tod for c in _states if c.rvol_tod is not None]
        _avwap = [bool(c.above_vwap) for c in _states
                 if c.above_vwap is not None]
        _or_states = [c for c in _anchor_valid_states if c.or_complete]

        def _mean_or_none(vals):
            return round(float(_np.mean(vals)), 2) if vals else None

        def _median_or_none(vals):
            return round(float(_np.median(vals)), 2) if vals else None

        scan_record["universe_facets"] = {
            "n_states": len(_states),
            "n_session_anchor_valid": _n_anchor_valid,
            "session_anchor_valid_frac": round(
                _n_anchor_valid / len(_states), 2) if _states else None,
            "above_vwap_frac": _mean_or_none(_avwap),
            "gap_environment": {
                "median_abs_gap": round(float(_np.median(
                    [abs(g) for g in _gaps])), 4) if _gaps else None,
                "material_gap_frac": _mean_or_none(
                    [abs(g) >= 0.02 for g in _gaps]) if _gaps else None},
            "participation_median_rvol": _median_or_none(_rvols),
            "opening_behavior": {
                "n_or_complete": len(_or_states),
                "or_break_up_frac": _mean_or_none(
                    [c.or_break_up for c in _or_states]),
                "or_break_down_frac": _mean_or_none(
                    [c.or_break_down for c in _or_states])},
            "breakout_success_environment": {"status":
                                             "DORMANT_NEEDS_OUTCOMES"}}
    else:
        scan_record["universe_facets"] = {"status":
                                          "SCOUT_FACETS_UNAVAILABLE"}
    scan_record["session_date"] = date
    scan_record["universe_limitation"] = universe.get("universe_limitation")

    births = birthlib.load_births()
    seen, seen_baseline = existing_decision_keys(date)
    decisions = []
    # SESSION INTEGRITY GATE (v1.2): a playbook that NEVER got a chance
    # to evaluate its required features (session-anchored: vwap,
    # rvol_tod, or_complete) must be distinguishable from one that
    # evaluated and genuinely found no match. Both playbooks_v1.py
    # matchers already fail-closed internally on `None in (cs.vwap,
    # cs.rvol_tod, ...)` -- untouched, unchanged -- but that makes
    # REFUSE_INSUFFICIENT_VALID_STATE indistinguishable from NO_MATCH
    # from the outside. This check is ORCHESTRATION, not a playbook
    # predicate or threshold: it decides whether to call the matcher at
    # all, never how the matcher decides.
    REQUIRED_FOR_MATCH = ("vwap", "rvol_tod")

    def _insufficient_state(cs: ChartState) -> bool:
        fv = cs.feature_validity or {}
        return any(fv.get(name, {}).get("status") != "VALID"
                  for name in REQUIRED_FOR_MATCH)

    refusals = []
    for _entry in result.watchlist:
        sym = _entry.symbol
        cs, rs = cs_by_symbol[sym], rs_by_symbol[sym]
        if _insufficient_state(cs):
            refusals.append({
                "kind": "playbook_match_refused", "symbol": sym,
                "t_utc": str(t), "session_date": date,
                "match_result": "REFUSE_INSUFFICIENT_VALID_STATE",
                "reason": {k: v for k, v in (cs.feature_validity or {}).items()
                          if k in REQUIRED_FOR_MATCH and v.get("status") != "VALID"},
                "playbooks_not_evaluated": ("HUNTER-001", "HUNTER-002")})
            continue
        geo = extension_geometry(bars_by_symbol[sym], t)
        for m in (match_hunter_001(cs, rs, market_cs),
                  match_hunter_002(cs, rs, geo)):
            if m is None:
                continue
            key = (sym, m["playbook_id"], m["direction"])
            if key in seen:
                continue
            seen.add(key)
            # deps of THIS forecast: shared kinds + its OWN playbook only —
            # a later playbook's birth never disqualifies an older one's
            # forecast, and an unborn playbook fails the required-kind check
            deps = {n: b for n, b in births.items()
                    if b["dependency_kind"] != "playbook"
                    or n == m["playbook_id"]}
            eligibility, reasons = birthlib.forward_eligibility(t, deps)
            bstamp = birthlib.birth_stamp(deps)
            # F-09: content-derived id — identical inputs replay to an
            # identical ledger, bit for bit
            rec = stamp({
                "kind": "decision",
                "decision_id": content_hash(
                    {"t": str(t), "symbol": sym,
                     "playbook": m["playbook_id"],
                     "direction": m["direction"]})[:16],
                "session_date": date, "t_utc": str(t),
                "symbol": sym, **m,
                "horizons_minutes": list(HORIZONS_MINUTES),
                "chart_state": cs.as_record(),
                "relative_strength": rs.as_record(),
                "market_state": (market_cs.as_record()
                                 if market_cs else None),
                "forward_eligibility": eligibility,
                "eligibility_reasons": list(reasons),
                **bstamp,
            }, EvidenceClass.EODHD_FORWARD_OBSERVATION)
            decisions.append(rec)

    scan_record["playbook_match_refusals"] = refusals

    # frozen baselines: same subjects, same ledger, same machinery —
    # deliberately naive directions (protocol §6; no separate system)
    decisions.extend(baseline_decisions(
        t, date, tuple(e.symbol for e in result.watchlist),
        cs_by_symbol, rs_by_symbol, market_cs, births, seen_baseline))

    if not enrich:
        # THE ORDERING LAW: the caller persists scan + decisions FIRST,
        # then calls enrichment_pass — an LLM can therefore never delay
        # or lose a canonical observation or candidate record
        return scan_record, decisions
    return scan_record, decisions + enrichment_pass(
        t, date, decisions, universe, bars_by_symbol=bars_by_symbol,
        model_history_by_symbol=build_model_history(decisions, bars_by_symbol, t))


def _uncertain_from_record(market_state: dict | None) -> bool:
    """Dict-shaped twin of capital.intraday_market_uncertain, so the
    enrichment pass depends only on PERSISTED records (replayable)."""
    if not market_state or market_state.get("day_return") is None:
        return True                                   # fail closed
    if market_state.get("data_quality"):
        return True
    return abs(market_state["day_return"]) >= 0.015


def build_model_history(decisions: list, bars_by_symbol: dict | None, t, gov=None) -> dict:
    """ONE builder, called by both entry points. The variance model's sample is not the setup's frame."""
    from apex.hunter.model_history import build as _build
    from apex.intraday.eodhd import QuotaGovernor
    import pandas as pd
    gov = gov or QuotaGovernor(daily_budget=2000, purpose="LAB")
    as_of = float(pd.Timestamp(t).timestamp())
    out, seen = {}, set()
    for d in decisions or []:
        sym = d.get("symbol")
        if not sym or sym in seen or str(d.get("playbook_id", "")).startswith("BASELINE-"):
            continue
        seen.add(sym)
        frame, prov = _build(sym, (bars_by_symbol or {}).get(sym), as_of_epoch=as_of, gov=gov)
        out[sym] = {"frame": frame, "provenance": prov}
    return out


def enrichment_pass(t, date: str, decisions: list, universe: dict,
                    bars_by_symbol: dict | None = None,
                    model_history_by_symbol: dict | None = None) -> list:
    """THE OPTIONAL INTELLIGENCE PASS — runs strictly AFTER candidates are
    persistable, reading ONLY the decision records themselves (analog ->
    swarm -> ForecastBundle -> APEX CAPITAL). Every seat is
    fault-isolated: a hung subprocess, a rate limit, or a dead network
    can cost enrichment, never the archive. Per-tick swarm budget of 2."""
    t = pd.Timestamp(t)
    from apex.portfolio.risk import PortfolioState
    portfolio = PortfolioState(nav=100_000.0, positions={}, sector_weights={},
                               heat=0.0, drawdown_budget_left=1.0,
                               sleeve_correlations={})
    out: list = []
    captain_states: list = []
    swarm_budget = 2
    for d in decisions:
        if d.get("playbook_id", "").startswith("BASELINE-"):
            continue
        meta = universe["symbols"].get(d["symbol"], {})
        uncertain = _uncertain_from_record(d.get("market_state"))
        bundle_rec, disagreement_level, support_low = None, None, False
        assassin_rec = None
        try:
            from apex.analog.engine import AnalogQuery, retrieve
            from apex.hunter.forecast import assemble_bundle
            from apex.hunter.memory import analog_memory_rows
            from apex.hunter.swarm import run_specialists
            analog = retrieve(
                AnalogQuery(as_of=str(t), security_id=d["symbol"],
                            horizon_minutes=60,
                            playbook_id=d["playbook_id"],
                            candidate_record=d),
                analog_memory_rows(str(t)),
                evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
            from apex.hunter.halflife import estimate, route_intelligence
            from apex.hunter.memory import _rows as _ledger_rows
            realized = {r["decision_id"]: r for r in _ledger_rows()
                        if r.get("kind") == "realization"
                        and r.get("resolvable")}
            scored = [{**dd, **realized[dd["decision_id"]]}
                      for dd in _ledger_rows()
                      if dd.get("kind") == "decision"
                      and dd.get("playbook_id") == d["playbook_id"]
                      and dd.get("forward_eligibility") == "FORWARD_ELIGIBLE"
                      and dd.get("decision_id") in realized]
            halflife = estimate(d["playbook_id"], scored)
            routing = route_intelligence(halflife)
            if swarm_budget > 0:
                swarm = run_specialists(
                    d, as_of=str(t),
                    allow_deep=routing["allow_deep_swarm"])
                swarm_budget -= 1
            else:
                from apex.hunter.forecast import SwarmAssessment
                swarm = SwarmAssessment(
                    candidate_id=d.get("decision_id", "?"), as_of=str(t),
                    status="NOT_REQUESTED",
                    provenance={"reason": "per-tick swarm budget spent; "
                                          "archive outranks enrichment"})
            # ASK EVERY LAYER. Until 2026-09-14 this call passed neither a prediction nor a simulation, so the
            # bundle recorded assemble_bundle's own defaults and no reader could tell a starved model from one
            # that was never wired. Both layers may still refuse -- but now they refuse with a number.
            from apex.hunter.intelligence_wiring import ml_view, simulation_view
            mlv = ml_view(d, _ledger_rows(), horizon_minutes=60,
                          evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
            # Bars reach enrichment only when the caller supplies them. Absent, the simulation layer records
            # a named refusal -- never a silent None, which is what could not be told from "not wired".
            _mh = (model_history_by_symbol or {}).get(d["symbol"]) or {}
            simv = simulation_view(d, (bars_by_symbol or {}).get(d["symbol"]),
                                   as_of_epoch=float(pd.Timestamp(t).timestamp()),
                                   history=_mh.get("frame"),
                                   history_sessions=1 + len((_mh.get("provenance") or {})
                                                            .get("prior_sessions", [])))
            if _mh.get("provenance"):
                simv.provenance.setdefault("model_history", _mh["provenance"])
            bundle = assemble_bundle(d, analog_result=analog, swarm=swarm,
                                     ml_prediction=mlv, simulation=simv)
            bundle_rec = stamp(bundle.as_record(),
                               EvidenceClass.EODHD_FORWARD_OBSERVATION)
            bundle_rec["session_date"] = date
            # THE ASSASSIN — the formal kill stage between Oracle and
            # Capital: every attack attempted is recorded; wounds feed
            # the monotone caution law (identical semantics, now a named
            # stage with its own ledger record)
            from apex.hunter.assassin import review as assassin_review
            rev = assassin_review(d, bundle)
            assassin_rec = stamp(rev.as_record(),
                                 EvidenceClass.EODHD_FORWARD_OBSERVATION)
            assassin_rec["session_date"] = date
            assassin_rec["decision_id"] = d.get("decision_id")
            disagreement_level = rev.disagreement_level
            support_low = rev.analog_support_low
        except Exception as e:                              # noqa: BLE001
            assassin_rec = None
            print(f"bundle {d['symbol']}: {type(e).__name__}: {e}")
        cd = evaluate_candidate(
            d, sector=meta.get("sector"),
            median_dollar_volume=meta.get("median_dollar_volume"),
            ann_vol=(d.get("chart_state") or {}).get("realized_vol_ann"),
            market_uncertain=uncertain, forecast=ForecastSlot(),
            portfolio=portfolio,
            disagreement_level=disagreement_level,
            analog_support_low=support_low)
        rec = stamp(cd.as_record(), EvidenceClass.EODHD_FORWARD_OBSERVATION)
        rec["session_date"] = date
        rec["t_utc"] = str(t)
        try:
            rec["edge_persistence"] = halflife
            rec["intelligence_routing"] = routing
        except NameError:
            pass                                  # enrichment seat failed
        if bundle_rec is not None:
            out.append(bundle_rec)
        if assassin_rec is not None:
            out.append(assassin_rec)
        out.append(rec)
        # THE CAPTAIN — observational in Epoch 1: records what the desk
        # SHOULD do next; changes no outcome (decision_power NONE)
        try:
            from apex.captain.kernel import assess as captain_assess
            cst = captain_assess(d, bundle_rec, assassin_rec, rec,
                                 persistence=rec.get("edge_persistence"))
            crec = stamp(cst.as_record(),
                         EvidenceClass.EODHD_FORWARD_OBSERVATION)
            crec["session_date"] = date
            captain_states.append(cst)
            out.append(crec)
        except Exception as e:                              # noqa: BLE001
            print(f"captain {d['symbol']}: {type(e).__name__}: {e}")
    # the board: one scarce unit of risk, many candidates
    if captain_states:
        try:
            from apex.captain.board import build as build_board
            caps = {r["decision_id"]: r for r in out
                    if r.get("kind") == "capital_decision"}
            brec = stamp(build_board(captain_states, caps,
                                     t_utc=str(t)).as_record(),
                         EvidenceClass.EODHD_FORWARD_OBSERVATION)
            brec["session_date"] = date
            out.append(brec)
        except Exception as e:                              # noqa: BLE001
            print(f"board: {type(e).__name__}: {e}")
    return out


def resolve_decision(decision: dict, day_bars: pd.DataFrame) -> dict:
    """MECHANICAL_DETERMINISTIC outcome measurement from full-session bars.
    Forward window starts strictly AFTER formation time."""
    t0 = pd.Timestamp(decision["t_utc"])
    f = day_bars[day_bars["event_time_utc"] + BAR > t0].reset_index(drop=True)
    entry = float(decision["entry"])
    sign = 1.0 if decision["direction"] == "LONG" else -1.0
    # baselines carry no geometry: raw subject-horizon returns only
    stop = (float(decision["stop"])
            if decision.get("stop") is not None else None)
    target = (float(decision["target"])
              if decision.get("target") is not None else None)
    out = {"kind": "realization", "decision_id": decision["decision_id"],
           "session_date": decision["session_date"],
           "playbook_id": decision["playbook_id"],
           "symbol": decision["symbol"], "direction": decision["direction"],
           "label": "MECHANICAL_DETERMINISTIC",
           "forward_bars": int(len(f))}
    if f.empty:
        out["resolvable"] = False
        return stamp(out, EvidenceClass.EODHD_FORWARD_OBSERVATION)
    px = f["close"].astype(float)
    hi, lo = f["high"].astype(float), f["low"].astype(float)
    times = f["event_time_utc"]
    for h in HORIZONS_MINUTES:
        m = times + BAR <= t0 + pd.Timedelta(minutes=h)
        sub = f[m]
        if sub.empty:
            out[f"ret_{h}m"] = None
            continue
        c = float(sub["close"].iloc[-1])
        out[f"ret_{h}m"] = round(sign * (c / entry - 1), 6)
        fav = (sub["high"].max() if sign > 0 else sub["low"].min())
        adv = (sub["low"].min() if sign > 0 else sub["high"].max())
        out[f"mfe_{h}m"] = round(sign * (float(fav) / entry - 1), 6)
        out[f"mae_{h}m"] = round(sign * (float(adv) / entry - 1), 6)
        out[f"truncated_{h}m"] = bool(
            times.iloc[-1] + BAR < t0 + pd.Timedelta(minutes=h))
    if stop is not None and target is not None:
        if sign > 0:
            stop_hits = f.index[lo <= stop]
            tgt_hits = f.index[hi >= target]
        else:
            stop_hits = f.index[hi >= stop]
            tgt_hits = f.index[lo <= target]
        s_i = int(stop_hits[0]) if len(stop_hits) else None
        t_i = int(tgt_hits[0]) if len(tgt_hits) else None
        out["stop_hit"] = s_i is not None
        out["target_hit"] = t_i is not None
        out["target_before_stop"] = (t_i is not None
                                     and (s_i is None or t_i < s_i))
        out["stop_before_target"] = (s_i is not None
                                     and (t_i is None or s_i <= t_i))
        out["same_bar_ambiguous"] = (s_i is not None and t_i is not None
                                     and s_i == t_i)
    out["closing_return"] = round(sign * (float(px.iloc[-1]) / entry - 1), 6)
    out["resolvable"] = True
    return stamp(out, EvidenceClass.EODHD_FORWARD_OBSERVATION)
