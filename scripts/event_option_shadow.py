"""AUTONOMOUS PUT-EXPRESSION SHADOW for the event tournament.

For every watched PM earnings event whose reaction session is TODAY,
capture real executable option quotes at two predeclared moments:

  entry  ~09:36 ET  (matches the +5m physical checkpoint)
  exit   ~15:55 ET  (matches the physical close-out window)

PREDECLARED contract selection (sealed here; never chosen after the
fact, never optimized):
  expiry        smallest expiration with 5 <= DTE <= 21 calendar days
  LONG_PUT      put strike nearest to spot at entry
  PUT_VERTICAL  the same long put + short put at the strike nearest
                to 0.95 * spot (must be strictly below the long)

Quotes come from Alpaca's options feed (indicative NBBO). IV/greeks
are recorded when the feed provides them, otherwise NOT_ESTIMABLE --
never computed from guessed vol. Executable convention (conservative):
buy at ask, sell at bid, both directions.

No orders. No sizing. decision_power: SHADOW_PROSPECTIVE_ONLY.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apex.governance.chain_ledger import chain_append  # noqa: E402

LEDGER = Path("results/event_sprint/prospective_ledger.jsonl")
OPT = "https://data.alpaca.markets/v1beta1/options/snapshots/{u}"
TRD = "https://data.alpaca.markets/v2/stocks/{s}/trades/latest"
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
            pass
    return out


def _prev_weekday(d):
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _todays_reaction_events(today):
    """PM watch rows whose reaction session is `today`: the report
    date is the previous weekday. (A market holiday shifts reaction
    by a day; that capture is then simply missed and recorded as a
    gap -- physical resolution is unaffected.)"""
    prev = _prev_weekday(today).isoformat()
    return [r for r in _rows()
            if r.get("kind") == "watch" and r.get("timing") == "pm"
            and r.get("report_date") == prev]


def _spot(sym):
    d = _get(TRD.format(s=sym) + "?feed=sip")
    try:
        return float(d["trade"]["p"])
    except Exception:
        return None


def _chain(sym, spot, today):
    lo, hi = today + timedelta(days=5), today + timedelta(days=21)
    q = {"feed": "indicative", "type": "put", "limit": 1000,
         "strike_price_gte": round(spot * 0.85, 2),
         "strike_price_lte": round(spot * 1.10, 2),
         "expiration_date_gte": lo.isoformat(),
         "expiration_date_lte": hi.isoformat()}
    d = _get(OPT.format(u=sym) + "?" + urllib.parse.urlencode(q))
    snaps = (d or {}).get("snapshots") or {}
    out = []
    for occ, s in snaps.items():
        try:
            # OCC: SYM + YYMMDD + P + strike*1000 (8 digits)
            tail = occ[len(sym):]
            exp = "20" + tail[0:2] + "-" + tail[2:4] + "-" + tail[4:6]
            strike = int(tail[7:]) / 1000.0
            lq = s.get("latestQuote") or {}
            out.append({"occ": occ, "expiry": exp, "strike": strike,
                        "bid": lq.get("bp"), "ask": lq.get("ap"),
                        "bid_size": lq.get("bs"),
                        "ask_size": lq.get("as"),
                        "iv": s.get("impliedVolatility",
                                    "NOT_ESTIMABLE"),
                        "greeks": s.get("greeks", "NOT_ESTIMABLE")})
        except Exception:
            continue
    return out


def _select(chain, spot):
    quoted = [c for c in chain if c["bid"] and c["ask"]
              and c["ask"] > c["bid"] > 0]
    if not quoted:
        return None
    expiry = min(c["expiry"] for c in quoted)
    exp = [c for c in quoted if c["expiry"] == expiry]
    atm = min(exp, key=lambda c: abs(c["strike"] - spot))
    lower = [c for c in exp if c["strike"] < atm["strike"]]
    short = (min(lower, key=lambda c: abs(c["strike"] - 0.95 * spot))
             if lower else None)
    return {"long_put": atm, "short_put": short}


def entry():
    today = datetime.now(NY).date()
    done = {(r["symbol"], r["reaction_session"]) for r in _rows()
            if r.get("kind") == "option_entry"}
    n = 0
    for ev in _todays_reaction_events(today):
        key = (ev["symbol"], today.isoformat())
        if key in done:
            continue
        spot = _spot(ev["symbol"])
        rec = {"kind": "option_entry", "symbol": ev["symbol"],
               "report_date": ev["report_date"],
               "reaction_session": today.isoformat(),
               "captured_utc": datetime.now(timezone.utc).isoformat(),
               "selection_rule": "SEALED: min expiry 5-21 DTE; long="
                                 "nearest-ATM put; short=nearest "
                                 "0.95*spot strictly below long"}
        if spot is None:
            rec["status"] = "NOT_ESTIMABLE_NO_SPOT"
        else:
            sel = _select(_chain(ev["symbol"], spot, today), spot)
            rec["spot"] = spot
            if sel is None:
                rec["status"] = "NOT_ESTIMABLE_NO_QUOTED_CHAIN"
            else:
                rec["status"] = "QUOTED"
                rec["long_put"] = sel["long_put"]
                rec["short_put"] = sel["short_put"] \
                    or "NOT_AVAILABLE"
        chain_append(LEDGER, rec)
        n += 1
    print(json.dumps({"option_entries": n,
                      "date": today.isoformat()}))


def exit_():
    today = datetime.now(NY).date().isoformat()
    entries = [r for r in _rows() if r.get("kind") == "option_entry"
               and r.get("reaction_session") == today
               and r.get("status") == "QUOTED"]
    done = {r["symbol"] for r in _rows()
            if r.get("kind") == "option_exit"
            and r.get("reaction_session") == today}
    n = 0
    for e in entries:
        if e["symbol"] in done:
            continue
        occs = [e["long_put"]["occ"]]
        if isinstance(e.get("short_put"), dict):
            occs.append(e["short_put"]["occ"])
        q = {"feed": "indicative", "symbols": ",".join(occs)}
        d = _get("https://data.alpaca.markets/v1beta1/options/"
                 "quotes/latest?" + urllib.parse.urlencode(q))
        quotes = (d or {}).get("quotes") or {}
        legs = {}
        for occ in occs:
            lq = quotes.get(occ) or {}
            legs[occ] = {"bid": lq.get("bp"), "ask": lq.get("ap")}
        spot = _spot(e["symbol"])
        chain_append(LEDGER, {
            "kind": "option_exit", "symbol": e["symbol"],
            "reaction_session": today, "spot": spot,
            "legs": legs,
            "captured_utc": datetime.now(timezone.utc).isoformat()})
        n += 1
    print(json.dumps({"option_exits": n, "date": today}))


if __name__ == "__main__":
    {"entry": entry, "exit": exit_}[sys.argv[1]]()
