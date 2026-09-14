#!/usr/bin/env python
"""PREMARKET-FLIGHT-001-SYNTHETIC, R4 — the complete fake morning driven THROUGH THE PRODUCTION ENTRY POINT.

This script starts no premarket logic of its own. It sets a controlled clock, points the two declared transport
seams at frozen fixtures, and then invokes `scripts/premarket_stage.py` as a SEPARATE OS PROCESS once per stage,
exactly as the prepared launchd agents will. Everything the morning does is done by production code.

    python scripts/premarket_synthetic_morning.py --root /tmp/xyz            # the full morning
    python scripts/premarket_synthetic_morning.py --root /tmp/xyz --parity   # + the legacy oracle comparison
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

_S = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

REPO = _S.parent
CLI = "scripts/premarket_stage.py"


def env_for(root, clock_file, *, captain="apex.audit.premarket_fixture:captain",
            transport="apex.audit.premarket_fixture:transport", crash=None, extra=None):
    e = dict(os.environ)
    e["APEX_PREMARKET_ROOT"] = str(root)
    e["APEX_PREMARKET_CLOCK_FILE"] = str(clock_file)
    e["APEX_PREMARKET_TRANSPORT"] = transport
    e["APEX_PREMARKET_CAPTAIN"] = captain
    e.pop("APEX_PREMARKET_CRASH_AFTER", None)
    if crash:
        e["APEX_PREMARKET_CRASH_AFTER"] = crash
    e["PYTHONPATH"] = str(REPO)
    if extra:
        e.update(extra)
    return e


def set_clock(clock_file, h, m, *, date=None):
    from apex.audit import premarket_fixture as FX
    pathlib.Path(clock_file).write_text("%.6f" % FX.et_epoch(h, m, date or FX.TRADING_DATE))


def invoke(stage, root, clock_file, **kw):
    """One OS process, the production CLI, exactly as launchd will invoke it."""
    r = subprocess.run([sys.executable, CLI, "--stage", stage], cwd=str(REPO),
                       env=env_for(root, clock_file, **kw), capture_output=True, text=True, timeout=600)
    return {"stage": stage, "rc": r.returncode, "out": r.stdout.strip(), "err": r.stderr.strip()[-600:]}


def run_morning(root, clock_file, *, lines, captain="apex.audit.premarket_fixture:captain"):
    from apex.audit import premarket_fixture as FX
    from apex.frontier import premarket_stages as PS
    results = []
    for stage, h, m in PS.STAGE_SCHEDULE:
        set_clock(clock_file, h, m)
        r = invoke(stage, root, clock_file, captain=captain)
        results.append(r)
        for ln in r["out"].splitlines():
            lines.append("   %-18s | %s" % (stage, ln))
        if r["rc"] not in (0,):
            lines.append("   %-18s | rc=%d %s" % (stage, r["rc"], r["err"][:200]))
    set_clock(clock_file, 9, 40)
    r = invoke("reconcile", root, clock_file, captain=captain)
    results.append(r)
    for ln in r["out"].splitlines():
        lines.append("   %-18s | %s" % ("reconcile", ln))
    return results


def independent_reconstruction(root, trading_date):
    """Rebuild the sealed packet from the persisted stage artifacts WITHOUT using the finalizer's own answer.

    Reads the event log, re-hashes every link, picks the newest COMPLETED absorption, loads its packet blob,
    applies only the one documented finalization mutation (as_of_time), and recomputes the seal digest with the
    same formula seal() uses. Nothing here calls finalize() or trusts anything it recorded."""
    import hashlib
    d = pathlib.Path(root) / "journal" / trading_date
    events = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines() if x.strip()]
    prev = None
    for i, ev in enumerate(events):
        body = {k: v for k, v in ev.items() if k != "digest"}
        rec = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                        default=str).encode()).hexdigest()
        assert rec == ev["digest"], "event %d digest mismatch" % i
        assert ev["prev"] == prev, "chain break at %d" % i
        prev = ev["digest"]
    completed = [e for e in events if e["state"] == "COMPLETED"
                 and (e.get("payload") or {}).get("packet_blob") and e["stage"] != "seal"]
    newest = completed[-1]
    blob = (d / "blobs" / ("%s.json" % newest["payload"]["packet_blob"])).read_text()
    assert hashlib.sha256(blob.encode()).hexdigest() == newest["payload"]["packet_blob"]
    packet = json.loads(blob)
    seal_ev = [e for e in events if e["stage"] == "seal" and e["state"] == "COMPLETED"][-1]
    sealed_blob = (d / "blobs" / ("%s.json" % seal_ev["payload"]["sealed_blob"])).read_text()
    sealed = json.loads(sealed_blob)
    body = {k: v for k, v in sealed.items() if k != "packet_sha256"}
    recomputed = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    return {"events": len(events), "chain": "INTACT", "rebuilt_from": newest["stage"],
            "packet_blob": newest["payload"]["packet_blob"],
            "recorded_sha": seal_ev["payload"]["packet_sha256"], "recomputed_sha": recomputed,
            "agrees": recomputed == seal_ev["payload"]["packet_sha256"],
            "packet_fields_match": all(packet[k] == sealed[k] for k in packet if k != "as_of_time"),
            "as_of_time_packet": packet["as_of_time"], "as_of_time_sealed": sealed["as_of_time"]}


def run_oracle(root, clock_file, *, start_h, start_m, captain="apex.audit.premarket_fixture:captain"):
    """The legacy long-sleeping runner, in its own process, on a virtual clock."""
    set_clock(clock_file, start_h, start_m)
    r = subprocess.run([sys.executable, "-c",
                        "import sys;sys.path.insert(0,'.');from apex.audit.legacy_oracle import run;"
                        "raise SystemExit(run(sys.argv[1]))", str(clock_file)],
                       cwd=str(REPO), env=env_for(root, clock_file, captain=captain),
                       capture_output=True, text=True, timeout=900)
    return {"rc": r.returncode, "out": r.stdout.strip(), "err": r.stderr.strip()[-800:]}


def compare_packets(a: dict, b: dict) -> list:
    """Field by field, not a hash. A hash tells you THAT two things differ; it never tells you what."""
    out, keys = [], sorted(set(a) | set(b))
    for k in keys:
        if k in ("packet_sha256", "sealed"):
            continue
        va, vb = a.get(k, "<ABSENT>"), b.get(k, "<ABSENT>")
        out.append({"field": k, "same": va == vb,
                    "legacy": json.dumps(va, default=str)[:120], "staged": json.dumps(vb, default=str)[:120]})
    return out


def parity(root, lines):
    from apex.audit import premarket_fixture as FX
    from apex.frontier import premarket_stages as PS
    legacy_root, staged_root = root / "parity_legacy", root / "parity_staged"
    lclock, sclock = root / "clock.legacy", root / "clock.staged"

    lines.append("== PARITY: LEGACY RUNNER vs STAGED PRODUCTION ENTRY POINT ==")
    lines.append("   identical frozen transport, identical recorded Captain response, identical fixture world.")
    o = run_oracle(legacy_root, lclock, start_h=8, start_m=14)
    for ln in o["out"].splitlines():
        lines.append("   legacy | %s" % ln)
    if o["rc"] != 0:
        lines.append("   legacy | rc=%d %s" % (o["rc"], o["err"][:400]))
    run_morning(staged_root, sclock, lines=[])
    lines.append("   staged | five separate OS processes completed (see THE MORNING above for their output)")

    lp = json.loads((legacy_root / ("%s.json" % FX.TRADING_DATE)).read_text())
    sp = json.loads((staged_root / ("%s.json" % FX.TRADING_DATE)).read_text())
    rows = compare_packets(lp, sp)
    diff = [r for r in rows if not r["same"]]
    lines.append("")
    lines.append("   %-22s %s" % ("PACKET FIELD", "AGREE"))
    for r in rows:
        lines.append("   %-22s %s" % (r["field"], "yes" if r["same"] else "NO"))
    for r in diff:
        lines.append("      %s: legacy=%s staged=%s" % (r["field"], r["legacy"], r["staged"]))
    lines.append("   fields compared: %d   differing: %d" % (len(rows), len(diff)))

    # the derived comparisons the brick asks for by name
    def obs(p):
        return {"indices": p["indices"], "gap_map": p["gap_map"]}

    def rejections(p):
        return {k: v.get("status") for k, v in p["indices"].items()} | {
            "blind_spots": p["blind_spots"], "source_coverage": p["source_coverage"]}
    checks = [
        ("accepted source observations", obs(lp) == obs(sp)),
        ("rejection and unavailable reasons", rejections(lp) == rejections(sp)),
        ("accumulated factual state", {k: v for k, v in lp.items() if k not in ("packet_sha256",)}
         == {k: v for k, v in sp.items() if k not in ("packet_sha256",)}),
        ("packet classification (watch_map / states)", lp["watch_map"] == sp["watch_map"]),
        ("Captain input (the exact prompt)", PS.brief_prompt(lp) == PS.brief_prompt(sp)),
        ("final seal input", {k: v for k, v in lp.items() if k not in ("packet_sha256", "sealed")}
         == {k: v for k, v in sp.items() if k not in ("packet_sha256", "sealed")}),
        ("packet_sha256 (reported, not relied on)", lp["packet_sha256"] == sp["packet_sha256"]),
    ]
    lines.append("")
    for name, ok in checks:
        lines.append("   %-45s %s" % (name, "IDENTICAL" if ok else "DIFFERS"))
    lines.append("   legacy sha=%s" % lp["packet_sha256"][:16])
    lines.append("   staged sha=%s" % sp["packet_sha256"][:16])
    return all(ok for _n, ok in checks), diff


def early_start(root, lines):
    """The defect, on a controlled early-start fixture, and the repaired behaviour beside it."""
    from apex.audit import premarket_fixture as FX
    lines.append("== EARLY START: THE OLD BEHAVIOUR AND THE NEW ONE, SAME CLOCK ==")
    lines.append("   NOTE ON WHAT THIS DOES AND DOES NOT SHOW: 02:00 ET is a CONTROLLED early-start fixture.")
    lines.append("   It establishes that any sufficiently early process start makes the legacy runner absorb")
    lines.append("   hours early under the target stage's label. It does NOT establish that launchd actually")
    lines.append("   produced such a start on this host; only the disposable operating-system test can.")
    lroot, lclock = root / "early_legacy", root / "clock.early"
    o = run_oracle(lroot, lclock, start_h=2, start_m=0)
    for ln in o["out"].splitlines():
        if "absorb[" in ln or "SEALED" in ln or "ORACLE" in ln or "nothing to seal" in ln:
            lines.append("   legacy | %s" % ln)
    # WHAT THE EARLY START ACTUALLY COSTS, measured rather than asserted
    try:
        early_pkt = json.loads((lroot / ("%s.json" % FX.TRADING_DATE)).read_text())
        good_pkt = json.loads((root / "parity_legacy" / ("%s.json" % FX.TRADING_DATE)).read_text())
        import pandas as pd
        last_bar = max((v.get("last_bar_time") or "") for v in early_pkt["indices"].values())
        stale_s = (pd.Timestamp(early_pkt["as_of_time"]) - pd.Timestamp(last_bar)).total_seconds()
        lines.append("   DAMAGE, from the two sealed packets themselves:")
        lines.append("      early-start sha   %s" % early_pkt["packet_sha256"][:16])
        lines.append("      on-time sha       %s" % good_pkt["packet_sha256"][:16])
        lines.append("      same market_date=%s, same absorption_label=%s, DIFFERENT CONTENT"
                     % (early_pkt["market_date"], early_pkt["absorption_label"]))
        lines.append("      newest bar in the early packet: %s; sealed as_of %s -> the packet labelled the"
                     % (last_bar, early_pkt["as_of_time"]))
        lines.append("      09:20 ET final refresh carries data %.0f minutes old, and nothing in it says so."
                     % (stale_s / 60.0))
        lines.append("      UNKNOWN_CATALYST_MOVERS early=%s  on-time=%s"
                     % (early_pkt["watch_map"]["UNKNOWN_CATALYST_MOVERS"],
                        good_pkt["watch_map"]["UNKNOWN_CATALYST_MOVERS"]))
    except Exception as e:                                              # noqa: BLE001
        lines.append("   DAMAGE MEASUREMENT UNAVAILABLE: %s: %s" % (type(e).__name__, e))

    sroot, sclock = root / "early_staged", root / "clock.early2"
    set_clock(sclock, 2, 0)
    for stage, _h, _m in [(s, h, m) for s, h, m in __import__(
            "apex.frontier.premarket_stages", fromlist=["x"]).STAGE_SCHEDULE]:
        r = invoke(stage, sroot, sclock)
        for ln in r["out"].splitlines():
            if "disposition" in ln or "exited" in ln:
                lines.append("   staged | %s" % ln)
    return True


def observation_table(root, trading_date):
    """Each declared observation, adjudicated where PRODUCTION actually decides it.

    R2 reported all ten as PASS. That table could not have been right: the production packet builder ingests no
    news at all, so a 'macro event' and a 'hostile headline' were being adjudicated by the harness. Here every row
    names the production symbol that decides it, and rows where production has NO policy say so."""
    import pandas as pd

    from apex.audit import premarket_fixture as FX
    from apex.events.catalyst import catalyst_state
    from apex.events.cik_bridge import cik_of
    from apex.frontier import premarket_stages as PS
    packet = json.loads((pathlib.Path(root) / ("%s.json" % trading_date)).read_text())
    at_final = pd.Timestamp("%s 09:20" % trading_date, tz="America/New_York")
    at_first = pd.Timestamp("%s 08:15" % trading_date, tz="America/New_York")
    rows = []

    def add(name, expected, actual, decided_by, evidence):
        rows.append({"observation": name, "expected": expected, "actual": actual,
                     "decided_by": decided_by, "evidence": evidence,
                     "verdict": "AS DECLARED" if actual == expected else "DIFFERS"})

    mem = packet["yesterday_memory"]
    add("overnight_state", "ACCEPTED_AS_PRIOR_MEMORY",
        "ACCEPTED_AS_PRIOR_MEMORY" if mem.get("memory_sha256") else "NO_PRIOR_MEMORY",
        "assemble -> closing.load_memory", "memory_sha256=%s" % str(mem.get("memory_sha256"))[:12])

    spy = packet["indices"]["SPY.US"]
    add("premarket_price_and_volume", "ACCEPTED", "ACCEPTED" if spy.get("status") == "OK" and
        "premarket_volume" in spy else "UNAVAILABLE_%s" % spy.get("status"),
        "_premarket_state", "SPY gap_frac=%s volume=%s bars=%s"
        % (spy.get("gap_frac"), spy.get("premarket_volume"), spy.get("premarket_bars")))

    add("macro_event", "MARKED_UNAVAILABLE",
        "MARKED_UNAVAILABLE" if packet["source_coverage"]["MACRO_CALENDAR"] == "NOT_CONNECTED" else "INGESTED",
        "premarket.SOURCES", "MACRO_CALENDAR=%s; it is named in blind_spots=%s"
        % (packet["source_coverage"]["MACRO_CALENDAR"], "MACRO_CALENDAR" in packet["blind_spots"]))

    g = {a["symbol"]: a for a in packet["gap_map"]}
    add("company_catalyst", "ACCEPTED_AS_KNOWN_CATALYST",
        "ACCEPTED_AS_KNOWN_CATALYST" if g.get("NVDA.US", {}).get("catalyst_status") == "KNOWN_CATALYST"
        else str(g.get("NVDA.US", {}).get("catalyst_status")),
        "catalyst_state", "NVDA.US catalyst_status=%s" % g.get("NVDA.US", {}).get("catalyst_status"))

    synd = catalyst_state("SYND.US", at_final, cik=cik_of("SYND.US"))
    add("syndicated_duplicate", "RETAINED_BOTH_NO_DEDUPLICATION_IN_PRODUCTION",
        "RETAINED_BOTH_NO_DEDUPLICATION_IN_PRODUCTION" if len(synd.events) == 2 else
        "DEDUPLICATED_TO_%d" % len(synd.events),
        "catalyst_state", "two byte-distinct filings of one announcement -> %d event(s) retained: %s"
        % (len(synd.events), [e["accession"] for e in synd.events]))

    corr = catalyst_state("CORR.US", at_final, cik=cik_of("CORR.US"))
    forms = [e["form_type"] for e in corr.events]
    add("revision_or_retraction", "RETAINED_BOTH_NO_REVISION_LINKAGE_IN_PRODUCTION",
        "RETAINED_BOTH_NO_REVISION_LINKAGE_IN_PRODUCTION" if sorted(forms) == ["8-K", "8-K/A"]
        else "OTHER_%s" % forms,
        "catalyst_state", "forms retained=%s; no field links the amendment to the original" % forms)

    dia = packet["indices"]["DIA.US"]
    add("unavailable_source", "MARKED_UNAVAILABLE",
        "MARKED_UNAVAILABLE" if dia.get("status") != "OK" else "ACCEPTED",
        "_premarket_state", "DIA.US status=%s (the transport returned no rows)" % dia.get("status"))

    stal = catalyst_state("STAL.US", at_final, cik=cik_of("STAL.US"))
    add("stale_observation", "EXCLUDED_AS_STALE",
        "EXCLUDED_AS_STALE" if not stal.events and stal.status.startswith("NO_KNOWN_CATALYST")
        else "INCLUDED_%s" % stal.status,
        "catalyst.LOOKBACK_HOURS", "a filing 100h old is outside the real %dh window -> %s"
        % (__import__("apex.events.catalyst", fromlist=["x"]).LOOKBACK_HOURS, stal.status))

    early = catalyst_state("FUTR.US", at_first, cik=cik_of("FUTR.US"))
    late = catalyst_state("FUTR.US", at_final, cik=cik_of("FUTR.US"))
    add("future_observation", "REFUSED_AS_FUTURE",
        "REFUSED_AS_FUTURE" if not early.events and late.events else
        "NOT_REFUSED(%s/%s)" % (len(early.events), len(late.events)),
        "catalyst PIT filter on known_from_utc",
        "knowable 09:00 ET: at 08:15 -> %s; at 09:20 -> %s. The packet shows it leaving "
        "UNKNOWN_CATALYST_MOVERS between the 08:32 and 09:05 stages." % (early.status, late.status))

    v = PS.brief_verdict(FX.HOSTILE_BRIEF)
    add("hostile_headline", "REFUSED_BY_FIREWALL", v["verdict"], "premarket_stages.brief_verdict",
        "the real firewall matched %s in the Captain response" % v["firewall_hits"])
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args()
    from apex.audit import premarket_fixture as FX

    root = pathlib.Path(a.root); root.mkdir(parents=True, exist_ok=True)
    clock = root / "clock.epoch"
    world = FX.install_world(repo_root=str(REPO))
    lines = ["PREMARKET-FLIGHT-001-SYNTHETIC (R4) — driven through %s, one OS process per stage" % CLI,
             "fixture=%s trading_date=%s" % (FX.FIXTURE_ID, FX.TRADING_DATE),
             "REAL: symbol selection, assemble(), normalize_rows(), _premarket_state(), catalyst_state() with its",
             "      PIT filter and 72h/12h staleness policy, packet schema, seal(), brief firewall, journal,",
             "      run accounting, window logic, and scripts/premarket_stage.py itself.",
             "SUBSTITUTED: clock, EODHD transport, Captain transport, output root — each named in every record.",
             "fixture world: %s" % json.dumps(world, indent=1), ""]

    staged_root = root / "staged"
    lines.append("== THE MORNING ==")
    run_morning(staged_root, clock, lines=lines)

    lines.append("")
    lines.append("== THE TEN DECLARED OBSERVATIONS, ADJUDICATED WHERE PRODUCTION DECIDES THEM ==")
    lines.append("   %-27s %-46s %-46s %s" % ("OBSERVATION", "EXPECTED", "ACTUAL", "VERDICT"))
    for r in observation_table(staged_root, FX.TRADING_DATE):
        lines.append("   %-27s %-46s %-46s %s" % (r["observation"], r["expected"], r["actual"], r["verdict"]))
        lines.append("        decided by %s: %s" % (r["decided_by"], r["evidence"]))

    lines.append("")
    lines.append("== INDEPENDENT RECONSTRUCTION FROM PERSISTED ARTIFACTS ==")
    rec = independent_reconstruction(staged_root, FX.TRADING_DATE)
    for k, v in rec.items():
        lines.append("   %-22s %s" % (k, v))

    if a.parity:
        lines.append("")
        ok, diff = parity(root, lines)
        lines.append("")
        early_start(root, lines)

    out = root / "SYNTHETIC_MORNING.txt"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nwrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
