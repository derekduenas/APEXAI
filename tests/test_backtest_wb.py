"""PILOT-REPLAY-001 engine on a SYNTHETIC corpus: contract validity; sealed-period exclusion before any read; the
temporal firewall (a poison row after the exit minute changes nothing); planted-drift detection (the engine reports
P&L when it exists and the reversed control loses it); evaluation reports exactly the planned comparisons."""
import csv
import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from apex.backtest_wb import contract as C, evaluate as EV, replay as R
from apex.pulse_options.inference import default_artifact

ET = ZoneInfo("America/New_York")


def _corpus(root: Path, day: str, *, drift_per_min: float = 0.02, poison: bool = False, spot0: float = 300.0, wiggle: float = 0.0):
    d = datetime.fromisoformat(day)
    base = root / "SPY"; base.mkdir(parents=True, exist_ok=True)
    bars, rows = [], []
    spot = spot0
    exp = (d + timedelta(days=25)).strftime("%Y-%m-%d")
    strikes = [spot0 - 4, spot0 - 2, spot0, spot0 + 2, spot0 + 4]
    for i in range(391):
        t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET) + timedelta(minutes=i)
        o = spot; spot = spot + drift_per_min + (wiggle if i % 2 == 0 else -wiggle); c = spot
        bars.append({"t": t.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": max(o, c) + 0.01, "l": min(o, c) - 0.01, "c": c,
                     "v": 1000 + i, "n": 10, "vw": 0.5 * (o + c), "session": "REG"})
        ts = t.strftime("%Y-%m-%dT%H:%M:%S.000")
        for k in strikes:
            call = max(0.05, 3.0 + (spot - k) * 0.5)             # a call that tracks the drift
            put = max(0.05, 3.0 - (spot - k) * 0.5)
            for right, mid in (("CALL", call), ("PUT", put)):
                rows.append({"symbol": "SPY", "expiration": exp, "strike": "%.3f" % k, "right": right, "timestamp": ts, "bid_size": 20, "bid_exchange": 0,
                             "bid": "%.2f" % (mid - 0.02), "bid_condition": 50, "ask_size": 20, "ask_exchange": 0, "ask": "%.2f" % (mid + 0.02),
                             "ask_condition": 50, "underlying_ref": "%.2f" % c, "underlying_ref_label": "", "underlying_ref_age_s": 0, "moneyness_status": "CAUSAL"})
    if poison:
        rows.append({**rows[-1], "timestamp": rows[-1]["timestamp"][:11] + "15:59:00.000", "bid": "999.00", "ask": "999.50"})
    d8 = day.replace("-", "")
    with gzip.open(base / ("underlying_%s.json.gz" % d8), "wt") as fh:
        json.dump({"source": "SYNTHETIC", "bars": bars}, fh)
    with gzip.open(base / ("quotes_%s.csv.gz" % d8), "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


def test_contract_is_valid_and_declares_the_period_policy():
    v = C.validated()
    assert v["valid"] and v["authorizes_data_access"] is False and "SEALED" in C.CONTRACT.notes and C.CONTRACT.search_budget == 3


def test_sealed_days_are_excluded_before_any_read(tmp_path):
    _corpus(tmp_path, "2019-06-03"); _corpus(tmp_path, "2023-03-01")
    assert R.session_days(tmp_path, "SPY") == ["2019-06-03"]
    assert R.session_days(tmp_path, "SPY", last_date="2021-12-31") == ["2019-06-03"]


def test_planted_drift_is_detected_and_the_firewall_holds(tmp_path):
    _corpus(tmp_path, "2019-06-03", drift_per_min=0.02, poison=True)
    art = default_artifact()
    recs = R.replay_session(tmp_path, "SPY", "2019-06-03", artifact=art, out_path=tmp_path / "scans.jsonl")
    allscans = [r for r in recs if r["kind"] == "replay_scan"]
    assert len(allscans) == len(R.SCAN_MINUTES_ET) and all(r["evidence_class"] == "HISTORICAL_DEVELOPMENT_REPLAY" for r in allscans)
    assert allscans[0]["decision"] == "REFUSE" and allscans[0]["why"].startswith("FORECAST")     # 10:00: 30-bar warm-up not yet satisfied
    scans = [r for r in allscans if r.get("forecast")]
    assert len(scans) == len(allscans) - 1
    pol = [r["variants"]["POLICY"] for r in scans if r.get("variants")]
    assert all(v["direction"] == "LONG" for v in pol)                        # upward drift -> LONG label
    trades = [v for v in pol if v["decision"] == "TRADE"]
    assert trades and all(v["pnl"]["net"] > 0 for v in trades)               # the call tracks the drift: gross beats fees
    rev = [r["variants"]["REVERSED_DIRECTION"] for r in scans if r.get("variants")]
    assert all(v["direction"] == "SHORT" for v in rev) and all(v["pnl"]["net"] < 0 for v in rev if v["decision"] == "TRADE")
    # the poison row at 15:59 (after every exit minute) is never used: no entry/exit quote equals it
    assert not any(v.get("exit", {}).get("bid") == 999.0 or v["entry_quote"]["ask"] == 999.5 for r in scans for v in r["variants"].values() if v.get("entry_quote"))
    # realized target and forecast recorded per scan; artifact identity carried
    assert all(r["realized_log_return_15m"] is not None and r["forecast"]["params_hash"] == "ca04fc6e713e1a5c" for r in scans)
    s = EV.summarize(recs)
    assert s["variants"]["POLICY"]["trades"] == len(trades) and s["policy_vs_wait"]["mean_net_per_trade"] > 0
    assert s["policy_vs_reversed_direction"]["mean_diff"] > 0 and s["policy_vs_reversed_direction"]["n_common"] == len(trades)
    assert s["friction"]["friction_total"] > 0 and "artifact_calibration" in s and s["cap_free_counterfactual"]["label"].startswith("COUNTERFACTUAL")
    assert s["direction_label"]["sign_agreement"] == 1.0
    rows = [json.loads(l) for l in (tmp_path / "scans.jsonl").read_text().splitlines()]
    assert len(rows) == len(recs) and all("entry_hash" in r for r in rows)


def test_no_drift_gives_no_edge_and_costs_dominate(tmp_path):
    _corpus(tmp_path, "2019-06-04", drift_per_min=0.0, wiggle=0.03)           # zero-mean sawtooth: no drift, positive variance
    recs = R.replay_session(tmp_path, "SPY", "2019-06-04", artifact=default_artifact())
    scans = [r for r in recs if r.get("variants")]
    assert scans
    for name in ("POLICY", "RANDOM_DIRECTION", "REVERSED_DIRECTION"):
        nets = [r["variants"][name]["pnl"]["net"] for r in scans if r["variants"][name]["decision"] == "TRADE"]
        assert nets and sum(nets) < 0                                          # no drift: spread crossing + fees dominate every variant
    s = EV.summarize(recs)
    assert s["policy_vs_wait"]["mean_net_per_trade"] < 0
