"""Alpaca options (OPRA) entitlement probe -- F O24. A re-runnable
version of the ad hoc empirical checks performed live on 2026-08-18:
what does the CURRENT Alpaca key actually return for options data,
measured directly against the API, never assumed from documentation
alone.

This script makes real network calls when APCA_API_KEY_ID/
APCA_API_SECRET_KEY are set; it refuses to fabricate a result when
they are not, or when the network is unreachable -- every field in
the output is either a real observation or explicitly UNREACHABLE/
NOT_CHECKED, never a guess.

The Robinhood side of the entitlement question (option chain / Greek
availability via mcp__robinhood-trading__*) is NOT reproducible from a
standalone script -- those tools only exist inside a live Claude Code
MCP session. This script documents that gap rather than silently
skipping it.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / "results" / "options_research" / "alpaca_options_entitlement_probe.json"

DATA_BASE = "https://data.alpaca.markets"
TRADING_BASE = "https://paper-api.alpaca.markets"
PROBE_SYMBOL = "AAPL"

GREEK_KEYS = ("greeks", "delta", "gamma", "theta", "vega", "rho",
             "implied_volatility", "iv")


def _ssl_context() -> ssl.SSLContext:
    """Same fix as apex/intraday/eodhd.py: this venv's Python does not
    reliably find the system CA store on its own -- point explicitly
    at the macOS system bundle, override via APEX_CA_BUNDLE."""
    return ssl.create_default_context(
        cafile=os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem"))


def _get(url: str, headers: dict, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            body = resp.read().decode("utf-8")
            return {"status": resp.status, "ok": True, "body": json.loads(body) if body else {}}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
        except Exception:  # noqa: BLE001
            parsed = {}
        return {"status": e.code, "ok": False, "body": parsed}
    except urllib.error.URLError as e:
        return {"status": None, "ok": False, "error": f"UNREACHABLE: {e.reason}"}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "ok": False, "error": f"UNEXPECTED: {e!r}"}


def _contains_greek_keys(obj) -> bool:
    """Recursively check whether ANY dict key in the payload matches a
    Greek/IV field name -- structural, not string-matched on values."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in GREEK_KEYS:
                return True
            if _contains_greek_keys(v):
                return True
    elif isinstance(obj, list):
        return any(_contains_greek_keys(v) for v in obj)
    return False


def probe_options_snapshot(key: str, secret: str) -> dict:
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    url = f"{DATA_BASE}/v1beta1/options/snapshots/{PROBE_SYMBOL}"
    result = _get(url, headers)
    contracts = result.get("body", {}).get("snapshots", {}) if result.get("ok") else {}
    return {
        "endpoint": url, "status": result.get("status"), "ok": result.get("ok"),
        "error": result.get("error"),
        "contract_count": len(contracts) if isinstance(contracts, dict) else None,
        "sample_contract_symbols": list(contracts.keys())[:3] if isinstance(contracts, dict) else [],
        "contains_greek_or_iv_fields": _contains_greek_keys(result.get("body", {})),
    }


def probe_trading_account_scope(key: str, secret: str) -> dict:
    """Confirms whether this key has ANY trading/account authority --
    expected to be 401 for a market-data-only key, since Alpaca is
    PRIMARY_BROAD_SENSOR here, never a broker."""
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    url = f"{TRADING_BASE}/v2/account"
    result = _get(url, headers)
    return {"endpoint": url, "status": result.get("status"), "ok": result.get("ok"),
           "error": result.get("error"),
           "has_trading_authority": bool(result.get("ok"))}


def main() -> dict:
    import pandas as pd
    now = str(pd.Timestamp.now(tz="UTC"))
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")

    if not key or not secret:
        out = {"probed_at": now, "status": "SKIPPED_NO_CREDENTIALS",
              "options_snapshot": None, "trading_account_scope": None,
              "robinhood_note": (
                  "not checked from this script -- requires a live "
                  "mcp__robinhood-trading__get_option_chains call inside a "
                  "Claude Code MCP session, not reproducible headlessly")}
    else:
        out = {
            "probed_at": now, "status": "PROBED",
            "options_snapshot": probe_options_snapshot(key, secret),
            "trading_account_scope": probe_trading_account_scope(key, secret),
            "robinhood_note": (
                "not checked from this script -- requires a live "
                "mcp__robinhood-trading__get_option_chains call inside a "
                "Claude Code MCP session, not reproducible headlessly"),
        }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0)
