#!/usr/bin/env python
"""Resident PRIMARY_BROAD_SENSOR daemon (Alpaca, Phase 0.4). Subscribes
ALL 164 intended-universe symbols on ONE WebSocket connection (Algo
Trader Plus: unlimited symbols per connection, per Alpaca's published
plan table), persists canonical 1m bars (shared builder with EODHD),
and publishes health + UniverseCoverageState artifacts.

    python scripts/alpaca_fabric_daemon.py [--minutes 400]

CANNOT RUN YET: requires both APCA_API_KEY_ID (in Keychain) and
APCA_API_SECRET_KEY (not yet provided). Fails closed with a clear
message rather than attempting a partial/broken auth.

decision_power NONE_OBSERVATIONAL_EPOCH1 — a sensor, nothing more.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from apex.intraday.alpaca_fabric import (  # noqa: E402
    AlpacaFabricViolation, AlpacaRealtimeFabric,
)
from apex.intraday.provider_interface import AlpacaBroadProvider  # noqa: E402
from apex.ops.heartbeat import Heartbeat                       # noqa: E402

BARS_DIR = Path("data/live/alpaca_fabric/bars")
HEALTH_ARTIFACT = Path("results/intraday/alpaca_fabric_health.json")
COVERAGE_ARTIFACT = Path("results/intraday/universe_coverage.json")


def _intended_universe() -> list:
    """3 index ETFs + 11 sector ETFs + the frozen hunter scan universe
    + THE OPTIONS COMBAT UNIVERSE -- one universe, read not redeclared.

    MIG-2026-08-26-A. On 2026-08-26 this returned only 14 symbols on
    DigitalOcean, because results/hunter/scan_universe_*.json is written
    by a Mac job and does not exist there. AAPL, NVDA and MSFT are in
    the Options combat universe and were therefore absent from the tape,
    making 78 of 130 refusal observations unresolvable and confounding
    the L2 workload comparison.

    THE LAW THIS ENFORCES: every Options decision must have the causal
    underlying tape required to resolve its outcome. The combat universe
    is read from the session module, so the two can never drift.
    """
    sys.path.insert(0, "scripts")
    from hunter_forward_clock import INDEXES, SECTOR_ETF
    syms = {s.replace(".US", "") for s in INDEXES}
    syms |= {s.replace(".US", "") for s in SECTOR_ETF.values()}
    uni = sorted(Path("results/hunter").glob("scan_universe_*.json"))
    if uni:
        d = json.loads(uni[-1].read_text())
        syms |= {s.replace(".US", "") for s in d.get("symbols", {})}
    # non-negotiable floor: whatever Options will decide on today
    from options_paper_session import UNIVERSE as OPTIONS_UNIVERSE
    syms |= {s.replace(".US", "") for s in OPTIONS_UNIVERSE}
    # the EQUITY SHADOW FIELD's sealed universe (predator-evidence
    # instrumentation): the sensor captures it so the frozen hunter can
    # be evaluated broadly IN SHADOW. Capturing a symbol grants it no
    # authority -- the canonical trader's universe is PINNED to
    # EQUITY_UNIVERSE_V1 in equity_shadow_session and cannot widen by
    # a bar file appearing.
    field = Path("results/equities/field/universe_v1.json")
    if field.exists():
        try:
            syms |= set(json.loads(
                field.read_text().splitlines()[0]).get("symbols", []))
        except (json.JSONDecodeError, OSError, IndexError):
            pass          # sensor never dies because research config is bad
    return sorted(syms)


def options_universe_coverage(subscribed: list) -> dict:
    """Prove the tape can resolve every Options decision."""
    sys.path.insert(0, "scripts")
    from options_paper_session import UNIVERSE as OPTIONS_UNIVERSE
    want = {s.replace(".US", "") for s in OPTIONS_UNIVERSE}
    have = set(subscribed)
    missing = sorted(want - have)
    return {"kind": "options_universe_resolution_coverage",
            "required": sorted(want), "missing": missing,
            "coverage_fraction": round(
                (len(want) - len(missing)) / max(len(want), 1), 4),
            "verdict": "COVERED" if not missing
                       else "OPTIONS_TAPE_GAP",
            "law": "every Options decision must have the causal "
                   "underlying tape required for outcome resolution"}


def _write_json(path: Path, record: dict) -> None:
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, default=str))
    os.replace(tmp, path)


def persist_bars(fab: AlpacaRealtimeFabric, day: str) -> dict:
    """ACCUMULATING SESSION STREAM -- merge, never overwrite.

    THE 2026-08-19 EVIDENCE LOSS (P0-2). This function used to write the
    in-memory rolling tail straight over the session file every cycle.
    When the ring rolled past 400 minutes it did not merely stop
    extending the file, it ERASED the earlier bars from disk: SPY and
    QQQ finished the day with 09:30-11:39 ET simply absent, and the only
    surviving proof of the open was SessionAnchorEvidence, which exists
    precisely because this already happened once on 2026-08-18.

    A bar that has been observed is evidence. Evidence does not expire
    because a deque filled up. So: the in-memory ring is working
    storage, and this file is the durable session record. Bars are
    merged by event_time_utc, and once a minute is on disk it stays.

    The single exception is the CURRENT forming minute, whose newer
    version legitimately supersedes the older partial one -- so on a key
    collision the freshly built bar wins.
    """
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    written = {}
    for sym in fab.symbols:
        bars = fab.bars_1m(sym)
        out = BARS_DIR / f"{sym}_{day}.json"
        fresh = (json.loads(bars.to_json(orient="records", date_format="iso"))
                 if len(bars) else [])

        prior = []
        if out.exists():
            try:
                prior = (json.loads(out.read_text()) or {}).get("bars") or []
            except (json.JSONDecodeError, OSError) as e:
                # never destroy a session file we merely failed to read
                try:
                    from apex.governance.ledger_error import record as _lerr
                    _lerr(service="alpaca_fabric_daemon",
                          operation="ARTIFACT_READ", exc=e, ledger=str(out),
                          recovery_action="SKIPPED this symbol's write to "
                                          "avoid overwriting unreadable "
                                          "session evidence")
                except Exception:                           # noqa: BLE001
                    pass
                written[sym] = -1
                continue

        merged = {b.get("event_time_utc"): b for b in prior}
        merged.update({b.get("event_time_utc"): b for b in fresh})
        recs = [merged[k] for k in sorted(merged) if k]
        if not recs:
            written[sym] = 0
            continue
        _write_json(out, {"symbol": sym, "market_date": day,
                          "transport": "ALPACA_WEBSOCKET_SIP_V1",
                          "written_at_utc": str(pd.Timestamp.now(tz="UTC")),
                          "retention_model": "ACCUMULATING_SESSION_STREAM",
                          "bars_from_ring": len(fresh),
                          "bars_retained_from_disk": len(recs) - len(fresh),
                          "bars": recs})
        written[sym] = len(recs)
    return written


CONTINUITY_REFERENCE_SYMBOLS = ("SPY", "QQQ", "IWM")


def _tape_continuity(day: str) -> dict:
    """Regular-session minute continuity per reference symbol, computed
    from the PERSISTED session files -- the independent reconciliation
    Layer 2 commissioning requires. 1.0 is only possible when every
    elapsed regular-session minute is actually on disk."""
    import json as _json

    import pandas as pd
    out: dict = {}
    open_t = pd.Timestamp(f"{day} 09:30:00",
                          tz="America/New_York").tz_convert("UTC")
    close_t = pd.Timestamp(f"{day} 16:00:00",
                           tz="America/New_York").tz_convert("UTC")
    now = pd.Timestamp.now(tz="UTC")
    end = min(now.floor("min") - pd.Timedelta(minutes=2), close_t)
    if end <= open_t:
        return {"status": "PRE_OPEN"}
    expected = pd.date_range(open_t, end, freq="min", inclusive="left")
    for sym in CONTINUITY_REFERENCE_SYMBOLS:
        f = BARS_DIR / f"{sym}_{day}.json"
        if not f.exists():
            out[sym] = 0.0
            continue
        try:
            bars = _json.loads(f.read_text()).get("bars", [])
        except (ValueError, OSError):
            out[sym] = 0.0
            continue
        present = {pd.Timestamp(b["event_time_utc"]).floor("min")
                   for b in bars}
        out[sym] = round(sum(1 for m in expected if m in present)
                         / max(len(expected), 1), 4)
    out["expected_minutes"] = len(expected)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=400)
    ap.add_argument("--persist-every", type=float, default=20.0)
    a = ap.parse_args()

    universe = _intended_universe()
    cov = options_universe_coverage(universe)
    print(f"intended universe: {len(universe)} symbols", flush=True)
    print(f"options-universe coverage: {cov['verdict']} "
          f"({cov['coverage_fraction']:.0%})"
          + (f" MISSING {cov['missing']}" if cov["missing"] else ""),
          flush=True)
    if cov["missing"]:
        print("REFUSED TO START: the tape cannot resolve every Options "
              "decision", flush=True)
        return 2

    # FAIL FAST: credentials are checked synchronously here, not left to
    # surface only inside the background connection thread's _on_open
    # (where a raised AlpacaFabricViolation would just trigger a silent
    # reconnect loop -- UNAUTHORIZED forever, never a clean exit).
    from apex.intraday.alpaca_fabric import _credentials
    try:
        _credentials()
    except AlpacaFabricViolation as e:
        print(f"REFUSED TO START: {e}", flush=True)
        return 2

    fab = AlpacaRealtimeFabric(symbols=universe)
    provider = AlpacaBroadProvider(fab)
    fab.start()
    # WORK HEARTBEAT (OPS-2026-08-26-B). The fabric processed 1.68M
    # trades and 12.8M quotes on 2026-08-26 while first_work_seen()
    # read False all session, because it emitted no heartbeat at all.
    # The verifier could not distinguish PROCESS PRESENT from REAL
    # MARKET WORK PROGRESSING, and would have raised a false
    # SESSION_MISSED_START. Work here is BARS PERSISTED -- progression
    # of the actual product, never mere liveness.
    beat = Heartbeat(service="equity-fabric",
                     authority="NONE_OBSERVATIONAL")
    beat.beat()

    t_end = time.time() + a.minutes * 60
    last_report = 0.0
    while time.time() < t_end:
        time.sleep(a.persist_every)
        day = str(pd.Timestamp.now(tz="America/New_York").date())
        h = fab.health()
        try:
            written = persist_bars(fab, day)
            cov = provider.get_coverage()
            _write_json(COVERAGE_ARTIFACT, cov.as_record())
        except Exception as e:                              # noqa: BLE001
            h["persist_error"] = f"{type(e).__name__}: {e}"
            written = {}
        h["bars_persisted"] = written
        # WORK = BARS PERSISTED. A cycle that persisted nothing is
        # reported as backlog, not silently counted as progress.
        try:
            beat.work(f"persisted {len(written)} symbols",
                      backlog=max(0, len(universe) - len(written)))
        except Exception:                                   # noqa: BLE001
            pass
        # LAYER 2 COMMISSIONING (2026-08-21): TAPE CONTINUITY is its own
        # axis, reconciled against the PERSISTED bars -- Friday proved
        # coverage_fraction (symbol reachability) can read 1.0 while 26%
        # of the session's minutes are missing. The acceptance metric
        # must itself reconcile against reality: continuity = minutes
        # present on disk / regular-session minutes elapsed, for the
        # reference symbols. Health can no longer claim data_preservation
        # while multi-minute holes exist.
        try:
            h["health_axes"]["tape_continuity"] = _tape_continuity(day)
            cont = h["health_axes"]["tape_continuity"]
            fracs = [v for v in cont.values() if isinstance(v, float)]
            h["health_axes"]["tape_continuity_ok"] = (
                bool(fracs) and min(fracs) >= 0.97)
            if fracs and min(fracs) < 0.97 and h["status"] == "HEALTHY":
                h["status"] = "DEGRADED"
        except Exception as e:                          # noqa: BLE001
            h["health_axes"]["tape_continuity"] = {
                "error": f"{type(e).__name__}: {e}"}
        _write_json(HEALTH_ARTIFACT, h)
        if time.time() - last_report > 60:
            last_report = time.time()
            tot = sum(written.values()) if written else 0
            print(f"{pd.Timestamp.now(tz='UTC'):%H:%M:%S} {h['status']} "
                  f"trades={h['counters']['trades']} "
                  f"quotes={h['counters']['quote_messages']} "
                  f"bars={tot} n_sym={len(universe)}", flush=True)
    fab.stop()
    print("alpaca fabric stopped (budget reached)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
