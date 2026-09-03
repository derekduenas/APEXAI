"""EQUITY_FABRIC_VALIDATION_PROFILE_V1 -- external observer for the
repaired candidate.

EXTERNAL BY DESIGN. This runs from the repo, never from the release
under test, and only READS: cgroup files, /proc, the fabric's own
health artifact, and its canonical bar outputs. It cannot perturb the
thing it is measuring, and it is not part of the candidate.

It supersedes ef_rth_profile.py for VALIDATION runs. That script stays
untouched -- it is the sealed evidence of the OLD failure curve
(EQUITY_FABRIC_RTH_FAILURE_PROFILE_V0) and rewriting it would edit the
benchmark we are measuring against.

What it adds, because the acceptance list needs it and the old profiler
predates these fields:

    working_state.*          raw / dedup / bar cardinality, evictions,
                             oldest+newest retained bucket, bound
                             violations               (BOUND A/B/C)
    ordering_semantics.*     semantic_health, ambiguity events and the
                             affected symbol/bucket, out_of_order,
                             late_after_finalize
    late_trade_contract      the PARTIAL limitation, kept visible
    ACTIVE_FABRIC_WRITERS    the single-writer law, sampled every tick
                             rather than assumed once at start

Usage: ef_validation_profile.py [minutes] [interval_s] [unit]
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

UNIT = sys.argv[3] if len(sys.argv) > 3 else "apex-equity-fabric-v1.service"
CG = Path("/sys/fs/cgroup/apex.slice/apex-market.slice") / UNIT
BARS = Path("/apex-data/runtime/data/live/alpaca_fabric/bars")
HEALTH = Path("/apex-data/core/intraday/alpaca_fabric_health.json")
OUT = Path("/apex-data/core/equity_fabric_validation_profile")
OUT.mkdir(parents=True, exist_ok=True)
LEDGER = OUT / f"validation_{datetime.now(timezone.utc):%Y%m%d}.jsonl"

MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 400
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 60

# every fabric that could legitimately write the canonical bars
WRITER_UNITS = ("apex-equity-fabric.service", "apex-equity-fabric-v1.service")


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True,
                          text=True).stdout.strip()


def cg_read(name):
    try:
        return (CG / name).read_text().strip()
    except OSError:
        return None


def cg_kv(name, keys=None):
    out = {}
    try:
        for ln in (CG / name).read_text().splitlines():
            k, _, v = ln.partition(" ")
            if keys is None or k in keys:
                try:
                    out[k] = int(v)
                except ValueError:
                    out[k] = v
    except OSError:
        pass
    return out


def proc_status(pid):
    out = {}
    if not pid:
        return out
    try:
        for ln in Path(f"/proc/{pid}/status").read_text().splitlines():
            for k in ("VmRSS", "VmHWM", "VmSize", "Threads"):
                if ln.startswith(k):
                    out[k] = int(ln.split()[1]) if k != "Threads" \
                        else int(ln.split()[1])
    except OSError:
        pass
    return out


def bars_state():
    """Canonical output: is it CURRENT, not merely present."""
    try:
        files = sorted(BARS.glob("*.json"))
    except OSError:
        return {}
    now = time.time()
    fresh = [f for f in files if now - f.stat().st_mtime < 300]
    total = sum(f.stat().st_size for f in files)
    newest = max((f.stat().st_mtime for f in files), default=None)
    return {"files": len(files), "fresh_5min": len(fresh),
            "total_bytes": total,
            "newest_age_s": round(now - newest, 1) if newest else None}


def health_state():
    """The fabric's OWN report -- bounded state and semantics."""
    try:
        h = json.loads(HEALTH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"available": False}
    ws = h.get("working_state") or {}
    ordering = h.get("ordering_semantics") or {}
    c = ws.get("counters") or {}
    return {
        "available": True,
        "status": h.get("status"),
        "beat_age_s": None,
        # --- BOUND A/B/C telemetry
        "state_model": ws.get("state_model"),
        "raw_trades_retained": ws.get("raw_trades_retained"),
        "raw_trades_retained_max_symbol":
            ws.get("raw_trades_retained_max_symbol"),
        "dedup_keys_retained": ws.get("dedup_keys_retained"),
        "bars_retained": ws.get("bars_retained"),
        "open_buckets": ws.get("open_buckets"),
        "oldest_retained_bucket_s": ws.get("oldest_retained_bucket_s"),
        "newest_retained_bucket_s": ws.get("newest_retained_bucket_s"),
        "buckets_finalized": c.get("buckets_finalized"),
        "buckets_evicted": c.get("buckets_evicted"),
        "dedup_keys_evicted": c.get("dedup_keys_evicted"),
        "bound_violations": c.get("bound_violations"),
        "forced_finalize": c.get("forced_finalize"),
        "state_bound_ok": (h.get("health_axes") or {}).get("state_bound_ok"),
        "state_bound_error": h.get("state_bound_error"),
        # --- semantic equivalence telemetry
        "semantic_health": (h.get("semantic_health")
                            or ordering.get("semantic_health")),
        "ordering_semantics_exact":
            (h.get("health_axes") or {}).get("ordering_semantics_exact"),
        "ordering_ambiguity_events":
            ordering.get("ordering_ambiguity_events"),
        "affected_buckets_sample": ordering.get("affected_buckets_sample"),
        "buckets_with_ns_tie": ordering.get("buckets_with_ns_tie"),
        "symbols_with_non_monotonic_arrival":
            ordering.get("symbols_with_non_monotonic_arrival"),
        "out_of_order": ordering.get("out_of_order"),
        "late_after_finalize": ordering.get("late_after_finalize"),
        "late_trade_contract": h.get("late_trade_contract"),
        "equivalence_claim": h.get("equivalence_claim"),
        # --- provider / coverage
        "provider_trades": (h.get("counters") or {}).get("trades"),
        "duplicates": (h.get("counters") or {}).get("duplicates"),
        "future_rejected": (h.get("counters") or {}).get("future_rejected"),
        "reconnects": (h.get("counters") or {}).get("reconnects"),
        "frames_dropped": (h.get("counters") or {}).get("frames_dropped"),
        "coverage_fraction":
            (h.get("health_axes") or {}).get("coverage_fraction"),
        "tape_continuity": (h.get("health_axes") or {}).get("tape_continuity"),
        "symbol_count": h.get("symbol_count"),
    }


def writers():
    """THE SINGLE-WRITER LAW, sampled -- not assumed once at start. Two
    fabrics interleaving into one session file is the failure this
    prevents, and it could begin at any moment, not only at launch."""
    active = [u for u in WRITER_UNITS
              if sh(f"systemctl is-active {u}") == "active"]
    return {"active_units": active, "count": len(active)}


def main():
    t_end = time.time() + MINUTES * 60
    last_pid = None
    n = 0
    print(f"observing {UNIT} for {MINUTES:.0f} min every {INTERVAL:.0f}s")
    print(f"-> {LEDGER}")
    while time.time() < t_end:
        pid = sh(f"systemctl show {UNIT} -p MainPID --value")
        pid = int(pid) if pid.isdigit() else 0
        rec = {
            "kind": "equity_fabric_validation_sample",
            "regime": "EQUITY_FABRIC_VALIDATION_PROFILE_V1",
            "unit": UNIT,
            "utc": datetime.now(timezone.utc).isoformat(),
            "pid": pid,
            "pid_changed": (last_pid is not None and pid != last_pid),
            "active_state": sh(f"systemctl show {UNIT} -p ActiveState --value"),
            "n_restarts": sh(f"systemctl show {UNIT} -p NRestarts --value"),
            "release": sh("grep '^RELEASE=' "
                          "/home/apex/bin/apex_equity_fabric_v1.sh "
                          "| cut -d= -f2"),
            "memory_current": int(cg_read("memory.current") or 0),
            "memory_peak": int(cg_read("memory.peak") or 0),
            "memory_max": cg_read("memory.max"),
            "memory_events": cg_kv("memory.events"),
            "memory_stat": cg_kv("memory.stat",
                                 {"anon", "file", "slab", "pgfault",
                                  "pgmajfault"}),
            "proc": proc_status(pid),
            "bars": bars_state(),
            "health": health_state(),
            "writers": writers(),
        }
        with LEDGER.open("a") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
        n += 1
        h = rec["health"]
        w = rec["writers"]
        flag = ""
        if rec["pid_changed"]:
            flag += " PID_CHANGED"
        if w["count"] != 1:
            flag += f" WRITERS={w['count']}"
        if h.get("state_bound_ok") is False:
            flag += " BOUND_VIOLATION"
        if h.get("ordering_semantics_exact") is False:
            flag += " ORDERING_AMBIGUITY"
        if (rec["memory_events"] or {}).get("max"):
            flag += " AT_MEMORY_CAP"
        print("%s rss=%6.0fMiB raw=%-9s dedup=%-9s bars=%-7s sem=%-28s%s"
              % (rec["utc"][11:19],
                 rec["memory_current"] / 1048576,
                 h.get("raw_trades_retained"),
                 h.get("dedup_keys_retained"),
                 h.get("bars_retained"),
                 h.get("semantic_health"), flag))
        last_pid = pid
        time.sleep(INTERVAL)
    print(f"done: {n} samples -> {LEDGER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
