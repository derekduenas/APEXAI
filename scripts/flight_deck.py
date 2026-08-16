#!/usr/bin/env python
"""APEX FLIGHT DECK — the operating cockpit. CONSUMER ONLY.

    python scripts/flight_deck.py [--port 8787]
    open http://127.0.0.1:8787

Reads canonical ledgers and serves them; it creates no decision
authority, no second source of truth, and no state of its own. Zero
external dependencies (no CDN, no TradingView licensing): the chart is
vanilla canvas over APEX's own bars.

Panels: live chart · Captain · Digital World · Oracle · Assassin ·
Capital · Execution · Opportunity Board · Replay. Unavailable sensors
are rendered UNAVAILABLE, never neutral — a missing feed must LOOK
missing.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

CRYPTO_LEDGER = Path("results/crypto/arena_ledger.jsonl")
EQUITY_LEDGER = Path("results/hunter/forward_ledger.jsonl")
INTENT_LEDGER = Path("results/execution/order_intents.jsonl")


def _rows(path: Path, limit: int = 4000) -> list:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-limit:]
    out = []
    for ln in lines:
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def _last(rows: list, kind: str):
    for r in reversed(rows):
        if r.get("kind") == kind:
            return r
    return None


def crypto_state() -> dict:
    rows = _rows(CRYPTO_LEDGER)
    world = _last(rows, "crypto_world")
    decisions = [r for r in rows if r.get("kind") == "crypto_decision"]
    exits = {r["decision_id"] for r in rows
             if r.get("kind") == "crypto_shadow_exit"}
    captain = _last(rows, "captain_state")
    assassin = _last(rows, "crypto_assassin")
    bars = []
    try:
        from apex.crypto import feed
        f = feed.candles_1m("BTC-USD", hours=3)
        bars = [{"t": int(pd.Timestamp(r.event_time_utc).timestamp()),
                 "o": float(r.open), "h": float(r.high), "l": float(r.low),
                 "c": float(r.close), "v": float(r.volume)}
                for r in f.itertuples()]
    except Exception as e:                                  # noqa: BLE001
        bars = []
        world = world or {"error": type(e).__name__}
    open_pos = [d for d in decisions if d["decision_id"] not in exits]
    return {
        "world": world, "captain": captain, "assassin": assassin,
        "bars": bars[-180:],
        "decisions": decisions[-25:],
        "open_shadow_positions": open_pos[-10:],
        "exits": [r for r in rows
                  if r.get("kind") == "crypto_shadow_exit"][-10:],
        "counts": {k: sum(1 for r in rows if r.get("kind") == k)
                   for k in ("crypto_world", "crypto_decision",
                             "crypto_assassin", "crypto_shadow_exit",
                             "crypto_realization")},
    }


def equity_state() -> dict:
    rows = _rows(EQUITY_LEDGER)
    return {
        "forward_state": _last(rows, "forward_state"),
        "world_state": _last(rows, "world_state"),
        "scan": _last(rows, "scan"),
        "board": _last(rows, "opportunity_board"),
        "captain": _last(rows, "captain_state"),
        "bundle": _last(rows, "forecast_bundle"),
        "assassin": _last(rows, "assassin_review"),
        "capital": _last(rows, "capital_decision"),
        "counts": {k: sum(1 for r in rows if r.get("kind") == k)
                   for k in ("forward_state", "scan", "decision",
                             "capital_decision", "realization")},
        "ledger_exists": EQUITY_LEDGER.exists(),
    }


def _broker_row(ex: dict) -> str:
    """NO_TRANSPORT and BLOCKED_BROKER_AUTH are different facts. Collapsing
    them tells the operator to wait for something that will never arrive
    (the Python process holds no OAuth token and cannot acquire one)."""
    st = ex["broker"]["status"]
    if st == "READY":
        return "READY"
    if ex.get("transport_mode") == "NO_TRANSPORT":
        return "NO_TRANSPORT_NOT_AUTH_ISSUE"
    return "BLOCKED_BROKER_AUTH"


def execution_state() -> dict:
    from apex.execution.killswitch import state as kstate
    from apex.execution.robinhood import RobinhoodAdapter
    from apex.execution.sealing import scan_package_for_placement
    from apex.execution.mcp_transport import default
    transport, mode = default()               # honest: no route from here
    adapter = RobinhoodAdapter(transport)
    rows = _rows(INTENT_LEDGER)
    return {
        "broker": adapter.connection_health(),
        "transport_mode": mode,
        "kill_switch": kstate(),
        "live_placement": "SEALED",
        "placement_scan": scan_package_for_placement("apex"),
        "recent_intents": [{"state": r.get("state"),
                            "symbol": (r.get("intent") or {}).get("symbol"),
                            "reasons": r.get("reasons", [])[:3]}
                           for r in rows[-8:]],
        "order_ready_count": sum(1 for r in rows
                                 if r.get("state") == "ORDER_READY"),
    }


def _component(module: str, qualifier: str = "READY") -> str:
    """INSTR-01: a readiness row must MEASURE the thing it describes.

    Eleven rows on this board were hardcoded string literals -- "Scout":
    "READY" was true only because someone typed it. Deleting the scanner
    would not have changed the cockpit. A control that reports a state it
    never measured is not a control, and this is the surface the operator
    watches to decide whether the machine is alive.

    The measurement here is deliberately modest and honest: the module
    imports. That is a real fact about the running system, and it fails
    loudly when the thing is gone.
    """
    import importlib
    try:
        importlib.import_module(module)
    except Exception as e:                                  # noqa: BLE001
        return f"UNAVAILABLE_{type(e).__name__}"
    return qualifier


def readiness_board() -> dict:
    """The unified execution-readiness surface. Every row is MEASURED;
    a row that cannot be measured says so rather than claiming READY."""
    ex = execution_state()
    eq = equity_state()
    cr = crypto_state()
    import subprocess
    try:
        loaded = subprocess.run(["launchctl", "list"], capture_output=True,
                                text=True).stdout
    except Exception:                                       # noqa: BLE001
        loaded = ""
    return {
        "Market feeds": ("READY" if cr["bars"] else "DEGRADED"),
        "Crypto daemon": ("READY" if "crypto-daemon" in loaded
                          else "NOT_LOADED"),
        "Equity clock": ("ARMED" if "hunter-clock" in loaded
                         else "NOT_LOADED"),
        "Event archive": ("ARMED" if "event-capture" in loaded
                          else "NOT_LOADED"),
        "Digital World": _component("apex.world.twin2"),
        "Scout": _component("apex.hunter.scanner"),
        "Hunter": _component("apex.hunter.playbooks_v1"),
        "Oracle": _component("apex.analog.engine", "PARTIAL_DATA_GATED"),
        "Assassin": _component("apex.hunter.assassin"),
        "Captain": _component("apex.captain.kernel", "READY_OBSERVATIONAL"),
        "Capital": _component("apex.hunter.capital",
                              "READY_NO_FORECAST_AUTH"),
        "Options Expression": _component("apex.execution.expression_v2",
                                         "READY_DIAGNOSTIC"),
        "Robinhood connection": ex["broker"]["status"],
        "Broker review": _broker_row(ex),
        "Flight Deck": "READY",          # measured by being able to answer
        "Trade Manager": _component("apex.hunter.paper"),
        "ORDER CONSTRUCTION": _component("apex.execution.gateway"),
        "BROKER PREVIEW": _broker_row(ex),
        "LIVE PLACEMENT": "SEALED",
        "KILL SWITCH": ("ENGAGED" if ex["kill_switch"]["engaged"]
                        else "ARMED"),
        "equity_ledger": ("LIVE" if eq["ledger_exists"]
                          else "EMPTY_UNTIL_MONDAY"),
    }


HTML = (Path(__file__).resolve().parent / "flight_deck.html")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                              # quiet
        pass

    def do_GET(self):                                       # noqa: N802
        try:
            if self.path.startswith("/api/state"):
                payload = {"crypto": crypto_state(),
                           "equity": equity_state(),
                           "execution": execution_state(),
                           "readiness": readiness_board(),
                           "t": str(pd.Timestamp.now(tz="UTC"))}
                body = json.dumps(payload, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:                              # noqa: BLE001
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"{type(e).__name__}: {e}".encode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    print(f"APEX FLIGHT DECK -> http://127.0.0.1:{a.port}  (consumer only; "
          f"LIVE PLACEMENT SEALED)")
    HTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
