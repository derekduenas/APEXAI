"""STAGE 0a — stage census at DEFAULT settings over the collected SPY session (read-only, nothing tuned).

    python scripts/stage0_census.py <collection_dir> > docs/evidence/stage0_census_2026-09-11.json

Counts, per snapshot and in total, how many candidates reach each stage on BOTH decision paths, at the defaults the
Monday package would run with:
    RULE path   (PILOT_RULE_V2, the Monday policy):  chain rows -> valid rows -> on-side strikes -> cap-feasible -> chosen
                                                     -> intent accepted by the boundary's rule step -> certified approval at
                                                     the LIVE default fee schedule (UNVERIFIED)
    FUNNEL path (FULL_FUNNEL_V1, default FunnelEngine, k_side=4): forecast -> fit -> candidates -> envelope -> eligible -> PRIME -> proposal
    JOINT path  (JOINT_FUNNEL_V1): no authorized fit -> 0 by construction, recorded as such
No setting is changed to produce a count. A zero is reported with its named reason."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot import expression_rule as ER  # noqa: E402
from apex.options_pilot.risk_authority import CertifiedRiskAuthority, entry_cap_price, envelope_for  # noqa: E402
from apex.options_pilot.fees import UNVERIFIED_FEES  # noqa: E402
from apex.options_pilot.clock import Clock, to_utc_string  # noqa: E402
from apex.pulse_options import sources as SRC  # noqa: E402
from apex.pulse_options.providers import SyntheticBarProvider  # noqa: E402

D = Path(sys.argv[1])


def rows(path):
    for line in open(path):
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                pass


chains = [r for r in rows(D / "chain_SPY.jsonl") if r.get("kind") == "pilot_collection_chain"]
nbbo = sorted((r["payload"]["as_of"], r["payload"]) for r in rows(D / "nbbo_SPY.jsonl") if r.get("kind") == "pilot_collection_nbbo")
bars = []
for r in rows(D / "bars_SPY.jsonl"):
    if r.get("kind") == "pilot_collection_bars":
        bars.extend(r["payload"])
bars = sorted({b["event_time"]: b for b in bars}.values(), key=lambda b: b["event_time"])


def spot_at(t):
    prev = [p for (ts, p) in nbbo if ts <= t]
    if not prev:
        return None
    p = prev[-1]
    return 0.5 * (p["bid"] + p["ask"]), t - p["as_of"]


class _Bars:
    provider = "ALPACA_DATA_V2"

    def bars(self, symbol, *, start_epoch, end_epoch):
        return [{"symbol": "SPY", "event_time": b["event_time"], "available_time": b.get("available", b["event_time"] + 60.0), "receipt_time": b.get("receipt", b["event_time"] + 60.0),
                 "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": b.get("volume", 0), "provider": "ALPACA_DATA_V2"}
                for b in bars if start_epoch <= b["event_time"] < end_epoch]


out = {"kind": "STAGE0_CENSUS", "session": "2026-09-11", "settings": "DEFAULT (PILOT_RULE_V2 cap %.2f; FunnelEngine defaults k_side=4; UNVERIFIED fee schedule; no tuning)" % entry_cap_price(),
       "n_chain_snapshots": len(chains), "n_bars": len(bars), "n_nbbo": len(nbbo), "rule_path": {"per_snapshot": []}, "funnel_path": {"per_snapshot": []},
       "joint_path": {"count": 0, "reason": "NO_AUTHORIZED_FIT: JOINT_FUNNEL_V1 requires an R4 fit (R4-FIT-001/002 not granted); 0 by construction, not by tuning"}}
tot = Counter()
risk = CertifiedRiskAuthority(fee_schedule=UNVERIFIED_FEES, provenance="LIVE_FEED")
for rec in chains:
    t = rec["receipt_epoch"]
    quotes = rec["payload"]["quotes"]
    exp = rec["payload"]["expiration"]
    norm = SRC.live_chain_rows([{**q, "expiration": q.get("expiration", exp), "symbol": "SPY"} for q in quotes], symbol="SPY", receipt_time=t)
    sp = spot_at(t)
    row = {"t_utc": to_utc_string(t), "chain_rows": len(quotes), "valid_rows": len(norm), "excluded": len(norm.exclusions),
           "exclusion_reasons": dict(Counter(x["why"].split(":")[0] for x in norm.exclusions)), "conflicted": len(norm.conflicted), "spot": (round(sp[0], 2) if sp else None)}
    tot["chain_rows"] += len(quotes); tot["valid_rows"] += len(norm)
    if sp is None:
        row["outcome"] = "NO_SPOT"; out["rule_path"]["per_snapshot"].append(row); continue
    for sig in ("LONG", "SHORT"):
        try:
            v = ER.choose(symbol="SPY", direction_signal=sig, spot=sp[0], as_of=to_utc_string(t), available=norm, max_entry_price=entry_cap_price(), as_of_epoch=t)
            c = v["strike_selection"]["census"]
            row[sig] = {"on_side": c["on_signal_side"], "feasible": c["feasible"], "chosen": v["contract"]["strike"], "ask": v["reference_ask"], "strikes_from_atm": v["strike_selection"]["strikes_from_atm"]}
            tot["rule_feasible_%s" % sig] += c["feasible"]; tot["rule_chosen_%s" % sig] += 1
            env = envelope_for(reference_ask=v["reference_ask"], quantity=1)
            body = {**v, "contract_id": "SPY|%s|%s|%s" % (v["contract"]["expiration"], v["contract"]["strike"], v["contract"]["right"]), "risk_envelope": env,
                    "session_id": "CENSUS", "scan_id": "CENSUS", "intent_id": "CENSUS", "signal_used": sig}
            try:
                from apex.options_pilot.book import load_book
                ap = risk.approve(body, book=load_book(D / "_no_ledger.jsonl", session_id="CENSUS", fee_schedules={UNVERIFIED_FEES.schedule_id: UNVERIFIED_FEES}))
                row[sig]["certified_at_live_default"] = ap.get("approved"); row[sig]["certified_why"] = (ap.get("why") or "")[:80]
                tot["certified_approved_%s" % sig] += 1 if ap.get("approved") else 0
            except Exception as e:                                       # noqa: BLE001
                row[sig]["certified_at_live_default"] = False; row[sig]["certified_why"] = "%s: %s" % (type(e).__name__, str(e)[:80])
        except ER.RuleRefused as e:
            row[sig] = {"refused": str(e)[:100]}; tot["rule_refused_%s" % sig] += 1
    out["rule_path"]["per_snapshot"].append(row)

# FUNNEL path at defaults: the real TwinSources with the real FunnelEngine, real bars, real chain rows
tw = SRC.TwinSources(provenance="LIVE_FEED", clock=Clock(lambda: 0.0), bar_source=_Bars(), chain_fn=lambda s, t: None, quote_fn=lambda c: None,
                     exit_quote_fn=lambda c: None, fee_schedule=UNVERIFIED_FEES, selection_policy="FULL_FUNNEL_V1", sleep_fn=lambda s: None)
fc = Counter()
for rec in chains[::5]:                                                  # every 5th snapshot (~5 min cadence; the pilot scans every 15)
    t = rec["receipt_epoch"]
    tw.clock = Clock(lambda t=t: t)
    norm = SRC.live_chain_rows([{**q, "expiration": q.get("expiration", rec["payload"]["expiration"]), "symbol": "SPY"} for q in rec["payload"]["quotes"]], symbol="SPY", receipt_time=t)
    tw._chain_fn = lambda s, tt, norm=norm: norm
    tw._quote_fn = lambda c: None
    row = {"t_utc": to_utc_string(t)}
    try:
        forecast = tw.forecast_fn("SPY", t)
        row["forecast"] = "OK"; fc["forecast_ok"] += 1
    except Exception as e:                                               # noqa: BLE001
        row["forecast"] = "%s: %s" % (type(e).__name__, str(e)[:90]); fc["forecast_refused"] += 1
        out["funnel_path"]["per_snapshot"].append(row); continue
    try:
        res = tw.funnel_fn("SPY", t, forecast)
        tr = res.get("trace", {})
        cands = tr.get("candidates") or {}
        row.update(decision=res.get("decision"), why=(res.get("why") or "")[:100], n_candidates=cands.get("n") or len(cands.get("table", [])) if isinstance(cands, dict) else None,
                   fit=(tw.funnel_engine.fit_info or {}).get("status"))
        fc["funnel_%s" % res.get("decision")] += 1
        fc["why:" + str(res.get("why") or "")[:60]] += 1
        stages = tr.get("stages") or {}
        prime = tr.get("prime") or (tr.get("final") or {}).get("prime") or {}
        if isinstance(prime, dict) and prime.get("decision") in ("ACT", "ABSTAIN"):
            fc["reached_prime"] += 1
        if cands and (cands.get("table") or cands.get("n")):
            fc["snapshots_with_candidates"] += 1
    except Exception as e:                                               # noqa: BLE001
        row.update(decision="ERROR", why="%s: %s" % (type(e).__name__, str(e)[:120])); fc["funnel_error"] += 1
    out["funnel_path"]["per_snapshot"].append(row)
out["funnel_path"]["totals"] = dict(fc)
out["funnel_path"]["fit_info"] = {k: v for k, v in (tw.funnel_engine.fit_info or {}).items() if k in ("status", "why", "n_rows", "history_days")} if tw.funnel_engine.fit_info else None
out["rule_path"]["totals"] = dict(tot)
out["summary"] = {
    "rule_path": {"snapshots": len(chains), "chosen_LONG": tot["rule_chosen_LONG"], "chosen_SHORT": tot["rule_chosen_SHORT"],
                  "certified_at_live_default_LONG": tot["certified_approved_LONG"], "certified_at_live_default_SHORT": tot["certified_approved_SHORT"],
                  "note": "PRIME is not a stage of the rule path (PILOT_RULE_V2 does not consult the Multiverse/PRIME by design)"},
    "funnel_path": dict(fc), "joint_path": 0}
print(json.dumps(out, indent=1, default=str))
