"""EARNINGS_NEGATIVE_SURPRISE_DRIFT_V1 -- prospective shadow.

THE HISTORICAL RESULT NOMINATES. THE FUTURE DECIDES.

Two modes:

  seal <snapshot.json>
      Seal a forward-calendar snapshot (captured in-session from the
      broker MCP, actual=null rows only) into the prospective ledger
      with known_from = capture time. This is TRUE point-in-time
      consensus: the estimate is recorded before the outcome exists.
      Duplicate (symbol, report_date, fy, fq) rows are skipped, so
      repeated session captures never rewrite a sealed estimate.

  resolve
      For sealed watch rows whose reaction session has completed:
      fetch 1m bars from Alpaca, compute the FULL denominator
      outcome (entry at first bar >= 09:35 ET short vs SPY, exit at
      close) for EVERY watched event regardless of eventual surprise
      class, and append a resolution row. surprise_class stays
      PENDING_ACTUAL until a session supplies the actual EPS
      (finalize mode); a watch row whose bars cannot be found within
      5 sessions is sealed MISSED_EVIDENCE. No backfill: a snapshot
      never captured is permanently missing evidence.

  finalize <actuals.json>
      Attach in-session-captured actual EPS to resolved rows and
      classify POSITIVE / NEGATIVE / SMALL_NEUTRAL, sealing the
      event-expert prospective observation (including refusals).

decision_power: SHADOW_PROSPECTIVE_ONLY. No orders. No capital.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apex.governance.chain_ledger import chain_append  # noqa: E402

LEDGER = Path("results/event_sprint/prospective_ledger.jsonl")
API = "https://data.alpaca.markets/v2/stocks/{sym}/bars"
NY = ZoneInfo("America/New_York")


def _get(url):
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]})
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if a == 3:
                return None
            import time
            time.sleep(1.5 ** a)


def _rows():
    if not LEDGER.exists():
        return []
    out = []
    for l in LEDGER.read_text().splitlines():
        try:
            out.append(json.loads(l))
        except Exception:
            continue
    return out


def _key(r):
    return (r.get("symbol"), r.get("report_date"),
            r.get("fiscal_year"), r.get("fiscal_quarter"))


def seal(snapshot_path):
    snap = json.loads(Path(snapshot_path).read_text())
    captured = snap["captured_utc"]
    existing = {_key(r) for r in _rows() if r.get("kind") == "watch"}
    n_new = n_dup = 0
    for e in snap["events"]:
        if e.get("eps_actual") is not None:
            continue                      # already-reported: not PIT
        k = (e["symbol"], e["report_date"], e.get("fiscal_year"),
             e.get("fiscal_quarter"))
        if k in existing:
            n_dup += 1
            continue
        chain_append(LEDGER, {
            "kind": "watch", "alpha_id":
                "EARNINGS_NEGATIVE_SURPRISE_DRIFT_V1",
            "symbol": e["symbol"], "report_date": e["report_date"],
            "fiscal_year": e.get("fiscal_year"),
            "fiscal_quarter": e.get("fiscal_quarter"),
            "timing": e.get("timing") or "unknown",
            "verified": e.get("verified"),
            "eps_estimate_sealed": e.get("eps_estimate"),
            "consensus_provenance":
                "PIT_SEALED_BEFORE_OUTCOME_RH_MCP",
            "known_from": captured,
            "decision_power": "SHADOW_PROSPECTIVE_ONLY"})
        n_new += 1
    print(json.dumps({"sealed_new": n_new, "duplicates": n_dup}))


# predeclared formation checkpoints (edge-decay law: measure all,
# never select the best afterward)
CHECKPOINTS = {"open": 570, "+1m": 571, "+5m": 575, "+15m": 585}


def _session_outcome(sym, date):
    """{checkpoint: px} + close from Alpaca 1m SIP bars, or None."""
    q = {"start": f"{date}T13:00:00Z", "end": f"{date}T21:10:00Z",
         "timeframe": "1Min", "limit": 1000, "adjustment": "raw",
         "feed": "sip"}
    d = _get(API.format(sym=sym) + "?" + urllib.parse.urlencode(q))
    if not d or not d.get("bars"):
        return None
    entries, close, first_open = {}, None, None
    for b in d["bars"]:
        t = datetime.fromisoformat(
            b["t"].replace("Z", "+00:00")).astimezone(NY)
        m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            if first_open is None:
                first_open = b["o"]
            for k, cm in CHECKPOINTS.items():
                if k not in entries and m >= cm:
                    entries[k] = b["c"]
            close = b["c"]
    if first_open is not None:
        entries["open"] = first_open        # open print, unexecutable
    if not entries.get("+5m") or not close:
        return None
    return {"entries": entries, "close": close}


def resolve():
    rows = _rows()
    watch = {_key(r): r for r in rows if r.get("kind") == "watch"}
    done = {_key(r) for r in rows
            if r.get("kind") in ("price_resolution",
                                 "missed_evidence")}
    today = datetime.now(NY).date()
    n_res = n_miss = 0
    for k, w in watch.items():
        if k in done:
            continue
        rdate = datetime.strptime(w["report_date"], "%Y-%m-%d").date()
        # reaction session: report day (am) or next day (pm/unknown)
        react = rdate if w["timing"] == "am" else rdate \
            + timedelta(days=1)
        if react >= today:
            continue                       # not yet resolvable
        found = None
        probe = react
        for _ in range(5):
            if probe.weekday() < 5:
                o = _session_outcome(w["symbol"],
                                     probe.strftime("%Y-%m-%d"))
                s = _session_outcome("SPY",
                                     probe.strftime("%Y-%m-%d"))
                if o and s:
                    found = (probe.strftime("%Y-%m-%d"), o, s)
                    break
            probe += timedelta(days=1)
        if found is None:
            if (today - react).days > 7:
                chain_append(LEDGER, {
                    "kind": "missed_evidence", **{x: w[x] for x in
                        ("alpha_id", "symbol", "report_date",
                         "fiscal_year", "fiscal_quarter")},
                    "why": "no bars within 5 sessions",
                    "law": "missing evidence is recorded, never "
                           "backfilled"})
                n_miss += 1
            continue
        sess, o, s = found
        pnls = {}
        for k in CHECKPOINTS:
            e, se = o["entries"].get(k), s["entries"].get(k)
            if e and se:
                pnls[k] = round(-((o["close"] / e - 1.0)
                                  - (s["close"] / se - 1.0)) * 1e4, 1)
        chain_append(LEDGER, {
            "kind": "price_resolution",
            **{x: w[x] for x in ("alpha_id", "symbol", "report_date",
                                 "fiscal_year", "fiscal_quarter",
                                 "timing", "eps_estimate_sealed",
                                 "known_from")},
            "reaction_session": sess,
            "entries_px": o["entries"], "close_px": o["close"],
            "short_pnl_res_bps_by_checkpoint": pnls,
            "short_pnl_res_bps": pnls.get("+5m"),
            "surprise_class": "PENDING_ACTUAL",
            "resolved_utc": datetime.now(timezone.utc).isoformat()})
        n_res += 1
    print(json.dumps({"resolved": n_res, "missed": n_miss}))


def finalize(actuals_path):
    acts = {}
    for e in json.loads(Path(actuals_path).read_text())["events"]:
        if e.get("eps_actual") is not None:
            acts[(e["symbol"], e["report_date"], e.get("fiscal_year"),
                  e.get("fiscal_quarter"))] = float(e["eps_actual"])
    rows = _rows()
    final_done = {_key(r) for r in rows
                  if r.get("kind") == "prospective_observation"}
    n = 0
    for r in rows:
        if r.get("kind") != "price_resolution":
            continue
        k = _key(r)
        if k in final_done or k not in acts:
            continue
        actual = acts[k]
        est = r.get("eps_estimate_sealed")
        est = float(est) if est is not None else None
        if est is None:
            cls = "UNKNOWN_NO_ESTIMATE"
        else:
            d = actual - est
            cls = ("NEGATIVE" if d < 0 else
                   "POSITIVE" if d > 0 else "SMALL_NEUTRAL")
        is_pm = r["timing"] == "pm"
        # TOURNAMENT: both experts' shadow positions, sealed
        # separately. A1 needs only the PM event; A2 claims only the
        # increment on negative surprises and never inherits A1
        # credit.
        a1 = "SHORT_SHADOW" if is_pm else "REFUSED_NOT_PM"
        a2 = ("SHORT_SHADOW_INCREMENT_CLAIM"
              if (is_pm and cls == "NEGATIVE") else
              "REFUSED_" + ("NOT_NEGATIVE" if cls != "NEGATIVE"
                            else "TIMING_AM"))
        chain_append(LEDGER, {
            "kind": "prospective_observation",
            **{x: r.get(x) for x in
               ("symbol", "report_date", "fiscal_year",
                "fiscal_quarter", "timing", "known_from",
                "reaction_session", "short_pnl_res_bps",
                "short_pnl_res_bps_by_checkpoint")},
            "eps_estimate_sealed": est, "eps_actual": actual,
            "surprise_class": cls,
            "A1_EARNINGS_SESSION_PM_FADE_V1": a1,
            "A2_EARNINGS_NEGATIVE_SURPRISE_DRIFT_V1": a2,
            "counts_toward": "FULL_DENOMINATOR_AND_INCREMENT",
            "finalized_utc": datetime.now(timezone.utc).isoformat()})
        n += 1
    print(json.dumps({"finalized": n}))


def report():
    """Tournament scoreboard from finalized prospective observations.
    The increment is A2's cohort minus the non-negative PM cohort --
    computed, never assumed."""
    import statistics
    obs = [r for r in _rows()
           if r.get("kind") == "prospective_observation"]
    pend = [r for r in _rows()
            if r.get("kind") == "price_resolution"]
    watch = [r for r in _rows() if r.get("kind") == "watch"]

    def blk(vals):
        n = len(vals)
        if n == 0:
            return {"n": 0}
        return {"n": n, "mean_bps": round(statistics.mean(vals), 1),
                "median_bps": round(statistics.median(vals), 1),
                "win": round(sum(1 for v in vals if v > 0) / n, 3)}

    out = {"kind": "tournament_scoreboard",
           "watch_rows": len(watch),
           "price_resolved_pending_actual": len(pend) - len(obs),
           "finalized": len(obs)}
    pm = [r for r in obs if r["timing"] == "pm"
          and r.get("short_pnl_res_bps") is not None]
    neg = [r for r in pm if r["surprise_class"] == "NEGATIVE"]
    non_neg = [r for r in pm if r["surprise_class"] != "NEGATIVE"]
    out["A1_pm_fade_all_pm"] = blk([r["short_pnl_res_bps"]
                                    for r in pm])
    out["A2_negative_cohort"] = blk([r["short_pnl_res_bps"]
                                     for r in neg])
    out["non_negative_pm"] = blk([r["short_pnl_res_bps"]
                                  for r in non_neg])
    if neg and non_neg:
        out["A2_increment_bps"] = round(
            statistics.mean([r["short_pnl_res_bps"] for r in neg])
            - statistics.mean([r["short_pnl_res_bps"]
                               for r in non_neg]), 1)
    else:
        out["A2_increment_bps"] = "NOT_ESTIMABLE_YET"
    by_cp = {}
    for cp in ("open", "+1m", "+5m", "+15m"):
        vals = [r["short_pnl_res_bps_by_checkpoint"][cp]
                for r in pm
                if r.get("short_pnl_res_bps_by_checkpoint", {}
                         ).get(cp) is not None]
        by_cp[cp] = blk(vals)
    out["A1_edge_decay_by_checkpoint"] = by_cp
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "seal":
        seal(sys.argv[2])
    elif mode == "resolve":
        resolve()
    elif mode == "finalize":
        finalize(sys.argv[2])
    elif mode == "report":
        report()
    else:
        raise SystemExit("mode: seal|resolve|finalize|report")
