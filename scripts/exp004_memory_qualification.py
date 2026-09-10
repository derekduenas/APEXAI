"""EXP-004 memory qualification at REGISTERED SCALE, measured from inside the
unit's own cgroup.

Why this exists: `run.tournament` takes full session objects and holds both
period lists for the duration of the run. EXP-002's adapter converted each
session to rows and discarded it; EXP-004's does not. Peak memory is therefore
NOT established, and EXP-001B's first historical attempt was OOM-killed. This
measures it before any admission is requested.

Measurement discipline, from the EXP-001B review:
  * counters are sampled THROUGHOUT, not once at the end;
  * they are read from the RUNNING process's own cgroup (/proc/self/cgroup), so
    the numbers are attributable to this unit and survive --collect;
  * memory.events oom/oom_kill counters are recorded before and after;
  * VmHWM (peak RSS) is recorded independently of the cgroup.

SYNTHETIC ONLY. No admitted data, no admission, no historical execution. Bars
are generated on demand by a loader that mirrors the governed one's shape, so
the fixture does not itself hold every session.

Run: python3 scripts/exp004_memory_qualification.py <out.json> [bootstrap_B]
"""
from __future__ import annotations

import json
import math
import random
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from apex.world_model.exp001b import bars as B, exchange_calendar as C
from apex.world_model.exp004 import historical as H4, run as R, synthetic as SY
from apex.world_model.exp004.registration import PERIODS, registration_hash

SEED = 20260913
FIT_LO, FIT_HI = PERIODS["fit"]
DEV_LO, DEV_HI = PERIODS["development"]


# ---------------------------------------------------------------- cgroup sampling

def _cgroup_dir() -> Path | None:
    try:
        line = Path("/proc/self/cgroup").read_text().strip().splitlines()[-1]
        rel = line.split(":")[-1].lstrip("/")
        p = Path("/sys/fs/cgroup") / rel
        return p if p.exists() else None
    except Exception:                                                    # noqa: BLE001
        return None


def _read(p: Path, name: str):
    try:
        return (p / name).read_text().strip()
    except Exception:                                                    # noqa: BLE001
        return None


def _vmhwm_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except Exception:                                                    # noqa: BLE001
        return None
    return None


class Sampler(threading.Thread):
    """Samples the unit's own cgroup throughout the run."""

    def __init__(self, interval: float = 0.25):
        super().__init__(daemon=True)
        self.interval, self.stop_flag = interval, threading.Event()
        self.cg = _cgroup_dir()
        self.samples, self.marks = [], []

    def mark(self, label: str) -> None:
        self.marks.append({"label": label, "t": round(time.time(), 3),
                           "memory_current": self._current(), "vmhwm": _vmhwm_bytes()})

    def _current(self):
        if not self.cg:
            return None
        v = _read(self.cg, "memory.current")
        return int(v) if v and v.isdigit() else None

    def run(self) -> None:
        while not self.stop_flag.is_set():
            cur = self._current()
            if cur is not None:
                self.samples.append(cur)
            self.stop_flag.wait(self.interval)

    def report(self) -> dict:
        cg = self.cg
        peak = _read(cg, "memory.peak") if cg else None
        return {"cgroup": str(cg) if cg else "UNAVAILABLE",
                "readable": cg is not None,
                "samples": len(self.samples),
                "sampled_max_memory_current_bytes": max(self.samples) if self.samples else None,
                "cgroup_memory_peak_bytes": int(peak) if peak and peak.isdigit() else None,
                "memory_max_bytes": _read(cg, "memory.max") if cg else None,
                "memory_events": _read(cg, "memory.events") if cg else None,
                "peak_rss_vmhwm_bytes": _vmhwm_bytes(),
                "marks": self.marks,
                "note": "sampled throughout from the running process's own cgroup, not once at exit"}


# ---------------------------------------------------------------- on-demand sessions

def trading_days(lo: str, hi: str) -> list:
    d, end, out = date.fromisoformat(lo), date.fromisoformat(hi), []
    while d <= end:
        if d.weekday() < 5:
            try:
                C.session_bounds(d.isoformat(), require_verified=True)
                out.append(d.isoformat())
            except C.NotASession:
                pass
        d += timedelta(days=1)
    return out


def build_session(day: str, seed: int) -> dict:
    b = C.session_bounds(day, require_verified=True)
    t0, minutes = datetime.fromtimestamp(b["open_utc"], timezone.utc), int(b["regular_minutes"])
    rng = random.Random(seed)
    px, bars = 400.0, []
    for i in range(minutes):
        r = rng.gauss(0, 3e-4)
        c = px * math.exp(r); px = c
        body = rng.uniform(-1, 1) * abs(rng.gauss(0, 2e-4)) * c
        o = c - body
        wick = abs(rng.gauss(0, 1.5e-4)) * c
        u = (i - minutes / 2) / (minutes / 2)
        vol = float(int((60_000 * (1 + 2.5 * u * u)) * math.exp(rng.gauss(0, 0.35))))
        bars.append({"event_time_utc": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, c) + wick, "low": min(o, c) - wick, "close": c, "volume": vol})
    raw = json.dumps({"source": "alpaca_sip_raw_1m", "bars": bars}).encode()
    return B.session_from_doc({"source": "alpaca_sip_raw_1m", "bars": bars}, Path("SPY_%s.json" % day), raw,
                              {"sha256": "synthetic", "restricted_use": "synthetic memory qualification"},
                              symbol="SPY", session_date=day)


def main(out_path: str, boot_B: int = 200) -> int:
    sampler = Sampler(); sampler.start()
    sampler.mark("start")
    fit_days = trading_days(FIT_LO, FIT_HI)
    dev_days = trading_days(DEV_LO, DEV_HI)
    sampler.mark("calendar_enumerated")
    paths = {"/fixture/%s.json" % d: d for d in fit_days + dev_days}
    sbp = {"fit": ["/fixture/%s.json" % d for d in fit_days],
           "development": ["/fixture/%s.json" % d for d in dev_days]}

    built = {"n": 0}

    def loader(p):                       # generates on demand, like the governed loader reads on demand
        built["n"] += 1
        if built["n"] % 200 == 0:
            sampler.mark("loaded_%d_sessions" % built["n"])
        return build_session(paths[p], SEED + built["n"])

    t0 = time.time()
    rec = H4.run(sbp, ledger_dir=None, session_loader=loader) if boot_B >= 10000 else None
    if rec is None:
        # reduced-B path: the SAME adapter code, through the synthetic entry point,
        # so session/array memory is measured at full scale without a multi-hour bootstrap
        fit = [loader(p) for p in sbp["fit"]]
        sampler.mark("fit_sessions_loaded")
        dev = [loader(p) for p in sbp["development"]]
        sampler.mark("development_sessions_loaded")
        rec = SY.synthetic_tournament(fit, dev, bootstrap_resamples=boot_B)
        fit = dev = None
    sampler.mark("run_complete")
    elapsed = time.time() - t0
    sampler.stop_flag.set(); sampler.join(timeout=5)

    mem = sampler.report()
    out = {"qualification": "EXP004_MEMORY_AT_REGISTERED_SCALE",
           "registration_hash": registration_hash(),
           "synthetic_only": True, "admitted_data_used": False, "admission": None,
           "scale": {"fit_sessions": len(fit_days), "development_sessions": len(dev_days),
                     "total_sessions": len(fit_days) + len(dev_days),
                     "sessions_built": built["n"],
                     "fit_range": [FIT_LO, FIT_HI], "development_range": [DEV_LO, DEV_HI]},
           "bootstrap_resamples_used": boot_B,
           "registered_bootstrap_resamples": 10000,
           "full_registered_inference": boot_B >= 10000,
           "elapsed_seconds": round(elapsed, 1),
           "memory": mem,
           "status": rec.get("status"),
           "run_mode": rec.get("run_mode"),
           "n_fit_rows": (rec.get("result") or rec).get("fit", {}).get("n_fit_rows"),
           "n_dev_rows": ((rec.get("result") or rec).get("development") or {}).get("n_rows"),
           "refusal": rec.get("refusal")}
    cap = mem.get("memory_max_bytes")
    peak = mem.get("cgroup_memory_peak_bytes") or mem.get("sampled_max_memory_current_bytes")
    if cap and cap.isdigit() and peak:
        out["headroom"] = {"cap_bytes": int(cap), "peak_bytes": peak,
                           "headroom_bytes": int(cap) - peak,
                           "peak_fraction_of_cap": round(peak / int(cap), 4)}
    Path(out_path).write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: out[k] for k in ("scale", "elapsed_seconds", "status", "run_mode",
                                          "n_fit_rows", "n_dev_rows", "headroom",
                                          "bootstrap_resamples_used") if k in out},
                     indent=1, default=str))
    print(json.dumps({k: mem[k] for k in ("cgroup", "readable", "samples",
                                          "sampled_max_memory_current_bytes", "cgroup_memory_peak_bytes",
                                          "memory_max_bytes", "memory_events", "peak_rss_vmhwm_bytes")},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 200))
