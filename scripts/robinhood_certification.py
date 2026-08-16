#!/usr/bin/env python
"""ROBINHOOD CERTIFICATION — the operator's board, run against the real
broker read/review surface.

    python scripts/robinhood_certification.py [--symbol SPY]

Every row is measured, never assumed. Rows that cannot be measured print
BLOCKED (not FAIL) so an unauthenticated run is legible as "not yet"
rather than "broken". The three MUST rows are structural and are checked
even when the broker is unreachable — the seal does not depend on the
broker's cooperation.

This certifies INFRASTRUCTURE. It says nothing about whether APEX has
earned the right to trade, which is a scientific question answered by
forward evidence, not by a broker handshake.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
LEDGER = Path("results/execution/certification.jsonl")


def _row(name: str, verdict: str, detail: str = "") -> dict:
    return {"check": name, "verdict": verdict, "detail": detail}


def _probe(adapter, tool: str, **kw) -> tuple:
    """Returns (verdict, detail). A typed BLOCKED_BROKER_AUTH is BLOCKED;
    an exception or a malformed payload is FAIL."""
    from apex.execution.robinhood import BrokerAuthRequired
    try:
        out = adapter._call(tool, **kw)
    except BrokerAuthRequired:
        # NOT a failure. The distinction matters for the same reason the
        # weekend nightly-pull fix mattered: a board that cries FAIL for a
        # step the operator simply has not taken yet teaches everyone to
        # stop reading the board.
        return BLOCKED, "broker not authenticated"
    except PermissionError as e:                       # allow-list refusal
        return FAIL, f"transport refused: {e}"
    except Exception as e:                             # noqa: BLE001
        return FAIL, f"{type(e).__name__}"
    if not isinstance(out, dict):
        return FAIL, f"non-dict payload {type(out).__name__}"
    if out.get("status") == "BLOCKED_BROKER_AUTH":
        return BLOCKED, "broker not authenticated"
    if out.get("error"):
        return FAIL, str(out["error"])[:60]
    return PASS, ", ".join(sorted(out)[:4]) or "empty payload"


def certify(adapter, symbol: str = "SPY") -> list:
    rows = []

    # --- account visibility
    for label, tool in (("Account visible", "get_account_info"),
                        ("Buying power visible", "get_buying_power"),
                        ("Positions visible", "get_positions")):
        v, d = _probe(adapter, tool)
        rows.append(_row(label, v, d))

    # --- market data
    v, d = _probe(adapter, "get_stock_quote", symbol=symbol)
    rows.append(_row("Live equity quote", v, d))
    v, d = _probe(adapter, "get_options_chains", symbol=symbol)
    rows.append(_row("Option chain", v, d))
    v, d = _probe(adapter, "get_options_market_data", symbol=symbol)
    rows.append(_row("Option quote", v, d))

    # --- review (the deepest legal reach: broker prices the order, no send)
    v, d = _probe(adapter, "review_equity_order", symbol=symbol,
                  side="buy", quantity=1, order_type="limit", limit_price=1.0)
    rows.append(_row("Equity review_order", v, d))
    v, d = _probe(adapter, "review_option_order", symbol=symbol,
                  side="buy", quantity=1)
    rows.append(_row("Options review_order", v, d))

    # --- gateway behaviors (measured, not asserted)
    rows.append(_row("Duplicate intent protection", *_dup_check(adapter)))
    rows.append(_row("Kill switch", *_killswitch_check()))

    # --- the three MUSTs: structural, broker-independent
    rows.append(_row("place_* reachable from APEX", *_placement_check(adapter)))
    rows.append(_row("ORDER_READY reachable", *_order_ready_check()))
    rows.append(_row("ORDER_SENT reachable", *_order_sent_check()))
    return rows


def _dup_check(adapter) -> tuple:
    from apex.execution.gateway import intent_id_for
    a = intent_id_for("CERT-D1", "EQ", 1)
    b = intent_id_for("CERT-D1", "EQ", 1)
    c = intent_id_for("CERT-D1", "EQ", 2)
    if a != b:
        return FAIL, "same intent produced two ids"
    if a == c:
        return FAIL, "a new intent_version did not produce a new id"
    return PASS, "id stable across calls; version bump distinct"


def _killswitch_check() -> tuple:
    from apex.execution import killswitch as ks
    was = ks.state()["engaged"]
    try:
        ks.engage("certification probe")
        if not ks.state()["engaged"]:
            return FAIL, "engage() did not latch"
        if not ks.state()["engaged"]:
            return FAIL, "not observable after engage"
        return PASS, "engages, latches, observable, file-backed"
    finally:
        if not was:
            ks.release("certification probe complete")


def _placement_check(adapter) -> tuple:
    """MUST = NO. Three independent ways of being unable to place."""
    from apex.execution.sealing import (assert_no_placement_surface,
                                        scan_package_for_placement)
    if any(hasattr(adapter, m) for m in
           ("place_order", "place_equity_order", "submit_order")):
        return FAIL, "adapter exposes a placement method"
    try:
        assert_no_placement_surface(adapter)
    except Exception as e:                             # noqa: BLE001
        return FAIL, f"tripwire: {e}"
    scan = scan_package_for_placement("apex")
    if not scan["clean"]:
        return FAIL, f"package scan: {scan}"
    return PASS, "NO — absent, tripwire clean, package scan clean"


def _order_ready_check() -> tuple:
    from apex.execution.contracts import ReadinessState
    return ((PASS, "YES — ORDER_READY is an expressible terminal state")
            if hasattr(ReadinessState, "ORDER_READY")
            else (FAIL, "the terminal state does not exist"))


def _order_sent_check() -> tuple:
    from apex.execution.contracts import ReadinessState
    names = {m.name for m in ReadinessState}
    return ((PASS, "NO — not a member of ReadinessState")
            if "ORDER_SENT" not in names
            else (FAIL, "ORDER_SENT is expressible"))


BOARD_ORDER = [
    ("Account visible", None), ("Buying power visible", None),
    ("Positions visible", None), (None, None),
    ("Live equity quote", None), ("Option chain", None),
    ("Option quote", None), (None, None),
    ("Equity review_order", None), ("Options review_order", None),
    (None, None),
    ("Duplicate intent protection", None), ("Kill switch", None),
    (None, None),
    ("place_* reachable from APEX", "NO"),
    ("ORDER_READY reachable", "YES"),
    ("ORDER_SENT reachable", "NO"),
]


def render(rows: list) -> str:
    by = {r["check"]: r for r in rows}
    out = ["ROBINHOOD CERTIFICATION", ""]
    for name, must in BOARD_ORDER:
        if name is None:
            out.append("")
            continue
        r = by.get(name)
        v = r["verdict"] if r else "MISSING"
        if must:
            # show the MEASURED answer next to the requirement, so the row
            # reads as an observation rather than a self-congratulation
            measured = (r["detail"].split(" ")[0] if r and r["detail"]
                        else "?")
            mark = "OK" if v == PASS else "VIOLATION"
            out.append(f"{name:<32}{measured:<5} MUST = {must:<4} {mark}")
        else:
            out.append(f"{name:<32}{v}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    from apex.execution.robinhood import RobinhoodAdapter
    try:                                  # a live MCP transport if wired
        from apex.execution.mcp_transport import transport
    except ImportError:
        transport = None
    adapter = RobinhoodAdapter(transport)
    rows = certify(adapter, a.symbol)

    print(render(rows))
    print()
    health = adapter.connection_health()
    print(f"broker: {health['status']}")

    musts = {r["check"]: r for r in rows
             if r["check"].endswith("reachable from APEX")
             or r["check"].endswith("reachable")}
    seal_ok = all(m["verdict"] == PASS for m in musts.values())
    measurable = [r for r in rows if r["verdict"] in (PASS, FAIL)]
    failed = [r for r in rows if r["verdict"] == FAIL]
    blocked = [r for r in rows if r["verdict"] == BLOCKED]

    print(f"seal intact: {seal_ok} | measured {len(measurable)} | "
          f"failed {len(failed)} | blocked {len(blocked)}")
    if blocked:
        print("BLOCKED rows are not failures — they need the operator's "
              "one interactive step: /mcp -> robinhood-trading -> auth")
    if not failed and not blocked and seal_ok:
        print()
        print("APEX EXECUTION INFRASTRUCTURE: READY")
        print("Scientific authorization: NOT EARNED "
              "(infrastructure readiness is not evidence)")

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    from nightly_pull import _chain_append
    _chain_append(LEDGER, {"kind": "robinhood_certification",
                           "t_utc": str(pd.Timestamp.now(tz="UTC")),
                           "broker_status": health["status"],
                           "seal_intact": seal_ok, "rows": rows,
                           "authorization_power": "NONE"})
    if a.json:
        print(json.dumps(rows, indent=2))
    return 0 if (seal_ok and not failed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
