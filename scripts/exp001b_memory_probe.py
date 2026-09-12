"""EXP001B memory retention probe.

Measures which structures in the registered run loop dominate resident memory,
using SYNTHETIC sessions at the admitted run's scale. Reads no real market data
and never touches the aborted run.
"""
from __future__ import annotations

import gc, hashlib, json, math, random, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def rss_bytes() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def doc(day: str, n: int, seed: int) -> dict:
    rng = random.Random(seed)
    t = datetime.fromisoformat("%sT14:30:00+00:00" % day)
    px, bars = 400.0, []
    for i in range(n):
        r = rng.gauss(0, 3e-4)
        o = px * math.exp(rng.gauss(0, 5e-5)); px = px * math.exp(r)
        bars.append({"event_time_utc": (t + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999,
                     "close": px, "volume": 1000})
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


def main(n_sessions: int, bars_per_session: int, root: Path) -> dict:
    from apex.world_model.exp001b import bars as B, models as M
    from apex.world_model import grader, inference
    from apex.world_model.targets import OutcomeRecord
    from apex.world_model.exp001b.registration import HORIZON
    from apex.world_model.exp001b.run import _usable, _n0_permute

    from apex.world_model.exp001b import exchange_calendar as C
    # only real trading days; the calendar refuses weekends and holidays, and
    # the probe must exercise the same admission path the run does
    days, d0 = [], datetime(2020, 1, 6, tzinfo=timezone.utc)
    k = 0
    while len(days) < n_sessions:
        day = (d0 + timedelta(days=k)).strftime("%Y-%m-%d"); k += 1
        try:
            C.session_bounds(day, require_verified=True)
            days.append(day)
        except Exception:
            continue
    root.mkdir(parents=True, exist_ok=True)
    fx = {}
    for k, day in enumerate(days):
        p = root / ("SYN_%s.json" % day)
        if not p.exists():
            p.write_text(json.dumps(doc(day, bars_per_session, seed=k + 1)))
        fx[p.name] = {"source_class": "SYNTHETIC_FIXTURE",
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "generator": "memory_probe"}
    (root / "_PROVENANCE.json").write_text(json.dumps({"fixtures": fx}))

    marks, gc_ = {}, gc.collect
    gc_(); base = rss_bytes(); marks["baseline"] = base

    # --- stage 1: rows, exactly as run() accumulates them
    rows_all, sessions = [], []
    for day in days:
        p = root / ("SYN_%s.json" % day)
        s = B.load_session(p, declared_class="SYNTHETIC_FIXTURE", fixture_root=root,
                           symbol="SPY", session_date=day)
        rws = B.observable_rows(s)
        tg = B.targets(s, rws)
        us = _usable(rws, tg)
        rows_all.extend(us)
        sessions.extend([s] * len(us))          # <-- the per-row session reference
    gc_(); marks["rows_and_sessions"] = rss_bytes()

    # how much of that is the retained session objects alone
    n_rows = len(rows_all)
    sessions_only = sessions
    sessions = None; gc_()
    marks["after_dropping_sessions"] = rss_bytes()
    sessions = sessions_only                    # put it back so the measurement is honest
    gc_()

    if n_rows < 40:
        return {"error": "too few usable rows to measure", "n_rows": n_rows}

    params = M.fit([r for r, _, _ in rows_all], [y for _, y, _ in rows_all])
    gc_(); marks["after_fit"] = rss_bytes()

    from apex.world_model.exp001b.registration import M0, M1
    now = time.time()
    f0, f1, sealed = [], [], []
    for r, y, tk in rows_all:
        iid = "%s|%s|%d" % ("PROBE", r["event_time"], r["i"])
        ih = hashlib.sha256(json.dumps({k: r[k] for k in ("event_time", "features", "close")},
                                       sort_keys=True).encode()).hexdigest()[:16]
        f0.append(M.forecast(M0["id"], params, r, input_id=iid, input_hash=ih, creation_time=now))
        f1.append(M.forecast(M1["id"], params, r, input_id=iid, input_hash=ih, creation_time=now))
        sealed.append(ih)                       # stand-in for the chain entry hash
    gc_(); marks["after_forecasts"] = rss_bytes()

    g0, g1 = [], []
    for a, b, (r, y, tk) in zip(f0, f1, rows_all):
        oc = OutcomeRecord(world_id="corpus", world_hash="PROBE", subject="SPY", step=r["i"],
                           horizon=HORIZON, target_value=y, outcome_known_time=tk)
        g0.append(grader.grade(a, oc, grading_time=tk + 1.0))
        g1.append(grader.grade(b, oc, grading_time=tk + 1.0))
    gc_(); marks["after_gradings"] = rss_bytes()

    ys = [y for _, y, _ in rows_all]
    yp = _n0_permute(ys, 7)
    g0n, g1n = [], []
    for a, b, (r, _, tk), y in zip(f0, f1, rows_all, yp):
        oc = OutcomeRecord(world_id="corpus", world_hash="PROBE|N0", subject="SPY", step=r["i"],
                           horizon=HORIZON, target_value=y, outcome_known_time=tk)
        g0n.append(grader.grade(a, oc, grading_time=tk + 1.0))
        g1n.append(grader.grade(b, oc, grading_time=tk + 1.0))
    gc_(); marks["after_null_gradings"] = rss_bytes()
    peak = rss_bytes()

    def d(a, b): return marks[b] - marks[a]
    per_row = {
        "rows_plus_sessions": d("baseline", "rows_and_sessions"),
        "sessions_alone": marks["rows_and_sessions"] - marks["after_dropping_sessions"],
        "forecasts_f0_f1_sealed": d("after_fit", "after_forecasts"),
        "gradings_g0_g1": d("after_forecasts", "after_gradings"),
        "null_gradings_g0n_g1n": d("after_gradings", "after_null_gradings"),
    }
    return {"n_sessions": n_sessions, "bars_per_session": bars_per_session, "n_usable_rows": n_rows,
            "marks_bytes": marks, "peak_bytes": peak,
            "attributed_bytes": per_row,
            "bytes_per_row": {k: round(v / n_rows, 1) for k, v in per_row.items()},
            "total_attributed": sum(per_row.values())}


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 390
    out = main(n, bars, Path(sys.argv[3] if len(sys.argv) > 3 else "/tmp/exp001b_probe_fixtures"))
    print(json.dumps(out, indent=1, sort_keys=True))
