#!/usr/bin/env python
"""OPTIONS PhD -- THETADATA vs ORATS FINAL PILOT (pre-staged).

Runs ONLY when the operator's Theta Terminal v3 is alive on
127.0.0.1:25503 (operator subscribes/logs in; credentials never touch
this repo). Exits with a clear refusal otherwise.

TIER: operator subscribed STANDARD (2026-08-22) -- historical NBBO
quotes AND trades AND (per docs) 8 years of history are in scope.
The PRIMARY TEST is unchanged: raw NBBO + APEX's own pricing stack --
can the Predator manufacture its own IV/surface intelligence from
market truth? Vendor analytics, where exposed, are a cross-check,
never the authority.
SECRET LAW: the API key lives in the macOS keychain and the Theta
Terminal's environment ONLY. It never appears in this file, any
ledger, any output, or any commit.

PRE-REGISTERED (2026-08-22, before any download):
    symbols  SPY NVDA AAPL
    dates    2023-07-19 quiet | 2024-08-05 yen-carry | 2024-05-22 NVDA
             event | 2022-09-13 CPI selloff | 2024-02-22 trend
    A/B      AAPL 2022-08-08 14:00-14:04Z vs the ORATS sample --
             same minutes, same contracts, two vendors
    filter   max_dte=120, strikes via strike_range around spot
             (server-side; count what it removes)
    OI law   OI_AS_OF = prior settlement; OI_KNOWN_FROM = actual
             availability; NEVER prior-close-by-default
decision_power: NONE -- data research only. Authority OBSERVE.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:25503/v3"
OUT = Path("results/world_lab/raw/options_pilot")
ORATS_SAMPLE = Path("/private/tmp/claude-501/-Users-derekduenas/"
                    "83f91d89-d01b-4fea-8a39-caf39e74e23f/scratchpad/"
                    "Intraday Sample Data")

SYMBOLS = ("SPY", "NVDA", "AAPL")
DATES = {"2023-07-19": "quiet", "2024-08-05": "yen-carry shock",
         "2024-05-22": "NVDA event", "2022-09-13": "CPI selloff",
         "2024-02-22": "trend"}
AB_DATE = "2022-08-08"          # ORATS-sample overlap, AAPL only
MAX_DTE = 120
STRIKE_RANGE = 15               # n strikes each side of spot + ATM


def _get(path: str, **params) -> str:
    q = urllib.parse.urlencode({k: v for k, v in params.items()
                                if v is not None})
    url = f"{BASE}/{path}?{q}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode()


def terminal_alive() -> bool:
    try:
        _get("option/history/quote", symbol="SPY", date="20240522",
             interval="1m", strike_range=1, right="call",
             expiration="*", max_dte=7, format="csv",
             start_time="10:00:00", end_time="10:01:00")
        return True
    except Exception as e:                                 # noqa: BLE001
        print(f"REFUSED: Theta Terminal v3 not reachable on :25503 "
              f"({type(e).__name__}). Operator must run the terminal "
              f"logged into Options Value. No credentials belong here.")
        return False


def pull_quotes(symbol: str, date: str) -> Path:
    """One symbol-day of 1m NBBO, server-filtered, stored raw."""
    OUT.mkdir(parents=True, exist_ok=True)
    d = date.replace("-", "")
    csv_text = _get("option/history/quote", symbol=symbol, date=d,
                    interval="1m", expiration="*", strike="*",
                    right="both", max_dte=MAX_DTE,
                    strike_range=STRIKE_RANGE, format="csv")
    p = OUT / f"theta_quotes_{symbol}_{d}.csv"
    p.write_text(csv_text)
    return p


def pull_oi(symbol: str, date: str) -> Path:
    d = date.replace("-", "")
    txt = _get("option/history/open_interest", symbol=symbol, date=d,
               expiration="*", strike="*", right="both",
               max_dte=MAX_DTE, format="csv")
    p = OUT / f"theta_oi_{symbol}_{d}.csv"
    p.write_text(txt)
    return p


def pull_trades(symbol: str, date: str):
    """Standard tier exposes historical option trades -- pull them as a
    SEPARATE stream (quote and trade semantics are never merged)."""
    d = date.replace("-", "")
    try:
        txt = _get("option/history/trade", symbol=symbol, date=d,
                   expiration="*", strike="*", right="both",
                   max_dte=MAX_DTE, format="csv")
    except Exception:                                      # noqa: BLE001
        return None
    p = OUT / f"theta_trades_{symbol}_{d}.csv"
    p.write_text(txt)
    return p


def main() -> int:
    if not terminal_alive():
        return 1
    print("terminal alive -- executing pre-registered pilot")
    manifest = {"kind": "thetadata_pilot_manifest",
                "law": "VALUE tier: trades/vendor-IV = "
                       "NOT_AVAILABLE_ON_PILOT_TIER, never FAIL",
                "preregistration": {"symbols": SYMBOLS,
                                    "dates": DATES,
                                    "ab_date": AB_DATE,
                                    "max_dte": MAX_DTE,
                                    "strike_range": STRIKE_RANGE},
                "pulled": []}
    for date in list(DATES) + [AB_DATE]:
        for sym in (("AAPL",) if date == AB_DATE else SYMBOLS):
            try:
                qp = pull_quotes(sym, date)
                op = pull_oi(sym, date)
                tp = pull_trades(sym, date)
                manifest["pulled"].append(
                    {"symbol": sym, "date": date,
                     "quotes": str(qp), "oi": str(op),
                     "trades": str(tp) if tp else
                     "TRADES_ENDPOINT_UNAVAILABLE",
                     "quote_bytes": qp.stat().st_size})
                print(f"  {sym} {date}: quotes "
                      f"{qp.stat().st_size/1e6:.1f} MB")
            except Exception as e:                        # noqa: BLE001
                manifest["pulled"].append(
                    {"symbol": sym, "date": date,
                     "status": f"SOURCE_DATE_UNAVAILABLE_OR_ERROR: "
                               f"{type(e).__name__}"})
                print(f"  {sym} {date}: UNAVAILABLE ({type(e).__name__})")
    (OUT / "pilot_manifest.json").write_text(
        json.dumps(manifest, indent=1))
    print("raw pull complete -- run the analysis battery next "
          "(integrity, A/B vs ORATS, dividend-aware own-IV, surface, "
          "RvI, expression, storage)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
