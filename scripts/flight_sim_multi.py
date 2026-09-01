"""FLIGHT SIMULATOR — sessions A/B/C/E (same frozen organism as
run 1; see scripts/flight_sim.py for the laws).

EVIDENCE CLASS: DIAGNOSTIC_REPLAY_ONLY. Sessions chosen for
behavioral diversity using known outcomes (legal for diagnostics):

  A quiet    SPY  2026-07-29  COMPRESSED vol, no event -> silence
  B trend    HIMS 2025-11-04  neg surprise, short thesis WON
  C crisis   SPY  2025-04-10  CRISIS regime, no event -> stress eye
  E chop     SBUX 2025-07-30  neg surprise, +494 -> -224 whipsaw

Option expiry selection uses the FROZEN A1 rule (first expiry >= 5
DTE, <= 21 DTE). decision_power: DIAGNOSTIC_REPLAY_ONLY.
"""
from __future__ import annotations

import json
import time as wallclock
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apex.monster import consult as monster_consult
from apex.monster.event_expert import EventRecord
from apex.organism import microstructure as ms
from apex.organism import options_surface as osf
from apex.organism import market_state

SESSIONS = [
    {"tag": "A_QUIET", "sym": "SPY", "session": "2026-07-29",
     "utc_off": 4, "event": None, "rt": 2.0},
    {"tag": "B_TREND", "sym": "HIMS", "session": "2025-11-04",
     "utc_off": 5, "rt": 9.34,
     "event": {"symbol": "HIMS", "report_date": "2025-11-03",
               "timing": "pm", "eps_estimate": 0.10,
               "eps_actual": 0.09,
               "consensus_provenance":
                   "BROKER_REPORTED_CONSENSUS_RH_MCP"}},
    {"tag": "C_CRISIS", "sym": "SPY", "session": "2025-04-10",
     "utc_off": 4, "event": None, "rt": 2.0},
    {"tag": "E_CHOP", "sym": "SBUX", "session": "2025-07-30",
     "utc_off": 4, "rt": 6.51,
     "event": {"symbol": "SBUX", "report_date": "2025-07-29",
               "timing": "pm", "eps_estimate": 0.65,
               "eps_actual": 0.50,
               "consensus_provenance":
                   "BROKER_REPORTED_CONSENSUS_RH_MCP"}},
]


def run_session(spec) -> dict:
    sym, day, off = spec["sym"], spec["session"], spec["utc_off"]
    t0w = wallclock.time()
    frames = []
    matrix: dict = {}

    def organ(name, material=False, unavailable=False):
        m = matrix.setdefault(name, {"invoked": 0, "material": 0,
                                     "unavailable": 0})
        m["invoked"] += 1
        m["material"] += int(material)
        m["unavailable"] += int(unavailable)

    d = ms._get("https://data.alpaca.markets/v2/stocks/"
                f"{sym}/bars?" + urllib.parse.urlencode(
                    {"start": f"{day}T{9 + off}:30:00Z",
                     "end": f"{day}T{16 + off}:00:00Z",
                     "timeframe": "1Min", "feed": "sip",
                     "limit": 10000}))
    px = {b["t"]: b["c"] for b in d.get("bars") or []}
    keys = sorted(px)
    if not keys:
        return {"tag": spec["tag"], "error": "NO_BARS"}
    open_px = px[keys[0]]

    # frozen A1 expiry rule: first expiry in [5, 21] DTE
    exps = osf.td_expirations(sym)
    d0 = datetime.strptime(day, "%Y-%m-%d")
    exp = next((e for e in exps
                if 5 <= (datetime.strptime(e, "%Y-%m-%d")
                         - d0).days <= 21), None)
    strike = float(round(open_px))
    otm_strike = float(round(open_px * 0.95))
    opt_p, opt_otm = [], []
    if exp:
        try:
            opt_p = osf.td_history_quote(sym, exp, strike, "P",
                                         day, interval="5m")
            opt_otm = osf.td_history_quote(sym, exp, otm_strike,
                                           "P", day, interval="5m")
        except Exception:                               # noqa: BLE001
            organ("options_surface", unavailable=True)

    def opt_asof(rows, hhmm):
        cut = f"{day}T{hhmm}:00.000"
        past = [r for r in rows if r["t"] <= cut]
        return past[-1] if past else None

    prior = (d0 - timedelta(days=1)).strftime("%Y-%m-%d")
    reg = market_state._regime(prior,
                               Path("exports/regime_atlas_v1"
                                    ".jsonl"))
    organ("regime_atlas", material=True)

    # ---- formation
    consult = None
    entry_px = None
    if spec["event"]:
        ev = EventRecord(**{**spec["event"],
                            "known_from": f"{day}T09:30:00",
                            "reaction_session": day})
        p935, po935 = opt_asof(opt_p, "09:35"), \
            opt_asof(opt_otm, "09:35")
        pq = None
        if p935 and po935:
            pq = {"long_put": {"strike": strike, "bid": p935["bid"],
                               "ask": p935["ask"], "expiry": exp},
                  "put_vertical": {"long": {"strike": strike,
                                            "ask": p935["ask"]},
                                   "short": {"strike": otm_strike,
                                             "bid": po935["bid"]},
                                   "expiry": exp}}
        organ("expert_A1_pm_fade", material=True)
        organ("expert_A2_neg_surprise", material=True)
        organ("capital_arena", material=True)
        consult = monster_consult.consult(
            ev, rt_cost_bps=spec["rt"], short_allowed=False,
            put_quotes=pq)
        entry_key = keys[min(5, len(keys) - 1)]
        entry_px = px[entry_key]
        frames.append({"kind": "decision_frame",
                       "sim_time": "09:35 ET",
                       "regime": reg.get("value", reg),
                       "thesis": consult["physical_thesis"],
                       "best_expression":
                           consult.get("best_expression"),
                       "final": consult["final"],
                       "why": consult["final_reason"],
                       "put_quotes_at_formation": pq})
    else:
        organ("expert_A1_pm_fade", material=False)
        organ("expert_A2_neg_surprise", material=False)
        frames.append({"kind": "decision_frame",
                       "sim_time": "09:35 ET",
                       "regime": reg.get("value", reg),
                       "experts": "SILENT -- no causally valid "
                                  "event this session",
                       "final": "NO_TRADE",
                       "why": "no expert produced an opportunity; "
                              "cash holds"})

    # ---- flight frames
    mfe = mae = 0.0
    last_mid = entry_px or open_px
    flow_flips = 0
    last_flow_sign = 0
    material_frames = 0
    n_trades = n_quotes = 0
    for h in range(9, 16):
        for m in range(0, 60, 5):
            if (h, m) <= (9, 35) or (h, m) > (15, 55):
                continue
            hhmm = f"{h:02d}:{m:02d}"
            t1 = datetime(d0.year, d0.month, d0.day, h + off, m,
                          tzinfo=timezone.utc)
            key = t1.strftime("%Y-%m-%dT%H:%M:00Z")
            if key not in px:
                continue
            mid = px[key]
            moved = abs(mid / last_mid - 1) * 1e4 > 30
            grid15 = m % 15 == 0
            if not (moved or grid15):
                continue
            micro = {"status": "NOT_PULLED"}
            if moved:
                material_frames += 1
                try:
                    tr = ms.fetch_ticks(
                        sym, (t1 - timedelta(minutes=5))
                        .isoformat(), t1.isoformat(),
                        what="trades", max_pages=2)
                    qt = ms.fetch_ticks(
                        sym, (t1 - timedelta(minutes=5))
                        .isoformat(), t1.isoformat(),
                        what="quotes", max_pages=2)
                    n_trades += len(tr)
                    n_quotes += len(qt)
                    micro = ms.micro_state(tr, qt,
                                           window_label=hhmm)
                    organ("microstructure", material=True)
                    s = micro.get("net_signed_volume")
                    if isinstance(s, int) and s != 0:
                        sign = 1 if s > 0 else -1
                        if last_flow_sign and \
                                sign != last_flow_sign:
                            flow_flips += 1
                        last_flow_sign = sign
                except Exception:                       # noqa: BLE001
                    organ("microstructure", unavailable=True)
            pnow = opt_asof(opt_p, hhmm) if opt_p else None
            organ("options_surface", material=bool(pnow),
                  unavailable=not opt_p)
            rec = {"kind": "flight_frame", "sim_time": f"{hhmm} ET",
                   "trigger": "MATERIAL_MOVE" if moved else "GRID",
                   "mid": mid,
                   "micro": {k: micro.get(k) for k in
                             ("status", "net_signed_volume",
                              "spread_bps_median")},
                   "atm_put": pnow and {"bid": pnow["bid"],
                                        "ask": pnow["ask"]}}
            if entry_px:
                pnl = (entry_px / mid - 1) * 1e4
                mfe, mae = max(mfe, pnl), min(mae, pnl)
                rec["position"] = {"pnl_bps": round(pnl, 1),
                                   "mfe": round(mfe, 1),
                                   "mae": round(mae, 1)}
                rec["management"] = "HOLD_PER_SEALED_RULES"
                organ("captain_reunderwrite", material=moved)
            frames.append(rec)
            last_mid = mid

    # ---- resolution
    close_px = px[keys[-1]]
    out = {"tag": spec["tag"], "sym": sym, "session": day,
           "regime": reg.get("value", reg),
           "final_decision": (consult or {}).get("final",
                                                 "NO_TRADE"),
           "frames": len(frames),
           "material_frames": material_frames,
           "flow_sign_flips_on_material": flow_flips,
           "wall_s": round(wallclock.time() - t0w, 1),
           "n_trades": n_trades, "n_quotes": n_quotes}
    if entry_px:
        short_net = (entry_px / close_px - 1) * 1e4 - spec["rt"]
        p935, p1555 = opt_asof(opt_p, "09:35"), \
            opt_asof(opt_p, "15:55")
        put_pnl = "NOT_ESTIMABLE"
        if p935 and p1555 and p935["ask"] > 0:
            put_pnl = round((p1555["bid"] - p935["ask"])
                            / p935["ask"] * 100, 1)
        out.update({
            "shadow_short_net_bps": round(short_net, 1),
            "mfe_bps": round(mfe, 1), "mae_bps": round(mae, 1),
            "long_put_pct": put_pnl,
            "monster_realized": 0.0,
            "monster_minus_dumb_bps": round(0.0 - short_net, 1),
            "expiry_used": exp,
            "thesis": (consult or {}).get("physical_thesis")})
    out["organ_matrix"] = matrix
    rec_path = Path(f"results/organism/flight_recorder_"
                    f"{spec['tag']}_{sym}_{day.replace('-', '')}"
                    f".jsonl")
    with rec_path.open("w") as f:
        for fr in frames:
            f.write(json.dumps(fr, default=str) + "\n")
    out["recorder"] = str(rec_path)
    return out


def main():
    for spec in SESSIONS:
        try:
            out = run_session(spec)
        except Exception as e:                          # noqa: BLE001
            out = {"tag": spec["tag"],
                   "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(out, default=str), flush=True)


if __name__ == "__main__":
    main()
