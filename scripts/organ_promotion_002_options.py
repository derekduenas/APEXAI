"""ORGAN PROMOTION #002 -- OPTIONS_MARKET_STATE as
ALPHA_SELECTOR / INFORMATION_CONFIRMATION.

Registered ORGAN-PROMOTION-002-OPTIONS-MARKET-STATE (sealed before
any result was viewed).

State (causal, 09:35 formation): skew_ratio = mid(5%-OTM put) /
mid(ATM put). Mids are used for STATE only; execution economics
stay bid/ask inside the sealed baseline P&L.

Rule: suppress to CASH when skew_ratio is BELOW the expanding
median of prior events in this population (min 30 priors) -- the
option market pricing LESS downside than typical contradicts the
bearish thesis. One representation, one selector, no thresholds.

decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
from datetime import datetime
from pathlib import Path

from apex.organism import microstructure as ms
from apex.organism import options_surface as osf

WAR = Path("results/edge_atlas/organism_war.jsonl")
OUT = Path("results/edge_atlas/organ002_options_shadow.jsonl")
MIN_PRIORS = 30


def utc_off(session: str) -> int:
    m = int(session[5:7])
    return 4 if 4 <= m <= 10 else 5


def spot_935(sym, session):
    off = utc_off(session)
    try:
        d = ms._get("https://data.alpaca.markets/v2/stocks/"
                    f"{sym}/bars?" + urllib.parse.urlencode(
                        {"start": f"{session}T{9 + off}:34:00Z",
                         "end": f"{session}T{9 + off}:36:00Z",
                         "timeframe": "1Min", "feed": "sip",
                         "limit": 3}))
        b = d.get("bars") or []
        return b[-1]["c"] if b else None
    except Exception:                                   # noqa: BLE001
        return None


def q_at_935(sym, exp, strike, session):
    try:
        rows = osf.td_history_quote(sym, exp, strike, "P", session,
                                    interval="5m")
    except Exception:                                   # noqa: BLE001
        return None
    cut = f"{session}T09:35:00.000"
    past = [r for r in rows if r["t"] <= cut
            and r["ask"] > r["bid"] > 0]
    return past[-1] if past else None


def main():
    war = [json.loads(l) for l in WAR.open() if l.strip()]
    war = [r for r in war if r.get("kind") == "war_event"]
    attacked = [r for r in war
                if r.get("arm4_choice") not in (None, "CASH")
                and isinstance(r.get("arm4"), (int, float))]
    attacked.sort(key=lambda r: r["session"])
    print(json.dumps({"stage1_population": len(attacked)}),
          flush=True)

    exps_cache: dict = {}
    priors: list = []
    rows_out = []
    for i, r in enumerate(attacked):
        sym, session = r["sym"], r["session"]
        row = {"kind": "organ002_shadow", "sym": sym,
               "session": session,
               "arm4_choice": r["arm4_choice"],
               "baseline_pnl_bps": r["arm4"]}
        spot = spot_935(sym, session)
        if sym not in exps_cache:
            try:
                exps_cache[sym] = osf.td_expirations(sym)
            except Exception:                           # noqa: BLE001
                exps_cache[sym] = []
        d0 = datetime.strptime(session, "%Y-%m-%d")
        exp = next((x for x in exps_cache[sym]
                    if 5 <= (datetime.strptime(x, "%Y-%m-%d")
                             - d0).days <= 21), None)
        atm = otm = None
        if spot and exp:
            atm = q_at_935(sym, exp, float(round(spot)), session)
            otm = q_at_935(sym, exp, float(round(spot * 0.95)),
                           session)
        if not (atm and otm):
            row["state"] = "NOT_ESTIMABLE"
            row["suppressed"] = None
            row["candidate_pnl_bps"] = r["arm4"]
        else:
            atm_mid = (atm["bid"] + atm["ask"]) / 2
            otm_mid = (otm["bid"] + otm["ask"]) / 2
            ratio = otm_mid / atm_mid if atm_mid > 0 else None
            if ratio is None:
                row["state"] = "NOT_ESTIMABLE"
                row["suppressed"] = None
                row["candidate_pnl_bps"] = r["arm4"]
            else:
                row["skew_ratio"] = round(ratio, 4)
                row["atm_mid"] = atm_mid
                row["otm_mid"] = otm_mid
                row["rel_spread_atm"] = round(
                    (atm["ask"] - atm["bid"]) / atm_mid, 4)
                if len(priors) < MIN_PRIORS:
                    row["state"] = "WARMUP"
                    row["suppressed"] = False
                    row["candidate_pnl_bps"] = r["arm4"]
                else:
                    med = statistics.median(priors)
                    supp = ratio < med
                    row["expanding_median"] = round(med, 4)
                    row["state"] = ("CONTRADICTS" if supp
                                    else "AGREES")
                    row["suppressed"] = supp
                    row["candidate_pnl_bps"] = (0.0 if supp
                                                else r["arm4"])
                priors.append(ratio)
        rows_out.append(row)
        if (i + 1) % 25 == 0:
            print(json.dumps({"progress": i + 1,
                              "at": session}), flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for row in rows_out:
            f.write(json.dumps(row) + "\n")
    print(json.dumps({"rows_written": len(rows_out)}), flush=True)


if __name__ == "__main__":
    main()
