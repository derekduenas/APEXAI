"""Arm SessionAnchorEvidence for today's session.

Runs at/just after the open and captures, per symbol, the facts that
prove the true 09:30 ET anchor was observed LIVE -- while those facts
still exist. The whole point is to beat the 400-bar rolling retention
that destroyed this evidence for 10 of 14 symbols on 2026-08-18.

    python scripts/arm_session_anchor_evidence.py [--minutes 45] [--cadence 60]

Re-captures on a short cadence for a bounded window: a symbol that has
not printed yet at 09:30 may print at 09:34, and we want the FIRST real
observation, not whatever happened to be true on a single pass. Each
capture is append-only; read_for() takes the last write per symbol.

Reads ONLY canonical persisted bars (the same artifact Hunter and
Frontier-2 read). Makes no network call of its own and takes no
decision.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from apex.intraday import session_anchor_evidence as sae
from apex.intraday.alpaca_fabric import BARS_DIR, TRANSPORT

REQUIRED_SYMBOLS = ("SPY", "QQQ", "IWM", "XLB", "XLC", "XLE", "XLF", "XLI",
                    "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")

TRANSPORT_BIRTHS = Path("results/intraday/transport_births.jsonl")


def _scheduled_session(session_date: str) -> tuple:
    """True exchange bounds from the existing calendar -- never invented
    here."""
    from apex.intraday.sessions import ET, EARLY_CLOSES
    d = pd.Timestamp(session_date).tz_localize(ET)
    open_t = d.normalize() + pd.Timedelta(hours=9, minutes=30)
    close_h, close_m = (13, 0) if session_date in EARLY_CLOSES else (16, 0)
    close_t = d.normalize() + pd.Timedelta(hours=close_h, minutes=close_m)
    return open_t.tz_convert("UTC"), close_t.tz_convert("UTC")


def _transport_birth() -> str | None:
    if not TRANSPORT_BIRTHS.exists():
        return None
    latest = None
    for line in TRANSPORT_BIRTHS.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("transport_id") == TRANSPORT:
            latest = r.get("birth_time")
    return latest


def capture_symbol(symbol: str, session_date: str, *, now, birth) -> dict | None:
    p = Path(BARS_DIR) / f"{symbol}_{session_date}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    bars = d.get("bars") or []
    if not bars:
        return None

    open_utc, close_utc = _scheduled_session(session_date)
    regular = [b for b in bars
               if pd.Timestamp(b["event_time_utc"]) >= open_utc
               and pd.Timestamp(b["event_time_utc"]) < close_utc]
    if not regular:
        return None
    first = regular[0]
    first_t = pd.Timestamp(first["event_time_utc"])

    # A completed bar with real trades is direct evidence the tape was
    # being observed in that minute. We do not have per-message trade or
    # quote timestamps in this artifact, so we record what we genuinely
    # have and leave the rest None rather than inferring.
    had_trades = (first.get("trades") or 0) > 0
    ev = sae.capture(
        symbol=symbol, session_date=session_date,
        scheduled_open=open_utc, scheduled_close=close_utc, now=now,
        provider=TRANSPORT,
        first_regular_trade_time=(first_t if had_trades else None),
        first_regular_quote_time=None,
        first_completed_regular_bar=first_t,
        opening_bar={"open": first.get("open"), "high": first.get("high"),
                     "low": first.get("low"), "close": first.get("close"),
                     "volume": first.get("volume")},
        transport_birth=birth, reconstructed_after_the_fact=False)
    sae.persist(ev)
    return ev.as_record()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=45.0)
    ap.add_argument("--cadence", type=float, default=60.0)
    ap.add_argument("--session-date", default=None)
    a = ap.parse_args()

    now0 = pd.Timestamp.now(tz="UTC")
    session_date = a.session_date or str(
        now0.tz_convert("America/New_York").date())
    birth = _transport_birth()
    captured: set = set()

    print(f"ARM SESSION ANCHOR EVIDENCE {session_date} "
          f"({len(REQUIRED_SYMBOLS)} symbols, {a.minutes:.0f} min window)",
          flush=True)

    t_end = time.time() + a.minutes * 60
    while time.time() < t_end:
        now = pd.Timestamp.now(tz="UTC")
        for s in REQUIRED_SYMBOLS:
            if s in captured:
                continue
            try:
                rec = capture_symbol(s, session_date, now=now, birth=birth)
            except Exception as e:                          # noqa: BLE001
                print(f"{s}: capture failed {type(e).__name__}: {e}", flush=True)
                continue
            if rec is not None:
                captured.add(s)
                print(f"{s}: anchor_source={rec['opening_anchor_source']} "
                      f"valid={rec['opening_anchor_valid']} "
                      f"first_bar={rec['first_completed_regular_bar']}", flush=True)
        if len(captured) == len(REQUIRED_SYMBOLS):
            print("all required symbols captured", flush=True)
            break
        remaining = t_end - time.time()
        if remaining <= 0:
            break
        time.sleep(max(1.0, min(a.cadence, remaining)))

    cert = sae.certify(session_date, REQUIRED_SYMBOLS)
    print(json.dumps(cert, indent=1, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
