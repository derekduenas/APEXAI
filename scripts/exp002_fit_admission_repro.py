"""Reproduce review finding 1 on a given checkout (PYTHONPATH decides which):
historical fitting vs the qualified tournament's admission, on a disposable
fixture that carries rows with rv_30 == 0 (< RV_FLOOR). Prints one JSON record."""
import json, math, random, sys, tempfile, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from apex.world_model.exp001b import bars as B, exchange_calendar as C
from apex.world_model.exp002 import historical as H2
from apex.world_model.exp002.run import _admit, tournament
from apex.world_model.exp002.registration import RV_FLOOR

FIT = ["2017-03-01", "2017-03-02", "2017-03-03", "2017-03-06", "2017-03-07"]
DEV = ["2019-06-03", "2019-06-04", "2019-06-05", "2019-06-06"]
OBS = ["2020-06-01", "2020-06-02", "2020-06-03"]
FLAT = {FIT[0]: (120, 60)}

def session(day, seed):
    b = C.session_bounds(day, require_verified=True)
    t0, minutes = datetime.fromtimestamp(b["open_utc"], timezone.utc), int(b["regular_minutes"])
    rng = random.Random(seed); px, bars, last = 400.0, [], 0.0; fl = FLAT.get(day)
    for i in range(minutes):
        r = 0.0 * last + rng.gauss(0, 3e-4); last = r
        if fl and fl[0] <= i < fl[0] + fl[1]:
            r = 0.0
        o = px * math.exp(rng.gauss(0, 5e-5)); px = px * math.exp(r)
        bars.append({"event_time_utc": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999, "close": px, "volume": 1000})
    return {"source": "alpaca_sip_raw_1m", "bars": bars}

tmp = Path(tempfile.mkdtemp()); paths = {}
for i, d in enumerate(FIT + DEV + OBS):
    p = tmp / ("SPY_%s.json" % d); p.write_text(json.dumps(session(d, 100 + i))); paths[d] = p

def load(p):
    p = Path(p); day = p.stem.split("_")[1]
    raw = p.read_bytes()
    return B.session_from_doc(json.loads(raw), p, raw, {"sha256": "repro", "restricted_use": "repro"},
                              symbol="SPY", session_date=day)

sbp = {"fit": [paths[d] for d in FIT], "development": [paths[d] for d in DEV], "observed": [paths[d] for d in OBS]}
fit_usable, _ = H2._rows_for(sbp["fit"], load)
dev_usable, _ = H2._rows_for(sbp["development"], load)
below = sum(1 for r, _, _ in fit_usable if r["features"]["rv_30"] < RV_FLOOR)
admitted, refused = _admit(fit_usable)
rec = {"checkout": sys.argv[1], "fit_usable_rows": len(fit_usable), "below_rv_floor_in_usable": below,
       "qualified_admitted_rows": len(admitted), "qualified_refused_rv_floor": refused}
q = tournament(fit_usable, dev_usable, bootstrap_resamples=20)
rec["tournament"] = {"status": q["status"], "params_hash": q.get("fit", {}).get("params_hash"),
                     "n_train": q.get("fit", {}).get("n_train"), "refusal": q.get("refusal")}
try:
    h = H2.run(sbp, ledger_dir=tmp / "led", session_loader=load)
    adm = next((s for s in h["stages"] if s["stage"] == "admission:fit"), {})
    rec["historical"] = {"status": h["status"], "params_hash": h.get("fit", {}).get("params_hash"),
                         "n_train": h.get("fit", {}).get("n_train"), "refusal": h.get("refusal"),
                         "admission_fit_stage": adm, "scientific_status": h.get("scientific_status"),
                         "execution": h.get("execution")}
except Exception as e:
    rec["historical"] = {"exception": "%s: %s" % (type(e).__name__, str(e)[:300]), "traceback": traceback.format_exc()[-1500:]}
hist = rec["historical"]
rec["fit_admission_consistent"] = (hist.get("params_hash") is not None and hist.get("params_hash") == rec["tournament"]["params_hash"]
                                   and hist.get("n_train") == len(admitted))
print(json.dumps(rec, indent=1, default=str))
