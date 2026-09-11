"""The replay engine for PILOT-REPLAY-001 (see contract.py). Streams one corpus session at a time.

Temporal firewall: for a decision at minute m (bar [m-1, m) complete at m:00), the engine may read
quote rows with timestamp <= m and bars with event_time < m. The exit reads exactly the row at m+15.
Rows after m+15 are never loaded for that scan. Every scan record states what it used.

Costs enter exactly once: entry at the ASK, exit at the BID (spread crossing is in the sides),
fees from the SYNTHETIC schedule per side. Latency: the simulated execution instant is m + 0.25 s
(EXECUTION_POLICY_V1); the corpus quote is the NBBO at m:00, so its age at execution is 0.25 s."""
from __future__ import annotations

import csv
import gzip
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apex.governance.chain_ledger import chain_append
from apex.options_pilot.expression_rule import DTE_MIN_DAYS, RuleRefused, choose
from apex.options_pilot.fees import EXECUTION_POLICY_V1, SYNTHETIC_FEES
from apex.options_pilot.risk_authority import envelope_for
from apex.pulse_options.features import FeaturesRefused
from apex.pulse_options.ingest import BarStore
from apex.pulse_options.inference import FrozenArtifact, default_artifact
from apex.pulse_options.snapshot import compose, usable_value

ET = ZoneInfo("America/New_York")
EVIDENCE_CLASS = "HISTORICAL_DEVELOPMENT_REPLAY"
DECISION_POWER = "NONE_REPLAY"
LAST_EXPOSED_DATE = "2021-12-31"
SCAN_MINUTES_ET = [(h, m) for h in range(10, 16) for m in (0, 15, 30, 45) if (h, m) <= (15, 30)]
HOLD_MIN = 15
MULT = 100.0
VARIANTS = ("POLICY", "RANDOM_DIRECTION", "REVERSED_DIRECTION")


class ReplayRefused(RuntimeError):
    pass


def _et_naive_to_epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).replace(tzinfo=ET).timestamp()


def session_days(root: Path, symbol: str, *, last_date: str = LAST_EXPOSED_DATE) -> list:
    """Corpus days with BOTH quote and underlying files, dated <= last_date. Later days are excluded BEFORE any read."""
    base = Path(root) / symbol
    days = []
    for f in base.iterdir():
        if f.name.startswith("quotes_") and f.name.endswith(".csv.gz"):
            d8 = f.name[7:15]
            d = "%s-%s-%s" % (d8[:4], d8[4:6], d8[6:])
            if d <= last_date and (base / ("underlying_%s.json.gz" % d8)).exists():
                days.append(d)
    return sorted(days)


def load_bars(root: Path, symbol: str, day: str) -> list:
    d8 = day.replace("-", "")
    doc = json.loads(gzip.open(Path(root) / symbol / ("underlying_%s.json.gz" % d8)).read())
    out = []
    for b in doc["bars"]:
        t = datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp()
        local = datetime.fromtimestamp(t, tz=ET)
        if not ((9, 30) <= (local.hour, local.minute) < (16, 0)):          # regular hours by exchange-local time, not by label
            continue
        out.append({"event_time": t, "open": float(b["o"]), "high": float(b["h"]), "low": float(b["l"]), "close": float(b["c"]),
                    "volume": float(b["v"]), "trades": b.get("n"), "vwap": b.get("vw"), "receipt_time": t + 60.0, "publication_time": None})
    return sorted(out, key=lambda x: x["event_time"])


def stream_quotes(root: Path, symbol: str, day: str, *, minutes_needed: set, expirations_window: tuple) -> dict:
    """{minute_hhmm: {(expiration, strike, right): quote}} for the minutes needed only. Streams the file once."""
    d8 = day.replace("-", "")
    out: dict = {m: {} for m in minutes_needed}
    lo, hi = expirations_window
    with gzip.open(Path(root) / symbol / ("quotes_%s.csv.gz" % d8), "rt") as fh:
        for r in csv.DictReader(fh):
            hhmm = r["timestamp"][11:16]
            if hhmm not in out or r.get("moneyness_status") != "CAUSAL":
                continue
            e = r["expiration"]
            if not (lo <= e <= hi):
                continue
            key = (e, float(r["strike"]), r["right"])
            out[hhmm][key] = {"bid": float(r["bid"]), "ask": float(r["ask"]), "bid_size": int(float(r["bid_size"])), "ask_size": int(float(r["ask_size"])),
                              "timestamp_epoch": _et_naive_to_epoch(r["timestamp"]), "underlying_ref": r.get("underlying_ref")}
    return out


def _hhmm(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(ET).strftime("%H:%M")


def fill_and_exit(q: dict, xq: dict | None, fee_schedule=SYNTHETIC_FEES) -> dict:
    """Entry at ask (m), exit at bid (m+15), fees once per side. Shared by every variant."""
    fe, fx = fee_schedule.entry(1)["total"], fee_schedule.exit(1)["total"]
    if xq is None or xq["bid"] <= 0 or xq["bid_size"] < 1:
        return {"exit": {"status": "NOT_ESTIMABLE", "why": "EXIT_BID_MISSING_OR_ZERO"}, "pnl": None}
    gross = MULT * (xq["bid"] - q["ask"])
    return {"exit": {"status": "RESOLVED", "bid": xq["bid"], "bid_size": xq["bid_size"]},
            "pnl": {"gross": round(gross, 2), "fees": round(fe + fx, 2), "net": round(gross - fe - fx, 2),
                    "spread_crossing_cost": round(MULT * ((q["ask"] - q["bid"]) / 2 + (xq["ask"] - xq["bid"]) / 2), 2) if xq["ask"] > 0 else None}}


def replay_session(root: Path, symbol: str, day: str, *, artifact: FrozenArtifact, fee_schedule=SYNTHETIC_FEES, seed: int = 11,
                   out_path: Path | None = None, funnel=None) -> list:
    bars = load_bars(root, symbol, day)
    if len(bars) < 60:
        return [{"kind": "replay_session_refused", "day": day, "why": "TOO_FEW_REGULAR_BARS: %d" % len(bars)}]
    st = BarStore(symbol, source="CORPUS:ALPACA_1M")
    for b in bars:
        st.add_provider_bar(event_time=b["event_time"], open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"],
                            receipt_time=b["receipt_time"], vwap=b.get("vwap"), trades=b.get("trades"))
    by_t = {b["event_time"]: b for b in bars}
    day_dt = datetime.fromisoformat(day)
    scan_epochs = [datetime(day_dt.year, day_dt.month, day_dt.day, h, m, tzinfo=ET).timestamp() for h, m in SCAN_MINUTES_ET]
    minutes_needed = {_hhmm(e) for e in scan_epochs} | {_hhmm(e + HOLD_MIN * 60) for e in scan_epochs}
    exp_lo = (day_dt + timedelta(days=DTE_MIN_DAYS)).strftime("%Y-%m-%d")
    exp_hi = (day_dt + timedelta(days=DTE_MIN_DAYS + 45)).strftime("%Y-%m-%d")
    quotes = stream_quotes(root, symbol, day, minutes_needed=minutes_needed, expirations_window=(exp_lo, exp_hi))
    rng = random.Random("%s|%s|%d" % (symbol, day, seed))
    records = []
    for k, m in enumerate(scan_epochs):
        rec = {"kind": "replay_scan", "study_id": "PILOT-REPLAY-001", "evidence_class": EVIDENCE_CLASS, "decision_power": DECISION_POWER,
               "symbol": symbol, "day": day, "scan": k + 1, "decision_epoch": m, "decision_et": _hhmm(m), "variants": {}}
        avail = st.bars_available_by(m)
        snap = compose(symbol=symbol, as_of=m + 0.001, bars=avail, source="CORPUS:ALPACA_1M")
        rec["state_hash"] = snap["state_hash"]
        try:
            fc = artifact.forecast(snap, created_epoch=m + 0.01)
        except (FeaturesRefused, Exception) as e:                          # noqa: BLE001
            rec.update(decision="REFUSE", why="FORECAST: %s: %s" % (type(e).__name__, str(e)[:120]))
            records.append(rec); continue
        rec["forecast"] = {k2: fc[k2] for k2 in ("location", "scale", "nu", "params_hash", "reference_time_utc", "input_cutoff_utc")}
        # realized 15-minute target from the bars (for calibration; the decision never sees it)
        tb = by_t.get(m + HOLD_MIN * 60 - 60)
        rb = by_t.get(m - 60)
        rec["realized_log_return_15m"] = (math.log(tb["close"] / rb["close"]) if tb and rb else None)
        r15 = usable_value(snap, "ret_15")
        policy_dir = None if r15 in (None, 0) else ("LONG" if r15 > 0 else "SHORT")
        dirs = {"POLICY": policy_dir, "RANDOM_DIRECTION": rng.choice(["LONG", "SHORT"]),
                "REVERSED_DIRECTION": (None if policy_dir is None else ("SHORT" if policy_dir == "LONG" else "LONG"))}
        spot = usable_value(snap, "last_bar_close")
        q_now = quotes.get(_hhmm(m), {})
        q_exit = quotes.get(_hhmm(m + HOLD_MIN * 60), {})
        available = [{"expiration": e, "strike": s, "right": r, "ask": q["ask"]} for (e, s, r), q in q_now.items() if q["ask"] > 0 and q["ask_size"] >= 1]
        for name, d in dirs.items():
            v = {"direction": d}
            if d is None:
                v.update(decision="REFUSE", why="NO_DIRECTION_SIGNAL")
                rec["variants"][name] = v; continue
            try:
                prop = choose(symbol=symbol, direction_signal=d, spot=spot, as_of=datetime.fromtimestamp(m, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              available=available)
            except RuleRefused as e:
                v.update(decision="REFUSE", why=str(e)[:120]); rec["variants"][name] = v; continue
            c = prop["contract"]; key = (c["expiration"], float(c["strike"]), c["right"])
            q = q_now.get(key)
            env = envelope_for(reference_ask=prop.get("reference_ask"), quantity=1)
            v.update(contract=c, contract_id="%s|%s|%s|%s" % (symbol, c["expiration"], float(c["strike"]), c["right"]),
                     entry_quote={k3: q[k3] for k3 in ("bid", "ask", "bid_size", "ask_size")}, envelope=env["max_entry_price"], envelope_feasible=env["feasible"])
            age_exec = (m + EXECUTION_POLICY_V1.simulated_latency_s) - q["timestamp_epoch"]
            if not env["feasible"]:
                v.update(decision="REFUSE", why="RISK_ENVELOPE_INFEASIBLE")
            elif q["ask"] > env["max_entry_price"]:
                v.update(decision="WAIT", why="ASK_ABOVE_ENVELOPE")
            elif age_exec > 15.0 or q["ask_size"] < 1:
                v.update(decision="WAIT", why="STALE_OR_NO_SIZE")
            else:
                v.update(decision="TRADE")
            # cap-free counterfactual on the same quote (labelled; never selected)
            xq = q_exit.get(key)
            fe, fx = fee_schedule.entry(1)["total"], fee_schedule.exit(1)["total"]
            if xq is None or xq["bid"] <= 0 or xq["bid_size"] < 1:
                v["exit"] = {"status": "NOT_ESTIMABLE", "why": "EXIT_BID_MISSING_OR_ZERO"}
                v["pnl_counterfactual_no_cap"] = None
            else:
                v["exit"] = {"status": "RESOLVED", "bid": xq["bid"], "bid_size": xq["bid_size"]}
                gross = MULT * (xq["bid"] - q["ask"])
                v["pnl_counterfactual_no_cap"] = {"gross": round(gross, 2), "fees": round(fe + fx, 2), "net": round(gross - fe - fx, 2),
                                                  "spread_crossing_cost": round(MULT * ((q["ask"] - q["bid"]) / 2 + (xq["ask"] - xq["bid"]) / 2), 2) if xq["ask"] > 0 else None}
            if v["decision"] == "TRADE":
                v["pnl"] = v["pnl_counterfactual_no_cap"]
                if v["pnl"] is None:
                    v["decision"], v["why"] = "TRADE_UNRESOLVED", "position filled; exit not estimable at +15 (outstanding obligation)"
            else:
                v["pnl"] = None
            rec["variants"][name] = v
        if funnel is not None:
            try:
                rec["variants"]["FULL_FUNNEL"] = funnel.decide(day=day, m=m, snapshot=snap, forecast=fc, q_now=q_now, q_exit=q_exit, spot=spot,
                                                              bars_prefix=[b for b in bars if b["event_time"] < m], fee_schedule=fee_schedule)
            except Exception as e:                                             # noqa: BLE001 - the funnel's failures are recorded, never hidden
                rec["variants"]["FULL_FUNNEL"] = {"decision": "REFUSE", "why": "FUNNEL_FAILED: %s: %s" % (type(e).__name__, str(e)[:160]), "direction": None}
        rec["decision"] = rec["variants"]["POLICY"].get("decision")
        rec["why"] = rec["variants"]["POLICY"].get("why")
        records.append(rec)
    if funnel is not None:
        funnel.end_session(day=day, bars=bars)
    if out_path is not None:
        for r in records:
            chain_append(out_path, r)
    return records
