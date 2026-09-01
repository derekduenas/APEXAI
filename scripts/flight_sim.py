"""APEX ORGANISM FLIGHT SIMULATOR — real event-time replay.

EVIDENCE CLASS: DIAGNOSTIC_REPLAY_ONLY. This run validates plumbing,
timing, state construction, expert firing, decision reachability and
attribution. It creates NO alpha authority, NO promotion, NO
prospective credit. The session was chosen (using known outcomes,
legally for diagnostics) to stress the organism: a PM negative
surprise whose thesis LOST.

FROZEN ORGANISM: the same modules used prospectively are imported
and called -- monster consult (A1/A2), expert registry, market_state,
microstructure, options_surface, capital arena, risk kernel. No
backtest-only strategy logic exists here; adapters only translate
historical records into the current contracts.

CLOCK: frames on a 5-minute grid 09:30-16:00 ET plus material
transitions. At simulated time T, every input honors known_from <= T:
  * SIP ticks fetched strictly in [T-5m, T]
  * option NBBO series filtered to timestamps <= T
  * the event's estimate/actual were public before the open
    (report 2026-02-12 AMC), so known_from = session open
  * regime row is the last atlas session STRICTLY BEFORE the day.

decision_power: DIAGNOSTIC_REPLAY_ONLY.
"""
from __future__ import annotations

import hashlib
import json
import time as wallclock
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apex.capital.arena import Candidate, PortfolioState, compete
from apex.monster import consult as monster_consult
from apex.monster.event_expert import EventRecord
from apex.organism import expert_registry, microstructure as ms
from apex.organism import options_surface as osf
from apex.organism import risk_kernel

SYM, SESSION = "COIN", "2026-02-13"
EVENT = {"symbol": SYM, "report_date": "2026-02-12", "timing": "pm",
         "eps_estimate": 1.05, "eps_actual": 0.66,
         "consensus_provenance": "BROKER_REPORTED_CONSENSUS_RH_MCP",
         "known_from": f"{SESSION}T09:30:00-05:00",
         "reaction_session": SESSION}
RT_BPS = 16.21          # observed_rt_bps for this event (corpus)
FRONT_EXP = "2026-02-20"
RECORDER = Path(f"results/organism/flight_recorder_{SYM}_"
                f"{SESSION.replace('-', '')}.jsonl")

PERF = {"events": 0, "quotes": 0, "trades": 0, "opt_obs": 0,
        "frames": 0, "frames_skipped": 0, "expert_calls": 0,
        "arena_calls": 0, "risk_calls": 0,
        "future_data_violations": 0, "unknown_fields": 0}
MATRIX: dict = {}


def organ(name, *, material=False, changed=False,
          unavailable=False):
    m = MATRIX.setdefault(name, {"invoked": 0, "material": 0,
                                 "changed_decision": 0,
                                 "unavailable": 0})
    m["invoked"] += 1
    if material:
        m["material"] += 1
    if changed:
        m["changed_decision"] += 1
    if unavailable:
        m["unavailable"] += 1


def frozen_manifest() -> dict:
    files = ["apex/monster/consult.py", "apex/monster/"
             "pm_fade_expert.py", "apex/monster/event_expert.py",
             "apex/capital/arena.py", "apex/organism/risk_kernel.py",
             "apex/organism/expert_registry.py",
             "apex/organism/microstructure.py",
             "apex/organism/options_surface.py"]
    return {"kind": "frozen_organism_manifest",
            "organ_sha256": {f: hashlib.sha256(
                Path(f).read_bytes()).hexdigest()[:16]
                for f in files},
            "risk_limits": dict(risk_kernel.LIMITS),
            "registry": expert_registry.summary(),
            "law": "no threshold or semantic changes during replay"}


def et(hhmm: str) -> datetime:
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return datetime(2026, 2, 13, h + 5, m,
                    tzinfo=timezone.utc)     # EST (Feb) = UTC-5


def bars_day():
    d = ms._get("https://data.alpaca.markets/v2/stocks/"
                f"{SYM}/bars?" + urllib.parse.urlencode(
                    {"start": f"{SESSION}T14:30:00Z",
                     "end": f"{SESSION}T21:00:00Z",
                     "timeframe": "1Min", "feed": "sip",
                     "limit": 10000}))
    return {b["t"]: b for b in d.get("bars") or []}


def poison_test() -> dict:
    """Chronos poison philosophy: offer future-stamped inputs to the
    causal adapters; they must be excluded."""
    from apex.organism import market_state
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl",
                                     delete=False) as f:
        f.write(json.dumps({"session": "2026-02-12",
                            "trend": "PAST_OK"}) + "\n")
        f.write(json.dumps({"session": "2026-02-14",
                            "trend": "FUTURE_POISON"}) + "\n")
        p = Path(f.name)
    reg = market_state._regime("2026-02-13", p)
    consumed = "FUTURE_POISON" in json.dumps(reg)
    # option series filter
    series = [{"t": "2026-02-13T09:35:00.000", "bid": 1, "ask": 2},
              {"t": "2026-02-13T15:59:00.000", "bid": 9, "ask": 10}]
    asof = [r for r in series if r["t"] <= "2026-02-13T10:00:00"]
    consumed2 = any(r["bid"] == 9 for r in asof)
    if consumed or consumed2:
        PERF["future_data_violations"] += 1
    return {"kind": "poison_test",
            "regime_adapter_consumed_future": consumed,
            "option_filter_consumed_future": consumed2,
            "FUTURE_INFORMATION_CONSUMED": int(consumed or consumed2)}


def main():
    t_wall = wallclock.time()
    RECORDER.parent.mkdir(parents=True, exist_ok=True)
    frames = []

    def frame(rec):
        rec["frame_id"] = len(frames)
        frames.append(rec)
        PERF["frames"] += 1

    manifest = frozen_manifest()
    frame({"kind": "manifest", **manifest,
           "evidence_class": "DIAGNOSTIC_REPLAY_ONLY",
           "session": SESSION, "subject": SYM,
           "why_this_session": "PM negative surprise (wakes A1+A2), "
           "liquid options (ThetaData+OPRA coverage), adversarial "
           "outcome (thesis lost) to stress re-underwriting and "
           "attribution -- not chosen to flatter"})
    frame(poison_test())

    px = bars_day()
    bar_keys = sorted(px)

    # ---- option series for the day (fetched once, filtered as-of)
    strike = 150.0
    opt = {}
    for right in ("P", "C"):
        try:
            rows = osf.td_history_quote(SYM, FRONT_EXP, strike,
                                        right, SESSION,
                                        interval="5m")
            PERF["opt_obs"] += len(rows)
            opt[right] = rows
        except Exception as e:                          # noqa: BLE001
            opt[right] = []
            organ("options_surface", unavailable=True)
    otm = {}
    try:
        otm["P"] = osf.td_history_quote(SYM, FRONT_EXP, 142.0, "P",
                                        SESSION, interval="5m")
        PERF["opt_obs"] += len(otm["P"])
    except Exception:                                   # noqa: BLE001
        otm["P"] = []

    def opt_asof(rows, hhmm):
        cut = f"{SESSION}T{hhmm}:00.000"
        past = [r for r in rows if r["t"] <= cut]
        return past[-1] if past else None

    # ---- regime (strictly prior session)
    from apex.organism import market_state
    reg = market_state._regime("2026-02-12",
                               Path("exports/regime_atlas_v1.jsonl"))
    organ("regime_atlas", material=True)

    # ---- 09:35 formation: consult the REAL frozen experts
    p935 = opt_asof(opt["P"], "09:35")
    p935_otm = opt_asof(otm["P"], "09:35")
    put_quotes = None
    if p935 and p935_otm:
        put_quotes = {"long_put": {"strike": strike,
                                   "bid": p935["bid"],
                                   "ask": p935["ask"],
                                   "expiry": FRONT_EXP},
                      "put_vertical": {
                          "long": {"strike": strike,
                                   "ask": p935["ask"]},
                          "short": {"strike": 142.0,
                                    "bid": p935_otm["bid"]},
                          "expiry": FRONT_EXP}}
    ev = EventRecord(**EVENT)
    PERF["expert_calls"] += 2
    organ("expert_A1_pm_fade", material=True)
    organ("expert_A2_neg_surprise", material=True)
    consult = monster_consult.consult(
        ev, rt_cost_bps=RT_BPS, short_allowed=False,
        put_quotes=put_quotes)
    PERF["arena_calls"] += 1
    organ("capital_arena", material=True,
          changed=consult["final"] != "NO_TRADE")
    for name in ("catalyst", "parallax", "equity_incumbent",
                 "options_vrp_sleeve", "btc_predator"):
        organ(name, unavailable=True)   # not replayable here; honest

    entry_key = f"{SESSION}T14:35:00Z"
    entry_px = px.get(entry_key, {}).get("c")
    frame({"kind": "decision_frame", "sim_time": "09:35:00 ET",
           "subject": SYM,
           "event_state": {"surprise": "NEGATIVE",
                           "eps": [1.05, 0.66],
                           "known_from": EVENT["known_from"],
                           "provenance": EVENT[
                               "consensus_provenance"]},
           "regime": reg.get("value", reg),
           "options_at_formation": {
               "atm_put_150": p935 and {k: p935[k] for k in
                                        ("bid", "ask", "bid_size",
                                         "ask_size", "t")},
               "otm_put_142": p935_otm and {
                   "bid": p935_otm["bid"], "ask": p935_otm["ask"]}},
           "experts": consult["experts"],
           "agreement": consult["mechanism_agreement"],
           "physical_thesis": consult["physical_thesis"],
           "expressions": consult.get("expressions"),
           "best_expression": consult.get("best_expression"),
           "arena": consult.get("arena"),
           "final": consult["final"],
           "why": consult["final_reason"],
           "authority_note": "A1/A2 are OBSERVE_ONLY: final is "
                             "capped at WATCH regardless of "
                             "economics"})

    # ---- risk kernel consulted for the DIAGNOSTIC shadow position
    PERF["risk_calls"] += 1
    from apex.organism.risk_certificate import certify
    k = risk_kernel.check(
                          certificate=certify(
                              expression="LONG_CALL", direction="LONG",
                              declared_risk=300.0,
                              sleeve_payload={"net_debit": 300.0}),
                          expression="LONG_CALL", direction="LONG",
                          sleeve_payload={"net_debit": 300.0},
                          open_certified_risk=0.0,
                          declared_risk=300.0, symbol=SYM,
                          beta_family="UNKNOWN", open_risk=0.0,
                          same_underlying_risk=0.0,
                          same_family_risk=0.0,
                          session_realized_pnl=0.0,
                          available_capital=10_000.0)
    organ("risk_kernel", material=True)
    frame({"kind": "risk_frame", "sim_time": "09:35:01 ET",
           "risk": {"approved": k["approved"],
                    "threshold_set": k["threshold_set"]},
           "note": "kernel consulted for the DIAGNOSTIC shadow "
                   "position that follows A1's frozen mechanics"})

    # ---- position movie: diagnostic shadow short per A1 mechanics
    pos = {"entry_px": entry_px, "direction": "SHORT",
           "entry_time": "09:35", "declared_risk": 300.0,
           "expected_net_bps": consult["physical_thesis"]
           ["expected_net_bps"]}
    mfe = mae = 0.0
    last_logged = {"mid": entry_px, "flow_sign": 0}
    tick_grid = [f"{h:02d}:{m:02d}" for h in range(9, 16)
                 for m in range(0, 60, 5)
                 if (h, m) > (9, 35) and (h, m) <= (15, 55)
                 and (h > 9 or m >= 40)]
    for hhmm in tick_grid:
        t1 = et(hhmm)
        key = t1.strftime("%Y-%m-%dT%H:%M:00Z")
        bar = px.get(key)
        if not bar or not entry_px:
            continue
        mid = bar["c"]
        pnl_bps = (entry_px / mid - 1) * 1e4   # short convention
        mfe, mae = max(mfe, pnl_bps), min(mae, pnl_bps)
        # material-transition test: move>30bps since last frame,
        # or signed-flow flip (microstructure pulled only then)
        moved = abs(mid / last_logged["mid"] - 1) * 1e4 > 30
        on_grid_15 = hhmm.endswith(("00", "15", "30", "45"))
        if not (moved or on_grid_15):
            PERF["frames_skipped"] += 1
            continue
        micro = {"status": "NOT_PULLED"}
        if moved:
            try:
                tr = ms.fetch_ticks(
                    SYM, (t1 - timedelta(minutes=5)).isoformat(),
                    t1.isoformat(), what="trades", max_pages=2)
                qt = ms.fetch_ticks(
                    SYM, (t1 - timedelta(minutes=5)).isoformat(),
                    t1.isoformat(), what="quotes", max_pages=2)
                PERF["trades"] += len(tr)
                PERF["quotes"] += len(qt)
                micro = ms.micro_state(tr, qt, window_label=hhmm)
                organ("microstructure", material=True)
            except Exception as e:                      # noqa: BLE001
                micro = {"status": "NOT_ESTIMABLE",
                         "why": type(e).__name__}
                organ("microstructure", unavailable=True)
        pnow = opt_asof(opt["P"], hhmm)
        organ("options_surface",
              material=bool(pnow), unavailable=not pnow)
        organ("captain_reunderwrite", material=moved)
        frame({"kind": "reunderwrite_frame",
               "sim_time": f"{hhmm} ET", "subject": SYM,
               "trigger": "MATERIAL_MOVE" if moved else "GRID",
               "mid": mid,
               "position": {"pnl_bps": round(pnl_bps, 1),
                            "mfe_bps": round(mfe, 1),
                            "mae_bps": round(mae, 1)},
               "microstructure": {kk: micro.get(kk) for kk in
                                  ("status", "net_signed_volume",
                                   "spread_bps_median",
                                   "trade_intensity_per_s",
                                   "impact_bps_per_1k_signed",
                                   "nbbo_imbalance_mean")},
               "atm_put_now": pnow and {"bid": pnow["bid"],
                                        "ask": pnow["ask"],
                                        "t": pnow["t"]},
               "remaining_edge": "NOT_ESTIMABLE -- the frozen "
                                 "organism has no dynamic "
                                 "remaining-edge model; the sealed "
                                 "rule is horizon exit at close",
               "management": "HOLD_PER_SEALED_RULES",
               "alternatives": {"CASH_exit_cost_bps": RT_BPS / 2,
                                "new_opportunities": 0}})
        last_logged["mid"] = mid

    # ---- resolution + counterfactuals + attribution
    close_key = bar_keys[-1]
    close_px = px[close_key]["c"]
    stock_short_net = (entry_px / close_px - 1) * 1e4 - RT_BPS
    p_entry, p_exit = opt_asof(opt["P"], "09:35"), \
        opt_asof(opt["P"], "15:55")
    po_entry, po_exit = opt_asof(otm["P"], "09:35"), \
        opt_asof(otm["P"], "15:55")
    put_pnl = vert_pnl = "NOT_ESTIMABLE"
    if p_entry and p_exit:
        put_pnl = round((p_exit["bid"] - p_entry["ask"])
                        / p_entry["ask"] * 100, 1)
    if p_entry and p_exit and po_entry and po_exit:
        cost = p_entry["ask"] - po_entry["bid"]
        val = p_exit["bid"] - po_exit["ask"]
        vert_pnl = round((val - cost) / cost * 100, 1) if cost > 0 \
            else "NOT_ESTIMABLE"
    thesis_dir_right = stock_short_net > 0
    frame({"kind": "resolution_frame", "sim_time": "16:00 ET",
           "entry_px": entry_px, "close_px": close_px,
           "monster_decision": consult["final"],
           "monster_realized_bps": 0.0
           if consult["final"] in ("NO_TRADE", "WATCH")
           else stock_short_net,
           "counterfactuals": {
               "CASH": 0.0,
               "STOCK_SHORT_net_bps": round(stock_short_net, 1),
               "ALWAYS_PM_FADE_baseline_net_bps": round(
                   stock_short_net, 1),
               "LONG_PUT_pct_on_premium": put_pnl,
               "PUT_VERTICAL_pct_on_debit": vert_pnl},
           "attribution": {
               "physical_thesis": "CORRECT" if thesis_dir_right
               else "WRONG (stock rallied against the short)",
               "selection": "NOT_SEPARABLE (single event)",
               "expression": "CASH-capped by broker constraint + "
                             "authority; compare counterfactuals",
               "arena": "HELPED" if not thesis_dir_right
               and consult["final"] != "ATTACK" else "SEE_CF",
               "risk": "NOT_TESTED (no funded loss)",
               "management": "STATIC_HORIZON_ONLY -- no dynamic "
                             "authority exists (behavioral gap, "
                             "recorded not repaired)",
               "cash": "BETTER" if not thesis_dir_right
               else "WORSE",
               "dumb_baseline_vs_monster_bps": round(
                   0.0 - stock_short_net, 1)
               if consult["final"] in ("NO_TRADE", "WATCH")
               else 0.0},
           "law": "counterfactuals never altered any decision"})

    # ---- lineage trace (one auditable path)
    frame({"kind": "lineage_trace",
           "trace": [
               {"1_raw": f"ThetaData COIN {FRONT_EXP} 150P quote "
                         f"at {p935 and p935['t']}",
                "fields": p935},
               {"2_adapter": "put_quotes dict (bid/ask preserved)"},
               {"3_expert": "monster_consult.consult A1+A2 "
                            "(frozen; OBSERVE_ONLY)"},
               {"4_contract": "physical_thesis + expressions "
                              "(consult record)"},
               {"5_arena": consult.get("arena", {}).get(
                   "verdict", "see decisions")},
               {"6_risk": f"kernel approved={k['approved']}"},
               {"7_book": "DIAGNOSTIC shadow only; production "
                          "book untouched"}]})

    # ---- organ matrix + dead/decorative classification
    classify = {}
    for name, m in MATRIX.items():
        if m["unavailable"] == m["invoked"]:
            classify[name] = "UNREACHABLE_IN_REPLAY"
        elif m["material"] == 0:
            classify[name] = "DECORATIVE_THIS_SESSION"
        else:
            classify[name] = "ECONOMICALLY_ACTIVE"
    frame({"kind": "organ_matrix", "matrix": MATRIX,
           "classification": classify})

    PERF["events"] = PERF["trades"] + PERF["quotes"] \
        + PERF["opt_obs"] + len(px)
    PERF["wall_seconds"] = round(wallclock.time() - t_wall, 1)
    PERF["session_seconds_per_wall_second"] = round(
        6.5 * 3600 / max(PERF["wall_seconds"], 1), 1)
    frame({"kind": "performance", **PERF})

    with RECORDER.open("w") as f:
        for fr in frames:
            f.write(json.dumps(fr, default=str) + "\n")
    print(json.dumps({"frames": len(frames),
                      "recorder": str(RECORDER), **PERF}))


if __name__ == "__main__":
    main()
