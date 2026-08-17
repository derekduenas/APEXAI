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

OFFICIAL = Path("results/hunter/forward_ledger.jsonl")
FASTWATCH = Path("results/hunter/fastwatch_ledger.jsonl")
STATE = Path("results/frontier/loop_state.json")
MAX_CHILD_CALLS = 80


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


def tick(st: dict) -> None:
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
        for entry in scan.get("watchlist") or []:
            try:
                sym, sigs, rvol = entry[0], entry[1], entry[2]
            except (TypeError, IndexError):
                continue
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
                                           "rvol": rvol})
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
    for d in fresh[:3]:
        did = d["decision_id"]
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

    if not decisions:
        print(f"{now:%H:%M:%S} frontier quiet — no candidates yet "
              f"(budget {MAX_CHILD_CALLS - st['child_calls']} child calls)")
    else:
        print(f"{now:%H:%M:%S} candidates={len(decisions)} "
              f"carded={len(st['carded'])}")
    _save(st)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=395)
    ap.add_argument("--cadence", type=float, default=120)
    a = ap.parse_args()
    print("FRONTIER SHADOW LOOP — decision_power NONE_FRONTIER_SHADOW")
    t_end = time.time() + a.minutes * 60
    while time.time() < t_end:
        try:
            tick(_state())
        except Exception as e:                              # noqa: BLE001
            print(f"tick failed (loop continues): {type(e).__name__}: {e}")
        time.sleep(a.cadence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
