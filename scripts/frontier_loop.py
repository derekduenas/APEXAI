#!/usr/bin/env python
"""FRONTIER SHADOW LOOP — Desk B, running beside the frozen control.

    python scripts/frontier_loop.py [--minutes 395] [--cadence 120]

Each tick (~2 minutes):
  1. read the OFFICIAL ledger and the FastWatch ledger (consumer only);
  2. emit typed frontier events (fastwatch conditions, scout
     abnormalities) onto the bus, transport-labeled POLLING;
  3. run dislocation detectors over canonical candidate states;
  4. snapshot the Frontier Opportunity Board;
  5. for each NEW official playbook decision: route reasoning tier,
     run microscope + Captain Eyes + autonomous visual challenge
     (child-session budget shared with the sensory loop), assemble and
     SEAL an APEXDecisionCard BEFORE outcomes exist.

decision_power = NONE_FRONTIER_SHADOW on every artifact. Epoch-1 neither
reads nor waits on any of this; kill this loop and the control is
untouched (tested).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from apex.governance.session_integrity_gate import (  # noqa: E402
    decision_eligible, refusal_reason,
)
from apex.hunter.watchlist import (  # noqa: E402
    parse_watchlist, record_parse_errors,
)

OFFICIAL = Path("results/hunter/forward_ledger.jsonl")
FASTWATCH = Path("results/hunter/fastwatch_ledger.jsonl")
STATE = Path("results/frontier/loop_state.json")
REFUSALS = Path("results/frontier/decision_refusals.jsonl")
MAX_CHILD_CALLS = 80


def _refuse_card(did: str, symbol: str, day: str, *,
                 gate: str = "SESSION_INTEGRITY_GATE",
                 reason: str | None = None) -> None:
    """SESSION INTEGRITY GATE or KILL/DEGRADE LAW: no Decision Card is
    sealed and no Shadow Paper position is opened when the session is
    ratified invalid OR this service's own progress is STALLED/FAILED
    -- a stale prior judgment can never remain 'current' merely because
    the process stopped completing cycles. Recorded, never silently
    skipped."""
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    REFUSALS.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(REFUSALS, {
        "kind": "frontier_decision_refused", "decision_id": did,
        "symbol": symbol, "session_date": day, "gate": gate,
        "reason": f"{gate}: {reason or refusal_reason(day)}",
        "refused": ("decision_card_seal", "shadow_paper_open"),
        "decision_power": "NONE_FRONTIER_SHADOW"})


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _state() -> dict:
    day = str(pd.Timestamp.now(tz="UTC").date())
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text())
            if st.get("day") == day:
                return st
        except json.JSONDecodeError:
            pass
    return {"day": day, "child_calls": 0, "carded": [],
            "bus_seen": [], "persistence": {}}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    import os
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, STATE)


def _premarket_section(d: dict) -> dict:
    """The sealed opening context, attached by hash. PRIOR_AGREEMENT is
    UNKNOWN in this lineage — computing alignment is a post-Day-1 act,
    not a bell-eve one; the field exists so H_PREMARKET can be tested
    later without retrofitting cards."""
    from apex.frontier.premarket import load_sealed
    import pandas as pd
    day = str(pd.Timestamp(d["t_utc"]).tz_convert(
        "America/New_York").date())
    pkt = load_sealed(day)
    if pkt is None:
        return {"status": "NO_SEALED_PACKET"}
    sym = d.get("symbol", "").replace(".US", "")
    in_watch = any(sym in [s.replace(".US", "") for s in v]
                   for v in pkt.get("watch_map", {}).values())
    return {"premarket_context_hash": pkt["packet_sha256"],
            "sealed": pkt["sealed"],
            "symbol_in_watch_map": in_watch,
            "premarket_prior_agreement": "UNKNOWN",
            "blind_spots": pkt.get("blind_spots", [])}


def build_card(d: dict, rows: list, st: dict) -> None:
    """Assemble + seal the BEFORE card from persisted records only."""
    from apex.frontier.decision_card import persist, seal_before
    from apex.frontier.senses import detect_dislocations, route_reasoning
    from apex.events.catalyst import catalyst_state
    from apex.events.cik_bridge import cik_of
    did, sym = d["decision_id"], d["symbol"]

    def last(kind, with_id=True):
        for r in reversed(rows):
            if r.get("kind") == kind and \
                    (not with_id or r.get("decision_id") == did):
                return r
        return None

    fw = [r for r in _rows(FASTWATCH)
          if r.get("symbol") == sym and r.get("kind") ==
          "fastwatch_observation"]
    first_cond = next((r for r in fw
                       if r.get("fastwatch_condition_observed")), None)
    cat = catalyst_state(sym, pd.Timestamp(d["t_utc"]), cik=cik_of(sym))
    cs, rs = d.get("chart_state") or {}, d.get("relative_strength") or {}
    dis = detect_dislocations(cs, rs, d.get("market_state") or {},
                              catalyst_status=cat.status)
    micro = last("microscope_result", with_id=False) or {"status": "UNKNOWN"}
    visual = None
    for r in reversed(_rows(Path("results/hunter/visual_ledger.jsonl"))):
        if r.get("decision_id") == did:
            visual = r
            break
    route = route_reasoning(
        is_hunter_candidate=True, on_watchlist=True,
        persistence_ticks=st["persistence"].get(did))

    card = seal_before(did, d.get("session_date", str(pd.Timestamp(
        d["t_utc"]).date())), {
        "identity": {"symbol": sym, "t_utc": d["t_utc"],
                     "evidence_class": d.get("evidence_class"),
                     "playbook_id": d.get("playbook_id")},
        "timing": {"official_detection": d["t_utc"],
                   "fastwatch_first_condition": (
                       first_cond or {}).get("observed_at"),
                   "sensing_transport": "POLLING"},
        "premarket": _premarket_section(d),
        "world": last("world_state", with_id=False) or {"status": "UNKNOWN"},
        "scout": {"rvol_tod": cs.get("rvol_tod"),
                  "gap_frac": cs.get("gap_frac"),
                  "above_vwap": cs.get("above_vwap")},
        "dislocation": ({"observations": list(dis)} if dis
                        else {"status": "NONE_OBSERVED"}),
        "hunter": {"playbook_id": d.get("playbook_id"),
                   "direction": d.get("direction"),
                   "entry": d.get("entry"), "stop": d.get("stop"),
                   "invalidation": d.get("invalidation"),
                   "official_status": "OFFICIAL_CANDIDATE"},
        "fastwatch": ({"first_condition": first_cond}
                      if first_cond else {"status": "UNKNOWN"}),
        "microscope": micro,
        "catalyst": cat.as_record(),
        "visual": visual or {"status": "UNKNOWN"},
        "oracle": last("forecast_bundle") or {"status": "UNKNOWN"},
        "assassin": last("assassin_review") or {"status": "UNKNOWN"},
        "captain": last("captain_state") or {"status": "UNKNOWN"},
        "opportunity_competition": {"status": "SEE_BOARD_LEDGER"},
        "capital": last("capital_decision") or {"status": "UNKNOWN"},
        "expression": {"status": "UNKNOWN"},
        "execution": {"status": "UNKNOWN"},
        "before_statement": {
            "what_i_see": f"{d.get('playbook_id')} {d.get('direction')} "
                          f"candidate on {sym}",
            "why_it_matters": (dis[0]["mechanism_hypothesis"] if dis
                               else "mechanism per playbook"),
            "what_could_make_me_wrong": d.get("invalidation",
                                              "per playbook stop law"),
            "entry_attractiveness": ((visual or {}).get("entry_geometry")
                                     or "UNKNOWN"),
            "what_would_make_it_better": "acceptance/retest per doctrine"},
    }, official_epoch_candidate=True, frontier_shadow_candidate=True)
    p = persist(card)
    print(f"  CARD SEALED {did} -> {p} sha={card['card_sha256'][:12]}")


def tick(st: dict, *, service_progress_status: str = "HEALTHY") -> None:
    from apex.frontier.senses import emit, rank_opportunities
    now = pd.Timestamp.now(tz="UTC")
    rows = _rows(OFFICIAL)
    decisions = [r for r in rows if r.get("kind") == "decision"
                 and not str(r.get("playbook_id", "")).startswith("BASELINE-")]
    for d in decisions:                       # persistence in loop ticks
        st["persistence"][d["decision_id"]] = \
            st["persistence"].get(d["decision_id"], 0) + 1

    # bus: new fastwatch conditions become typed events
    for r in _rows(FASTWATCH)[-40:]:
        if r.get("fastwatch_condition_observed") and \
                r.get("entry_hash") not in st["bus_seen"]:
            try:
                emit("FASTWATCH_OBSERVATION", r["symbol"],
                     event_time=r["last_market_timestamp"],
                     known_from=r["observed_at"], source="fastwatch",
                     transport="POLLING",
                     payload={"conditions":
                              r["fastwatch_condition_observed"]})
                st["bus_seen"] = (st["bus_seen"] + [r["entry_hash"]])[-500:]
            except Exception as e:                          # noqa: BLE001
                print(f"  bus emit failed: {type(e).__name__}")

    # THE DENOMINATOR: every watchlist member leaves a sealed trace,
    # including the ones that die here. Traced once per (day, symbol,
    # stage) so a quiet name is one row, not four hundred.
    from apex.frontier.decision_card import seal_trace
    scans = [r for r in rows if r.get("kind") == "scan"]
    day = st["day"]
    seen_tr = set(st.get("traced", []))
    hunter_syms = {d["symbol"] for d in decisions}
    for scan in scans[-2:]:
        # THE FASTWATCH-CLASS BUG, fixed at its second site: the
        # persisted watchlist is dicts (apex/hunter/watchlist.py), never
        # positional tuples. parse_watchlist() skips and RECORDS a
        # malformed entry instead of raising -- one bad row can never
        # again stall this whole loop the way it did from 14:52 UTC
        # onward on 2026-08-17 (root cause of the Frontier stall).
        wl_entries, wl_errors = parse_watchlist(scan.get("watchlist"))
        record_parse_errors(wl_errors, component="frontier_loop.tick",
                           input_reference=str(scan.get("t_utc")))
        for entry in wl_entries:
            sym, sigs, rvol = entry.symbol, entry.signals, entry.rvol
            stage = "HUNTER" if sym in hunter_syms else "WATCHLIST"
            key = f"{day}|{sym}|{stage}"
            if key in seen_tr:
                continue
            try:
                seal_trace(symbol=sym, session_date=day,
                           entered_because=f"scout signals {list(sigs)[:4]}",
                           stage_reached=stage,
                           died_at=None if stage == "HUNTER" else "WATCHLIST",
                           when=str(now),
                           what_was_known={"signals": list(sigs)[:6],
                                           "rvol": rvol,
                                           "rvol_status": entry.rvol_status})
                seen_tr.add(key)
            except Exception as e:                          # noqa: BLE001
                print(f"  trace failed for {sym}: {type(e).__name__}")
    st["traced"] = sorted(seen_tr)[-2000:]

    # board snapshot from current candidates
    cands = [{"symbol": d["symbol"], "as_of": d["t_utc"],
              "candidate_class": "HUNTER",
              "data_health": ("HEALTHY" if not (d.get("chart_state") or {})
                              .get("data_quality") else "DEGRADED")}
             for d in decisions[-10:]]
    if cands:
        rank_opportunities(cands)

    # decision cards + child-session work for new candidates
    fresh = [d for d in decisions if d["decision_id"] not in st["carded"]]
    day_elig, day_label = decision_eligible(st["day"])
    # KILL/DEGRADE LAW: a STALLED or FAILED Frontier loses decision
    # authority automatically -- a stale prior judgment can never remain
    # "current" merely because the process stopped completing cycles.
    # DEGRADED (occasional failures, still completing cycles) may still
    # act; STALLED/FAILED may not.
    service_ok = service_progress_status not in ("STALLED", "FAILED")
    elig = day_elig and service_ok
    label = day_label if not day_elig else (
        f"SERVICE_{service_progress_status}" if not service_ok else day_label)
    for d in fresh[:3]:
        did = d["decision_id"]
        if not elig:
            if not day_elig:
                _refuse_card(did, d["symbol"], st["day"],
                            gate="SESSION_INTEGRITY_GATE")
            else:
                _refuse_card(did, d["symbol"], st["day"],
                            gate="SERVICE_HEALTH_GATE",
                            reason=f"progress_status={service_progress_status}")
            st["carded"].append(did)     # seen, not retried -- refused, not skipped
            print(f"  CARD REFUSED {d['symbol']} ({label})")
            continue
        if MAX_CHILD_CALLS - st["child_calls"] >= 3:
            subprocess.run([sys.executable, "scripts/microscope_pass.py"],
                           capture_output=True, text=True, timeout=600)
            subprocess.run([sys.executable, "scripts/captain_eyes.py", did],
                           capture_output=True, text=True, timeout=600)
            eyes = Path(f"results/hunter/eyes/{did}_eyes.json")
            if eyes.exists():
                subprocess.run([sys.executable, "scripts/captain_eyes.py",
                                "--challenge", str(eyes)],
                               capture_output=True, text=True, timeout=600)
            st["child_calls"] += 3
        try:
            build_card(d, rows, st)
            st["carded"].append(did)
            # SHADOW PAPER: authorization is the only counterfactual.
            # Eligibility is the FROZEN rule; the fill needs the REAL
            # microscope quote or it refuses.
            from apex.frontier.shadow_paper import open_position
            card_p = Path(f"results/decision_cards/{st['day']}/{did}.json")
            chash = (json.loads(card_p.read_text())["before"]
                     ["card_sha256"] if card_p.exists() else None)
            cap = next((r for r in reversed(rows)
                        if r.get("kind") == "capital_decision"
                        and r.get("decision_id") == did), None)
            q = None
            for r in reversed(_rows(Path(
                    "results/hunter/microscope_ledger.jsonl"))):
                if r.get("kind") == "microscope_result" and                         r.get("symbol", "").replace(".US", "") ==                         d["symbol"].replace(".US", ""):
                    raw = (r.get("quote") or {})
                    inner = ((raw.get("data") or {}).get("results")
                             or [{}])[0].get("quote", {})                         if isinstance(raw.get("data"), dict) else raw
                    q = {"bid": float(inner["bid_price"])
                         if inner.get("bid_price") else None,
                         "ask": float(inner["ask_price"])
                         if inner.get("ask_price") else None,
                         "quote_time": inner.get("updated_at")
                         or r.get("response_time")}
                    break
            sp = open_position(d, cap, card_hash=chash, quote=q)
            st.setdefault("shadow_positions", {})[did] =                 {k: v for k, v in sp.as_record().items() if k != "kind"}
            print(f"  SHADOW {sp.state} {did}"
                  + (f" @ {sp.entry_price}" if sp.entry_price else
                     f" ({sp.exit_reason})"))
        except Exception as e:                              # noqa: BLE001
            print(f"  card build failed for {did}: {type(e).__name__}: {e}")
    # CONTINUOUS RE-UNDERWRITING: every carded candidate gets the
    # current-state question on material change or stale heartbeat.
    # Inputs are CURRENT canonical records; the prior judgment's content
    # cannot leak (enforced by reunderwrite's signature).
    from apex.frontier.underwriting import (OpportunityState,
                                            judgment_status, reunderwrite,
                                            what_changed)
    states = st.setdefault("opportunity_states", {})
    visuals = {r.get("decision_id"): r for r in
               _rows(Path("results/hunter/visual_ledger.jsonl"))
               if r.get("kind") == "visual_challenge"}
    for d in decisions:
        did = d["decision_id"]
        cs = d.get("chart_state") or {}
        vis = visuals.get(did) or {}
        cur = {"rs_state": ("PERSISTING" if (d.get("relative_strength")
                            or {}).get("excess_market_60m", 0) > 0
                            else "UNKNOWN"),
               "vwap_relationship": ("ABOVE" if cs.get("above_vwap")
                                     else "BELOW"
                                     if cs.get("above_vwap") is False
                                     else "UNKNOWN"),
               "visual_structure": vis.get("visual_structure", "UNKNOWN"),
               "assassin_verdict": next(
                   (r.get("verdict") for r in reversed(rows)
                    if r.get("kind") == "assassin_review"
                    and r.get("decision_id") == did), "UNKNOWN")}
        raw = states.get(did)
        prior = (OpportunityState(**raw) if raw else OpportunityState(
            candidate_id=did, symbol=d["symbol"], state="DISCOVERED"))
        if prior.state in ("INVALIDATED", "EXPIRED"):
            continue
        stale = judgment_status(prior, now)["status"] == "STALE"
        material = bool(what_changed(prior.inputs_snapshot, cur))
        if stale or material:
            eg = vis.get("entry_geometry", "UNKNOWN")
            dq = ("STRONG" if eg.startswith("DIRECTION_STRONG")
                  else "MODERATE" if eg == "UNKNOWN" else "WEAK")
            eq = ("STRONG" if eg.endswith("ENTRY_STRONG")
                  else "WEAK" if eg.endswith("ENTRY_WEAK") else "UNKNOWN")
            try:
                nxt = reunderwrite(prior, current_inputs=cur,
                                   direction_quality=dq, entry_quality=eq)
                states[did] = {k: v for k, v in nxt.as_record().items()
                               if k != "kind"}
            except Exception as e:                          # noqa: BLE001
                print(f"  reunderwrite failed for {did}: "
                      f"{type(e).__name__}")

    # manage open shadow positions on fresh completed bars
    from apex.frontier.shadow_paper import ShadowPosition, manage
    from apex.intraday.eodhd import QuotaGovernor, fetch_intraday_chunk, \
        normalize_rows
    spos = st.setdefault("shadow_positions", {})
    open_ids = [k for k, v in spos.items() if v.get("state") == "SHADOW_OPEN"]
    if open_ids:
        gov = QuotaGovernor(daily_budget=2000, purpose="LAB")
        for did in open_ids:
            v = spos[did]
            try:
                raw, _src = fetch_intraday_chunk(v["symbol"], st["day"],
                                                 st["day"], gov)
                f = normalize_rows(raw or [], v["symbol"])
                if not len(f):
                    continue
                bar = f.iloc[-1]
                nxt = manage(ShadowPosition(**v),
                             {"high": float(bar.high),
                              "low": float(bar.low),
                              "close": float(bar.close)}, now=now)
                spos[did] = {k: x for k, x in nxt.as_record().items()
                             if k != "kind"}
                if nxt.state == "SHADOW_FLAT":
                    print(f"  SHADOW FLAT {did} {nxt.exit_reason} "
                          f"@ {nxt.exit_price}")
            except Exception as e:                          # noqa: BLE001
                print(f"  shadow manage failed {did}: {type(e).__name__}")

    if not decisions:
        print(f"{now:%H:%M:%S} frontier quiet — no candidates yet "
              f"(budget {MAX_CHILD_CALLS - st['child_calls']} child calls)")
    else:
        print(f"{now:%H:%M:%S} candidates={len(decisions)} "
              f"carded={len(st['carded'])}")
    _save(st)


PROGRESS_STATE_PATH = Path("results/frontier/service_progress.json")


def main() -> int:
    import argparse
    import traceback
    from apex.governance import service_progress as sp
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=395)
    ap.add_argument("--cadence", type=float, default=120)
    a = ap.parse_args()
    print("FRONTIER SHADOW LOOP — decision_power NONE_FRONTIER_SHADOW")
    t_end = time.time() + a.minutes * 60

    # RESTART SEMANTICS: this PID starts a FRESH ServiceProgressState --
    # it never inherits a previous instance's last_successful_cycle as
    # evidence of ITS OWN health (the exact 2026-08-17 ambiguity).
    prog = sp.start("frontier_loop", expected_cadence_s=a.cadence)
    sp.write(prog, PROGRESS_STATE_PATH)

    while time.time() < t_end:
        prog.cycle_number += 1
        prog.last_cycle_start = str(pd.Timestamp.now(tz="UTC"))
        prog.heartbeat_time = prog.last_cycle_start
        t0 = time.monotonic()
        try:
            st = _state()
            prog.last_state_read = str(pd.Timestamp.now(tz="UTC"))
            # the gate reflects health COMING INTO this cycle (state
            # accumulated by prior cycles) -- a service cannot bless its
            # own current cycle's authority
            tick(st, service_progress_status=prog.progress_status())
            prog.last_state_write = str(pd.Timestamp.now(tz="UTC"))
            now = str(pd.Timestamp.now(tz="UTC"))
            prog.last_cycle_complete = now
            prog.last_successful_cycle = now
            prog.cycle_duration_s = round(time.monotonic() - t0, 3)
            prog.consecutive_failures = 0
            prog.blocking_operation = None
            prog.error_reference = None
        except Exception as e:                              # noqa: BLE001
            # NO SILENT EXCEPTION LOOPS: every failure is a STRUCTURED,
            # DURABLE record with a full traceback, the cycle it happened
            # on, and the exact input in play -- never print() into a
            # pipe that may sit unflushed for hours (2026-08-17's actual
            # failure mode: ~150 identical KeyErrors, invisible until the
            # process finally exited on its own budget).
            tb = traceback.format_exc()
            err_path = Path(f"results/frontier/errors/"
                           f"cycle_{prog.cycle_number:06d}.json")
            err_path.parent.mkdir(parents=True, exist_ok=True)
            err_path.write_text(json.dumps({
                "kind": "frontier_cycle_error", "cycle_number": prog.cycle_number,
                "timestamp_utc": str(pd.Timestamp.now(tz="UTC")),
                "exception_type": type(e).__name__, "message": str(e),
                "traceback": tb}, indent=1, default=str))
            prog.last_cycle_complete = str(pd.Timestamp.now(tz="UTC"))
            prog.consecutive_failures += 1
            prog.total_failures += 1
            prog.error_reference = str(err_path)
            print(f"CYCLE {prog.cycle_number} FAILED "
                  f"({prog.consecutive_failures} consecutive): "
                  f"{type(e).__name__}: {e} -> {err_path}")
        sp.write(prog, PROGRESS_STATE_PATH)
        time.sleep(a.cadence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
