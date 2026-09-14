#!/usr/bin/env python
"""THE FORWARD CLOCK: prospective market-state, scan, decision, and
realization records — frozen before outcomes exist.

    python scripts/hunter_forward_clock.py        # one tick (or fast exit)

Every 15 minutes via launchd. REGULAR session: market-state record, then
the Hunter perception pass (ChartState -> RelativeStrength -> abnormality
scan -> playbook matches -> DECISION records with dependency birth stamps
and mechanical forward-eligibility). POSTMARKET: deterministic realization
of today's unresolved decisions. Otherwise: immediate silent exit.

Monday's archive starts as clean prospective DATA; a playbook claims those
observations as forward EVIDENCE only after its own birth timestamp — the
eligibility verdict in each decision record is computed, never judged.

Cost: ~170 requests/tick during REGULAR (8 ETFs + ~150 universe names +
11 sector ETFs), ~27 ticks/session, one-time ~170 context fetches daily
=> ~5k/day of a 100k/day quota. Token from Keychain via wrapper; never
logged.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402

from apex.hunter import service_progress_hunter as _sph  # noqa: E402

from apex.hunter.context_builder import (  # noqa: E402
    SECTOR_ETF, build_scan_universe, load_or_build_contexts,
)
from apex.hunter.evidence import EvidenceClass, stamp  # noqa: E402
from apex.hunter.forward_pass import (  # noqa: E402
    decision_pass, resolve_decision, unrealized_decisions,
)
from apex.intraday.eodhd import (  # noqa: E402
    QuotaGovernor, cache_path, fetch_intraday_chunk, normalize_rows,
)
from apex.intraday.alpaca_fabric import (  # noqa: E402
    as_normalize_rows_shape as _alpaca_live_bars,
)
from apex.intraday.equity_fabric import (  # noqa: E402
    as_normalize_rows_shape as _live_bars,
)
from apex.intraday.sessions import Session, classify  # noqa: E402
from apex.governance.session_integrity_gate import (  # noqa: E402
    decision_eligible, refusal_reason,
)

LEDGER = Path("results/hunter/forward_ledger.jsonl")
PROTOCOL_FILE = Path("HUNTER-FORWARD-PROTOCOL.md")
INDEXES = ("SPY.US", "QQQ.US", "IWM.US")
STALE_AFTER_MIN = 10


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=_S.parent).stdout.strip()
    except Exception:                                       # noqa: BLE001
        return "unknown"


def _protocol_hash() -> str:
    import hashlib
    return hashlib.sha256(PROTOCOL_FILE.read_bytes()).hexdigest()[:16]


def _fetch_today(sym: str, gov: QuotaGovernor, today: str,
                 bust_cache: bool) -> pd.DataFrame:
    """DAY-1 P0 TRANSPORT REPAIR: the Intraday Historical endpoint
    finalizes bars hours after the session and is not a live source (it
    returned [] for the whole 2026-08-17 open). Live bars are tried in
    role order: PRIMARY_BROAD_SENSOR (Alpaca, full-universe) first,
    SECONDARY_DEEP_REALTIME_SENSOR (EODHD, ~50-name allocation) second
    -- neither silently replaces the other, this is a priority fallback
    chain, same column shape at every step. The historical endpoint
    remains the last-resort fallback and legitimately still returns no
    data for today for symbols neither live sensor reached; this is a
    transport swap only, no ChartState/Hunter logic touched."""
    alpaca_live = _alpaca_live_bars(sym, today)
    if len(alpaca_live):
        return alpaca_live
    live = _live_bars(sym, today)
    if len(live):
        return live
    if bust_cache:
        cp = cache_path(sym, today, today)
        if cp.exists():
            cp.unlink()                             # intraday: refetch fresh
    rows, _ = fetch_intraday_chunk(sym, today, today, gov)
    return normalize_rows(rows, sym)


def _etf_state(sym: str, f: pd.DataFrame, now) -> dict | None:
    reg = f[f["event_time_utc"].map(lambda t: classify(t) is Session.REGULAR)]
    if reg.empty:
        return None
    px = reg["close"].astype(float)
    vol = reg["volume"].astype(float)
    vwap = float((px * vol).sum() / max(vol.sum(), 1))
    r = px.pct_change().dropna()
    return {"symbol": sym,
            "day_return": round(float(px.iloc[-1] / px.iloc[0] - 1), 5),
            "above_vwap": bool(px.iloc[-1] > vwap),
            "realized_vol_ann": round(float(r.std() * np.sqrt(390 * 252)), 4),
            "cum_volume": float(vol.sum()),
            "last_bar_utc": str(reg["event_time_utc"].iloc[-1]),
            "minutes_recorded": int(len(reg))}


def _premarket_levels(f: pd.DataFrame) -> tuple:
    pre = f[f["event_time_utc"].map(
        lambda t: classify(t) is Session.PREMARKET)]
    if pre.empty:
        return None, None
    return float(pre["high"].max()), float(pre["low"].min())


def _state_snapshot(now, gov, today, bars_etf) -> dict:
    sector_syms = tuple(sorted(set(SECTOR_ETF.values())))
    states, health = [], []
    for sym in (*INDEXES, *sector_syms):
        f = bars_etf.get(sym)
        if f is None or f.empty:
            health.append(f"{sym}: no bars")
            continue
        s = _etf_state(sym, f, now)
        if s is None:
            health.append(f"{sym}: no regular-session bars yet")
            continue
        age = (now - pd.Timestamp(s["last_bar_utc"])).total_seconds() / 60
        if age > STALE_AFTER_MIN:
            health.append(f"{sym}: last bar {age:.0f}m old (STALE)")
        states.append(s)
    if not states:
        return stamp({"kind": "forward_state", "timestamp_utc": str(now),
                      "session": "REGULAR",
                      "data_health": ["NO DATA: " + "; ".join(health)],
                      "usable": False},
                     EvidenceClass.EODHD_FORWARD_OBSERVATION)
    idx = [s for s in states if s["symbol"] in INDEXES]
    sec = [s for s in states if s["symbol"] not in INDEXES]
    rets = [s["day_return"] for s in sec]
    spy = ([s for s in idx if s["symbol"] == "SPY.US"] or [{}])[0]
    # protocol §2 regime field (F-03): honest about what is wired — the
    # daily classifier is not yet in the intraday loop; the proxy is the
    # SAME conservative-only rule capital uses (one law, one source)
    regime = {"daily_classifier": "NOT_WIRED_INTRADAY",
              "intraday_vol_state": spy.get("realized_vol_ann"),
              "uncertain_proxy": bool(
                  bool(health) or spy.get("day_return") is None
                  or abs(spy.get("day_return", 0.0)) >= 0.015)}
    return stamp({
        "kind": "forward_state", "timestamp_utc": str(now),
        "session": "REGULAR", "regime": regime,
        "indexes": {s["symbol"]: s for s in idx},
        "sectors": {s["symbol"]: s["day_return"] for s in sec},
        "sector_dispersion": round(float(np.std(rets)), 5) if rets else None,
        "breadth_proxy_crude": (round(float(np.mean([r > 0 for r in rets])), 2)
                                if rets else None),
        "market_above_vwap": ([s for s in idx if s["symbol"] == "SPY.US"]
                              or [{}])[0].get("above_vwap"),
        "data_health": health or ["OK"],
        "usable": len(health) == 0,
        "quota_used_this_snapshot": gov.used,
    }, EvidenceClass.EODHD_FORWARD_OBSERVATION)


def _finalize(record: dict) -> dict:
    record["code_commit"] = _git_sha()
    record["protocol_hash"] = _protocol_hash()
    return _chain_append(LEDGER, record)


def _regular_tick(now, gov, today) -> None:
    import time as _time
    t_stamps = {"t0_tick_start": _time.monotonic()}
    sector_syms = tuple(sorted(set(SECTOR_ETF.values())))
    bars: dict = {}
    for sym in (*INDEXES, *sector_syms):
        try:
            bars[sym] = _fetch_today(sym, gov, today, bust_cache=True)
        except Exception as e:                              # noqa: BLE001
            print(f"fetch {sym}: {type(e).__name__}")
    t_stamps["t1_state_s"] = round(_time.monotonic()
                                   - t_stamps["t0_tick_start"], 1)
    entry = _finalize(_state_snapshot(now, gov, today, bars))
    print(f"forward state {entry['entry_hash'][:12]}")

    # Hunter perception pass — isolated so state recording never dies of it
    try:
        universe = build_scan_universe(today)
        contexts = load_or_build_contexts(
            universe["symbols"], today, gov,
            extra_symbols=(*INDEXES, *sector_syms))
        for sym in universe["symbols"]:
            try:
                f = _fetch_today(f"{sym}.US", gov, today, bust_cache=True)
                f["provider_symbol"] = sym
                bars[sym] = f
                pm_hi, pm_lo = _premarket_levels(f)
                if sym in contexts and pm_hi is not None:
                    contexts[sym] = dataclasses.replace(
                        contexts[sym], premarket_high=pm_hi,
                        premarket_low=pm_lo)
            except Exception as e:                          # noqa: BLE001
                print(f"fetch {sym}: {type(e).__name__}")
        # THE ORDERING LAW: canonical records persist BEFORE any optional
        # enrichment — an LLM hang, rate limit, or dead network can cost
        # enrichment, never a market observation or a candidate
        scan_record, decisions = decision_pass(now, universe, bars, contexts,
                                               enrich=False)
        # decision-latency telemetry (a first-class trading metric): how
        # long each stage of the funnel takes, so edge decay during
        # reasoning is measurable against the bars later
        t_stamps["t2_quant_s"] = round(_time.monotonic()
                                       - t_stamps["t0_tick_start"], 1)
        scan_record["latency"] = {"t0_wall_utc": str(now),
                                  "t1_state_s": t_stamps["t1_state_s"],
                                  "t2_quant_s": t_stamps["t2_quant_s"]}
        scan_record["quota_used_cumulative"] = gov.used
        # SESSION INTEGRITY GATE (operator-ratified, dated, additive
        # only — see apex/governance/session_integrity_gate.py). Never
        # touches ChartState math; only labels the outer envelope and
        # withholds Capital review below when a session is ratified
        # invalid, so nothing downstream can mistake corrupted
        # session-anchored features for decision evidence.
        elig, elig_label = decision_eligible(today)
        scan_record["session_integrity"] = {
            "official_epoch1_decision_eligibility": elig_label,
            "reason": refusal_reason(today)}
        _finalize(scan_record)
        # DIGITAL WORLD (Twin 2.0): the rich terrain record — observational
        # in Epoch 1 (decision_power NONE), fault-isolated like every seat
        try:
            from apex.hunter.context_builder import CONTEXT_LOOKBACK_DAYS
            from apex.world.twin2 import build_world, load_spy_daily
            lo = str((pd.Timestamp(today)
                      - pd.Timedelta(days=CONTEXT_LOOKBACK_DAYS)).date())
            hi = str((pd.Timestamp(today) - pd.Timedelta(days=1)).date())
            spy_rows, _src = fetch_intraday_chunk("SPY.US", lo, hi, gov)
            spy_daily = load_spy_daily(today,
                                       normalize_rows(spy_rows, "SPY.US"))
            spy_ctx = contexts.get("SPY.US")
            world = build_world(
                {k: v for k, v in bars.items() if k.endswith(".US")},
                now, today,
                universe_facets=scan_record.get("universe_facets"),
                spy_daily=spy_daily,
                spy_atr_frac=getattr(spy_ctx, "atr_frac", None))
            w = _finalize(stamp(world,
                                EvidenceClass.EODHD_FORWARD_OBSERVATION))
            print(f"WORLD regime="
                  f"{world['transition_state'].get('regime', 'n/a')} "
                  f"{w['entry_hash'][:12]}")
        except Exception as e:                              # noqa: BLE001
            print(f"twin2 world failed (archive intact): "
                  f"{type(e).__name__}: {e}")
        for d in decisions:
            # additive label only — decision_pass's own fields (incl.
            # forward_eligibility, the frozen birth law) are untouched
            d["decision_evidence_validity"] = (
                "VALID" if elig else "OBSERVATIONAL_INVALID_FOR_DECISION_EVIDENCE")
            e = _finalize(d)
            if not d["playbook_id"].startswith("BASELINE-"):
                print(f"DECISION {d['symbol']} {d['playbook_id']} "
                      f"{d['direction']} {d['forward_eligibility']} "
                      f"[{d['decision_evidence_validity']}] "
                      f"{e['entry_hash'][:12]}")
        print(f"scan: {scan_record['states_computed']} states, "
              f"{scan_record['abnormal']} abnormal, "
              f"{len(decisions)} decisions PERSISTED "
              f"(session_eligibility={elig_label})")
        if not elig:
            # SESSION INTEGRITY GATE: Capital review (the step that
            # would mint OBSERVE/WATCH/PAPER_ELIGIBLE/NO_TRADE/REFUSED
            # authorization state) is withheld entirely for a ratified-
            # invalid session — not run, not silently downgraded. This
            # is also what makes Shadow Paper refuse today via its own
            # EXISTING, untouched law: eligible() already returns
            # (False, None, "no capital decision exists") whenever no
            # capital_decision record exists for a symbol.
            for d in decisions:
                if d["playbook_id"].startswith("BASELINE-"):
                    continue
                _finalize({
                    "kind": "capital_review_refused", "symbol": d["symbol"],
                    "decision_id": d["decision_id"],
                    "reason": "SESSION_INTEGRITY_GATE: "
                             f"{refusal_reason(today)}",
                    "note": "Capital review withheld, not run -- no "
                            "capital_decision record was minted for this "
                            "decision today"})
            print(f"  CAPITAL REVIEW WITHHELD ({elig_label}) for "
                  f"{len([d for d in decisions if not d['playbook_id'].startswith('BASELINE-')])} "
                  f"non-baseline decision(s)")
        else:
            try:
                from apex.hunter.forward_pass import enrichment_pass
                t3 = _time.monotonic()
                from apex.hunter.forward_pass import build_model_history
                for r in enrichment_pass(now, today, decisions, universe,
                                         bars_by_symbol=bars,
                                         model_history_by_symbol=build_model_history(
                                             decisions, bars, now, gov)):
                    if r.get("kind") == "capital_decision":
                        # reasoning time from formation to capital verdict:
                        # the edge-decay clock (price at each stamp is
                        # recoverable from the day's bars at resolution)
                        r["latency"] = {
                            "t2_decisions_persisted_s": t_stamps["t2_quant_s"],
                            "t3_enrichment_s": round(_time.monotonic() - t3, 1),
                            "t4_capital_wall_utc": str(pd.Timestamp.now(tz="UTC"))}
                    e = _finalize(r)
                    if r.get("kind") == "capital_decision":
                        print(f"CAPITAL {r['symbol']} {r['final_state']} "
                              f"{e['entry_hash'][:12]}")
            except Exception as e:                          # noqa: BLE001
                print(f"enrichment pass failed (archive intact): "
                      f"{type(e).__name__}: {e}")
    except Exception as e:                                  # noqa: BLE001
        print(f"perception pass failed: {type(e).__name__}: {e}")


def _post_tick(now, gov, today) -> None:
    pending = unrealized_decisions(today)
    if not pending:
        return
    day_bars: dict = {}
    for d in pending:
        sym = d["symbol"]
        if sym not in day_bars:
            try:
                day_bars[sym] = _fetch_today(f"{sym}.US", gov, today,
                                             bust_cache=True)
            except Exception as e:                          # noqa: BLE001
                print(f"resolve fetch {sym}: {type(e).__name__}")
                continue
        rec = resolve_decision(d, day_bars[sym])
        e = _finalize(rec)
        print(f"REALIZATION {d['decision_id']} {sym} "
              f"tbs={rec.get('target_before_stop')} {e['entry_hash'][:12]}")
    # the day self-reports: scoreboard + funnel diagnostics (read-only)
    try:
        from hunter_scoreboard import main as scoreboard_main
        scoreboard_main()
    except Exception as e:                                  # noqa: BLE001
        print(f"scoreboard failed: {type(e).__name__}: {e}")


def _apply_tick_counters(sp, today: str) -> None:
    """Read the counters for THIS tick back out of the canonical ledger
    Hunter just wrote. Deliberately derived from the persisted record
    rather than threaded through _regular_tick's internals, so the
    observability layer cannot perturb the decision path in any way."""
    try:
        if not LEDGER.exists():
            return
        last_scan = None
        writes = 0
        matches = 0
        for line in LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("session_date") != today and not str(
                    r.get("t_utc", r.get("timestamp_utc", ""))).startswith(today):
                continue
            writes += 1
            if r.get("kind") == "scan":
                last_scan = r
            if (r.get("kind") == "decision"
                    and not str(r.get("playbook_id", "")).startswith("BASELINE-")):
                matches += 1
        sp.ledger_writes = writes
        sp.playbook_matches = matches
        if last_scan is not None:
            sp.states_computed = int(last_scan.get("states_computed") or 0)
            sp.watchlist_count = len(last_scan.get("watchlist") or [])
    except Exception as e:                                  # noqa: BLE001
        print(f"hunter progress counters failed: {type(e).__name__}: {e}")


def main() -> int:
    now = pd.Timestamp.now(tz="UTC")
    sess = classify(now)
    today = str(now.tz_convert("America/New_York").date())

    # OBSERVABILITY ONLY (Phase 1.1). Wraps the tick without touching a
    # single Hunter decision: the tick's own behaviour, ordering and
    # persistence are unchanged, and any failure inside the progress
    # layer is swallowed so it can never cost a market observation.
    sp = None
    try:
        sp = _sph.load_or_advance()
        _sph.write(sp)
    except Exception as e:                                  # noqa: BLE001
        print(f"hunter progress init failed (tick continues): "
              f"{type(e).__name__}: {e}")

    try:
        if sess is Session.REGULAR:
            _regular_tick(now, QuotaGovernor(purpose="FORWARD"), today)
        elif sess is Session.POSTMARKET:
            _post_tick(now, QuotaGovernor(purpose="FORWARD"), today)
        if sp is not None:
            _sph.mark_success(sp)
            _apply_tick_counters(sp, today)
    except Exception as e:                                  # noqa: BLE001
        if sp is not None:
            _sph.mark_failure(sp, f"{type(e).__name__}: {e}")
        raise
    finally:
        if sp is not None:
            try:
                _sph.write(sp)
            except Exception as e:                          # noqa: BLE001
                print(f"hunter progress write failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
