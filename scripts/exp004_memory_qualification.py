"""EXP-004 memory qualification at REGISTERED SCALE, measured from inside the
unit's own cgroup, with provenance captured BY THE RUNNING PROCESS.

Why this exists: `run.tournament` holds full session objects for both periods,
where EXP-002's adapter converted each session to rows and discarded it. Peak
memory was unestablished and EXP-001B's first historical attempt was OOM-killed.

What this script establishes, and what it does not:
  * it measures capacity of THIS implementation on SYNTHETIC bars;
  * it does NOT establish correctness, alpha, or anything about admitted data;
  * it does NOT exercise the governed loading, provenance or sealing path:
    sessions are generated on demand and `ledger_dir` is None.

Provenance discipline (the whole point of this revision):
  * the process records the executed commit, bound-tree hash, dirty list,
    interpreter, NumPy version and the imported module FILE PATHS itself;
  * it REFUSES to run against a dirty checkout, so an artifact can never
    describe a process whose source cannot be identified;
  * source identity is recomputed at completion and compared;
  * cgroup counters INCLUDING memory.events are sampled throughout and the
    full trajectory is preserved;
  * the inference parameters reported as "used" are read back from the run
    record, never copied from the command line.

Run: python3 scripts/exp004_memory_qualification.py <out.json> <mode> [B]
     mode = adapter   registered inference through run.tournament (HISTORICAL)
     mode = synthetic reduced B through the synthetic entry point
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

import numpy

from apex.world_model.exp001b import bars as B, exchange_calendar as C
from apex.world_model.exp004 import historical as H4, run as R, synthetic as SY
from apex.world_model.exp004.registration import PERIODS, registration_hash
from apex.world_model.real_data import boundary

SEED = 20260913
FIT_LO, FIT_HI = PERIODS["fit"]
DEV_LO, DEV_HI = PERIODS["development"]
REGISTERED_B = 10000
MIB = 1024 * 1024
CHAIN = ("apex.world_model.exp004.historical", "apex.world_model.exp004.run",
         "apex.world_model.exp004.features", "apex.world_model.exp004.models",
         "apex.world_model.exp004.dispersion", "apex.world_model.exp004.inference",
         "apex.world_model.exp004.bootstrap_adapter", "apex.world_model.exp004.registration",
         "apex.world_model.exp001b.bars", "apex.world_model.exp001b.exchange_calendar")


class QualificationRefused(RuntimeError):
    """The run cannot produce attributable evidence; nothing is measured."""


# ---------------------------------------------------------------- provenance

def provenance(checkout: Path) -> dict:
    ident = boundary.source_identity(checkout)
    if ident["dirty"]:
        raise QualificationRefused("DIRTY_CHECKOUT: %s; a qualification artifact must identify the source it ran"
                                   % ident["dirty"][:6])
    mods = {}
    for name in CHAIN:
        m = sys.modules.get(name)
        f = getattr(m, "__file__", None) if m else None
        mods[name] = str(Path(f).resolve()) if f else "NOT_IMPORTED"
    outside = {k: v for k, v in mods.items() if v != "NOT_IMPORTED" and not v.startswith(str(checkout))}
    return {"executed_commit": ident["commit"], "bound_tree_sha256": ident["tree_sha256"],
            "bound_files": ident["n_files"], "bound_paths": ident["paths"], "dirty": ident["dirty"],
            "checkout_root": str(checkout), "imported_module_files": mods,
            "modules_outside_checkout": outside,
            "interpreter": {"executable": sys.executable, "version": sys.version.split()[0],
                            "version_full": sys.version.replace("\n", " ")},
            "numpy": numpy.__version__,
            "captured_by": "the running process, before measurement"}


# ---------------------------------------------------------------- cgroup sampling

def _cgroup_dir():
    try:
        rel = Path("/proc/self/cgroup").read_text().strip().splitlines()[-1].split(":")[-1].lstrip("/")
        p = Path("/sys/fs/cgroup") / rel
        return p if p.exists() else None
    except Exception:                                                    # noqa: BLE001
        return None


def _read(p, name):
    try:
        return (p / name).read_text().strip()
    except Exception:                                                    # noqa: BLE001
        return None


def _events(text):
    if not text:
        return None
    return {k: int(v) for k, v in (l.split() for l in text.splitlines() if len(l.split()) == 2)}


def _vmhwm():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except Exception:                                                    # noqa: BLE001
        return None
    return None


class Sampler(threading.Thread):
    """Samples memory.current AND memory.events throughout, keeping the whole
    trajectory rather than only its maximum."""

    def __init__(self, interval: float = 0.25):
        super().__init__(daemon=True)
        self.interval, self.stop_flag = interval, threading.Event()
        self.cg = _cgroup_dir()
        self.trace, self.marks = [], []
        self.t0 = time.time()

    def _sample(self):
        if not self.cg:
            return None
        cur = _read(self.cg, "memory.current")
        return {"t": round(time.time() - self.t0, 3),
                "current": int(cur) if cur and cur.isdigit() else None,
                "events": _events(_read(self.cg, "memory.events"))}

    def mark(self, label):
        s = self._sample() or {}
        self.marks.append({"label": label, **s, "vmhwm": _vmhwm()})

    def run(self):
        while not self.stop_flag.is_set():
            s = self._sample()
            if s:
                self.trace.append(s)
            self.stop_flag.wait(self.interval)

    def report(self):
        cg = self.cg
        cur = [s["current"] for s in self.trace if s["current"] is not None]
        evs = [s["events"] for s in self.trace if s["events"]]
        keys = sorted({k for e in evs for k in e})
        peak = _read(cg, "memory.peak") if cg else None
        cap = _read(cg, "memory.max") if cg else None
        return {"cgroup": str(cg) if cg else "UNAVAILABLE", "readable": cg is not None,
                "samples": len(self.trace), "interval_s": self.interval,
                "sampled_max_memory_current_bytes": max(cur) if cur else None,
                "cgroup_memory_peak_bytes": int(peak) if peak and peak.isdigit() else None,
                "memory_max_bytes": int(cap) if cap and cap.isdigit() else None,
                "events_sampled_throughout": {k: max(e.get(k, 0) for e in evs) for k in keys} if evs else None,
                "events_final": _events(_read(cg, "memory.events")) if cg else None,
                "peak_rss_vmhwm_bytes": _vmhwm(),
                "trajectory_current_bytes": [[s["t"], s["current"]] for s in self.trace],
                "marks": self.marks,
                "note": "memory.current AND memory.events sampled throughout; full trajectory retained"}


# ---------------------------------------------------------------- fixtures

def trading_days(lo, hi):
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


def build_session(day, seed):
    b = C.session_bounds(day, require_verified=True)
    t0, minutes = datetime.fromtimestamp(b["open_utc"], timezone.utc), int(b["regular_minutes"])
    rng = random.Random(seed)
    px, bars = 400.0, []
    for i in range(minutes):
        c = px * math.exp(rng.gauss(0, 3e-4)); px = c
        o = c - rng.uniform(-1, 1) * abs(rng.gauss(0, 2e-4)) * c
        wick = abs(rng.gauss(0, 1.5e-4)) * c
        u = (i - minutes / 2) / (minutes / 2)
        bars.append({"event_time_utc": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, c) + wick, "low": min(o, c) - wick, "close": c,
                     "volume": float(int((60_000 * (1 + 2.5 * u * u)) * math.exp(rng.gauss(0, 0.35))))})
    raw = json.dumps({"source": "alpaca_sip_raw_1m", "bars": bars}).encode()
    return B.session_from_doc({"source": "alpaca_sip_raw_1m", "bars": bars}, Path("SPY_%s.json" % day), raw,
                              {"sha256": "synthetic", "restricted_use": "synthetic memory qualification"},
                              symbol="SPY", session_date=day)


# ---------------------------------------------------------------- main

def main(out_path: str, mode: str, requested_B=None) -> int:
    if mode not in ("adapter", "synthetic"):
        raise QualificationRefused("INVALID_MODE: %r" % mode)
    if mode == "adapter" and requested_B not in (None, REGISTERED_B):
        raise QualificationRefused("UNSUPPORTED_PARAMETER: the adapter path takes no inference parameters and always "
                                   "uses the registered B=%d; %r was requested and would be silently ignored"
                                   % (REGISTERED_B, requested_B))
    if mode == "synthetic":
        R.resolve_inference_parameters(requested_B, None, run_mode=R.SYNTHETIC_TEST)   # validate or refuse now

    checkout = Path(__file__).resolve().parents[1]
    prov_start = provenance(checkout)

    sampler = Sampler(); sampler.start(); sampler.mark("start")
    fit_days, dev_days = trading_days(FIT_LO, FIT_HI), trading_days(DEV_LO, DEV_HI)
    sampler.mark("calendar_enumerated")
    paths = {"/fixture/%s.json" % d: d for d in fit_days + dev_days}
    sbp = {"fit": ["/fixture/%s.json" % d for d in fit_days],
           "development": ["/fixture/%s.json" % d for d in dev_days]}
    built = {"n": 0}

    def loader(p):
        built["n"] += 1
        if built["n"] % 250 == 0:
            sampler.mark("loaded_%d_sessions" % built["n"])
        return build_session(paths[p], SEED + built["n"])

    t0 = time.time()
    if mode == "adapter":
        rec = H4.run(sbp, ledger_dir=None, session_loader=loader)
        inner = rec.get("result") or {}
    else:
        fit = [loader(p) for p in sbp["fit"]]; sampler.mark("fit_loaded")
        dev = [loader(p) for p in sbp["development"]]; sampler.mark("development_loaded")
        rec = SY.synthetic_tournament(fit, dev, bootstrap_resamples=requested_B)
        inner = rec
        fit = dev = None
    sampler.mark("run_complete")
    elapsed = time.time() - t0
    sampler.stop_flag.set(); sampler.join(timeout=5)

    prov_end = boundary.source_identity(checkout)
    used = (inner.get("inference_parameters") or rec.get("inference_parameters") or {})
    if requested_B is not None and used.get("resamples") != requested_B:
        raise QualificationRefused("PARAMETER_MISMATCH: requested B=%r, the run used %r"
                                   % (requested_B, used.get("resamples")))

    mem = sampler.report()
    peak = mem.get("cgroup_memory_peak_bytes") or mem.get("sampled_max_memory_current_bytes")
    cap = mem.get("memory_max_bytes")
    out = {"qualification": "EXP004_MEMORY_AT_REGISTERED_SCALE", "mode": mode,
           "registration_hash": registration_hash(),
           "provenance_at_start": prov_start,
           "source_identity_at_completion": {**prov_end,
                                             "unchanged": prov_end["commit"] == prov_start["executed_commit"]
                                             and prov_end["tree_sha256"] == prov_start["bound_tree_sha256"]
                                             and not prov_end["dirty"]},
           "synthetic_only": True, "admitted_data_used": False, "admission": None,
           "governed_path_exercised": False,
           "governed_path_note": ("sessions are generated on demand and ledger_dir is None: the admitted loader, "
                                  "import-provenance verification and result sealing are NOT exercised here"),
           "scale": {"fit_sessions": len(fit_days), "development_sessions": len(dev_days),
                     "total_sessions": len(fit_days) + len(dev_days), "sessions_built": built["n"],
                     "fit_range": [FIT_LO, FIT_HI], "development_range": [DEV_LO, DEV_HI]},
           "inference_parameters_requested": requested_B,
           "inference_parameters_used": used,
           "registered_bootstrap_resamples": REGISTERED_B,
           "elapsed_seconds": round(elapsed, 1),
           "memory": mem,
           "status": rec.get("status"), "run_mode": rec.get("run_mode") or inner.get("run_mode"),
           "n_fit_rows": (inner.get("fit") or {}).get("n_fit_rows"),
           "n_dev_rows": (inner.get("development") or {}).get("n_rows"),
           "refusal": rec.get("refusal")}
    if cap and peak:
        out["headroom"] = {"cap_bytes": cap, "cap_MiB": round(cap / MIB, 1),
                           "peak_bytes": peak, "peak_MiB": round(peak / MIB, 1),
                           "headroom_bytes": cap - peak, "headroom_MiB": round((cap - peak) / MIB, 1),
                           "peak_fraction_of_cap": round(peak / cap, 4), "unit": "MiB = 1024^2 bytes"}
    Path(out_path).write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    brief = {k: out[k] for k in ("mode", "scale", "elapsed_seconds", "status", "run_mode", "n_fit_rows",
                                 "n_dev_rows", "headroom", "inference_parameters_used") if k in out}
    brief["provenance"] = {k: prov_start[k] for k in ("executed_commit", "bound_tree_sha256", "bound_files", "numpy")}
    brief["provenance"]["interpreter"] = prov_start["interpreter"]["version"]
    brief["provenance"]["modules_outside_checkout"] = prov_start["modules_outside_checkout"]
    brief["source_unchanged_at_completion"] = out["source_identity_at_completion"]["unchanged"]
    brief["events"] = {"throughout": mem["events_sampled_throughout"], "final": mem["events_final"]}
    print(json.dumps(brief, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None))
