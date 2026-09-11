"""PROVIDER ADAPTERS (M2) — official interface shapes, synthetic fixtures, production disabled.

Two providers already used by the legacy session are wrapped WITHOUT changing them:
    Alpaca market data v2   underlying 1-minute bars (`/v2/stocks/{sym}/bars?timeframe=1Min`) and
                            latest NBBO (`/v2/stocks/{sym}/quotes/latest?feed=sip`)
    ThetaData v3            option expirations and chain snapshots (`/v3/option/list/expirations`,
                            `/v3/option/snapshot/quote`); quote timestamps arrive ET-naive (documented
                            in apex.predators.options.live_world) and are converted to UTC epochs HERE,
                            with the conversion recorded on every quote.

Every adapter takes an injectable `http_get(url, headers) -> str` so tests exercise the exact parsing
on fixture responses. `LiveGate` decides whether production connectivity may be attempted at all:
credentials must be present AND the operator switch APEX_PILOT_LIVE_DATA must equal "ENABLED";
otherwise every call raises ProviderUnavailable with a named reason, and nothing is contacted."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .ingest import BarStore, IngestRefused

ET = ZoneInfo("America/New_York")
ALPACA = "https://data.alpaca.markets/v2"
THETA = "http://127.0.0.1:25503/v3"
LIVE_SWITCH = "APEX_PILOT_LIVE_DATA"


class ProviderUnavailable(RuntimeError):
    pass


class LiveGate:
    """Production connectivity is DISABLED unless (a) the operator switch is set and (b) credentials exist.
    This gate never reads secret VALUES into records; it only reports presence."""

    def __init__(self, env: dict | None = None, secret_fn=None):
        self.env = os.environ if env is None else env
        self.secret_fn = secret_fn

    def status(self) -> dict:
        switch = self.env.get(LIVE_SWITCH)
        creds = {}
        for name in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
            try:
                creds[name] = bool(self.secret_fn(name)) if self.secret_fn else bool(self.env.get(name))
            except Exception:                                    # noqa: BLE001
                creds[name] = False
        return {"switch": switch, "switch_ok": switch == "ENABLED", "credentials_present": creds,
                "enabled": switch == "ENABLED" and all(creds.values())}

    def require(self, what: str) -> None:
        st = self.status()
        if not st["switch_ok"]:
            raise ProviderUnavailable("LIVE_DATA_DISABLED: %s not enabled (%s=%r); %s not contacted" % (what, LIVE_SWITCH, st["switch"], what))
        missing = [k for k, v in st["credentials_present"].items() if not v]
        if missing:
            raise ProviderUnavailable("CREDENTIALS_ABSENT: %s; %s not contacted" % (missing, what))


def _iso_to_epoch(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ---------------------------------------------------------------- Alpaca bars / NBBO

class AlpacaBarsAdapter:
    provider = "ALPACA_DATA_V2"

    def __init__(self, *, gate: LiveGate, http_get, headers_fn, clock=time.time):
        self.gate, self.http_get, self.headers_fn, self.clock = gate, http_get, headers_fn, clock

    def parse_bars(self, text: str, *, symbol: str, receipt_time: float) -> list:
        """Alpaca bar: {"t": "2026-09-10T13:30:00Z", "o","h","l","c","v","n","vw"}. `t` is the bar START."""
        doc = json.loads(text)
        out = []
        for b in doc.get("bars") or []:
            out.append({"event_time": _iso_to_epoch(b["t"]), "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"],
                        "volume": b["v"], "trades": b.get("n"), "vwap": b.get("vw"), "receipt_time": receipt_time,
                        "publication_time": None, "provider": self.provider, "symbol": symbol,
                        "timestamp_convention": "bar START, UTC ISO-8601 as published"})
        return out

    def bars(self, symbol: str, *, start_epoch: float, end_epoch: float) -> list:
        self.gate.require("Alpaca bars")
        s = datetime.fromtimestamp(start_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        e = datetime.fromtimestamp(end_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = "%s/stocks/%s/bars?timeframe=1Min&start=%s&end=%s&limit=10000&feed=sip" % (ALPACA, symbol, s, e)
        txt = self.http_get(url, self.headers_fn())
        return self.parse_bars(txt, symbol=symbol, receipt_time=self.clock())

    def parse_nbbo(self, text: str, *, receipt_time: float) -> dict:
        q = json.loads(text)["quote"]
        return {"bid": q["bp"], "ask": q["ap"], "bid_size": int(q["bs"]), "ask_size": int(q["as"]),
                "as_of": _iso_to_epoch(q["t"]), "available": receipt_time, "source": self.provider + ":sip"}

    def nbbo(self, symbol: str) -> dict:
        self.gate.require("Alpaca NBBO")
        txt = self.http_get("%s/stocks/%s/quotes/latest?feed=sip" % (ALPACA, symbol), self.headers_fn())
        return self.parse_nbbo(txt, receipt_time=self.clock())


# ---------------------------------------------------------------- ThetaData chain

class ThetaChainAdapter:
    provider = "THETADATA_V3"

    def __init__(self, *, gate: LiveGate, http_get, clock=time.time):
        self.gate, self.http_get, self.clock = gate, http_get, clock

    @staticmethod
    def et_naive_to_epoch(ts: str) -> float:
        """ThetaData quote timestamps are ET wall-clock without a zone; localize to America/New_York (DST-aware)."""
        naive = datetime.fromisoformat(ts)
        if naive.tzinfo is not None:
            return naive.timestamp()
        return naive.replace(tzinfo=ET).timestamp()

    def parse_chain(self, text: str, *, symbol: str, expiration: str, receipt_time: float) -> list:
        rows = json.loads(text)
        out = []
        for r in rows if isinstance(rows, list) else rows.get("response", []):
            out.append({"symbol": symbol, "expiration": expiration, "strike": float(r["strike"]),
                        "right": "CALL" if str(r["right"]).upper().startswith("C") else "PUT",
                        "bid": r.get("bid"), "ask": r.get("ask"), "bid_size": r.get("bid_size"), "ask_size": r.get("ask_size"),
                        "timestamp_epoch": self.et_naive_to_epoch(r["timestamp"]), "timestamp_raw": r["timestamp"],
                        "timestamp_convention": "provider ET-naive wall clock localized to America/New_York",
                        "receipt_time": receipt_time, "provider": self.provider})
        return out

    def chain(self, symbol: str, expiration: str) -> list:
        self.gate.require("ThetaData chain")
        txt = self.http_get("%s/option/snapshot/quote?symbol=%s&expiration=%s" % (THETA, symbol, expiration.replace("-", "")), None)
        return self.parse_chain(txt, symbol=symbol, expiration=expiration, receipt_time=self.clock())


# ---------------------------------------------------------------- synthetic fixtures

class SyntheticBarProvider:
    """Deterministic synthetic bars (a labelled fixture): a random-walk close series on exact minutes."""
    provider = "SYNTHETIC_FIXTURE"

    def __init__(self, *, seed: int = 7, start_price: float = 645.0):
        self.seed, self.start_price = seed, start_price

    def bars(self, symbol: str, *, start_epoch: float, end_epoch: float, receipt_lag_s: float = 0.5) -> list:
        import random
        rng = random.Random("%s|%d|%d" % (symbol, self.seed, int(start_epoch)))
        t = start_epoch - (start_epoch % 60)
        px = self.start_price
        out = []
        while t + 60 <= end_epoch:
            r = rng.gauss(0.0, 2.0e-4)
            o = px; c = px * (1.0 + r); h = max(o, c) * (1 + abs(rng.gauss(0, 5e-5))); l = min(o, c) * (1 - abs(rng.gauss(0, 5e-5)))
            v = float(rng.randint(500, 5000))
            out.append({"event_time": t, "open": o, "high": h, "low": l, "close": c, "volume": v, "trades": rng.randint(5, 50),
                        "vwap": 0.5 * (o + c), "receipt_time": t + 60 + receipt_lag_s, "publication_time": None,
                        "bar_complete": t + 60, "available": t + 60 + receipt_lag_s,
                        "provider": self.provider, "symbol": symbol})
            px = c
            t += 60
        return out


def load_bars(store: BarStore, provider_bars: list) -> dict:
    """Feed provider bars into a BarStore; malformed bars are counted and named, never dropped silently."""
    problems = []
    for b in provider_bars:
        try:
            store.add_provider_bar(event_time=b["event_time"], open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                                  volume=b["volume"], receipt_time=b["receipt_time"], publication_time=b.get("publication_time"),
                                  vwap=b.get("vwap"), trades=b.get("trades"))
        except IngestRefused as e:
            problems.append(str(e))
    return {"accepted": store.counters["provider_bars"], "problems": problems, "counters": dict(store.counters)}
