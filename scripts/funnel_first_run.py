"""FULL_FUNNEL_V1's first execution, on recorded data with a REAL variance fit (mechanism test, quarantined replay).

    python scripts/funnel_first_run.py <collection_dir> <prior_bars.json> <out_dir>

Pre-registered in docs/FUNNEL_FIRST_RUN_PREREGISTRATION.md as excluded from expectancy. Nothing is tuned."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot import expression_rule as ER  # noqa: E402
from apex.options_pilot.clock import Clock, to_utc_string  # noqa: E402
from apex.options_pilot.fees import ROBINHOOD_RHF_2026  # noqa: E402
from apex.options_pilot.risk_authority import entry_cap_price  # noqa: E402
from apex.pulse_options import sources as SRC  # noqa: E402

D, PRIOR, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
prior = json.loads(PRIOR.read_text())
chains, nbbo, session_bars = [], [], {}
for line in open(D / "chain_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_chain":
        chains.append((r["receipt_epoch"], r["payload"]))
for line in open(D / "nbbo_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_nbbo":
        nbbo.append((r["payload"]["as_of"], r["payload"]))
for line in open(D / "bars_SPY.jsonl"):
    r = json.loads(line)
    if r.get("kind") == "pilot_collection_bars":
        for b in r["payload"]:
            p = session_bars.get(b["event_time"])
            if p is None or b["receipt_time"] < p["receipt_time"]:
                session_bars[b["event_time"]] = b
allbars = sorted(list(prior) + list(session_bars.values()), key=lambda b: b["event_time"])
nbbo.sort()
print("prior bars %d, session bars %d, total %d" % (len(prior), len(session_bars), len(allbars)), file=sys.stderr)

NOW = {"t": chains[0][0]}


class Rec:
    provider = "ALPACA_DATA_V2"

    def bars(self, symbol, *, start_epoch, end_epoch):
        return [{"symbol": symbol, "event_time": b["event_time"], "available_time": b.get("receipt_time", b["event_time"] + 60.0),
                 "receipt_time": b.get("receipt_time", b["event_time"] + 60.0), "open": b["open"], "high": b["high"], "low": b["low"],
                 "close": b["close"], "volume": b.get("volume", 0), "publication_time": b.get("publication_time"),
                 "vwap": b.get("vwap"), "trades": b.get("trades"), "provider": "ALPACA_DATA_V2"}
                for b in allbars if start_epoch <= b["event_time"] < end_epoch and b.get("receipt_time", b["event_time"] + 60.0) <= NOW["t"]]


def snap_at(t):
    prior_ = [(ts, p) for ts, p in chains if ts <= t]
    return prior_[-1] if prior_ else None


def chain_fn(symbol, as_of):
    s = snap_at(NOW["t"])
    if s is None:
        from apex.pulse_options.providers import ProviderUnavailable
        raise ProviderUnavailable("NO_CHAIN")
    ts, p = s
    return SRC.live_chain_rows([{**q, "expiration": q.get("expiration", p["expiration"]), "symbol": symbol} for q in p["quotes"]],
                               symbol=symbol, receipt_time=ts)


def quote_fn(contract):
    rows = chain_fn(contract["symbol"], NOW["t"])
    want = (contract["expiration"], float(contract["strike"]), contract["right"])
    for r in rows:
        if (r["expiration"], r["strike"], r["right"]) == want:
            return r
    from apex.pulse_options.providers import ProviderUnavailable
    raise ProviderUnavailable("QUOTE_NOT_IN_SNAPSHOT: %s" % (want,))


def nbbo_fn(symbol, t):
    prev = [p for ts, p in nbbo if ts <= NOW["t"]]
    if not prev:
        return None
    p = prev[-1]
    return {"bid": p["bid"], "ask": p["ask"], "bid_size": p["bid_size"], "ask_size": p["ask_size"], "t": p["as_of"], "source": p["source"]}


tw = SRC.TwinSources(provenance="LIVE_FEED", clock=Clock(lambda: NOW["t"]), bar_source=Rec(), chain_fn=chain_fn, quote_fn=quote_fn,
                     exit_quote_fn=quote_fn, fee_schedule=ROBINHOOD_RHF_2026, sleep_fn=lambda s: None, book_fn=nbbo_fn,
                     selection_policy="FULL_FUNNEL_V1")
# the session supplies these two on every real scan; the driver must supply the SAME objects, not substitutes
from apex.options_pilot.book import Book  # noqa: E402
from apex.options_pilot.records import contract_id as _cid  # noqa: E402
from apex.options_pilot.risk_authority import CERTIFIED_PROVENANCE, CertifiedRiskAuthority, envelope_for  # noqa: E402
BOOK = Book([], session_id="FUNNEL-FIRST-RUN", fee_schedules={ROBINHOOD_RHF_2026.schedule_id: ROBINHOOD_RHF_2026})
RISK = CertifiedRiskAuthority(fee_schedule=ROBINHOOD_RHF_2026, provenance="LIVE_FEED")


def _certified_risk(proposal: dict) -> dict:
    env = envelope_for(reference_ask=proposal.get("reference_ask"), quantity=1)
    c = proposal.get("contract") or {}
    body = {"expression": proposal.get("expression"), "contract": c, "quantity": proposal.get("quantity", 1),
            "risk_envelope": env, "action": "BUY", "session_id": "FUNNEL-FIRST-RUN", "scan_id": "FUNNEL",
            "contract_id": _cid(c) if c else None, "intent_id": "PRESELECTION",
            "fees": ROBINHOOD_RHF_2026.identity(),
            "signal_used": ("LONG" if proposal.get("expression") == "LONG_CALL" else "SHORT")}
    try:
        ap = RISK.approve(body, book=BOOK)
    except Exception as e:                                               # noqa: BLE001
        return {"approved": False, "risk_provenance": CERTIFIED_PROVENANCE, "why": "%s: %s" % (type(e).__name__, str(e)[:140])}
    return {**ap, "envelope": env, "book_state_hash": BOOK.state_hash()}


out = {"kind": "FUNNEL_FIRST_RUN", "preregistration": "docs/FUNNEL_FIRST_RUN_PREREGISTRATION.md",
       "excluded_from": ["expectancy", "calibration", "alpha"], "quarantined": "REPLAY", "scans": []}
c = Counter()
for i in range(0, len(chains), 15):                      # every ~15 minutes, the pilot's cadence
    NOW["t"] = chains[i][0]
    row = {"i": i, "t_utc": to_utc_string(NOW["t"])}
    try:
        fc = tw.forecast_fn("SPY", NOW["t"])
    except Exception as e:                                                # noqa: BLE001
        row["stage"] = "FORECAST_REFUSED"; row["why"] = "%s: %s" % (type(e).__name__, str(e)[:110]); c["forecast_refused"] += 1
        out["scans"].append(row); continue
    try:
        res = tw.funnel_fn("SPY", NOW["t"], fc, book_summary=BOOK.summary(), certified_risk_fn=_certified_risk, scan_id="FUNNEL-%d" % i)
    except Exception as e:                                                # noqa: BLE001
        row["stage"] = "FUNNEL_ERROR"; row["why"] = "%s: %s" % (type(e).__name__, str(e)[:160]); c["funnel_error"] += 1
        out["scans"].append(row); continue
    tr = res.get("trace") or {}
    fit = (tw.funnel_engine.fit_info or {})
    cands = tr.get("candidates") or {}
    table = cands.get("table") or []
    prime = tr.get("prime") or (tr.get("decision_rule") or {}).get("rules", {}).get("5") or {}
    row.update(decision=res.get("decision"), why=(res.get("why") or "")[:140], fit_status=fit.get("status"),
               n_candidates=len(table), n_eligible=sum(1 for t in table if t.get("status") == "ELIGIBLE"),
               prime=(prime.get("decision") if isinstance(prime, dict) else None),
               selected=(res.get("proposal") or {}).get("contract"))
    c["funnel_" + str(res.get("decision"))] += 1
    c["fit_" + str(fit.get("status"))[:28]] += 1
    if row["prime"]:
        c["prime_" + row["prime"]] += 1
    if row["n_eligible"]:
        c["scans_with_eligible_candidates"] += 1
    # what the RULE path would pick at the same instant
    try:
        sp = nbbo_fn("SPY", NOW["t"])
        spot = 0.5 * (sp["bid"] + sp["ask"]) if sp else None
        rule = ER.choose(symbol="SPY", direction_signal=tw.signal_fn("SPY", NOW["t"]), spot=spot, as_of=to_utc_string(NOW["t"]),
                         available=chain_fn("SPY", NOW["t"]), max_entry_price=entry_cap_price(), as_of_epoch=NOW["t"])
        row["rule_path_would_pick"] = rule["contract"]
        row["selections_differ"] = (row["selected"] != rule["contract"]) if row["selected"] else None
        if row["selections_differ"]:
            c["selections_differ"] += 1
        elif row["selections_differ"] is False:
            c["selections_agree"] += 1
    except Exception as e:                                                # noqa: BLE001
        row["rule_path_would_pick"] = "REFUSED: %s" % str(e)[:80]
    out["scans"].append(row)
out["totals"] = dict(c)
out["fit_info"] = {k: v for k, v in (tw.funnel_engine.fit_info or {}).items() if k in ("status", "why", "n_rows", "model", "params")}
(OUT / "funnel_first_run.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
print(json.dumps({"totals": out["totals"], "fit": out["fit_info"]}, indent=1, default=str))
