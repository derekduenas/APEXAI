"""GATE 3 -- PULSE_V1 prebirth live-provider commissioning.

NON-PROSPECTIVE. No timer. Manual invocation only.
"""
import hashlib
import json
import resource
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/opt/apex-repo")
sys.path.insert(0, "/opt/apex-repo/scripts")
from pulse_v1_live_composer import (LiveProviderComposer,  # noqa: E402
                                      PREBIRTH_EVIDENCE_CLASS, REGIME)
from apex.pulse.packet_root import verify                    # noqa: E402
from apex.pulse.runtime_v1 import PulseV1Runtime             # noqa: E402

OUT = Path("/apex-data/core/pulse_v1_prebirth")
CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 6
FRESH = "--fresh" in sys.argv
if FRESH and OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True, exist_ok=True)


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def host_avail_mb():
    for ln in Path("/proc/meminfo").read_text().splitlines():
        if ln.startswith("MemAvailable"):
            return int(ln.split()[1]) / 1024
    return None


bar = "=" * 78
print(bar)
print(f"GATE 3 -- {REGIME}")
print("NON-PROSPECTIVE ENGINEERING EVIDENCE. NOT a prospective birth.")
print(bar)

comp = LiveProviderComposer(max_subjects=24)
print(f"  subjects        {len(comp.subjects)}  "
      f"(Tier-1 {sorted(comp.tier1)})")
print(f"  universe_version {comp.universe_version}")
print(f"  host MemAvailable {host_avail_mb():,.0f} MB")
print()

rt = PulseV1Runtime(results_dir=OUT, compose_packets=comp,
                    rolling_window_minutes=60)

print(f"  {'cycle':>5} {'pkts':>5} {'ckpt_KB':>8} {'occup_s':>8} "
      f"{'rss_MB':>7} {'alpaca':>7} {'btc':>9} {'cat':>6}")
print("  " + "-" * 68)
rows, reports = [], []
base = datetime.now(timezone.utc).replace(second=0, microsecond=0)
for i in range(CYCLES):
    slot = base - timedelta(minutes=(CYCLES - i))   # slots in the PAST
    r = rt.run_cycle(slot)
    rep = comp.provider_report
    reports.append(rep)
    occ = r.lifecycle.true_slot_occupancy_s
    rows.append((i, len(r.packets), r.checkpoint_bytes, occ, rss_mb()))
    print(f"  {i:>5} {len(r.packets):>5} {r.checkpoint_bytes/1024:>8.1f} "
          f"{occ:>8.1f} {rss_mb():>7.1f} "
          f"{rep.get('alpaca_returned', 0):>7} "
          f"{str(rep.get('cross_asset', {}).get('btc_status'))[:9]:>9} "
          f"{str(rep.get('catalyst', {}).get('status'))[:6]:>6}")

print()
print(bar)
print("PROVIDER PROOF (last cycle)")
print(bar)
last = reports[-1]
print(f"  session                 {last.get('session')}")
print(f"  ALPACA returned/errors  {last.get('alpaca_returned')} / "
      f"{last.get('alpaca_errors')}  fetch={last.get('alpaca_fetch_s')}s")
print(f"  CATALYST                {last.get('catalyst')}")
print(f"  CROSS-ASSET (BTC)       {last.get('cross_asset')}")
print(f"  OPTIONS (Tier-1)        {last.get('options')}")
if last.get("options_errors"):
    print(f"  options errors          {last['options_errors']}")
if last.get("errors"):
    print(f"  subject errors          "
          f"{dict(list(last['errors'].items())[:4])}")

# ---- evidence-class isolation ---------------------------------------
print()
print(bar)
print("EVIDENCE-CLASS ISOLATION")
print(bar)
classes, regimes = {}, {}
n = 0
with rt.ledger.open() as fh:
    for line in fh:
        if not line.strip():
            continue
        d = json.loads(line)
        n += 1
        classes[d.get("evidence_class")] = \
            classes.get(d.get("evidence_class"), 0) + 1
        regimes[d.get("regime")] = regimes.get(d.get("regime"), 0) + 1
print(f"  packets                 {n}")
print(f"  evidence_class          {classes}")
print(f"  regime                  {regimes}")
leak = [c for c in classes if c != PREBIRTH_EVIDENCE_CLASS]
print(f"  LIVE_PROSPECTIVE leak   "
      f"{'NONE' if not leak else 'LEAK ' + str(leak)}")

# ---- bounded state ---------------------------------------------------
print()
print(bar)
print("BOUNDED STATE UNDER LIVE LOAD")
print(bar)
ck = [r[2] for r in rows]
print(f"  checkpoint  first {ck[0]/1024:.1f} KB   last {ck[-1]/1024:.1f} KB")
print(f"  ledger      {rt.ledger.stat().st_size:,} bytes")
probe = rt.restore_cost_probe(base.strftime("%Y-%m-%d"))
print(f"  restore     {probe['restore_seconds']*1000:.1f} ms  "
      f"mode={probe['restore_mode']}  reads_ledger={probe['reads_ledger']}")
print(f"  peak RSS    {rss_mb():.1f} MB")
print(f"  host MemAvailable now {host_avail_mb():,.0f} MB")

# ---- packet root + chain --------------------------------------------
print()
print(bar)
print("PACKET ROOT + CYCLE CHAIN")
print(bar)
bad = 0
for i in range(CYCLES):
    slot = base - timedelta(minutes=(CYCLES - i))
    if not rt.verify_cycle(slot)["VALID"]:
        bad += 1
print(f"  packet roots valid      {CYCLES - bad}/{CYCLES}")
cl = [json.loads(x) for x in rt.cycle_log.read_text().splitlines()
      if x.strip()]
prev, broken = "GENESIS", 0
for r in cl:
    if r["prev_hash"] != prev:
        broken += 1
    prev = r["entry_hash"]
print(f"  cycle chain             {len(cl)} links, {broken} mismatch")

# offline tamper proof (copy, never the authoritative evidence)
tmp = Path("/tmp/gate3_tamper.jsonl")
rows_l = [json.loads(x) for x in rt.ledger.read_text().splitlines()
          if x.strip()]
slot0 = (base - timedelta(minutes=CYCLES)).isoformat()
c0 = next(r for r in cl if r["scheduled_time"] == slot0)
p0 = [r for r in rows_l if r.get("scheduled_time") == slot0]
print(f"  honest verify           {verify(c0, p0)['VALID']}")
t = json.loads(json.dumps(p0))
t[0]["packet_hash"] = "f" * 64
print(f"  substituted packet      {verify(c0, t)['VALID']} (want False)")
print(f"  deleted packet          {verify(c0, p0[:-1])['VALID']} "
      f"(want False)")

# ---- true occupancy --------------------------------------------------
print()
print(bar)
print("TRUE SLOT OCCUPANCY")
print(bar)
occ = sorted(r[3] for r in rows)


def q(a, p):
    return a[min(len(a) - 1, int(len(a) * p))]


print(f"  p50 {q(occ,.5):.1f}s  p90 {q(occ,.9):.1f}s  "
      f"p95 {q(occ,.95):.1f}s  max {occ[-1]:.1f}s")
print(f"  clock anomalies         "
      f"{sum(1 for r in rows if r[3] is not None and r[3] < 0)}")
print(f"  NOTE: slots are backdated by design in this engineering "
      f"regime, so occupancy includes the backdating offset and is "
      f"NOT a cadence verdict.")
print()
print(f"  evidence dir: {OUT}")
