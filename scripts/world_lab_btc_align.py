#!/usr/bin/env python
"""WORLD LAB -- BTC CAUSAL ALIGNMENT + LEVERAGE PRIMITIVES.

Joins the acquired venue histories at hourly stamps and derives DATA
PRIMITIVES only. It does NOT create LONG_TRAP, SHORT_TRAP, CASCADE,
SQUEEZE or DELEVERAGING -- those are BTC-L3 interpretations and BTC-L3
is NOT_AUTHORIZED.

LAWS:
  * No silent forward-fill. A field absent at T is UNKNOWN, never zero
    and never the last seen value pretending to be current.
  * Every aligned value carries its own source_time and age_at_T.
  * Venue identity survives the join: kraken_oi is Kraken's OI, never
    "the" OI.
  * Causality: a primitive at T uses only observations with
    event_time <= T.

    python scripts/world_lab_btc_align.py

Writes results/world_lab/derived/btc/aligned_hourly.jsonl (versioned)
       results/world_lab/derived/btc/alignment_report.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RAW = Path("results/world_lab/raw/btc")
DER = Path("results/world_lab/derived/btc")
HOUR = 3600

# how stale a source may be before its value is refused at T
MAX_AGE_S = {"kraken_oi": 2 * HOUR, "deribit_perp": 2 * HOUR,
             "coinbase_spot": 2 * HOUR, "dvol": 2 * HOUR,
             "deribit_funding": 8 * HOUR}


def _rows(p: Path) -> list:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def _latest(path: Path, stem: str) -> Path | None:
    """Newest version of a versioned raw stream."""
    cands = sorted(path.glob(f"{stem}.v*.jsonl"))
    base = path / f"{stem}.jsonl"
    return cands[-1] if cands else (base if base.exists() else None)


def _index(rows: list, tkey: str, scale: float = 1.0) -> dict:
    out = {}
    for r in rows:
        t = int(r[tkey] * scale)
        out[t - (t % HOUR)] = r
    return out


def build() -> dict:
    import pandas as pd
    oi_f = _latest(RAW / "kraken_futures", "open_interest_hourly")
    oi = _index(_rows(oi_f), "event_time_s") if oi_f else {}
    perp = _index(_rows(RAW / "deribit" / "perp_bars_1h.jsonl"),
                  "event_time_ms", 1 / 1000)
    spot = _index(_rows(RAW / "coinbase" / "spot_candles_hourly.jsonl"),
                  "event_time_s")
    dvol = _index(_rows(RAW / "deribit" / "dvol_hourly.jsonl"),
                  "event_time_ms", 1 / 1000)
    fund = {}
    for r in _rows(RAW / "deribit" / "funding_hourly.jsonl"):
        t = int(r["timestamp_ms"] / 1000)
        fund[t - (t % HOUR)] = r

    stamps = sorted(set(oi) | set(perp) | set(spot))
    aligned, prev = [], None
    missing = {k: 0 for k in ("kraken_oi", "deribit_perp",
                              "coinbase_spot", "dvol",
                              "deribit_funding")}

    for t in stamps:
        rec = {"stamp_s": t, "stamp": str(pd.Timestamp(t, unit="s",
                                                       tz="UTC"))}

        def put(name, src, tkey, scale, field_map):
            r = src.get(t)
            if r is None:
                rec[name] = {"status": "UNKNOWN",
                             "reason": "no observation at stamp"}
                missing[name] += 1
                return None
            st = int(r[tkey] * scale)
            age = t - st
            if age > MAX_AGE_S[name] or age < 0:
                rec[name] = {"status": "REFUSED_STALE", "age_at_T": age}
                missing[name] += 1
                return None
            rec[name] = {"status": "OK", "source_time_s": st,
                         "age_at_T": age,
                         "cadence_s": HOUR,
                         **{k: r.get(v) for k, v in field_map.items()}}
            return r

        put("kraken_oi", oi, "event_time_s", 1,
            {"oi": "oi_close", "oi_open": "oi_open",
             "units": "native_units", "oi_class": "oi_class"})
        put("deribit_perp", perp, "event_time_ms", 1 / 1000,
            {"close": "close", "high": "high", "low": "low",
             "volume": "volume"})
        put("coinbase_spot", spot, "event_time_s", 1,
            {"close": "close", "volume": "volume"})
        put("dvol", dvol, "event_time_ms", 1 / 1000, {"close": "close"})
        put("deribit_funding", fund, "timestamp_ms", 1 / 1000,
            {"interest_8h": "interest_8h", "index": "index_price"})

        # ---------- PRIMITIVES (data only; no interpretation)
        p = {}
        k, dp, cs, dv = (rec["kraken_oi"], rec["deribit_perp"],
                         rec["coinbase_spot"], rec["dvol"])
        if dp["status"] == "OK" and prev and \
                prev["deribit_perp"]["status"] == "OK":
            a, b = prev["deribit_perp"]["close"], dp["close"]
            p["perp_return"] = (b / a - 1.0) if a else None
        if cs["status"] == "OK" and prev and \
                prev["coinbase_spot"]["status"] == "OK":
            a, b = prev["coinbase_spot"]["close"], cs["close"]
            p["spot_return"] = (b / a - 1.0) if a else None
        if k["status"] == "OK" and prev and \
                prev["kraken_oi"]["status"] == "OK":
            a, b = prev["kraken_oi"]["oi"], k["oi"]
            p["oi_change"] = b - a
            p["oi_change_pct"] = (b / a - 1.0) if a else None
        if dp["status"] == "OK" and cs["status"] == "OK" and cs["close"]:
            p["perp_spot_premium"] = dp["close"] / cs["close"] - 1.0
        f = rec["deribit_funding"]
        if f["status"] == "OK":
            p["funding_level_8h"] = f["interest_8h"]
            if prev and prev["deribit_funding"]["status"] == "OK":
                pf = prev["deribit_funding"]["interest_8h"]
                if pf is not None and f["interest_8h"] is not None:
                    p["funding_change"] = f["interest_8h"] - pf
        if dv["status"] == "OK":
            p["dvol"] = dv["close"]
        if p.get("spot_return") is not None and \
                p.get("perp_return") is not None:
            p["perp_minus_spot_return"] = (p["perp_return"] -
                                           p["spot_return"])
        rec["primitives"] = p
        rec["primitive_law"] = ("DATA PRIMITIVES ONLY -- no trap, "
                                "cascade, squeeze or deleveraging "
                                "labels; those are BTC-L3")
        aligned.append(rec)
        prev = rec

    DER.mkdir(parents=True, exist_ok=True)
    out = DER / f"aligned_hourly.v{int(time.time())}.jsonl"
    with open(out, "w") as fh:
        for r in aligned:
            fh.write(json.dumps(r, sort_keys=True) + "\n")

    # ---------- quality
    ts = [r["stamp_s"] for r in aligned]
    gaps = sum(1 for i in range(1, len(ts)) if ts[i] - ts[i - 1] > HOUR)
    nonmono = sum(1 for i in range(1, len(ts)) if ts[i] <= ts[i - 1])
    full = sum(1 for r in aligned
               if all(r[k]["status"] == "OK"
                      for k in ("kraken_oi", "deribit_perp",
                                "coinbase_spot")))
    quad = {"up_up": 0, "up_down": 0, "down_up": 0, "down_down": 0}
    for r in aligned:
        pr = r["primitives"].get("perp_return")
        oc = r["primitives"].get("oi_change_pct")
        if pr is None or oc is None:
            continue
        quad[("up" if pr > 0 else "down") + "_" +
             ("up" if oc > 0 else "down")] += 1

    rep = {"kind": "btc_alignment_report",
           "decision_power": "NONE_WORLD_LAB",
           "file": str(out), "stamps": len(aligned),
           "coverage": (aligned[0]["stamp"], aligned[-1]["stamp"])
           if aligned else None,
           "fully_joined_stamps": full,
           "missing_by_source": missing,
           "quality": {"hour_gaps": gaps,
                       "non_monotonic": nonmono,
                       "forward_fill_used": False,
                       "interpolation_used": False},
           "price_oi_quadrants": quad,
           "law": "UNKNOWN is preserved as UNKNOWN; no field was "
                  "forward-filled or interpolated"}
    (DER / "alignment_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main() -> int:
    print(json.dumps(build(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
