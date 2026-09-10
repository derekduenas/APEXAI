"""Reproduce the reviewer's findings against the 2eaab8f6 boundary BEFORE the repair.
Run from a checkout whose apex/options_pilot is the OLD package. Prints one line per finding."""
import json
import sys
import tempfile
import threading
from pathlib import Path

from apex.options_pilot import boundary as B, ledger as L, records as R, session as S

SYM = "SPY"; AS_OF = "2026-09-10T14:00:00Z"; T0 = 1_789_000_000.0
CHAIN = [{"expiration": "2026-10-09", "strike": k, "right": r} for k in (640.0, 645.0, 650.0) for r in ("CALL", "PUT")]


def forecast(**o):
    f = {"symbol": SYM, "target": R.FORECAST_TARGET, "units": R.FORECAST_UNITS, "horizon_minutes": 15,
         "family": "STUDENT_T", "location": 1.2e-5, "scale": 3.1e-4, "nu": 6.38, "model_id": "X",
         "model_hash": "9155024f51825d13487cdc035432d85b357d22e3", "params_hash": "ca04fc6e713e1a5c" * 2,
         "input_cutoff_utc": "2026-09-10T13:59:00Z", "created_utc": "2026-09-10T13:59:30Z", "direction_signal": "LONG",
         "validation_status": "NOT_VALIDATED"}
    f.update(o); return f


def quote(c, ts=T0 - 1.0, size=12):
    return {**c, "bid": 2.4, "ask": 2.5, "bid_size": 9, "ask_size": size, "timestamp_epoch": ts}


def src(**o):
    s = {"forecast_fn": lambda s, t: forecast(), "signal_fn": lambda s, t: "LONG", "chain_fn": lambda s, t: CHAIN,
         "spot_fn": lambda s, t: 646.3, "quote_fn": lambda c: quote(c), "risk_fn": lambda p: {"approved": True},
         "clock_fn": lambda: T0}
    s.update(o); return s


out = {}
d = Path(tempfile.mkdtemp())
# F1: NaN provider timestamp fills
led = d / "f1.jsonl"
r = S.scan(led, symbol=SYM, as_of=AS_OF, **src(quote_fn=lambda c: quote(c, ts=float("nan"))))
fill = L.read_all(led)[r["fill_receipt"]["seq"] - 1]
out["F1_nan_timestamp"] = {"status": fill["status"], "line_has_NaN": "NaN" in led.read_text()}
# F2: caller-supplied risk approved=True is authorization
led = d / "f2.jsonl"
r = S.scan(led, symbol=SYM, as_of=AS_OF, **src(risk_fn=lambda p: {"approved": True}))
out["F2_self_attested_risk"] = {"status": L.read_all(led)[r["fill_receipt"]["seq"] - 1]["status"]}
# F3: string time check accepts a malformed instant ending in Z
led = d / "f3.jsonl"
try:
    r = S.scan(led, symbol=SYM, as_of=AS_OF, **src(forecast_fn=lambda s, t: forecast(input_cutoff_utc="2026-09-10 25:99:00Z", created_utc="2026-09-10 25:99:01Z")))
    out["F3_malformed_time_endswith_Z"] = {"status": L.read_all(led)[r["fill_receipt"]["seq"] - 1]["status"]}
except Exception as e:
    out["F3_malformed_time_endswith_Z"] = {"refused": type(e).__name__ + ": " + str(e)[:80]}
# F4: now_epoch sampled before quote_fn: a provider that stamps at request and takes 20 s looks fresh
led = d / "f4.jsonl"
clock = {"t": T0}
def slow(c):
    q = quote(c, ts=clock["t"] - 1.0); clock["t"] += 20.0; return q
r = S.scan(led, symbol=SYM, as_of=AS_OF, **src(quote_fn=slow, clock_fn=lambda: clock["t"]))
fill = L.read_all(led)[r["fill_receipt"]["seq"] - 1]
out["F4_freshness_before_receipt"] = {"status": fill["status"], "why": fill.get("why")}
# F5: non-atomic duplicate check: N workers past the check before any commits -> N fills
led = d / "f5.jsonl"
fr = B.record_forecast(led, forecast())
ir = B.record_intent(led, forecast_receipt=fr, intent={"expression": "LONG_CALL", "action": "BUY", "quantity": 1,
                     "contract": {"symbol": SYM, "expiration": "2026-10-09", "strike": 645.0, "right": "CALL"}, "risk": {"approved": True}})
n = 6; bar = threading.Barrier(n); res = []; errs = []
def qf(c):
    bar.wait(timeout=10); return quote(c)
def w():
    try: res.append(B.execute_intent(led, intent_receipt=ir, quote_fn=qf, now_epoch=T0))
    except B.BoundaryRefused as e: errs.append(str(e)[:40])
ts = [threading.Thread(target=w) for _ in range(n)]; [t.start() for t in ts]; [t.join(30) for t in ts]
out["F5_non_atomic_duplicate"] = {"fills_on_disk": [x.get("kind") for x in L.read_all(led)].count("pilot_fill"), "refused": len(errs)}
# F6: bool size: True < 1 is False -> FILLED on ask_size=True
led = d / "f6.jsonl"
r = S.scan(led, symbol=SYM, as_of=AS_OF, **src(quote_fn=lambda c: quote(c, size=True)))
out["F6_bool_size"] = {"status": L.read_all(led)[r["fill_receipt"]["seq"] - 1]["status"]}
# F7: verify_receipt verifies one record, not its predecessors
led = d / "f7.jsonl"
fr = B.record_forecast(led, forecast()); fr2 = B.record_forecast(led, forecast(location=2e-5))
lines = led.read_text().splitlines(); rec = json.loads(lines[0]); rec["scale"] = 9e-4; rec["entry_hash"] = L.recompute_entry_hash(rec)
lines[0] = json.dumps(rec, sort_keys=True); led.write_text("\n".join(lines) + "\n")
try:
    L.verify_receipt(led, fr2, expected_kind="pilot_forecast"); out["F7_single_record_verify"] = {"seq2_verifies_despite_altered_seq1": True}
except Exception as e:
    out["F7_single_record_verify"] = {"refused": str(e)[:60]}
print(json.dumps(out, indent=1, sort_keys=True))
