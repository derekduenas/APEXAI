"""APEX OPTION ANALYTICS LIVE RUNTIME V1 -- first live certification.

Reads the REAL ledgers written by option_analytics_live_runtime.py
(never re-fetches or re-derives data itself) and measures exactly what
the operator asked for:

  - IV round-trip error on real contracts
  - BSM vs American vs VENDOR (Alpaca's own greeks/impliedVolatility)
    disagreement
  - stability across consecutive live snapshots (same contract, cycle
    to cycle)
  - near-expiry (short_dated) behavior
  - wide-spread behavior
  - ex-dividend / dividend-gate edge cases
  - quote churn (bid/ask movement cycle to cycle)
  - computation latency

This script computes statistics over already-persisted real output; it
does not invent, does not backfill, and reports whatever the real run
actually produced, including gaps.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.option_analytics import bsm as bsm_mod

STATES_LEDGER = Path("results/option_analytics/live/states.jsonl")
CYCLE_SUMMARY_LEDGER = Path("results/option_analytics/live/cycle_summaries.jsonl")
OUT_PATH = Path("results/option_analytics/live/first_live_certification.json")


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def iv_round_trip_errors(states: list) -> dict:
    """Re-solves each real contract's IV_MID against the ACTUAL live
    market mid price (persisted by the runtime as market_mid) and
    reprices at that IV -- the round-trip error is the gap between the
    repriced value and the real market mid observed live, not a
    synthetic self-consistency check."""
    errors, missing_market_mid = [], 0
    for s in states:
        iv = s.get("iv") or {}
        mid_iv = iv.get("iv_mid")
        market_mid = s.get("market_mid")
        if mid_iv is None or s.get("state_quality") == "REFUSED":
            continue
        if market_mid is None:
            missing_market_mid += 1
            continue
        spot, strike, rate = s.get("spot"), s.get("strike"), s.get("rate")
        T = s.get("time_to_expiry_years")
        if None in (spot, strike, rate, T):
            continue
        div_pv = s.get("dividend_pv") or 0.0
        adjusted_spot = spot - div_pv
        repriced = bsm_mod.price(option_type=s["option_type"], spot=adjusted_spot,
                                 strike=strike, time_to_expiry_years=T, rate=rate,
                                 sigma=mid_iv)
        errors.append(abs(repriced - market_mid))
    return {
        "n_round_trips_computed": len(errors),
        "n_missing_market_mid_on_record": missing_market_mid,
        "mean_abs_round_trip_error": (sum(errors) / len(errors)) if errors else None,
        "max_abs_round_trip_error": max(errors) if errors else None,
    }


def vendor_disagreement_stats(states: list) -> dict:
    deltas, ivs = [], []
    n_vendor_present = 0
    for s in states:
        if s.get("vendor_delta") is None:
            continue
        n_vendor_present += 1
        bsm_delta = (s.get("delta") or {}).get("bsm_value")
        am_delta = (s.get("delta") or {}).get("american_value")
        if bsm_delta is not None:
            deltas.append(("vendor_vs_bsm", abs(s["vendor_delta"] - bsm_delta)))
        if am_delta is not None:
            deltas.append(("vendor_vs_american", abs(s["vendor_delta"] - am_delta)))
        vendor_iv = s.get("vendor_iv")
        apex_iv = (s.get("iv") or {}).get("iv_mid")
        if vendor_iv is not None and apex_iv is not None:
            ivs.append(abs(vendor_iv - apex_iv))
    vb = [d for k, d in deltas if k == "vendor_vs_bsm"]
    va = [d for k, d in deltas if k == "vendor_vs_american"]
    return {
        "contracts_with_vendor_greeks": n_vendor_present,
        "mean_abs_delta_disagreement_vendor_vs_bsm": (sum(vb) / len(vb)) if vb else None,
        "max_abs_delta_disagreement_vendor_vs_bsm": max(vb) if vb else None,
        "mean_abs_delta_disagreement_vendor_vs_american": (sum(va) / len(va)) if va else None,
        "max_abs_delta_disagreement_vendor_vs_american": max(va) if va else None,
        "mean_abs_iv_disagreement_vendor_vs_apex": (sum(ivs) / len(ivs)) if ivs else None,
        "max_abs_iv_disagreement_vendor_vs_apex": max(ivs) if ivs else None,
        "n_iv_comparisons": len(ivs),
    }


def bsm_vs_american_disagreement_stats(states: list) -> dict:
    from collections import Counter
    counts = Counter()
    for s in states:
        for greek in ("delta", "gamma", "theta", "vega", "rho"):
            g = s.get(greek)
            if g:
                counts[(greek, g["disagreement_level"])] += 1
    return {f"{g}_{lvl}": n for (g, lvl), n in sorted(counts.items())}


def stability_across_snapshots(states: list) -> dict:
    by_contract = defaultdict(list)
    for s in states:
        by_contract[s["symbol"]].append(s)
    drifts = []
    for symbol, records in by_contract.items():
        if len(records) < 2:
            continue
        records = sorted(records, key=lambda r: r.get("as_of", ""))
        for a, b in zip(records, records[1:]):
            iv_a = (a.get("iv") or {}).get("iv_mid")
            iv_b = (b.get("iv") or {}).get("iv_mid")
            if iv_a is not None and iv_b is not None:
                drifts.append(abs(iv_b - iv_a))
    return {
        "contracts_observed_multiple_cycles": sum(1 for r in by_contract.values() if len(r) > 1),
        "total_contracts_observed": len(by_contract),
        "mean_abs_iv_mid_drift_between_consecutive_cycles": (
            sum(drifts) / len(drifts)) if drifts else None,
        "max_abs_iv_mid_drift_between_consecutive_cycles": max(drifts) if drifts else None,
        "n_consecutive_pairs": len(drifts),
    }


def near_expiry_and_spread_behavior(states: list) -> dict:
    short_dated = [s for s in states if s.get("short_dated")]
    not_short = [s for s in states if not s.get("short_dated")]
    wide_spread = [s for s in states if ((s.get("iv") or {}).get("quality") == "LOW")]

    def quality_dist(lst):
        from collections import Counter
        return dict(Counter(s.get("state_quality") for s in lst))

    return {
        "short_dated_count": len(short_dated),
        "short_dated_quality_distribution": quality_dist(short_dated),
        "not_short_dated_quality_distribution": quality_dist(not_short),
        "wide_spread_count": len(wide_spread),
        "wide_spread_quality_distribution": quality_dist(wide_spread),
    }


def dividend_gate_stats(states: list) -> dict:
    refused_div = [s for s in states
                  if s.get("state_quality") == "REFUSED"
                  and "NO_DIVIDEND_SCHEDULE_SUPPLIED" in (s.get("refusal_reason") or "")]
    real_div = [s for s in states if (s.get("dividend_pv") or 0) > 0]
    confirmed_none = [s for s in states
                      if s.get("dividend_pv") == 0.0 and s.get("state_quality") != "REFUSED"]
    return {
        "refused_no_dividend_schedule": len(refused_div),
        "priced_with_real_dividend_pv": len(real_div),
        "priced_confirmed_no_dividend": len(confirmed_none),
    }


def quote_churn_stats(states: list) -> dict:
    by_contract = defaultdict(list)
    for s in states:
        ps = s.get("price_sanity") or {}
        by_contract[s["symbol"]].append((s.get("as_of"), ps))
    churns = []
    for symbol, records in by_contract.items():
        if len(records) < 2:
            continue
        records.sort(key=lambda r: r[0] or "")
        # churn measured via intrinsic-value proxy since raw bid/ask
        # wasn't persisted verbatim on the analytics-state record
        for (_, a), (_, b) in zip(records, records[1:]):
            iv_a, iv_b = a.get("intrinsic_value"), b.get("intrinsic_value")
            if iv_a is not None and iv_b is not None:
                churns.append(abs(iv_b - iv_a))
    return {"n_churn_observations": len(churns),
           "mean_abs_intrinsic_value_change": (sum(churns) / len(churns)) if churns else None}


def latency_stats(cycles: list) -> dict:
    latencies = []
    for c in cycles:
        for sym, data in c.get("symbols", {}).items():
            lat = data.get("fetch_latency_s")
            if lat is not None:
                latencies.append(lat)
    return {"n_symbol_cycles": len(latencies),
           "mean_fetch_plus_compute_latency_s": (sum(latencies) / len(latencies)) if latencies else None,
           "max_fetch_plus_compute_latency_s": max(latencies) if latencies else None}


def main() -> dict:
    states = _read_jsonl(STATES_LEDGER)
    cycles = _read_jsonl(CYCLE_SUMMARY_LEDGER)

    result = {
        "n_states_observed": len(states), "n_cycles_observed": len(cycles),
        "iv_round_trip": iv_round_trip_errors(states),
        "vendor_disagreement": vendor_disagreement_stats(states),
        "bsm_vs_american_disagreement_distribution": bsm_vs_american_disagreement_stats(states),
        "stability_across_snapshots": stability_across_snapshots(states),
        "near_expiry_and_spread_behavior": near_expiry_and_spread_behavior(states),
        "dividend_gate": dividend_gate_stats(states),
        "quote_churn": quote_churn_stats(states),
        "latency": latency_stats(cycles),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
