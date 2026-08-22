"""The paper execution harness -- order lifecycle, blotter, recovery.

    submit -> (fill | cancel | modify->fill) -> position -> exit
           -> P&L / R / MFE / MAE -> blotter

BACKENDS:
  SIMULATED     fills at the caller-supplied reference price plus half
                the supplied spread (adverse-side, honest: paper fills
                should never be more generous than reality). Fully
                commissionable offline. No network.
  ALPACA_PAPER  adapter for a real paper account; REFUSES until
                dedicated paper keys exist (ALPACA_PAPER_KEY_ID /
                ALPACA_PAPER_SECRET_KEY in the keychain env). The
                stored market-data keys authenticate against the LIVE
                trading API and are therefore never accepted here.

IDEMPOTENCY: client_order_id is the identity. Re-submitting an id that
exists returns the existing order untouched (never a second order).
RECOVERY: state is a pure replay of the blotter; a restarted harness
sees exactly the orders/positions the ledger proves.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from apex.execution_paper import (
    ALLOWED_BROKER_HOSTS, ORDER_MODES, PAPER_EXECUTION_POWER,
)
from apex.governance import authority_ladder as ladder

BLOTTER = Path("results/execution_paper/blotter.jsonl")

STATES = ("SUBMITTED", "FILLED", "CANCELLED", "CLOSED")


class PaperExecutionViolation(RuntimeError):
    pass


@dataclass
class PaperOrder:
    client_order_id: str
    mode: str
    symbol: str
    side: str                       # BUY | SELL
    qty: float
    order_type: str                 # MARKET | LIMIT
    limit_price: float | None
    stop_price: float | None
    state: str
    submitted_at: str
    fill_price: float | None = None
    filled_at: str | None = None
    exit_price: float | None = None
    closed_at: str | None = None
    realized_pnl: float | None = None
    r_multiple: float | None = None
    mfe: float | None = None
    mae: float | None = None
    slippage: float | None = None
    tags: dict = field(default_factory=dict)

    def as_record(self) -> dict:
        return {"kind": "paper_order_event", **asdict(self),
                "decision_power": PAPER_EXECUTION_POWER}


def _check_host(url: str) -> None:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_BROKER_HOSTS:
        raise PaperExecutionViolation(
            f"host {host!r} is not a permitted PAPER endpoint; the live "
            f"trading API is refused by construction (the stored data "
            f"keys were proven live-capable on 2026-08-21)")


class PaperHarness:
    """One instance per process; all durable truth lives in the blotter."""

    def __init__(self, blotter: Path | None = None):
        self.blotter = Path(blotter or BLOTTER)
        self._orders: dict = {}
        self._replay()

    # ---------------------------------------------------------- recovery
    def _replay(self) -> None:
        """Restart recovery: rebuild in-memory state purely from the
        blotter. The LAST event per client_order_id wins."""
        self._orders.clear()
        if not self.blotter.exists():
            return
        for line in self.blotter.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") != "paper_order_event":
                continue
            fields = {k: r[k] for k in PaperOrder.__dataclass_fields__
                      if k in r}
            self._orders[r["client_order_id"]] = PaperOrder(**fields)

    def _persist(self, o: PaperOrder) -> None:
        from apex.governance.chain_ledger import chain_append
        self.blotter.parent.mkdir(parents=True, exist_ok=True)
        chain_append(self.blotter, o.as_record())

    # --------------------------------------------------------- lifecycle
    def submit(self, *, mode: str, symbol: str, side: str, qty: float,
               order_type: str = "MARKET", limit_price: float | None = None,
               stop_price: float | None = None,
               client_order_id: str | None = None, now,
               tags: dict | None = None) -> PaperOrder:
        if mode not in ORDER_MODES:
            raise PaperExecutionViolation(
                f"mode {mode!r} does not exist -- there is no live order "
                f"mode in this package, by construction")
        if not ladder.may_submit(mode):
            raise PaperExecutionViolation(
                f"authority ladder at {ladder.current_level()!r} does not "
                f"permit {mode} orders -- promotion is explicit, never "
                f"implicit")
        if side not in ("BUY", "SELL"):
            raise PaperExecutionViolation(f"bad side {side!r}")
        if qty <= 0:
            raise PaperExecutionViolation("qty must be positive")
        coid = client_order_id or f"APEX-PAPER-{uuid.uuid4().hex[:12]}"
        # IDEMPOTENCY: an existing id returns the existing order,
        # untouched -- never a duplicate submission.
        if coid in self._orders:
            return self._orders[coid]
        import pandas as pd
        o = PaperOrder(client_order_id=coid, mode=mode, symbol=symbol,
                       side=side, qty=qty, order_type=order_type,
                       limit_price=limit_price, stop_price=stop_price,
                       state="SUBMITTED", submitted_at=str(pd.Timestamp(now)),
                       tags=dict(tags or {}))
        self._orders[coid] = o
        self._persist(o)
        return o

    def fill_simulated(self, client_order_id: str, *, reference_price: float,
                       spread: float = 0.0, now) -> PaperOrder:
        """SIMULATED backend fill: adverse half-spread, never generous.
        BUY fills at ref + spread/2, SELL at ref - spread/2. A LIMIT
        order refuses to fill through its limit."""
        o = self._get(client_order_id)
        if o.state != "SUBMITTED":
            raise PaperExecutionViolation(
                f"{client_order_id} is {o.state}; only SUBMITTED fills")
        px = (reference_price + spread / 2 if o.side == "BUY"
              else reference_price - spread / 2)
        if o.order_type == "LIMIT" and o.limit_price is not None:
            if (o.side == "BUY" and px > o.limit_price) or \
               (o.side == "SELL" and px < o.limit_price):
                return o                     # no fill; order stands
            px = o.limit_price if (
                (o.side == "BUY" and px > o.limit_price)
                or (o.side == "SELL" and px < o.limit_price)) else px
        import pandas as pd
        o.state = "FILLED"
        o.fill_price = round(px, 6)
        o.filled_at = str(pd.Timestamp(now))
        o.slippage = round(abs(px - reference_price) * o.qty, 6)
        self._persist(o)
        return o

    def cancel(self, client_order_id: str, *, now) -> PaperOrder:
        o = self._get(client_order_id)
        if o.state != "SUBMITTED":
            raise PaperExecutionViolation(
                f"{client_order_id} is {o.state}; only SUBMITTED cancels")
        import pandas as pd
        o.state = "CANCELLED"
        o.closed_at = str(pd.Timestamp(now))
        self._persist(o)
        return o

    def modify(self, client_order_id: str, *, limit_price: float,
               now) -> PaperOrder:
        o = self._get(client_order_id)
        if o.state != "SUBMITTED":
            raise PaperExecutionViolation(
                f"{client_order_id} is {o.state}; only SUBMITTED modifies")
        o.limit_price = limit_price
        self._persist(o)
        return o

    def close_position(self, client_order_id: str, *, exit_price: float,
                       mfe: float | None = None, mae: float | None = None,
                       now) -> PaperOrder:
        o = self._get(client_order_id)
        if o.state != "FILLED":
            raise PaperExecutionViolation(
                f"{client_order_id} is {o.state}; only FILLED closes")
        import pandas as pd
        sign = 1.0 if o.side == "BUY" else -1.0
        o.exit_price = round(exit_price, 6)
        o.realized_pnl = round(sign * (exit_price - o.fill_price) * o.qty, 4)
        if o.stop_price is not None and o.fill_price != o.stop_price:
            risk = abs(o.fill_price - o.stop_price) * o.qty
            o.r_multiple = round(o.realized_pnl / risk, 3) if risk else None
        o.mfe, o.mae = mfe, mae
        o.state = "CLOSED"
        o.closed_at = str(pd.Timestamp(now))
        self._persist(o)
        return o

    # ------------------------------------------------------------ views
    def _get(self, coid: str) -> PaperOrder:
        if coid not in self._orders:
            raise PaperExecutionViolation(f"unknown order {coid!r}")
        return self._orders[coid]

    def positions(self) -> list:
        return [o for o in self._orders.values() if o.state == "FILLED"]

    def blotter_view(self, mode: str | None = None) -> list:
        out = [o for o in self._orders.values()
               if mode is None or o.mode == mode]
        return sorted(out, key=lambda o: o.submitted_at)


def alpaca_paper_account() -> dict:
    """The real-paper-broker adapter. REFUSES until dedicated PAPER keys
    exist -- the stored market-data keys authenticate against the LIVE
    trading API and are never accepted here."""
    import os
    key = os.environ.get("ALPACA_PAPER_KEY_ID")
    secret = os.environ.get("ALPACA_PAPER_SECRET_KEY")
    if not key or not secret:
        return {"status": "REFUSED",
                "reason": "dedicated Alpaca PAPER keys absent "
                          "(ALPACA_PAPER_KEY_ID / ALPACA_PAPER_SECRET_KEY)"
                          " -- generate them in the Alpaca dashboard; the"
                          " live-capable data keys are refused here by "
                          "policy"}
    url = "https://paper-api.alpaca.markets/v2/account"
    _check_host(url)
    import ssl
    import urllib.request
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        d = json.loads(r.read())
    if not str(d.get("account_number", "")).startswith("PA"):
        raise PaperExecutionViolation(
            "endpoint returned a non-paper account number -- refusing")
    return {"status": "OK", "account_number": d.get("account_number"),
            "cash": d.get("cash"), "equity": d.get("equity")}
