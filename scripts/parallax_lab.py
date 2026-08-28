"""PARALLAX OBSERVATION LAB — live console, causal playback, stats,
historical diagnostics. RESEARCH VISIBILITY ONLY.

    WE MAY REPLAY WHAT APEX ACTUALLY BELIEVED.
    WE MAY BACKTEST DETERMINISTIC MECHANICS.
    WE MAY STUDY GENUINELY TIMESTAMPED HISTORICAL EXPECTATIONS.
    WE MAY NOT PRETEND A MODERN LLM REASONING ABOUT THE PAST
    IS A CONTEMPORANEOUS HISTORICAL FORECAST.

Commands:
    parallax live [--top N]         current prospective state + previews
    parallax replay --session S     chronological causal playback
    parallax stats                  tiered statistics, never pooled
    parallax historical-diagnostic --mode sealed|proxy|contaminated

Nothing here writes to a canonical prospective ledger. Previews go to
their own append-only ledger and may never replace or mutate a
canonical result -- a preview that later disagrees with the canonical
post-close pass is CALIBRATION INFORMATION, and both survive.

decision_power: PARALLAX_SHADOW_OBSERVATORY. Kill this process and the
organism must not notice.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.catalyst.pipeline import (BARS_ROOT, _atr,  # noqa: E402
                                    _load_bars, eligible_events)
from apex.governance.chain_ledger import chain_append  # noqa: E402
from apex.ops.orchestrator import session_bounds  # noqa: E402
from apex.ops.timebase import ET  # noqa: E402
from apex.organism import parallax as PX  # noqa: E402

PREVIEWS = Path("results/parallax/live_previews.jsonl")
HIST_SEALED = Path("results/parallax/historical_sealed.jsonl")
HIST_PROXY = Path("results/parallax/historical_contemporaneous.jsonl")
CHECKPOINTS_MIN = (15, 30, 60)

BANNER = ("PARALLAX AUTHORITY: SHADOW OBSERVATORY\n"
          "TRADING INFLUENCE:  NONE\n"
          "CAPITAL VISIBILITY: FORBIDDEN")

DEBT_ORDER = {"EXTREME": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3,
              "NONE": 4, "NOT_ESTIMABLE": 5}


def _now():
    return datetime.now(timezone.utc)


def spec_freeze() -> dict:
    """Hash the exact rules before any diagnostic run -- no changing
    rules mid-run, and the record proves it."""
    src = Path(PX.__file__).read_bytes()
    taxonomy = json.dumps([PX.VIOLATION_CLASSES, PX.DEBT_BANDS,
                           PX.RESOLUTIONS, PX.RELATIVE_FLOOR_ATR])
    try:
        release = json.loads(Path("/opt/apex/current/RELEASE.json")
                             .read_text()).get("commit", "UNKNOWN")
    except (OSError, json.JSONDecodeError):
        release = "UNKNOWN"
    return {"release_sha": release,
            "parallax_source_sha256": hashlib.sha256(src).hexdigest(),
            "taxonomy_sha256": hashlib.sha256(
                taxonomy.encode()).hexdigest(),
            "frozen_utc": _now().isoformat()}


# ------------------------------------------------------------ timeline

def _expectations(session: str, close_iso: str, symbol=None) -> list:
    exps = []
    for ev in eligible_events(session=session, close_utc=close_iso):
        d = dataclasses.asdict(ev) if dataclasses.is_dataclass(ev) \
            else ev
        exp = PX.expectation_from_event(d)
        if exp is None:
            continue
        if symbol and exp["symbol"] != symbol:
            continue
        exp["headline"] = str(d.get("headline", ""))[:90]
        exp["verification"] = d.get("verification", "UNKNOWN")
        exp["event_type"] = d.get("event_type", "UNKNOWN")
        exps.append(exp)
    return exps


def _measure_at(exp: dict, checkpoint, close, bars_cache) -> dict:
    """Classify using ONLY bars with t <= checkpoint. The as-known-at
    fence of the playback: nothing later leaks into an earlier frame."""
    cut = checkpoint.isoformat()
    bars = {}
    for s in ({exp["symbol"], exp.get("sector_etf"),
               exp.get("index_etf")} - {None}):
        bars[s] = [b for b in bars_cache(s)
                   if str(b.get("event_time_utc", ""))[:19] <=
                   cut[:19]]
    atr = _atr(bars.get(exp["symbol"], []))
    kf = datetime.fromisoformat(
        str(exp["known_from"]).replace("Z", "+00:00"))
    horizon = max(1, int((min(checkpoint, close) - kf)
                         .total_seconds() // 60))
    return PX.measure_violation(
        exp, bars_by_symbol=bars, close_utc=min(checkpoint, close),
        atr=atr if isinstance(atr, (int, float)) else -1,
        horizon_min=horizon, ledger=None)


def timeline(session: str, *, symbol=None, now_utc=None) -> list:
    """Chronological playback items from genuinely sealed artifacts.
    The expectation is read, NEVER recomputed with present knowledge."""
    b = session_bounds(session)
    if not b.get("close_utc"):
        return []
    close = b["close_utc"]
    horizon_cap = now_utc or close

    def bars_cache(s, _c={}):
        if s not in _c:
            _c[s] = _load_bars(s, session, BARS_ROOT)
        return _c[s]

    items = []
    for exp in _expectations(session, close.isoformat(), symbol):
        kf = datetime.fromisoformat(
            str(exp["known_from"]).replace("Z", "+00:00"))
        items.append({"t": kf, "stage": "EXPECTATION_SEALED",
                      "exp": exp,
                      "provenance": "ORIGINAL_PROSPECTIVE_SOURCE",
                      "sealed_at": exp["expectation_created_at"]})
        for m in CHECKPOINTS_MIN:
            cp = kf + timedelta(minutes=m)
            if cp > horizon_cap:
                items.append({"t": cp, "stage": f"CHECKPOINT_{m}m",
                              "exp": exp, "pending": True})
                continue
            v = _measure_at(exp, cp, close, bars_cache)
            items.append({"t": cp, "stage": f"CHECKPOINT_{m}m",
                          "exp": exp, "violation": v,
                          "provenance":
                          "RETROSPECTIVE_PARALLAX_DERIVATION"})
        if horizon_cap >= close:
            v = _measure_at(exp, close, close, bars_cache)
            items.append({"t": close, "stage": "SESSION_CLOSE",
                          "exp": exp, "violation": v,
                          "provenance":
                          "RETROSPECTIVE_PARALLAX_DERIVATION"})
    items.sort(key=lambda i: (i["t"], i["exp"]["parallax_id"]))
    return items


# ----------------------------------------------------------- rendering

def render(item) -> str:
    e = item["exp"]
    t = item["t"].astimezone(ET).strftime("%H:%M:%S")
    head = f"{t} ET  {e['symbol']}  [{item['stage']}]"
    lines = [head]
    if item["stage"] == "EXPECTATION_SEALED":
        lines += [
            f"  EVENT        {e['event_type']}  ({e['verification']})",
            f"  HEADLINE     {e['headline']}",
            f"  EXPECTATION  {e['expected_direction']}",
            f"  SEALED_AT    {item['sealed_at']}",
            f"  KNOWN_FROM   {e['known_from']}",
            f"  PROVENANCE   {item['provenance']}",
            "  STATUS       WAITING_FOR_REACTION"]
        return "\n".join(lines)
    if item.get("pending"):
        lines.append("  STATUS       PENDING -- horizon not matured")
        return "\n".join(lines)
    v = item["violation"]
    if not v.get("eligible"):
        lines.append(f"  STATUS       UNMEASURABLE ({v.get('why')})")
        return "\n".join(lines)
    lines += [
        f"  ACTUAL       {v['signed_return'] * 100:+.2f}%"
        f"   ({v['aligned_move_atr']:+.2f} ATR vs expectation)",
        f"  RELATIVE     sector={v['relative'].get('SECTOR')}"
        f"  index={v['relative'].get('INDEX')}",
        f"  VIOLATION    {v['violation_class']}",
        f"  DEBT         {v['expectation_debt']}",
        f"  EXPRESSIBILITY  NOT_ASSESSED",
        f"  PROVENANCE   {item['provenance']}",
        "  CAPITAL VISIBILITY: FORBIDDEN"]
    return "\n".join(lines)


# ------------------------------------------------------------ commands

def cmd_replay(a) -> int:
    print(BANNER)
    print(f"\nCAUSAL PLAYBACK {a.session} -- sealed expectations "
          "colliding with the recorded tape.\nExpectations are READ, "
          "never recomputed; each frame shows only bars with "
          "t <= frame time.\n")
    items = timeline(a.session, symbol=a.symbol)
    if not items:
        print("no eligible sealed expectations for this session")
        return 1
    prev_t = None
    for it in items:
        if a.step:
            input("\n[ENTER for next] ")
        elif not a.instant and prev_t is not None:
            gap = (it["t"] - prev_t).total_seconds() / max(a.speed, 1)
            time.sleep(min(max(gap, 0), 3.0))
        prev_t = it["t"]
        print()
        print(render(it))
    print(f"\nplayback complete: {len(items)} frames, "
          f"tier = TIER_A expectation provenance, "
          f"RETROSPECTIVE_PARALLAX_DERIVATION classifications")
    return 0


def cmd_live(a) -> int:
    print(BANNER)
    now = _now()
    session = now.astimezone(ET).strftime("%Y-%m-%d")
    b = session_bounds(session)
    if not b.get("trading_day"):
        print(f"\n{session}: not a trading day. The observatory "
              "waits; a quiet screen is valid.")
        return 0
    items = timeline(session, symbol=a.symbol, now_utc=now)
    if not items:
        print(f"\n{session}: no sealed expectations yet.")
        return 0
    # latest matured classification per expectation
    latest = {}
    for it in items:
        if it.get("violation") and it["violation"].get("eligible"):
            latest[it["exp"]["parallax_id"]] = it
    print(f"\nPARALLAX -- LIVE  {now.astimezone(ET):%H:%M:%S} ET  "
          f"({len(latest)} measurable / "
          f"{len({i['exp']['parallax_id'] for i in items})} sealed)\n")
    ranked = sorted(
        latest.values(),
        key=lambda i: (DEBT_ORDER.get(
            i["violation"]["expectation_debt"], 9),
            -abs(i["violation"]["aligned_move_atr"])))
    for it in ranked[: a.top or len(ranked)]:
        print(render(it))
        print()
        _record_preview(it)
    for it in items:
        if it["stage"] == "EXPECTATION_SEALED" and \
                it["exp"]["parallax_id"] not in latest:
            print(render(it))
            print()
    return 0


def _record_preview(item) -> None:
    """Durable preview trail: appended only when the classification
    CHANGES, labeled, and never a substitute for the canonical seal."""
    v = item["violation"]
    key = (v["parallax_id"], v["violation_class"],
           v["expectation_debt"])
    seen = set()
    if PREVIEWS.exists():
        for line in PREVIEWS.read_text().splitlines():
            try:
                r = json.loads(line)
                seen.add((r.get("parallax_id"),
                          r.get("violation_class"),
                          r.get("expectation_debt")))
            except json.JSONDecodeError:
                continue
    if key in seen:
        return
    rec = dict(v)
    rec["kind"] = "parallax_live_preview"
    rec["label"] = "PARALLAX_LIVE_PREVIEW"
    rec["law"] = ("preview may never replace or mutate the canonical "
                  "result; a preview/canonical disagreement is "
                  "calibration information and both survive")
    chain_append(PREVIEWS, rec)


def _tier_rows() -> dict:
    def rows(p, want_kind):
        if not Path(p).exists():
            return []
        out = []
        for line in Path(p).read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == want_kind and r.get("eligible"):
                out.append(r)
        return out
    return {
        "PROSPECTIVE": rows(PX.VIOLATIONS, "parallax_violation"),
        "LIVE_PREVIEW": rows(PREVIEWS, "parallax_live_preview"),
        "RETROSPECTIVE_COMMISSIONING": rows(
            "results/parallax/commissioning.jsonl",
            "parallax_violation"),
        "HISTORICAL_SEALED": rows(HIST_SEALED, "parallax_violation"),
        "HISTORICAL_CONTEMPORANEOUS": rows(HIST_PROXY,
                                           "parallax_violation"),
        "MODEL_TIME_CONTAMINATED": rows(
            "results/parallax/model_time_contaminated.jsonl",
            "parallax_violation"),
    }


def cmd_stats(a) -> int:
    print(BANNER)
    print("\nPARALLAX STATISTICS -- tiers are NEVER pooled.\n")
    for tier, vs in _tier_rows().items():
        print(f"== {tier} ==")
        if not vs:
            print("  (no observations)\n")
            continue
        acct = PX.episode_accounting(vs)
        print(f"  raw observations     {acct['raw_observations']}")
        print(f"  event-hour clusters  {acct['event_hour_clusters']}")
        print(f"  independent episodes {acct['independent_episodes']}")
        by = {}
        for v in vs:
            by[v["violation_class"]] = by.get(
                v["violation_class"], 0) + 1
        for k in sorted(by, key=by.get, reverse=True):
            print(f"    {k:<32} {by[k]}")
        if tier == "PROSPECTIVE":
            rets = [v["signed_return"] for v in vs
                    if isinstance(v.get("signed_return"), float)]
            if rets:
                print(f"  descriptive signed return: "
                      f"median {sorted(rets)[len(rets) // 2] * 100:+.2f}%"
                      f" over n={len(rets)} raw (NO significance "
                      f"claim at this n)")
        print()
    print("law: retrospective, preview, and contaminated rows can "
          "never support an edge claim.\nPARALLAX_EDGE = NOT_ESTIMABLE")
    return 0


CONTAMINATION_REFUSAL = """\
REFUSED -- MODEL TIME CONTAMINATION LAW

An expectation generated TODAY by a current LLM about a HISTORICAL
event is not a contemporaneous historical forecast: the model's
weights may already contain the outcome.

    CURRENT_LLM + HISTORICAL_EVENT
      != CONTEMPORANEOUS_HISTORICAL_EXPECTATION

If you truly want an exploratory contaminated run, pass
--allow-model-time-contaminated. Every row will be stamped
MODEL_TIME_CONTAMINATED_DIAGNOSTIC and is structurally excluded from
prospective stats, edge cohorts, promotion evidence, and tournament
eligibility. This law is permanent."""


def cmd_historical(a) -> int:
    print(BANNER)
    freeze = spec_freeze()
    print(f"\nSPEC FREEZE  release={freeze['release_sha'][:8]}  "
          f"taxonomy={freeze['taxonomy_sha256'][:12]}  "
          f"source={freeze['parallax_source_sha256'][:12]}")
    print("NO OPTIMIZATION: incumbent predeclared rules only -- no "
          "threshold/horizon/universe search.\n")
    if a.mode == "contaminated":
        if not a.allow_model_time_contaminated:
            print(CONTAMINATION_REFUSAL)
            return 3
        print("WARNING: MODEL_TIME_CONTAMINATED_DIAGNOSTIC mode.\n"
              "No contaminated generator is wired into this lab -- "
              "generation is intentionally absent. If contaminated "
              "expectations are ever produced they must be stamped "
              "MODEL_TIME_CONTAMINATED_DIAGNOSTIC and land only in "
              "results/parallax/model_time_contaminated.jsonl.")
        return 0

    b = session_bounds(a.session)
    if not b.get("close_utc"):
        print(f"{a.session} is not a trading day")
        return 1
    close = b["close_utc"].isoformat()

    if a.mode == "sealed":
        # MODE A: genuinely sealed pre-outcome expectations, replayed.
        rep = PX.observe_session(
            session=a.session, close_utc=close,
            events=eligible_events(session=a.session, close_utc=close),
            load_bars=lambda s: _load_bars(s, a.session, BARS_ROOT),
            atr_fn=_atr, label="HISTORICAL_SEALED_EXPECTATION_REPLAY",
            expectations_ledger=HIST_SEALED,
            violations_ledger=HIST_SEALED)
        rep["evidence_tier"] = ("expectation provenance "
                                "ORIGINAL_PROSPECTIVE_SOURCE; "
                                "classification retrospective")
    else:
        # MODE B: deterministic proxy -- consensus-surprise sign, no
        # LLM anywhere. Tests PARALLAX-LIKE MECHANICS, not the live
        # intelligence.
        proxies = []
        for ev in eligible_events(session=a.session, close_utc=close):
            d = dataclasses.asdict(ev)
            exp_v, act_v = d.get("expected_value"), d.get(
                "actual_value")
            if not (isinstance(exp_v, (int, float))
                    and isinstance(act_v, (int, float))
                    and act_v != exp_v):
                continue
            d["directional_expectation"] = ("POSITIVE"
                                            if act_v > exp_v
                                            else "NEGATIVE")
            d["expectation_known_from"] = d["known_from"]
            proxies.append(d)
        rep = PX.observe_session(
            session=a.session, close_utc=close, events=proxies,
            load_bars=lambda s: _load_bars(s, a.session, BARS_ROOT),
            atr_fn=_atr, label="HISTORICAL_CONTEMPORANEOUS_PROXY",
            expectations_ledger=HIST_PROXY,
            violations_ledger=HIST_PROXY)
        rep["proxy_rule"] = "COMPANY_SURPRISE_SIGN_V1 (deterministic)"
        rep["caveat"] = ("tests PARALLAX-LIKE MECHANICS, not the "
                         "complete live PARALLAX intelligence")
    rep["spec_freeze"] = freeze
    ledger = HIST_SEALED if a.mode == "sealed" else HIST_PROXY
    chain_append(ledger, rep)
    print(json.dumps(rep, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="parallax")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("live")
    p.add_argument("--top", type=int, default=None)
    p.add_argument("--symbol", default=None)
    p = sub.add_parser("replay")
    p.add_argument("--session", required=True)
    p.add_argument("--symbol", default=None)
    p.add_argument("--speed", type=float, default=600)
    p.add_argument("--step", action="store_true")
    p.add_argument("--instant", action="store_true")
    sub.add_parser("stats")
    p = sub.add_parser("historical-diagnostic")
    p.add_argument("--mode", required=True,
                   choices=("sealed", "proxy", "contaminated"))
    p.add_argument("--session", default=None)
    p.add_argument("--allow-model-time-contaminated",
                   action="store_true")
    a = ap.parse_args()
    return {"live": cmd_live, "replay": cmd_replay,
            "stats": cmd_stats,
            "historical-diagnostic": cmd_historical}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
