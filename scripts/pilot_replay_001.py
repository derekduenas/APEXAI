"""Run PILOT-REPLAY-001 over the exposed sessions of the validated corpus. Writes hash-chained scan records and a
summary JSON to --out-dir. Refuses any day after the last exposed date before reading a byte of it."""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.backtest_wb import contract as C, evaluate as EV, replay as R                   # noqa: E402
from apex.pulse_options.inference import default_artifact                               # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/apex-data/history-a/options_history")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit-days", type=int, default=0)
    ap.add_argument("--last-date", default=R.LAST_EXPOSED_DATE)
    a = ap.parse_args(argv)
    if a.last_date > R.LAST_EXPOSED_DATE:
        print(json.dumps({"refused": "SEALED_PERIOD: last_date %s > %s" % (a.last_date, R.LAST_EXPOSED_DATE)})); return 3
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    contract = C.validated()
    (out / "contract.json").write_text(json.dumps({"contract": contract, "declared": C.CONTRACT.__dict__}, indent=1, default=str))
    days = R.session_days(Path(a.root), a.symbol, last_date=a.last_date)
    if a.limit_days:
        days = days[:a.limit_days]
    art = default_artifact()
    ledger = out / "replay_scans.jsonl"
    t0 = time.time()
    all_records = []
    for i, d in enumerate(days):
        recs = R.replay_session(Path(a.root), a.symbol, d, artifact=art, out_path=ledger)
        all_records.extend(recs)
        n_tr = sum(1 for r in recs if r.get("decision") == "TRADE")
        print("%3d/%d %s scans=%d trades=%d elapsed=%.0fs" % (i + 1, len(days), d, len(recs), n_tr, time.time() - t0), flush=True)
    summary = EV.summarize(all_records)
    ru = resource.getrusage(resource.RUSAGE_SELF)
    summary.update(days=days, contract_digest=contract["contract_digest"], artifact=art.describe()["params_hash"], elapsed_s=round(time.time() - t0, 1),
                   max_rss_bytes=ru.ru_maxrss * (1024 if sys.platform != "darwin" else 1), last_date=a.last_date, root=a.root)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: summary[k] for k in ("sessions", "scans", "policy_decisions", "policy_non_trade_reasons", "variants", "policy_vs_wait",
                                               "policy_vs_random_direction", "policy_vs_reversed_direction", "friction", "artifact_calibration",
                                               "direction_label", "cap_free_counterfactual", "elapsed_s", "max_rss_bytes") if k in summary}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
