"""Demonstrate the repaired run completing at the admitted run's scale under the
UNCHANGED 1400M cap, on synthetic fixtures. Reads no real market data."""
from __future__ import annotations

import hashlib, json, math, random, resource, sys, time
from datetime import datetime, timedelta
from pathlib import Path


def rss_peak_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def cgroup_path() -> str:
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        parts = line.split(":")
        if len(parts) == 3 and parts[1] == "":
            return parts[2]
    return ""


def cgroup_counters() -> dict:
    """Read the cgroup's own counters BEFORE the process exits.

    A unit started with --collect takes its cgroup away at exit, so anything
    not captured here cannot be verified afterwards."""
    base = Path("/sys/fs/cgroup") / cgroup_path().lstrip("/")
    out = {"cgroup": cgroup_path(), "readable": base.is_dir()}
    for name in ("memory.peak", "memory.current", "memory.max", "memory.events",
                 "memory.events.local", "cgroup.procs"):
        try:
            out[name] = (base / name).read_text().strip()
        except OSError as e:
            out[name] = "unreadable: %s" % e
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc(day, n, seed):
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


def main(n_train, n_val, bars_n, root: Path, out: Path):
    from apex.world_model.exp001b import bars as B, run as R, exchange_calendar as C
    days, k, d0 = [], 0, datetime.fromisoformat("2016-01-04")
    while len(days) < n_train + n_val:
        day = (d0 + timedelta(days=k)).strftime("%Y-%m-%d"); k += 1
        try:
            C.session_bounds(day, require_verified=True); days.append(day)
        except Exception:
            continue
    root.mkdir(parents=True, exist_ok=True)
    fx = {}
    t_gen = time.time()
    for i, day in enumerate(days):
        p = root / ("SYN_%s.json" % day)
        if not p.exists():
            p.write_text(json.dumps(doc(day, bars_n, seed=i + 1)))
        fx[p.name] = {"source_class": "SYNTHETIC_FIXTURE",
                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "generator": "scale_demo"}
    (root / "_PROVENANCE.json").write_text(json.dumps({"fixtures": fx}))
    gen_s = round(time.time() - t_gen, 1)

    def loader(p):
        day = Path(p).stem.replace("SYN_", "")
        return B.load_session(Path(p), declared_class="SYNTHETIC_FIXTURE", fixture_root=root,
                              symbol="SPY", session_date=day)

    out.mkdir(parents=True, exist_ok=True)
    sessions = {"train": [root / ("SYN_%s.json" % d) for d in days[:n_train]],
                "validation": [root / ("SYN_%s.json" % d) for d in days[n_train:]],
                "evaluation": []}
    t0 = time.time()
    rec = R.run(sessions, ledger_dir=out, session_loader=loader, seed=7)
    elapsed = round(time.time() - t0, 1)
    val = rec.get("validation") or {}
    counters = cgroup_counters()                     # captured BEFORE exit
    outputs = {}
    for f in sorted(out.iterdir()):
        if f.is_file() and f.stat().st_size:
            outputs[f.name] = {"bytes": f.stat().st_size, "sha256": sha256_file(f),
                               "records": sum(1 for _ in open(f)) if f.suffix == ".jsonl" else None}
    fixtures = sorted(root.glob("SYN_*.json"))
    return {"cgroup_counters_before_exit": counters,
            "output_artifacts": outputs,
            "fixture_root": str(root), "fixture_count": len(fixtures),
            "fixture_provenance_sha256": sha256_file(root / "_PROVENANCE.json"),
            "scale": {"train_sessions": n_train, "validation_sessions": n_val,
                      "bars_per_session": bars_n, "fixture_gen_seconds": gen_s},
            "completed": rec.get("status") is not None,
            "status": rec.get("status"),
            "validation_rows": val.get("n"),
            "elapsed_seconds": elapsed,
            "peak_rss_bytes": rss_peak_bytes(),
            "peak_rss_mb": round(rss_peak_bytes() / 1048576, 1),
            "cap_mb": 1400,
            "headroom_mb": round(1400 - rss_peak_bytes() / 1048576, 1),
            "forecasts_written": sum(1 for _ in open(out / "forecasts_validation.jsonl"))
                                 if (out / "forecasts_validation.jsonl").exists() else 0,
            "stages": rec.get("stages")}


if __name__ == "__main__":
    a = sys.argv[1:]
    r = main(int(a[0]), int(a[1]), int(a[2]), Path(a[3]), Path(a[4]))
    print(json.dumps(r, indent=1, sort_keys=True, default=str))
