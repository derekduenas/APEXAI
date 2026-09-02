"""GATE 3 EXTENDED -- PULSE_V1 prebirth live run past the 60-minute
rolling horizon.

NON-PROSPECTIVE. No systemd timer. This engineering loop is explicitly
NOT the future prospective service identity.

Five cycles proved integration. They cannot prove plateau, because the
rolling window is 60 minutes wide. This run crosses that boundary and
measures WINDOW_FILL and POST_WINDOW_PLATEAU as separate regimes --
comparing against an empty cycle-0 checkpoint would conflate the window
filling with unbounded growth, which is the error I made once already.

Boundedness proven here is OFF-HOURS ONLY. RTH provider load is a
different regime and is NOT inferred from this.
"""
import json
import resource
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/opt/apex-repo")
sys.path.insert(0, "/opt/apex-repo/scripts")
from apex.pulse.runtime_v1 import PulseV1Runtime          # noqa: E402
from pulse_v1_live_composer import (LiveProviderComposer,  # noqa: E402
                                    PREBIRTH_EVIDENCE_CLASS, REGIME)

OUT = Path("/apex-data/core/pulse_v1_prebirth_extended")
CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 90
WINDOW = 60
OUT.mkdir(parents=True, exist_ok=True)


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def host_avail_mb():
    for ln in Path("/proc/meminfo").read_text().splitlines():
        if ln.startswith("MemAvailable"):
            return int(ln.split()[1]) / 1024
    return 0


def oom_counts():
    out = subprocess.run(
        ["sudo", "journalctl", "-k", "--since", "-30m", "--no-pager"],
        capture_output=True, text=True).stdout
    return {
        "global": sum(1 for l in out.splitlines()
                      if "oom-kill:" in l and "CONSTRAINT_NONE" in l),
        "pulse": sum(1 for l in out.splitlines()
                     if "oom-kill:" in l and "pulse" in l),
    }


bar = "=" * 78
print(bar)
print(f"GATE 3 EXTENDED -- {REGIME}")
print(f"  {CYCLES} cycles, rolling window {WINDOW} min, REAL providers")
print("  NON-PROSPECTIVE. No timer. Off-hours boundedness only.")
print(bar)

oom_before = oom_counts()
comp = LiveProviderComposer(max_subjects=24)
rt = PulseV1Runtime(results_dir=OUT, compose_packets=comp,
                    rolling_window_minutes=WINDOW)

base = datetime.now(timezone.utc).replace(second=0, microsecond=0)
rows = []
t_wall = time.time()
print(f"  {'cyc':>4} {'pkts':>5} {'ckpt_KB':>9} {'roll_card':>10} "
      f"{'restore_ms':>11} {'ledger_MB':>10} {'rss_MB':>7} {'avail_MB':>9}")
print("  " + "-" * 74)
for i in range(CYCLES):
    slot = base - timedelta(minutes=(CYCLES - i))
    r = rt.run_cycle(slot)
    t0 = time.perf_counter()
    ck, mode = rt.restore(slot.strftime("%Y-%m-%d"))
    rest_ms = (time.perf_counter() - t0) * 1000
    card = ck.rolling.cardinality()
    row = {"cycle": i, "packets": len(r.packets),
           "ckpt": r.checkpoint_bytes, "card": card,
           "restore_ms": rest_ms,
           "ledger": rt.ledger.stat().st_size,
           "rss": rss_mb(), "avail": host_avail_mb(),
           "occ": r.lifecycle.true_slot_occupancy_s,
           "order_ok": (r.lifecycle.service_start >= slot
                        and r.lifecycle.persistence_complete
                        >= r.lifecycle.service_start)}
    rows.append(row)
    if i % 10 == 0 or i in (WINDOW - 1, WINDOW, CYCLES - 1):
        print(f"  {i:>4} {len(r.packets):>5} {r.checkpoint_bytes/1024:>9.1f} "
              f"{card:>10} {rest_ms:>11.2f} {row['ledger']/1048576:>10.2f} "
              f"{row['rss']:>7.0f} {row['avail']:>9.0f}")

wall = time.time() - t_wall
oom_after = oom_counts()

fill = [r for r in rows if r["cycle"] < WINDOW]
plateau = [r for r in rows if r["cycle"] >= WINDOW]

print()
print(bar)
print("WINDOW_FILL vs POST_WINDOW_PLATEAU")
print(bar)


def span(rs, k):
    v = [r[k] for r in rs]
    return min(v), max(v), (max(v) / min(v) if min(v) else float("inf"))


for name, rs in (("WINDOW_FILL  (cycles 0-59)", fill),
                 ("POST_PLATEAU (cycles 60+) ", plateau)):
    if not rs:
        continue
    ck = span(rs, "ckpt")
    cd = span(rs, "card")
    rm = span(rs, "restore_ms")
    print(f"  {name}  n={len(rs)}")
    print(f"     checkpoint  {ck[0]/1024:8.1f} -> {ck[1]/1024:8.1f} KB "
          f"({ck[2]:.3f}x)")
    print(f"     rolling     {cd[0]:8d} -> {cd[1]:8d} obs "
          f"({cd[2]:.3f}x)")
    print(f"     restore     {rm[0]:8.2f} -> {rm[1]:8.2f} ms "
          f"({rm[2]:.3f}x)")

print()
print(bar)
print("ACCEPTANCE (post-window only)")
print(bar)
ck_r = span(plateau, "ckpt")[2] if plateau else 99
cd_r = span(plateau, "card")[2] if plateau else 99
rm_r = span(plateau, "restore_ms")[2] if plateau else 99
led_grow = rows[-1]["ledger"] / max(rows[0]["ledger"], 1)
rss_max = max(r["rss"] for r in rows)
ok_ck, ok_cd = ck_r < 1.10, cd_r < 1.10
ok_rm, ok_rss = rm_r < 2.0, rss_max < 1500
ok_oom = (oom_after["global"] - oom_before["global"]) == 0 and \
         (oom_after["pulse"] - oom_before["pulse"]) == 0
print(f"  ledger grew                {led_grow:8.1f}x   "
      f"(evidence must keep growing)")
print(f"  checkpoint plateau <1.10x  {ck_r:8.3f}x   "
      f"{'PASS' if ok_ck else 'FAIL'}")
print(f"  rolling plateau   <1.10x   {cd_r:8.3f}x   "
      f"{'PASS' if ok_cd else 'FAIL'}")
print(f"  restore plateau   <2.0x    {rm_r:8.3f}x   "
      f"{'PASS' if ok_rm else 'FAIL'}")
print(f"  peak RSS          <1500MB  {rss_max:8.0f}MB  "
      f"{'PASS' if ok_rss else 'FAIL'}")
print(f"  GLOBAL_OOM / PULSE_OOM     "
      f"{oom_after['global']-oom_before['global']} / "
      f"{oom_after['pulse']-oom_before['pulse']}   "
      f"{'PASS' if ok_oom else 'FAIL'}")

print()
print(bar)
print("OCCUPANCY ORDERING + EVIDENCE INTEGRITY")
print(bar)
bad_order = [r["cycle"] for r in rows if not r["order_ok"]]
anom = [r["cycle"] for r in rows if r["occ"] is not None and r["occ"] < 0]
print(f"  lifecycle ordering violations   {len(bad_order)}")
print(f"  CLOCK_ANOMALY (negative occ)    {len(anom)}")
cl = [json.loads(x) for x in rt.cycle_log.read_text().splitlines()
      if x.strip()]
prev, broken = "GENESIS", 0
for r in cl:
    if r["prev_hash"] != prev:
        broken += 1
    prev = r["entry_hash"]
print(f"  cycle chain                     {len(cl)} links, "
      f"{broken} mismatch")
sample = [0, WINDOW, CYCLES - 1]
badroot = sum(0 if rt.verify_cycle(
    base - timedelta(minutes=(CYCLES - i)))["VALID"] else 1
    for i in sample)
print(f"  packet roots (sampled {len(sample)})         "
      f"{len(sample)-badroot}/{len(sample)} valid")
classes = set()
with rt.ledger.open() as fh:
    for line in fh:
        if line.strip():
            classes.add(json.loads(line).get("evidence_class"))
print(f"  evidence classes                {classes}")
print(f"  LIVE_PROSPECTIVE leak           "
      f"{'NONE' if classes == {PREBIRTH_EVIDENCE_CLASS} else 'LEAK'}")

verdict = all([ok_ck, ok_cd, ok_rm, ok_rss, ok_oom,
               not bad_order, not anom, broken == 0, badroot == 0,
               classes == {PREBIRTH_EVIDENCE_CLASS}])
print()
print(f"  PULSE_V1_LIVE_BOUNDEDNESS_OFFHOURS = "
      f"{'PASS' if verdict else 'FAIL'}")
print(f"  PULSE_V1_LIVE_BOUNDEDNESS_RTH      = NOT_PROVEN "
      f"(off-hours load is not RTH load)")
print(f"  wall time {wall/60:.1f} min   evidence dir {OUT}")
