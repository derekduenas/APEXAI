"""THE CRYPTO SHADOW ARENA — the Profit Machine's 24/7 proving ground.

CRYPTO FORWARD EPOCH 0: zero capital, forever, by construction (the feed
module cannot place orders; no broker exists in this package). BTC-USD
is the instrument; ETH/SOL are world context. Every tick:

  feed -> CryptoWorld -> CryptoChartState -> playbooks -> DECISION
  (persisted FIRST — the ordering law) -> Assassin (Swarm tier-1,
  budgeted) -> capital-lite caution -> SHADOW verdict -> later ticks
  resolve 15/30/60/90m outcomes continuously (24/7 market: no EOD).

SHADOW EXECUTION HONESTY: a SHADOW_TRADE's entry is the RECORDED ask
(long) / bid (short) at decision time — the spread is paid on paper from
observation one, and outcomes are measured from that entry to later
candle closes. MAE/MFE computed over the horizon window.

Evidence: COINBASE_FORWARD_OBSERVATION — its own class, its own ledger,
never mixed with equity statistics (the unmixed law enforces), and NEVER
evidence that the equity Hunter works. What it CAN test, genuinely
prospectively: does Scout -> Hunter -> Oracle -> Assassin -> Capital
raise the economic quality of survivors on live unseen data, and do the
Assassin's objections mark worse outcomes?
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from apex.crypto import feed
from apex.crypto.perception import (INSTRUMENT, PRODUCTS, compute_state,
                                    crypto_world, hour_volume_baseline)
from apex.crypto.playbooks import match_crypto_001, match_crypto_002
from apex.hunter.contracts import content_hash
from apex.hunter.evidence import EvidenceClass, stamp

ARENA_VERSION = "crypto_arena_v1"
LEDGER = Path("results/crypto/arena_ledger.jsonl")
BASELINE_CACHE = Path("results/crypto/hour_baseline.json")
HORIZONS = (15, 30, 60, 90)
SWARM_DAILY_BUDGET = 12          # tier-1 assassin calls per UTC day


def _append(record: dict) -> dict:
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, record)


def _rows() -> list:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_baseline(candles_14d: pd.DataFrame) -> dict:
    """Hour-of-UTC volume baseline, rebuilt daily, cached."""
    today = str(pd.Timestamp.now(tz="UTC").date())
    if BASELINE_CACHE.exists():
        c = json.loads(BASELINE_CACHE.read_text())
        if c.get("date") == today:
            return c["baseline"]
    b = hour_volume_baseline(candles_14d)
    if len(b) >= 20:                     # healthy: most hours represented
        BASELINE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_CACHE.write_text(json.dumps({"date": today, "baseline": b}))
    return b


def extreme_ages(candles: pd.DataFrame, t) -> dict:
    w = candles[candles["event_time_utc"] + pd.Timedelta(minutes=1)
                > t - pd.Timedelta(hours=4)]
    if len(w) < 30:
        return {}
    w = w.iloc[:-1]
    hi, lo = w["high"].astype(float), w["low"].astype(float)
    hmax, lmin = hi.max(), lo.min()
    ht = w["event_time_utc"][hi >= hmax * (1 - 1e-9)].iloc[-1]
    lt = w["event_time_utc"][lo <= lmin * (1 + 1e-9)].iloc[-1]
    return {"high": (t - ht).total_seconds() / 60,
            "low": (t - lt).total_seconds() / 60}


def swarm_budget_left(rows: list, today: str) -> int:
    used = sum(1 for r in rows if r.get("kind") == "crypto_assassin"
               and r.get("t_utc", "").startswith(today)
               and (r.get("swarm_view") or {}).get("status") == "OK")
    return max(0, SWARM_DAILY_BUDGET - used)


def resolve_pending(rows: list, candles: pd.DataFrame, now) -> list:
    """Continuous resolution: any shadow decision whose horizon elapsed
    gets its outcome measured from RECORDED entry to candle closes."""
    resolved_ids = {r["decision_id"] for r in rows
                    if r.get("kind") == "crypto_realization"}
    out = []
    px = candles.set_index("event_time_utc")["close"].astype(float)
    for d in rows:
        if d.get("kind") != "crypto_decision" \
                or d["decision_id"] in resolved_ids:
            continue
        t0 = pd.Timestamp(d["t_utc"])
        if now < t0 + pd.Timedelta(minutes=max(HORIZONS)) + \
                pd.Timedelta(minutes=2):
            continue                                # not mature yet
        entry = d["shadow_entry_price"]
        sign = 1.0 if d["direction"] == "LONG" else -1.0
        rec = {"kind": "crypto_realization",
               "decision_id": d["decision_id"], "t_utc": str(now),
               "label": "MECHANICAL_DETERMINISTIC"}
        window = candles[(candles["event_time_utc"] > t0)]
        ok = False
        for h in HORIZONS:
            sub = px[(px.index > t0)
                     & (px.index <= t0 + pd.Timedelta(minutes=h))]
            if len(sub):
                rec[f"ret_{h}m"] = round(sign * (sub.iloc[-1] / entry - 1), 6)
                hwin = window[window["event_time_utc"]
                              <= t0 + pd.Timedelta(minutes=h)]
                if len(hwin):
                    fav = hwin["high"].max() if sign > 0 else hwin["low"].min()
                    adv = hwin["low"].min() if sign > 0 else hwin["high"].max()
                    rec[f"mfe_{h}m"] = round(sign * (float(fav) / entry - 1), 6)
                    rec[f"mae_{h}m"] = round(sign * (float(adv) / entry - 1), 6)
                ok = True
        if ok and d.get("stop") and d.get("target"):
            hz = window[window["event_time_utc"]
                        <= t0 + pd.Timedelta(minutes=d.get(
                            "time_stop_minutes", 90))]
            if len(hz):
                l, hgh = hz["low"].astype(float), hz["high"].astype(float)
                if sign > 0:
                    s_i = hz.index[l <= d["stop"]]
                    t_i = hz.index[hgh >= d["target"]]
                else:
                    s_i = hz.index[hgh >= d["stop"]]
                    t_i = hz.index[l <= d["target"]]
                si = s_i[0] if len(s_i) else None
                ti = t_i[0] if len(t_i) else None
                rec["target_before_stop"] = (ti is not None and
                                             (si is None or ti < si))
                rec["stop_before_target"] = (si is not None and
                                             (ti is None or si <= ti))
        rec["resolvable"] = ok
        out.append(rec)
    return out


def tick(now=None, fabric=None) -> dict:
    """One arena cycle. With a live MarketFabric the book/quote/liquidity
    state comes from the continuous stream (execution fidelity); REST
    remains the memory (trailing history) and the fallback. Strategy
    semantics are identical either way."""
    now = pd.Timestamp(now) if now else pd.Timestamp.now(tz="UTC")
    today = str(now.date())
    candles = {p: feed.candles_1m(p, hours=26) for p in PRODUCTS}
    fab_snap = None
    bar_health = None
    if fabric is not None:
        fab_snap = fabric.snapshot()
        # LIVE BARS: splice the fabric's own trade-built bars over the
        # REST tail so the newest minutes are stream-fresh, not cached
        live = fabric.bars_1m(INSTRUMENT, minutes=120)
        if len(live):
            # BAR HEALTH DOCTRINE: gapped/incomplete bars have no
            # ChartState authority — dropped, never silently trusted
            unhealthy = int((live["coverage_status"]
                             != "COMPLETE_HEALTHY").sum())
            live = live[live["coverage_status"] == "COMPLETE_HEALTHY"]
            bar_health = {"healthy": len(live), "dropped_unhealthy":
                          unhealthy}
        else:
            bar_health = {"healthy": 0, "dropped_unhealthy": 0}
        if len(live) >= 5:
            base = candles[INSTRUMENT]
            cutoff = live["event_time_utc"].min()
            candles[INSTRUMENT] = pd.concat(
                [base[base["event_time_utc"] < cutoff],
                 live[["event_time_utc", "open", "high", "low", "close",
                       "volume"]]], ignore_index=True)
    if fab_snap and fabric.microstructure_authorized():
        bsnap = fab_snap["books"][INSTRUMENT]
        book = {"spread_bps": bsnap["spread_bps"],
                "imbalance_top10": bsnap["imbalance_top10"],
                "mid": bsnap["mid"]}
        tick_px = {"bid": bsnap["best_bid"], "ask": bsnap["best_ask"],
                   "last": bsnap["mid"]}
    else:
        # DEGRADED or no fabric: REST quote, and microstructure loses
        # authority (recorded on every decision, never assumed unchanged)
        book = feed.book_top(INSTRUMENT)
        tick_px = feed.ticker(INSTRUMENT)
    baseline = load_baseline(feed.candles_1m(INSTRUMENT, hours=24 * 14)
                             if not BASELINE_CACHE.exists()
                             or json.loads(BASELINE_CACHE.read_text()
                                           ).get("date") != today
                             else candles[INSTRUMENT])

    states = {p: compute_state(p, candles[p], now,
                               baseline if p == INSTRUMENT else None,
                               book if p == INSTRUMENT else None)
              for p in PRODUCTS}
    world = crypto_world(states, now)
    world_rec = stamp({**world, "arena_version": ARENA_VERSION,
                       "fabric": (fab_snap or {}).get("health",
                                                      "NO_FABRIC")},
                      EvidenceClass.COINBASE_FORWARD_OBSERVATION)
    _append(world_rec)

    stats = {"decisions": 0, "resolved": 0, "verdict": None}
    cs = states.get(INSTRUMENT)
    rows = _rows()
    if cs is not None:
        ages = extreme_ages(candles[INSTRUMENT], now)
        seen = {(r["playbook_id"], r["direction"])
                for r in rows if r.get("kind") == "crypto_decision"
                and pd.Timestamp(r["t_utc"]) > now - pd.Timedelta(hours=2)}
        for m in (match_crypto_001(cs, world),
                  match_crypto_002(cs, world, ages)):
            if m is None or (m["playbook_id"], m["direction"]) in seen:
                continue
            # THE ORDERING LAW: persist the decision before enrichment.
            # Shadow entry honesty: cross the recorded spread.
            entry = tick_px["ask"] if m["direction"] == "LONG" \
                else tick_px["bid"]
            # EXECUTION FIDELITY: walk the live book for realistic fills
            fills, book_evidence = {}, None
            if fabric is not None and fabric.microstructure_authorized():
                side = "BUY" if m["direction"] == "LONG" else "SELL"
                for notional in (1_000, 10_000, 50_000):
                    fills[f"${notional//1000}k"] = fabric.books[
                        INSTRUMENT].walk(side, notional)
                # FORENSIC EVIDENCE: the ladder that produced those fills,
                # kept with the decision (the firehose is not archived)
                book_evidence = fabric.books[INSTRUMENT].decision_snapshot()
            last_bar = candles[INSTRUMENT]["event_time_utc"].iloc[-1]
            latency = {
                "last_market_timestamp": str(last_bar),
                "decision_timestamp": str(now),
                "data_age_seconds": round(
                    (now - last_bar).total_seconds(), 1),
                "feed_mode": ("LIVE_FABRIC" if fabric is not None
                              and fabric.microstructure_authorized()
                              else "REST_FALLBACK"),
                "bar_health": bar_health if fabric is not None else None,
                "book_health": (fab_snap or {}).get(
                    "health", {}).get("book_health", "NO_FABRIC")}
            dec = stamp({
                "kind": "crypto_decision",
                "decision_id": content_hash(
                    {"t": str(now), "pb": m["playbook_id"],
                     "dir": m["direction"]})[:16],
                "t_utc": str(now), "product": INSTRUMENT, **m,
                "shadow_entry_price": entry,
                "bid_at_decision": tick_px["bid"],
                "ask_at_decision": tick_px["ask"],
                "spread_paid_bps": round(abs(entry - (tick_px["bid"]
                                         + tick_px["ask"]) / 2)
                                         / entry * 1e4, 3),
                "book_walk_fills": fills,
                "decision_book_snapshot": book_evidence,
                "latency": latency,
                "microstructure_authorized": bool(
                    fabric is not None
                    and fabric.microstructure_authorized()),
                "chart_state": cs.as_record(), "world": world,
                "horizons_minutes": list(HORIZONS),
                "capital_note": "SHADOW ONLY — zero capital by "
                                "construction, forever in Epoch 0",
            }, EvidenceClass.COINBASE_FORWARD_OBSERVATION)
            _append(dec)
            stats["decisions"] += 1
            # enrichment AFTER persistence: tier-1 assassin, budgeted
            try:
                from apex.hunter.swarm import run_specialists
                budget = swarm_budget_left(rows, today)
                if budget > 0:
                    swarm = run_specialists(
                        {**dec, "symbol": INSTRUMENT,
                         "market_state": {"day_return": world.get(
                             "returns_60m", {}).get("BTC-USD"),
                             "above_vwap": cs.above_vwap},
                         "relative_strength": {
                             "excess_market_60m": world.get(
                                 "btc_eth_rs_60m")}},
                        as_of=str(now), allow_deep=False)
                    sv = {"status": swarm.status,
                          "adversary_verdict": (swarm.provenance or {}).get(
                              "adversary_verdict"),
                          "flags": list(swarm.adversarial_flags)[:6]}
                else:
                    sv = {"status": "NOT_REQUESTED",
                          "reason": "daily swarm budget spent"}
            except Exception as e:                          # noqa: BLE001
                sv = {"status": "FAILED", "error": type(e).__name__}
            objection = sv.get("adversary_verdict") == "MATERIAL_OBJECTION"
            verdict = ("SHADOW_WATCH" if (world.get("uncertain")
                                          or objection)
                       else "SHADOW_TRADE")
            rev = stamp({"kind": "crypto_assassin",
                         "decision_id": dec["decision_id"],
                         "t_utc": str(now), "swarm_view": sv,
                         "world_uncertain": world.get("uncertain"),
                         "verdict": verdict,
                         "caution_rule": "objection or uncertain world "
                                         "caps at SHADOW_WATCH "
                                         "(conservative-only)"},
                        EvidenceClass.COINBASE_FORWARD_OBSERVATION)
            _append(rev)
            stats["verdict"] = verdict

    for rec in resolve_pending(rows, candles[INSTRUMENT], now):
        _append(stamp(rec, EvidenceClass.COINBASE_FORWARD_OBSERVATION))
        stats["resolved"] += 1
    return stats
