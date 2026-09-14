#!/usr/bin/env python
"""FAILURE AND RECOVERY FLIGHTS — fourteen ways a staged morning can go wrong, each flown through the real CLI.

Every scenario below runs `scripts/premarket_stage.py` as a real OS process against the real journal. The crashes
are real process deaths (`os._exit`, no unwinding, no finally, no lock release) at real phase boundaries, injected
through the declared `APEX_PREMARKET_CRASH_AFTER` seam, which can kill a process and can do nothing else.

The two properties under test, stated before the runs: EXACTLY-ONCE ABSORPTION (no crash, duplicate, race or
retry causes one stage's data to be absorbed twice, and none causes the original captured bytes to be lost) and
IMMUTABLE SEALED OUTPUT (once a packet is sealed, no later invocation rewrites it).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

_S = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))
REPO = _S.parent

from premarket_synthetic_morning import env_for, invoke, set_clock  # noqa: E402

ROWS = []


def record(name, expected, actual, detail=""):
    ROWS.append({"scenario": name, "expected": expected, "actual": actual,
                 "verdict": "PASS" if actual == expected else "FAIL", "detail": detail})


def events(root, date):
    p = pathlib.Path(root) / "journal" / date / "events.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def absorbed_count(root, date, stage):
    return sum(1 for e in events(root, date) if e["stage"] == stage and e["state"] == "ABSORBED")


def fresh(base, name):
    r = pathlib.Path(base) / name
    if r.exists():
        import shutil
        shutil.rmtree(r)
    r.mkdir(parents=True)
    return r


def morning_to(root, clock, stages, **kw):
    from apex.frontier import premarket_stages as PS
    out = []
    for stage, h, m in PS.STAGE_SCHEDULE:
        if stage not in stages:
            continue
        set_clock(clock, h, m)
        out.append(invoke(stage, root, clock, **kw))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    a = ap.parse_args()
    from apex.audit import premarket_fixture as FX
    base = pathlib.Path(a.root); base.mkdir(parents=True, exist_ok=True)
    clock = base / "clock.epoch"
    FX.install_world(repo_root=str(REPO))
    D = FX.TRADING_DATE
    S0 = "0815_ET_initial"

    # ---------------------------------------------------------- 1-3: real process deaths at phase boundaries
    for point, before in (("capture", "NORMALIZED"), ("normalize", "ABSORBED"), ("absorb", "COMPLETED")):
        r = fresh(base, "crash_%s" % point)
        set_clock(clock, 8, 15)
        killed = invoke(S0, r, clock, crash=point)
        st_after_kill = [e["state"] for e in events(r, D) if e["stage"] == S0]
        blobs_after_kill = sorted(p.name for p in (r / "journal" / D / "blobs").glob("*.json"))
        # the stage is re-invoked, exactly as a second launchd trigger or a manual retry would
        resumed = invoke(S0, r, clock)
        st_after = [e["state"] for e in events(r, D) if e["stage"] == S0]
        blobs_after = sorted(p.name for p in (r / "journal" / D / "blobs").glob("*.json"))
        kept = set(blobs_after_kill) <= set(blobs_after)
        evs = [e for e in events(r, D) if e["stage"] == S0]
        replayed = any((e.get("payload") or {}).get("replayed_from_capture") for e in evs)
        resumed = any((e.get("payload") or {}).get("resumed_from") == "ABSORBED" for e in evs)
        no_refetch = replayed or resumed
        ok = (st_after[-1] == "COMPLETED" and absorbed_count(r, D, S0) == 1 and kept and no_refetch)
        record("crash after %s, before %s" % (point, before),
               "recovered; exactly 1 ABSORBED; original bytes reused, not refetched",
               "recovered; exactly 1 ABSORBED; original bytes reused, not refetched" if ok else
               "states=%s absorbed=%d bytes_kept=%s no_refetch=%s"
               % (st_after, absorbed_count(r, D, S0), kept, no_refetch),
               "killed rc=%d (no stdout survived the hard death; the fsync'd journal did). states before retry "
               "%s; recovery path: %s"
               % (killed["rc"], st_after_kill,
                  "replayed the recorded capture" if replayed else
                  "reused the recorded packet, no capture phase at all" if resumed else "REFETCHED"))

    # ---------------------------------------------------------- 4: duplicate stage delivery
    r = fresh(base, "duplicate")
    set_clock(clock, 8, 15)
    invoke(S0, r, clock)
    dup = invoke(S0, r, clock)
    record("duplicate stage delivery", "RECONCILED_DUPLICATE and exactly 1 absorption",
           "RECONCILED_DUPLICATE and exactly 1 absorption"
           if "RECONCILED_DUPLICATE" in dup["out"] and absorbed_count(r, D, S0) == 1
           else "out=%s absorptions=%d" % (dup["out"][-90:], absorbed_count(r, D, S0)),
           dup["out"].splitlines()[-1][:120])

    # ---------------------------------------------------------- 5: out-of-order delivery
    r = fresh(base, "out_of_order")
    set_clock(clock, 9, 5)
    o = invoke("0905_ET_refresh", r, clock)
    miss = [e for e in events(r, D) if e["stage"] == "0905_ET_refresh" and e["state"] == "STARTED"]
    record("out-of-order stage delivery", "proceeds with predecessors named MISSING",
           "proceeds with predecessors named MISSING"
           if miss and miss[0]["payload"]["missing_predecessors"] == ["0815_ET_initial", "0832_ET_post_macro"]
           else "missing=%s" % (miss[0]["payload"]["missing_predecessors"] if miss else "NO RECORD"),
           "recorded missing_predecessors=%s" % (miss[0]["payload"]["missing_predecessors"] if miss else None))

    # ---------------------------------------------------------- 6: concurrent stage processes
    r = fresh(base, "concurrent")
    set_clock(clock, 8, 15)
    procs = [subprocess.Popen([sys.executable, "scripts/premarket_stage.py", "--stage", S0], cwd=str(REPO),
                              env=env_for(r, clock), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(5)]
    outs = [p.communicate()[0] for p in procs]
    # BOTH halves matter. "No duplicate absorption" is satisfied by absorbing ZERO times, which is how this
    # scenario failed in R5 -- a losing racer poisoned the winner and the whole stage was lost. So the assertion
    # is exactly one absorption AND a COMPLETED outcome.
    states = [e["state"] for e in events(r, D) if e["stage"] == S0]
    done = "COMPLETED" in states
    record("concurrent stage processes (5)", "exactly 1 absorption AND the stage COMPLETED",
           "exactly 1 absorption AND the stage COMPLETED"
           if absorbed_count(r, D, S0) == 1 and done
           else "%d absorptions, completed=%s" % (absorbed_count(r, D, S0), done),
           "; ".join(o.strip().splitlines()[-1][:60] for o in outs if o.strip()))

    # ---------------------------------------------------------- 7: altered predecessor, old digest retained
    r = fresh(base, "altered")
    morning_to(r, clock, {S0})
    blobs = sorted((r / "journal" / D / "blobs").glob("*.json"))
    victim = max(blobs, key=lambda p: p.stat().st_size)
    original = victim.read_text()
    victim.write_text(json.dumps({"tampered": True}))
    set_clock(clock, 8, 32)
    t = invoke("0832_ET_post_macro", r, clock)
    detected = "JOURNAL_CHAIN_BROKEN" in t["out"] or "BLOB_DIGEST_MISMATCH" in t["out"]
    record("altered predecessor with retained digest", "REFUSED as JOURNAL_CHAIN_BROKEN",
           "REFUSED as JOURNAL_CHAIN_BROKEN" if detected else "NOT DETECTED (rc=%d)" % t["rc"],
           "%s -> %s" % (victim.name[:16], t["out"].splitlines()[-1][:140] if t["out"] else "no output"))
    victim.write_text(original)

    # ---------------------------------------------------------- 8: missing predecessor at the finalizer
    r = fresh(base, "missing_pred")
    morning_to(r, clock, {S0, "0920_ET_final"})
    set_clock(clock, 9, 25)
    f = invoke("seal", r, clock)
    seal_ev = [e for e in events(r, D) if e["stage"] == "seal" and e["state"] == "COMPLETED"]
    named = seal_ev and seal_ev[0]["payload"]["missing_stages"] == ["0832_ET_post_macro", "0905_ET_refresh"]
    record("missing predecessor", "seals and NAMES the missing stages",
           "seals and NAMES the missing stages" if named else "missing_stages=%s"
           % (seal_ev[0]["payload"]["missing_stages"] if seal_ev else "DID NOT SEAL"),
           "rebuilt from %s" % (seal_ev[0]["payload"]["rebuilt_from"] if seal_ev else "-"))

    # ---------------------------------------------------------- 9: finalizer invoked twice
    pkt = r / ("%s.json" % D)
    sha_before = hashlib.sha256(pkt.read_bytes()).hexdigest()
    f2 = invoke("seal", r, clock)
    sha_after = hashlib.sha256(pkt.read_bytes()).hexdigest()
    record("finalizer invoked twice", "RECONCILED_DUPLICATE; sealed bytes unchanged",
           "RECONCILED_DUPLICATE; sealed bytes unchanged"
           if "RECONCILED_DUPLICATE" in f2["out"] and sha_before == sha_after
           else "out=%s bytes_same=%s" % (f2["out"][-90:], sha_before == sha_after),
           "packet file sha %s" % sha_before[:16])

    # ---------------------------------------------------------- 10: source unavailable for one stage
    r = fresh(base, "source_down")
    set_clock(clock, 8, 15)
    u = invoke(S0, r, clock, transport="apex.audit.premarket_fixture:transport_all_unavailable")
    st = [e["state"] for e in events(r, D) if e["stage"] == S0]
    record("source unavailable for one stage", "SOURCE_UNAVAILABLE recorded, not silence",
           "SOURCE_UNAVAILABLE recorded, not silence" if "SOURCE_UNAVAILABLE" in st else "states=%s" % st,
           "rc=%d %s" % (u["rc"], u["out"].splitlines()[-1][:110] if u["out"] else ""))
    set_clock(clock, 9, 25)
    s2 = invoke("seal", r, clock)
    record("seal with every absorption failed", "NOTHING_TO_SEAL, non-zero exit, no packet written",
           "NOTHING_TO_SEAL, non-zero exit, no packet written"
           if "NOTHING_TO_SEAL" in s2["out"] and s2["rc"] != 0 and not (r / ("%s.json" % D)).exists()
           else "rc=%d out=%s packet_exists=%s" % (s2["rc"], s2["out"][:60], (r / ("%s.json" % D)).exists()),
           "matches the legacy runner's 'nothing to seal' exit")

    # ---------------------------------------------------------- 11/12: Captain timeout and invalid schema
    for cap, expect in (("captain_timeout", "CAPTAIN_TIMEOUT"), ("captain_invalid", "CAPTAIN_SCHEMA_INVALID")):
        r = fresh(base, cap)
        morning_to(r, clock, {S0})
        set_clock(clock, 9, 25)
        c = invoke("seal", r, clock, captain="apex.audit.premarket_fixture:%s" % cap)
        ev = [e for e in events(r, D) if e["stage"] == "seal" and e["state"] == "COMPLETED"]
        status = ev[0]["payload"]["captain"]["status"] if ev else "NO SEAL"
        record("Captain %s" % ("timeout" if "timeout" in cap else "invalid schema"),
               "%s; packet still sealed" % expect,
               "%s; packet still sealed" % status if ev and (r / ("%s.json" % D)).exists() else status,
               "packet sha %s" % (ev[0]["payload"]["packet_sha256"][:16] if ev else "-"))

    # ---------------------------------------------------------- 13: a stage attempted after the seal
    r = fresh(base, "post_seal")
    morning_to(r, clock, {S0})
    set_clock(clock, 9, 25)
    invoke("seal", r, clock)
    sha_before = hashlib.sha256((r / ("%s.json" % D)).read_bytes()).hexdigest()
    set_clock(clock, 9, 26)
    late = invoke("0920_ET_final", r, clock)
    sha_after = hashlib.sha256((r / ("%s.json" % D)).read_bytes()).hexdigest()
    record("stage attempted after the seal", "REFUSED_INPUT/POST_SEAL; sealed bytes unchanged",
           "REFUSED_INPUT/POST_SEAL; sealed bytes unchanged"
           if "POST_SEAL" in late["out"] and sha_before == sha_after
           else "out=%s bytes_same=%s" % (late["out"][:70], sha_before == sha_after),
           late["out"].splitlines()[-1][:120] if late["out"] else "")

    # ---------------------------------------------------------- 14: invocation far before the target
    r = fresh(base, "too_early")
    set_clock(clock, 2, 0)
    t0 = time.time()
    e = invoke(S0, r, clock)
    elapsed = time.time() - t0
    st = [x["state"] for x in events(r, D) if x["stage"] == S0]
    blobs = list((r / "journal" / D / "blobs").glob("*.json"))
    record("invocation >1h before the target", "TOO_EARLY, no fetch, returns immediately",
           "TOO_EARLY, no fetch, returns immediately"
           if "TOO_EARLY" in st and not blobs and elapsed < 30 else
           "states=%s blobs=%d elapsed=%.1fs" % (st, len(blobs), elapsed),
           "exited in %.1fs (the legacy runner would have slept 3600s and then absorbed)" % elapsed)

    lines = ["FAILURE AND RECOVERY FLIGHTS (R4) — every scenario through scripts/premarket_stage.py as a real",
             "OS process. Crashes are real process deaths at real phase boundaries.", "",
             "   %-42s %-52s %s" % ("SCENARIO", "ACTUAL", "VERDICT")]
    for r_ in ROWS:
        lines.append("   %-42s %-52s %s" % (r_["scenario"], r_["actual"][:52], r_["verdict"]))
        if r_["detail"]:
            lines.append("        %s" % r_["detail"])
    npass = sum(1 for x in ROWS if x["verdict"] == "PASS")
    lines += ["", "   %d/%d PASS" % (npass, len(ROWS))]
    out = base / "FAILURE_FLIGHTS.txt"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if npass == len(ROWS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
