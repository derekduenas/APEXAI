#!/usr/bin/env python
"""One Candidate Microscope pass — Robinhood enrichment via a headless
child session. T1 item 2, operational.

    python scripts/microscope_pass.py            # targets from the ledger
    python scripts/microscope_pass.py --smoke SPY

Transport: `claude -p` with a hard --allowedTools list (read/review only).
The child binds the authenticated robinhood-trading MCP at ITS startup;
this process never holds a token. Every record stamps
transport=CLAIMED_MCP_CHILD_SESSION so the archive never implies the
Python layer spoke to the broker.

Selection is `apex.hunter.microscope.select_targets` — deterministic,
LLM-free. The child fetches; it does not choose. decision_power
NONE_OBSERVATIONAL_EPOCH1 on every record; the frozen pipeline consumes
none of this.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from apex.hunter.microscope import (LEDGER, MicroscopeTarget,  # noqa: E402
                                    record_request, record_result,
                                    select_targets)

TRANSPORT = "CLAIMED_MCP_CHILD_SESSION"
ALLOWED = ",".join(f"mcp__robinhood-trading__{t}" for t in
                   ("get_equity_quotes", "get_equity_price_book",
                    "get_equity_tradability"))
REDACT = re.compile(r'"(\w*account\w*number\w*)":\s*"[^"]+"', re.I)


def _append(rec: dict) -> None:
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, rec)


def fetch(symbols_l2: list, symbols_quote: list) -> dict:
    prompt = (
        "READ ONLY. Never call place_/cancel_/update_/create_/exercise_/"
        "watchlist tools.\n"
        f"1. get_equity_quotes for: {', '.join(symbols_quote)}\n"
        f"2. get_equity_price_book for each of: {', '.join(symbols_l2)}\n"
        f"3. get_equity_tradability for each of: {', '.join(symbols_l2)}\n"
        'Output ONLY JSON: {"quotes": {SYM: raw}, "books": {SYM: raw}, '
        '"tradability": {SYM: raw}}. Omit anything that errors. No prose.')
    r = subprocess.run(["claude", "-p", "--allowedTools", ALLOWED,
                        "--output-format", "text"],
                       input=prompt, capture_output=True, text=True,
                       timeout=420)
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        return {"__status__": "CHILD_SESSION_NO_JSON",
                "__stderr__": r.stderr[-200:]}
    return json.loads(REDACT.sub(r'"\1": "REDACTED"', m.group(0)))


def run(smoke: str | None) -> int:
    rows = []
    led = Path("results/hunter/forward_ledger.jsonl")
    if led.exists():
        for line in led.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    decisions = [r for r in rows if r.get("kind") == "decision"]
    scans = [r for r in rows if r.get("kind") == "scan"]
    targets, errors = select_targets(decisions=decisions, scans=scans[-4:])
    targets = list(targets)
    if errors:
        from apex.hunter.watchlist import record_parse_errors
        record_parse_errors(errors, component="microscope_pass.run",
                            input_reference=(scans[-1].get("t_utc")
                                             if scans else None))
    if not targets and smoke:
        targets = [MicroscopeTarget(symbol=smoke, priority=1,
                                    reason_selected="SMOKE_TEST_OPERATOR",
                                    wants_l2=True)]
    if not targets:
        print("no targets (no candidates/watchlist yet) — correct silence")
        return 2

    now = str(pd.Timestamp.now(tz="UTC"))
    for t in targets:
        _append(record_request(t, request_time=now, transport=TRANSPORT))
    l2 = [t.symbol.replace(".US", "") for t in targets if t.wants_l2]
    quotes = [t.symbol.replace(".US", "") for t in targets]
    data = fetch(l2, quotes)
    done = str(pd.Timestamp.now(tz="UTC"))
    status = data.get("__status__", "OK")
    for t in targets:
        sym = t.symbol.replace(".US", "")
        _append(record_result(
            t, request_time=now, response_time=done, transport=TRANSPORT,
            quote=(data.get("quotes") or {}).get(sym),
            l2=(data.get("books") or {}).get(sym),
            context=(data.get("tradability") or {}).get(sym),
            status=status))
        print(f"{t.symbol:<10} p{t.priority} l2={t.wants_l2} "
              f"quote={'Y' if (data.get('quotes') or {}).get(sym) else 'UNKNOWN'} "
              f"book={'Y' if (data.get('books') or {}).get(sym) else 'UNKNOWN'}")
    print(f"-> {LEDGER} ({status})")
    return 0 if status == "OK" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", default=None,
                    help="force one symbol when the ledger is empty")
    a = ap.parse_args()
    return run(a.smoke)


if __name__ == "__main__":
    raise SystemExit(main())
