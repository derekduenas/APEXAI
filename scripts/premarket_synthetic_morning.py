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


def PS_schedule():
    from apex.frontier import premarket_stages as PS
    return list(PS.STAGE_SCHEDULE) + [("reconcile", 9, 40)]


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


# The thirteen fields a V1 packet carried. R5 changes the packet SCHEMA, so byte parity with the legacy runner is
# no longer an acceptance requirement -- but these thirteen must still mean exactly the same thing, and that is
# what is now compared. Everything outside this set is an INTENTIONAL ADDITION and is listed as one.
V1_FIELDS = ("kind", "yesterday_memory", "market_date", "prior_session", "as_of_time", "created_at",
             "source_coverage", "indices", "gap_map", "watch_map", "blind_spots", "decision_power",
             "absorption_label")


def compare_packets(a: dict, b: dict) -> tuple:
    """Field by field, not a hash. A hash tells you THAT two things differ; it never tells you what."""
    out = []
    for k in V1_FIELDS:
        va, vb = a.get(k, "<ABSENT>"), b.get(k, "<ABSENT>")
        out.append({"field": k, "same": va == vb,
                    "legacy": json.dumps(va, default=str)[:110], "staged": json.dumps(vb, default=str)[:110]})
    added = sorted((set(a) | set(b)) - set(V1_FIELDS) - {"packet_sha256", "sealed"})
    return out, added


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
    rows, added = compare_packets(lp, sp)
    diff = [r for r in rows if not r["same"]]
    lines.append("")
    lines.append("   SEMANTIC PARITY OVER THE THIRTEEN V1 FIELDS (byte parity is no longer required: R5 changes")
    lines.append("   the packet SCHEMA, so the two producers legitimately emit different bytes).")
    lines.append("   %-22s %s" % ("PACKET FIELD", "AGREE"))
    for r in rows:
        lines.append("   %-22s %s" % (r["field"], "yes" if r["same"] else "NO"))
    for r in diff:
        lines.append("      %s: legacy=%s staged=%s" % (r["field"], r["legacy"], r["staged"]))
    lines.append("   V1 fields compared: %d   differing: %d" % (len(rows), len(diff)))
    lines.append("")
    lines.append("   INTENTIONAL ADDITIONS in PREMARKET_CONTEXT_PACKET_V2 (present in both producers, because")
    lines.append("   both call the same authoritative absorb):")
    for k in added:
        lines.append("      %-24s legacy=%s staged=%s" % (k, k in lp, k in sp))

    # the derived comparisons the brick asks for by name
    def obs(p):
        return {"indices": p["indices"], "gap_map": p["gap_map"]}

    def rejections(p):
        return {k: v.get("status") for k, v in p["indices"].items()} | {
            "blind_spots": p["blind_spots"], "source_coverage": p["source_coverage"]}
    checks = [
        ("accepted source observations", obs(lp) == obs(sp)),
        ("source_observations table", lp.get("source_observations") == sp.get("source_observations")),
        ("time block", lp.get("time") == sp.get("time")),
        ("rejection and unavailable reasons", rejections(lp) == rejections(sp)),
        ("accumulated factual state (V1 fields)",
         {k: lp.get(k) for k in V1_FIELDS} == {k: sp.get(k) for k in V1_FIELDS}),
        ("packet classification (watch_map / states)", lp["watch_map"] == sp["watch_map"]),
        ("Captain input (the exact prompt)", PS.brief_prompt(lp) == PS.brief_prompt(sp)),
        ("final seal input (V1 fields)",
         {k: lp.get(k) for k in V1_FIELDS} == {k: sp.get(k) for k in V1_FIELDS}),
        ("packet_sha256 (reported, NOT an acceptance requirement)",
         lp["packet_sha256"] == sp["packet_sha256"]),
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
        lines.append("   CONSEQUENCE: EARLY OBSERVATIONS MISREPRESENTED AS FINAL-PREMARKET OBSERVATIONS.")
        lines.append("")
        lines.append("   A CORRECTION TO THE R4 REPORT, which overstated this. The 03:00 ET catalyst")
        lines.append("   classifications were NOT intrinsically false: at 03:00 the NVDA, SYND and FUTR filings")
        lines.append("   were genuinely not yet knowable, and NO_KNOWN_CATALYST was the correct point-in-time")
        lines.append("   answer for that instant. Nothing was fabricated. The defect is that those correct")
        lines.append("   EARLY observations were stored under the 09:20-final stage identity and packet context,")
        lines.append("   where a reader is entitled to read them as the state of the world at 09:20. The")
        lines.append("   misrepresentation is in the LABEL and the CONTEXT, not in the classification.")
        lines.append("")
        lines.append("      early-start sha   %s" % early_pkt["packet_sha256"][:16])
        lines.append("      on-time sha       %s" % good_pkt["packet_sha256"][:16])
        lines.append("      same market_date=%s, same absorption_label=%s, DIFFERENT CONTENT"
                     % (early_pkt["market_date"], early_pkt["absorption_label"]))
        lines.append("      newest bar in the early packet: %s; sealed as_of %s -- %.0f minutes apart"
                     % (last_bar, early_pkt["as_of_time"], stale_s / 60.0))
        lines.append("      UNKNOWN_CATALYST_MOVERS early=%s"
                     % (early_pkt["watch_map"]["UNKNOWN_CATALYST_MOVERS"],))
        lines.append("                             on-time=%s"
                     % (good_pkt["watch_map"]["UNKNOWN_CATALYST_MOVERS"],))
        lines.append("      -- correct for 03:00-06:00 ET; wrong to present as the 09:20 final refresh.")
        lines.append("")
        lines.append("   WHAT R5 CHANGES ABOUT THIS. Under PREMARKET_CONTEXT_PACKET_V2 the same early packet")
        lines.append("   CARRIES ITS OWN CONTRADICTION, because the instants are now separate fields:")
        et_ = early_pkt.get("time") or {}

        def _et(v):
            return (pd.Timestamp(v, unit="s", tz="America/New_York").strftime("%H:%M ET")
                    if isinstance(v, (int, float)) else v)
        lines.append("      time.packet_data_cutoff        %s   <- when this packet stopped accepting input"
                     % _et(et_.get("packet_data_cutoff")))
        lines.append("      time.latest_accepted_known_from %s  <- the newest thing that actually got in"
                     % _et(et_.get("latest_accepted_known_from")))
        lines.append("      time.packet_sealed_at          %s   <- when it was sealed" % _et(et_.get("packet_sealed_at")))
        lines.append("      as_of_time                     %s   (means PACKET_SEALED_AT, and now says so)"
                     % early_pkt["as_of_time"])
        gap = (et_.get("packet_sealed_at", 0) - et_.get("packet_data_cutoff", 0)
               if isinstance(et_.get("packet_sealed_at"), (int, float)) else 0)
        lines.append("      A reader comparing the cutoff with the seal instant sees a %.0f-minute gap on a"
                     % (gap / 60.0))
        lines.append("      packet labelled the final refresh. In V1 there was one field and no way to ask.")
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


def time_verification(root, trading_date, lines):
    """Independently re-derive every instant the packet claims, from the FIXTURE's declared ground truth and the
    journal -- never from the packet's own time block. A packet that grades its own timestamps proves nothing."""
    import pandas as pd

    from apex.audit import premarket_fixture as FX
    from apex.frontier import premarket as PM
    from apex.frontier import premarket_stages as PS
    pkt = json.loads((pathlib.Path(root) / ("%s.json" % trading_date)).read_text())
    t = pkt["time"]
    rows = []

    def ck(name, expected, actual):
        ok = (expected == actual) or (isinstance(expected, float) and isinstance(actual, float)
                                      and abs(expected - actual) < 1e-6)
        rows.append({"check": name, "expected": expected, "actual": actual, "ok": ok})

    def et(h, m):
        return FX.et_epoch(h, m, trading_date)

    final_stage, fh, fm = PS.ABSORB_STAGES[-1]
    seal_h, seal_m = PS.STAGES["seal"]

    ck("schema is the new version", PM.PACKET_SCHEMA_V2, pkt.get("schema"))
    ck("morning_started_at = first stage instant", et(*PS.STAGES[PS.ABSORB_STAGES[0][0]]), t["morning_started_at"])
    ck("collection_started_at = sealing stage's own start", et(fh, fm), t["packet_collection_started_at"])
    ck("declared information cutoff = that stage's absorption end", et(fh, fm), t["packet_data_cutoff"])
    ck("latest accepted content known_from", et(fh, fm), t["latest_accepted_known_from"])
    ck("ai_request_time = the seal stage instant", et(seal_h, seal_m), t["ai_request_time"])
    ck("ai_response_time = the seal stage instant", et(seal_h, seal_m), t["ai_response_time"])
    ck("packet_created_at = absorption end", et(fh, fm), t["packet_created_at"])
    ck("packet_sealed_at = the seal stage instant", et(seal_h, seal_m), t["packet_sealed_at"])
    ck("packet_known_from = packet_sealed_at", t["packet_sealed_at"], t["packet_known_from"])
    ck("as_of_time resolves to packet_sealed_at",
       pd.Timestamp(pkt["as_of_time"]).timestamp(), t["packet_sealed_at"])
    ck("as_of_time_semantics declares that", "PACKET_SEALED_AT", pkt["as_of_time_semantics"]["means"])

    # per-source: SEC's newest CONTENT is the FUTR filing, knowable at 09:00 ET by the fixture's own declaration
    ck("SEC_EDGAR newest content known_from", et(9, 0), t["per_source_known_from"]["SEC_EDGAR"])
    ck("SEC_EDGAR freshness at cutoff", et(fh, fm) - et(9, 0), t["per_source_freshness_s"]["SEC_EDGAR"])
    ck("SEC_EDGAR last probed at the stage instant", et(fh, fm), t["per_source_last_probe"]["SEC_EDGAR"])
    ck("EODHD newest content known_from", et(fh, fm), t["per_source_known_from"]["EODHD_PREMARKET"])
    ck("EODHD freshness at cutoff", 0.0, t["per_source_freshness_s"]["EODHD_PREMARKET"])

    # per-observation: every SEC content observation's known_from must be the fixture's declared availability
    declared = {}
    for e in FX._edgar_events():
        declared[e["accession"]] = pd.Timestamp(e["known_from_utc"]).timestamp()
    mismatched = []
    for o in pkt["source_observations"]:
        if o["source_kind"] == "SEC_EDGAR" and o.get("carries_content"):
            acc = str(o["source_id"]).split(":", 1)[-1]
            if acc in declared and abs(declared[acc] - o["source_known_from"]) > 1e-6:
                mismatched.append(acc)
    ck("every SEC observation carries the filing's declared availability", [], mismatched)
    ck("every observation names its timezone", [],
       [o["source_id"] for o in pkt["source_observations"] if o["source_timezone"] == "UNAVAILABLE"])
    ck("every observation names its availability basis", [],
       [o["source_id"] for o in pkt["source_observations"] if not o.get("availability_basis")])

    # stage identity
    st = pkt["stage_time"]
    ck("stage_time names the sealing stage's source stage", final_stage, st["stage"])
    ck("stage target instant", et(fh, fm), st["target_epoch"])
    ck("stage lateness", 0.0, st["lateness_s"])

    # the digest, recomputed with seal()'s own formula
    import hashlib
    body = {k: v for k, v in pkt.items() if k != "packet_sha256"}
    ck("final packet digest recomputes", pkt["packet_sha256"],
       hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest())
    ck("the time block is INSIDE the digest", False,
       hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != "time"}, sort_keys=True,
                                 default=str).encode()).hexdigest() == pkt["packet_sha256"])

    lines.append("== INDEPENDENT TIME RECONSTRUCTION (expectations derived from the fixture, not the packet) ==")
    for r in rows:
        lines.append("   %-52s %-22s %-22s %s"
                     % (r["check"], str(r["expected"])[:22], str(r["actual"])[:22],
                        "OK" if r["ok"] else "MISMATCH"))
    bad = [r for r in rows if not r["ok"]]
    lines.append("   %d/%d checks agree" % (len(rows) - len(bad), len(rows)))
    return not bad


def future_input_proof(root, trading_date, lines):
    """A provider-declared FUTURE input must not reach the packet's facts or the Captain prompt. Its REFUSAL must
    be on the record -- the two are different requirements and both are checked."""
    from apex.audit import premarket_fixture as FX
    from apex.frontier import premarket_stages as PS
    pkt = json.loads((pathlib.Path(root) / ("%s.json" % trading_date)).read_text())
    sym = FX.FUTURE_AVAILABLE_SYMBOL
    fact_fields = ("indices", "gap_map", "watch_map", "blind_spots", "source_coverage", "yesterday_memory")
    lines.append("== A PROVIDER-DECLARED FUTURE INPUT (%s, stamped available %02d:%02d ET) ==" %
                 (sym, *FX.FUTURE_AVAILABLE_AT_ET))
    for f in fact_fields:
        lines.append("   %-24s contains it: %s" % (f, sym.split(".")[0] in json.dumps(pkt[f])))
    prompt = PS.brief_prompt(pkt)
    lines.append("   %-24s contains it: %s" % ("the Captain prompt", sym.split(".")[0] in prompt))
    obs = [o for o in pkt["source_observations"] if sym in str(o["source_id"])]
    lines.append("   %-24s contains it: %s   <- the REFUSAL is recorded, which is the requirement"
                 % ("source_observations", bool(obs)))
    lines.append("   normalization: %s" % (obs[0]["normalization"] if obs else "NO RECORD"))
    ok = (not any(sym.split(".")[0] in json.dumps(pkt[f]) for f in fact_fields)
          and sym.split(".")[0] not in prompt and obs and obs[0]["normalization"] == "REFUSED_AS_FUTURE")
    lines.append("   VERDICT: %s" % ("REFUSED AT THE BOUNDARY, RECORDED, NEVER IN THE FACTS" if ok else "FAILED"))
    return ok


def late_stage_proof(root, clock, lines):
    """A stage that starts late but inside its window must absorb AND keep its ACTUAL time visible. Backdating a
    late stage to its target is the exact failure mode the old runner had in reverse."""
    from apex.audit import premarket_fixture as FX
    from apex.frontier import premarket_stages as PS
    r = pathlib.Path(root)
    stage = "0832_ET_post_macro"
    h, m = PS.STAGES[stage]
    set_clock(clock, 8, 15)
    invoke("0815_ET_initial", r, clock)
    set_clock(clock, h, m + 5)                    # five minutes late: inside the ten-minute window
    out = invoke(stage, r, clock)
    set_clock(clock, 9, 25)
    invoke("seal", r, clock)
    pkt = json.loads((r / ("%s.json" % FX.TRADING_DATE)).read_text())
    st = pkt["stage_time"]
    lines.append("== A LATE-BUT-ALLOWED STAGE (%s started 5 minutes after target) ==" % stage)
    lines.append("   disposition            %s" % st["disposition"])
    lines.append("   target_instant         %s" % st["target_instant"])
    lines.append("   process_started_market %s   <- the ACTUAL start, not the target" % st["process_started_market"])
    lines.append("   lateness_s             %s" % st["lateness_s"])
    lines.append("   window_closes          %s" % st["window_closes"])
    lines.append("   packet_data_cutoff     %s" % pkt["time"]["packet_data_cutoff"])
    ok = (st["disposition"] == "LATE_START" and abs(st["lateness_s"] - 300.0) < 1.0
          and st["process_started_market"] != st["target_instant"])
    lines.append("   VERDICT: %s" % ("LATE START RECORDED AT ITS ACTUAL TIME, NOT BACKDATED" if ok else "FAILED"))
    return ok


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

    lines.append("== MARKET TIME VS LOCAL TIME (the scheduler fires local; every target is a market instant) ==")
    from apex.frontier import market_time as MT
    host = MT.host_timezone()
    nxt = MT.next_market_session()
    lines.append("   host timezone        %s   (%s: %s)" % (host["name"], host["source"], host["evidence"]))
    lines.append("   market timezone      %s   (authoritative)" % MT.MARKET_TZ)
    lines.append("   tracks the market    %s" % MT.offset_is_stable(host["name"]))
    lines.append("   next market session  %s" % nxt)
    lines.append("   %-20s %-11s %-8s %-26s %-8s %s"
                 % ("STAGE", "MARKET", "LOCAL", "UTC INSTANT", "MKT-LOC", "ALL-YEAR TRIGGERS"))
    for r in MT.schedule_table(list(PS_schedule()), host["name"], nxt):
        lines.append("   %-20s %-11s %-8s %-26s %+-8.1f %s"
                     % (r["stage"], r["market_time"] + " ET", r["local_time"], r["utc_instant"],
                        r["market_minus_local_hours"], ", ".join("%02d:%02d" % t for t in r["triggers_all_year"])))
    lines.append("")

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
    time_verification(staged_root, FX.TRADING_DATE, lines)
    lines.append("")
    future_input_proof(staged_root, FX.TRADING_DATE, lines)
    lines.append("")
    late_stage_proof(root / "late", root / "clock.late", lines)

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
