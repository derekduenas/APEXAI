"""Run PILOT-REPLAY-002: the FULL_FUNNEL variant alongside POLICY/controls on the exposed SPY corpus sessions."""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.backtest_wb import contract2 as C2, evaluate as EV, funnel as F, replay as R          # noqa: E402
from apex.pulse_options.inference import default_artifact                                       # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/apex-data/history-a/options_history")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit-days", type=int, default=0)
    ap.add_argument("--n-paths", type=int, default=2000)
    a = ap.parse_args(argv)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    contract = C2.validated()
    (out / "contract.json").write_text(json.dumps({"contract": contract, "declared": C2.CONTRACT.__dict__}, indent=1, default=str))
    days = R.session_days(Path(a.root), a.symbol)
    if a.limit_days:
        days = days[:a.limit_days]
    art = default_artifact()
    funnel = F.FunnelRunner(n_paths=a.n_paths)
    ledger = out / "replay_scans.jsonl"
    t0 = time.time(); all_records = []
    for i, d in enumerate(days):
        recs = R.replay_session(Path(a.root), a.symbol, d, artifact=art, out_path=ledger, funnel=funnel)
        all_records.extend(recs)
        n_ff = sum(1 for r in recs if (r.get("variants") or {}).get("FULL_FUNNEL", {}).get("decision") == "TRADE")
        n_p = sum(1 for r in recs if r.get("decision") == "TRADE")
        print("%3d/%d %s policy_trades=%d funnel_trades=%d fit=%s elapsed=%.0fs" % (i + 1, len(days), d, n_p, n_ff, (funnel.fit_log[-1].get("status") if funnel.fit_log else "-"), time.time() - t0), flush=True)
    summary = EV.summarize(all_records)
    ru = resource.getrusage(resource.RUSAGE_SELF)
    summary.update(study_id="PILOT-REPLAY-002", days=days, contract_digest=contract["contract_digest"], fits=funnel.fits, fit_log=funnel.fit_log,
                   elapsed_s=round(time.time() - t0, 1), max_rss_bytes=ru.ru_maxrss * (1024 if sys.platform != "darwin" else 1), n_paths=a.n_paths)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    keys = ("sessions", "scans", "variants", "full_funnel_vs_policy", "full_funnel_vs_wait", "full_funnel_non_trade_reasons", "full_funnel_rights",
            "full_funnel_coverage", "policy_vs_wait", "fits", "elapsed_s", "max_rss_bytes")
    print(json.dumps({k: summary[k] for k in keys if k in summary}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
