"""AFFORDABILITY DIAGNOSIS from RETAINED ARTIFACTS ONLY (no provider request, no historical read).

    python scripts/affordability_diagnosis.py <collection_dir> <out.json>

For every candidate the funnel's rule would construct at each scan instant, emit: contract identity, quote unit,
multiplier, quantity, ask, entry fees, certified maximum loss, the applicable limit, and the named rejection
reason. Then INDEPENDENTLY recompute affordability from those retained inputs, without calling the envelope, and
compare. The question is whether the zero-candidate result is an arithmetic defect, a universe/policy
incompatibility, missing data, or unresolved. Nothing is changed to force a trade."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")
from apex.decision_wb.engine import DTE_MIN_DAYS, FunnelEngine  # noqa: E402
from apex.options_pilot.book import CONTRACT_MULTIPLIER  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026 as FEES  # noqa: E402
from apex.options_pilot.risk_authority import envelope_for  # noqa: E402
from apex.organism import risk_certificate as RC  # noqa: E402
from apex.organism import risk_kernel as RK  # noqa: E402
from apex.pulse_options import sources as SRC  # noqa: E402

D, OUT = Path(sys.argv[1]), Path(sys.argv[2])
K_SIDE = FunnelEngine().k_side                       # the funnel's own default candidate width, unchanged

chains, nbbo = [], []
for line in open(D / "chain_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_chain":
        chains.append((r["receipt_epoch"], r["payload"]))
for line in open(D / "nbbo_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_nbbo":
        nbbo.append((r["payload"]["as_of"], r["payload"]))
chains.sort(); nbbo.sort()


def spot_at(t):
    prev = [p for ts, p in nbbo if ts <= t]
    return (0.5 * (prev[-1]["bid"] + prev[-1]["ask"])) if prev else None


rows, per_scan = [], []
for i in range(0, len(chains), 15):                  # the same 15-minute cadence the funnel run used
    t, payload = chains[i]
    spot = spot_at(t)
    norm = SRC.live_chain_rows([{**q, "expiration": q.get("expiration", payload["expiration"]), "symbol": "SPY"} for q in payload["quotes"]],
                               symbol="SPY", receipt_time=t)
    today = date.fromisoformat(datetime.fromtimestamp(t, tz=timezone.utc).isoformat()[:10])
    exps = sorted({r["expiration"] for r in norm if (date.fromisoformat(r["expiration"]) - today).days >= DTE_MIN_DAYS})
    if not exps or spot is None:
        per_scan.append({"t": t, "skip": "NO_EXPIRY_OR_SPOT"}); continue
    exp = exps[0]
    strikes = sorted({r["strike"] for r in norm if r["expiration"] == exp})
    atm = min(strikes, key=lambda k: (abs(k - spot), k))
    j = strikes.index(atm)
    band = strikes[max(0, j - K_SIDE): j + K_SIDE + 1]
    scan = {"t_utc": datetime.fromtimestamp(t, tz=timezone.utc).isoformat(), "spot": round(spot, 4), "expiration": exp,
            "atm_strike": atm, "candidate_band": band, "n_strikes_in_chain": len(strikes),
            "band_rule": "ATM +/- %d strikes (FunnelEngine default, unchanged)" % K_SIDE, "candidates": []}
    for k in band:
        for right in ("CALL", "PUT"):
            q = next((r for r in norm if r["expiration"] == exp and r["strike"] == k and r["right"] == right), None)
            if q is None:
                scan["candidates"].append({"strike": k, "right": right, "rejection": "NO_QUOTE_IN_SNAPSHOT"}); continue
            ask = q["ask"]
            env = envelope_for(reference_ask=ask, quantity=1)
            fe = FEES.entry(1)
            cert = RC.certify(expression=("LONG_CALL" if right == "CALL" else "LONG_PUT"), direction=("LONG" if right == "CALL" else "SHORT"),
                              declared_risk=float(env["envelope_debit"]),
                              sleeve_payload={"legs": [("BUY", right, float(k), float(env["max_entry_price"]))],
                                              "multiplier": CONTRACT_MULTIPLIER, "contracts": 1,
                                              "net_debit": float(env["envelope_debit"]), "expiration": exp})
            # INDEPENDENT recomputation, not the envelope's own answer
            indep_debit = round(ask * CONTRACT_MULTIPLIER * 1, 2)
            indep_max_loss = round(indep_debit + (fe.get("total") or 0.0), 2)
            limit = RK.MAX_RISK_PER_TRADE
            indep_affordable = indep_debit <= limit
            row = {"contract_id": "SPY|%s|%s|%s" % (exp, k, right), "expiration": exp, "strike": k, "right": right,
                   "quote_unit": "USD per share of the underlying (option premium quoted per share)",
                   "multiplier": CONTRACT_MULTIPLIER, "quantity": 1, "ask": ask, "bid": q["bid"],
                   "entry_fees": fe.get("total"), "entry_fee_components": fe.get("components"),
                   "debit_usd": indep_debit, "certified_max_loss": cert.get("certified_max_loss"),
                   "certificate_class": cert.get("risk_class"),
                   "applicable_limit_usd": limit, "limit_name": "risk_kernel.MAX_RISK_PER_TRADE",
                   "envelope_feasible": env["feasible"], "envelope_max_entry_price": env["max_entry_price"],
                   "envelope_reason": env.get("why_infeasible"),
                   "independent_affordable": indep_affordable,
                   "independent_reason": (None if indep_affordable else
                                          "debit %.2f = ask %.2f x multiplier %d x qty 1 EXCEEDS limit %.2f"
                                          % (indep_debit, ask, CONTRACT_MULTIPLIER, limit)),
                   "agrees_with_envelope": (indep_affordable == bool(env["feasible"] and ask <= env["max_entry_price"]))}
            scan["candidates"].append(row); rows.append(row)
    per_scan.append(scan)

aff = [r for r in rows if r.get("independent_affordable")]
disagree = [r for r in rows if r.get("agrees_with_envelope") is False]
cheapest = min((r for r in rows if "ask" in r), key=lambda r: r["ask"], default=None)
chain_min = None
for t, payload in chains[:1]:
    norm = SRC.live_chain_rows([{**q, "expiration": q.get("expiration", payload["expiration"]), "symbol": "SPY"} for q in payload["quotes"]],
                               symbol="SPY", receipt_time=t)
    ok = [r for r in norm if r["ask"] * CONTRACT_MULTIPLIER <= RK.MAX_RISK_PER_TRADE]
    chain_min = {"n_rows": len(norm), "n_affordable_in_whole_chain": len(ok),
                 "nearest_affordable_strikes": sorted({r["strike"] for r in ok})[:3] + sorted({r["strike"] for r in ok})[-3:]}
out = {"kind": "AFFORDABILITY_DIAGNOSIS", "source": "RETAINED ARTIFACTS ONLY (%s); no provider request, no historical read" % D,
       "limit": {"name": "risk_kernel.MAX_RISK_PER_TRADE", "value_usd": RK.MAX_RISK_PER_TRADE,
                 "implied_max_ask_per_share": RK.MAX_RISK_PER_TRADE / CONTRACT_MULTIPLIER},
       "multiplier": CONTRACT_MULTIPLIER, "candidate_band_rule": "ATM +/- %d strikes" % K_SIDE,
       "totals": {"scans": len([s for s in per_scan if "candidates" in s]), "candidates_examined": len(rows),
                  "independently_affordable": len(aff), "envelope_independent_disagreements": len(disagree),
                  "cheapest_candidate_ask": (cheapest or {}).get("ask"), "cheapest_candidate_debit": (cheapest or {}).get("debit_usd")},
       "whole_chain_at_first_scan": chain_min, "disagreements": disagree[:5], "per_scan": per_scan}
OUT.write_text(json.dumps(out, indent=1, default=str) + "\n")
print(json.dumps({k: out[k] for k in ("limit", "multiplier", "candidate_band_rule", "totals", "whole_chain_at_first_scan")}, indent=1, default=str))
