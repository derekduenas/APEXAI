"""Representative EXP-004 records on the predeclared synthetic fixtures: one
successful classification and one integrity refusal. Synthetic only; no market
data. Run: python3 scripts/exp004_synthetic_records.py <out_dir>"""
import copy
import json
import sys
from pathlib import Path

from apex.world_model.exp004 import run as R
from tests import exp004_fixtures as X


def main(out_dir: str) -> int:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    fit, dev = X.fit_sessions(), X.dev_sessions_years()
    dev2 = copy.deepcopy(dev)
    day = dev2[3]["session_date"]; bars = X.build_bars(day, X.SEEDS["dev"] + 100 + 3)
    bars[200]["high"] = bars[200]["close"] - 0.01           # pressure-only refusals on ten rows
    dev2[3] = X.session_from_bars(day, bars)
    ok = R.tournament(fit, dev2, bootstrap_resamples=2000, unregistered_inference_override=True)
    broken = [X.session_from_bars(s["session_date"], [dict(b, open=b["high"] + 1) for b in X.build_bars(s["session_date"], 1)])
              for s in dev[:2]]
    bad = R.tournament(fit, broken, bootstrap_resamples=50, unregistered_inference_override=True)
    for name, rec in (("exp004_synthetic_successful_record.json", ok), ("exp004_synthetic_refused_record.json", bad)):
        rec["NOTE"] = ("SYNTHETIC FIXTURE (seeds %s): establishes implementation behaviour only; not market signal, "
                       "size or power" % X.SEEDS)
        (out / name).write_text(json.dumps(json.loads(R.strict_json(rec)), indent=1, sort_keys=True) + "\n")
    print(json.dumps({"ok_status": ok["status"], "ok_flags": ok["development"]["classification"].get("flags"),
                      "ok_n_rows": ok["development"]["n_rows"], "ok_theta": ok["development"]["theta_F_c_in_C"]["value"],
                      "bad_status": bad["status"], "bad_refusal": bad["refusal"]["detail"][:80],
                      "registration_hash": ok["registration_hash"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
