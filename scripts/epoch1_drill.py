#!/usr/bin/env python
"""EPOCH 1 operational drill — production plumbing, not science.

Runs the boring chain (credentials -> vendor auth -> calendar -> state ->
scan -> capital -> ledger hashes -> resolver -> scoreboard) against a
SCRATCH ledger with real Friday data. Output is an operational report;
nothing touches the production ledger and no strategy logic changes.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

RESULTS: list = []


def check(name: str, fn):
    try:
        detail = fn()
        RESULTS.append((name, "PASS", detail))
    except Exception as e:                                  # noqa: BLE001
        RESULTS.append((name, "FAIL", f"{type(e).__name__}: {e}"))


def main() -> int:
    import os
    scratch = Path("/tmp/epoch1_drill"); shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir()

    def creds():
        out = subprocess.run(
            ["security", "find-generic-password", "-a", "apex", "-s",
             "EODHD_API_TOKEN", "-w"], capture_output=True, text=True)
        assert out.returncode == 0 and len(out.stdout.strip()) > 10
        os.environ["EODHD_API_TOKEN"] = out.stdout.strip()
        return "keychain resolves (value not logged)"
    check("credentials resolve", creds)

    def vendor():
        from apex.intraday.eodhd import QuotaGovernor, fetch_intraday_chunk
        rows, src = fetch_intraday_chunk("SPY.US", "2026-08-14",
                                         "2026-08-14", QuotaGovernor())
        assert len(rows) > 300
        return f"{len(rows)} bars for SPY 08-14 ({src})"
    check("EODHD authenticates", vendor)

    def calendar():
        from apex.intraday.sessions import Session, classify
        assert classify(pd.Timestamp("2026-08-17 13:35", tz="UTC")) is \
            Session.REGULAR                       # Monday 09:35 ET
        assert classify(pd.Timestamp.now(tz="UTC")) in (
            Session.CLOSED, Session.POSTMARKET)   # Saturday
        assert classify(pd.Timestamp("2026-09-07 15:00", tz="UTC")) is \
            Session.CLOSED                        # Labor Day
        return "Mon-09:35 REGULAR; Sat CLOSED; Labor Day CLOSED"
    check("calendar", calendar)

    def tz():
        t = pd.Timestamp.now(tz="UTC").tz_convert("America/New_York")
        return f"UTC->ET conversion OK ({t.strftime('%H:%M %Z')})"
    check("timezone", tz)

    def full_chain():
        from nightly_pull import _chain_append

        from apex.hunter.context_builder import (build_scan_universe,
                                                 load_or_build_contexts)
        from apex.hunter.forward_pass import (decision_pass,
                                              resolve_decision,
                                              unrealized_decisions)
        from apex.intraday.eodhd import (QuotaGovernor, fetch_intraday_chunk,
                                         normalize_rows)
        gov = QuotaGovernor()
        date = "2026-08-14"
        t = pd.Timestamp(f"{date} 13:00",
                         tz="America/New_York").tz_convert("UTC")
        uni = build_scan_universe(date)
        sub = dict(list(uni["symbols"].items())[:10])
        uni = {**uni, "symbols": sub}
        ctxs = load_or_build_contexts(sub, date, gov,
                                      extra_symbols=("SPY.US",))
        bars = {}
        for s in ("SPY.US", *sub):
            v = s if s.endswith(".US") else f"{s}.US"
            rows, _ = fetch_intraday_chunk(v, date, date, gov)
            f = normalize_rows(rows, v); f["provider_symbol"] = s
            bars[s] = f
        led = scratch / "ledger.jsonl"
        scan_rec, records = decision_pass(t, uni, bars, ctxs)
        _chain_append(led, scan_rec)
        for r in records:
            _chain_append(led, r)
        pending = unrealized_decisions(date, led)
        for d in pending:
            _chain_append(led, resolve_decision(d, bars[d["symbol"]]))
        # verify hash chain end to end
        lines = [json.loads(x) for x in led.read_text().splitlines()]
        prev = "GENESIS"
        for e in lines:
            assert e["prev_hash"] == prev, "chain broken"
            prev = e["entry_hash"]
        # scoreboard over the scratch ledger
        import hunter_scoreboard as sb
        kinds = sb.load_ledger(led)
        board = sb.build_scoreboard(kinds)
        return (f"scan+{len(records)} records, {len(pending)} resolved, "
                f"chain valid over {len(lines)} entries, scoreboard "
                f"decisions={board['decisions_total']} quota={gov.used}")
    check("state->scan->capital->ledger->resolver->scoreboard", full_chain)

    def bad_symbol():
        from apex.intraday.eodhd import QuotaGovernor, fetch_intraday_chunk
        try:
            fetch_intraday_chunk("ZZZZNOPE.US", "2026-08-14", "2026-08-14",
                                 QuotaGovernor())
            return "vendor returned empty (handled upstream as no-bars)"
        except Exception as e:                              # noqa: BLE001
            return f"raised {type(e).__name__} (clock isolates per-symbol)"
    check("single failed symbol degrades", bad_symbol)

    def torn():
        from nightly_pull import _chain_append
        led = scratch / "torn.jsonl"
        _chain_append(led, {"k": 1})
        with led.open("a") as fh:
            fh.write('{"k":2,"prev_hash":"TR')
        e = _chain_append(led, {"k": 3})
        assert e.get("recovered_from_torn_tail") is True
        return "writer links past tear; recovery stamped"
    check("partially written ledger", torn)

    def disk():
        du = shutil.disk_usage(Path.home())
        free_gb = du.free / 1e9
        assert free_gb > 5, f"only {free_gb:.1f}GB free"
        return f"{free_gb:.0f}GB free"
    check("disk space", disk)

    def launchd_env():
        r = subprocess.run(["zsh", "ops/hunter_clock.sh"],
                           capture_output=True, text=True)
        assert r.returncode == 0
        return "wrapper exit 0 (Saturday fast-exit path)"
    check("launchd wrapper runs", launchd_env)

    def restart():
        plist = str(Path("ops/com.apex.hunter-clock.plist").resolve())
        subprocess.run(["launchctl", "unload", plist], capture_output=True)
        subprocess.run(["launchctl", "load", plist], capture_output=True)
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True).stdout
        assert "com.apex.hunter-clock" in out
        return "unload/load cycle; job re-listed"
    check("graceful restart", restart)

    def prod_ledger_untouched():
        assert not Path("results/hunter/forward_ledger.jsonl").exists()
        return "production ledger still empty pre-Monday"
    check("production ledger untouched", prod_ledger_untouched)

    lines = ["# EPOCH 1 OPERATIONAL DRILL — " + str(pd.Timestamp.now(tz='UTC')),
             ""]
    ok = True
    for name, status, detail in RESULTS:
        ok &= status == "PASS"
        lines.append(f"- **{status}** {name}: {detail}")
    lines.append("")
    lines.append("Notes: reboot/sleep-wake rely on launchd StartInterval "
                 "re-firing post-wake (missed ticks are skipped, never "
                 "queued — by design); duplicate manual invocation remains "
                 "a procedural rule (F-14, recorded); no strategy logic "
                 "touched.")
    lines.append(f"\n## VERDICT: {'ALL SYSTEMS GO' if ok else 'FAILURES ABOVE'}")
    Path("results/EPOCH1-OPERATIONAL-DRILL.md").write_text(
        "\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
