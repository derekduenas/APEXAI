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


# ------------------------------------------------------------------ PILOT-REPLAY-002: the FULL_FUNNEL variant inside the replay
class _PlantedArtifact:
    """The frozen artifact with its LOCATION replaced by a planted value (a fixture, labelled): tests the funnel's plumbing, not the artifact."""

    def __init__(self, location: float):
        self._a = default_artifact(); self.location_value = location

    def forecast(self, snapshot, *, created_epoch, direction_signal=None):
        f = self._a.forecast(snapshot, created_epoch=created_epoch, direction_signal=direction_signal)
        return {**f, "location": self.location_value, "model_id": "PLANTED_LOCATION_FIXTURE", "params_hash": "PLANTED", "direction_signal": direction_signal}


def test_full_funnel_on_planted_drift(tmp_path):
    from apex.backtest_wb import contract2 as C2, funnel as FN
    assert C2.validated()["contract_digest"]
    days = ["2019-06-03", "2019-06-04", "2019-06-05", "2019-06-06"]
    for d in days:
        _corpus(tmp_path, d, drift_per_min=0.02, wiggle=0.03)                     # upward drift + variance; the call tracks the drift
    runner = FN.FunnelRunner(window_sessions=20, n_paths=300, seed=5)
    art = _PlantedArtifact(+0.004)                                               # planted +40 bps location per 15 minutes
    recs = []
    for d in days:
        recs.extend(R.replay_session(tmp_path, "SPY", d, artifact=art, out_path=tmp_path / "scans.jsonl", funnel=runner))
    scans = [r for r in recs if r.get("variants")]
    ff = [r["variants"]["FULL_FUNNEL"] for r in scans]
    assert all("trace" in v and v["decision"] in ("TRADE", "WAIT", "TRADE_UNRESOLVED") for v in ff)
    first_day = [r["variants"]["FULL_FUNNEL"] for r in scans if r["day"] == days[0]]
    assert all(v["decision"] == "WAIT" and "INSUFFICIENT_HISTORY" in v["why"] for v in first_day)   # no prior session to fit on
    later = [r["variants"]["FULL_FUNNEL"] for r in scans if r["day"] in days[2:]]
    trades = [v for v in later if v["decision"] == "TRADE"]
    assert trades, [v["why"] for v in later][:5]
    assert all(v["contract"]["right"] == "CALL" and v["direction"] == "LONG" for v in trades)     # planted upward location -> calls
    assert all(v["pnl"]["net"] > 0 for v in trades)                                               # the corpus call tracks the drift
    assert all(v["rule_id"].startswith("FULL_FUNNEL_V1") and v["trace"]["expression_war"]["table"][0]["label"] == "WAIT" for v in trades)
    assert runner.fits >= 2 and all(f.get("status") == "READY" or f.get("status").startswith("INSUFFICIENT_HISTORY") for f in runner.fit_log)
    s = EV.summarize(recs)
    assert s["variants"]["FULL_FUNNEL"]["trades"] == len(trades)
    assert s["full_funnel_vs_policy"]["n_common_scans"] >= 1 and s["full_funnel_vs_policy"]["population"].startswith("COMMON_SCANS")
    assert s["full_funnel_vs_wait_per_scan"]["mean_diff_per_scan"] > 0 and s["full_funnel_vs_wait"]["label"].startswith("SUPPLEMENTARY")
    assert "INSUFFICIENT_HISTORY" not in s["full_funnel_non_trade_reasons"] or s["full_funnel_non_trade_reasons"]["PRIME_ABSTAIN"] >= 1
    assert s["full_funnel_rights"] == {"CALL": len(trades)} and s["full_funnel_coverage"]["funnel_trades"] == len(trades)
    rows = [json.loads(l) for l in (tmp_path / "scans.jsonl").read_text().splitlines()]
    assert all("entry_hash" in r for r in rows) and len(rows) == len(recs)


def test_per_scan_population_keeps_wait_as_zero_and_excludes_unresolved():
    """Reviewer fixture: three scans. Per-trade overlap alone says the funnel is WORSE; the contract's per-scan estimand says it is BETTER."""
    def scan(day, i, pol, ff):
        return {"kind": "replay_scan", "day": day, "scan": i, "forecast": {"location": 0.0}, "variants": {"POLICY": pol, "FULL_FUNNEL": ff}}
    trade = lambda net: {"decision": "TRADE", "pnl": {"net": net, "gross": net, "fees": 0.0}, "contract": {"right": "CALL"}}
    wait = {"decision": "WAIT"}
    scans = [scan("2019-06-03", 1, trade(10.0), trade(8.0)),        # both trade: funnel -2 on the overlap
             scan("2019-06-03", 2, trade(-20.0), wait),             # policy loses 20, funnel legitimately waits (0)
             scan("2019-06-03", 3, wait, trade(0.0))]                # funnel trades flat where policy waited
    r = EV.paired_per_scan(scans, "FULL_FUNNEL", "POLICY", draws=50)
    assert r["n_common_scans"] == 3 and r["mean_diff_per_scan"] == pytest.approx((8 - 10 - 0 + 20 + 0 - 0) / 3)      # = +6 per scan
    assert r["pair_census"] == {"TRADE/TRADE": 1, "WAIT/TRADE": 1, "TRADE/WAIT": 1} and r["excluded"] == {"FULL_FUNNEL": {}, "POLICY": {}}
    from apex.worldmodel_wb.tournament import paired_comparison
    trades_only = paired_comparison({"2019-06-03:1": 8.0, "2019-06-03:3": 0.0}, {"2019-06-03:1": 10.0, "2019-06-03:2": -20.0})
    assert trades_only["mean_diff"] == -2.0                                                                            # the wrong population's answer
    # unresolved trades and refusals are EXCLUDED and counted, never scored as zero
    scans.append(scan("2019-06-04", 1, trade(5.0), {"decision": "TRADE_UNRESOLVED", "pnl": None}))
    scans.append(scan("2019-06-04", 2, {"decision": "REFUSE"}, trade(5.0)))
    r2 = EV.paired_per_scan(scans, "FULL_FUNNEL", "POLICY", draws=50)
    assert r2["n_common_scans"] == 3 and r2["excluded"] == {"FULL_FUNNEL": {"TRADE_UNRESOLVED": 1}, "POLICY": {"REFUSE": 1}}
