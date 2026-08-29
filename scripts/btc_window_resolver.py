"""BTC WINDOW-OUTCOME RESOLVER — 24/7 predator evidence. SHADOW ONLY.

    What future distribution follows the states the incumbent BTC
    hunter is currently refusing or almost recognizing?

Every 15-minute window the frozen BTC hunter already seals a cohort
(NONE_OBSERVED / SUSCEPTIBLE_NOT_TRIGGERED / attack states) plus full
attack geometry -- direction, invalidation, R/R -- even when nothing
fires. This resolver prospectively measures what the market did NEXT
(15m / 1h / 4h, MFE/MAE), per cohort, from the Deribit mark series the
derivatives poller already captures at ~25s cadence.

It changes NOTHING: no thresholds, no candidate logic, no capital, no
risk, no trader import is even present. It reads two sealed ledgers
and writes one research ledger. The question is never "what trades
could we have invented?" -- it is the base-rate library that makes the
first violent forced-flow regime interpretable, because the resolver
existed BEFORE the episode arrived.

EPISODES, NOT HOURS: contiguous same-cohort runs are one episode; the
representative outcome is the FIRST window of the run (the sealed
field-standard convention). A weekend with no qualifying regime is
valid evidence about regime frequency, not a failure.

decision_power: PREDATOR_EVIDENCE_ONLY.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append  # noqa: E402
from apex.ops.heartbeat import Heartbeat  # noqa: E402

SERVICE = "btc-resolver"
AUTHORITY = "PREDATOR_EVIDENCE_ONLY"
DECISIONS = Path("results/btc/paper_ledger.jsonl")
DERIVS = Path("results/btc/derivatives_ledger.jsonl")
OUTCOMES = Path("results/btc/window_outcomes.jsonl")
HORIZONS_MIN = (15, 60, 240)
MATURITY_MIN = max(HORIZONS_MIN)
PRICE_TOLERANCE_S = 180        # a mark within 3 min of the target or
                               # the horizon is NOT_ESTIMABLE


def _parse_t(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def load_marks() -> list:
    """(utc, deribit mark) series from the sealed derivatives ledger."""
    out = []
    if not DERIVS.exists():
        return out
    for line in DERIVS.read_text().splitlines():
        if '"DERIBIT"' not in line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = _parse_t(r.get("known_from"))
        m = ((r.get("venues") or {}).get("DERIBIT") or {}) \
            .get("mark_price")
        if t is not None and isinstance(m, (int, float)):
            out.append((t, float(m)))
    out.sort()
    return out


def mark_at(marks: list, when: datetime) -> float | str:
    """Nearest sealed mark within tolerance -- never interpolated,
    never invented."""
    best, gap = None, None
    lo, hi = 0, len(marks)
    while lo < hi:                       # bisect on time
        mid = (lo + hi) // 2
        if marks[mid][0] < when:
            lo = mid + 1
        else:
            hi = mid
    for idx in (lo - 1, lo):
        if 0 <= idx < len(marks):
            g = abs((marks[idx][0] - when).total_seconds())
            if gap is None or g < gap:
                best, gap = marks[idx][1], g
    if best is None or gap > PRICE_TOLERANCE_S:
        return "NOT_ESTIMABLE"
    return best


def resolve(*, now: datetime | None = None,
            decisions: Path | None = None,
            outcomes: Path | None = None,
            marks: list | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    dpath = decisions or DECISIONS
    opath = outcomes or OUTCOMES
    if not dpath.exists():
        return {"resolved": 0, "why": "no decisions ledger"}
    already = set()
    if opath.exists():
        for line in opath.read_text().splitlines():
            try:
                already.add(json.loads(line).get("T"))
            except (json.JSONDecodeError, AttributeError):
                continue
    marks = marks if marks is not None else load_marks()
    resolved = pending = unmeasurable = 0
    denominator: dict[str, int] = {}
    for line in dpath.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") != "btc_paper_decision":
            continue
        T = _parse_t(r.get("T"))
        if T is None:
            continue
        cohort = r.get("cohort", "UNKNOWN")
        denominator[cohort] = denominator.get(cohort, 0) + 1
        if str(r.get("T")) in already:
            continue
        if T + timedelta(minutes=MATURITY_MIN) > now:
            pending += 1                 # maturity fence: a young
            continue                     # window is PENDING, not partial
        p0 = mark_at(marks, T)
        if p0 == "NOT_ESTIMABLE":
            unmeasurable += 1
            chain_append(opath, {
                "kind": "btc_window_outcome", "T": str(r.get("T")),
                "cohort": cohort, "eligible": False,
                "why": "no sealed mark near window start",
                "decision_power": AUTHORITY})
            continue
        geo = r.get("attack_geometry") or {}
        direction = geo.get("direction", "UNKNOWN")
        sign = 1.0 if direction == "LONG" else -1.0 \
            if direction == "SHORT" else None
        fwd = {}
        for m in HORIZONS_MIN:
            p1 = mark_at(marks, T + timedelta(minutes=m))
            fwd[f"{m}m"] = (round((p1 - p0) / p0, 6)
                            if isinstance(p1, float) else
                            "NOT_ESTIMABLE")
        window = [px for t, px in marks
                  if T <= t <= T + timedelta(minutes=MATURITY_MIN)]
        mfe = mae = "NOT_ESTIMABLE"
        if window and sign is not None:
            rets = [sign * (px - p0) / p0 for px in window]
            mfe, mae = round(max(rets), 6), round(min(rets), 6)
        chain_append(opath, {
            "kind": "btc_window_outcome", "T": str(r.get("T")),
            "cohort": cohort, "eligible": True,
            "geometry_direction": direction,
            "fwd_return": fwd,
            "aligned_mfe_4h": mfe, "aligned_mae_4h": mae,
            "mark_source": "DERIBIT mark, sealed derivatives ledger",
            "law": "cohort base rates, never invented trades; the "
                   "resolver existed before the first violent regime "
                   "so its evidence is prospective",
            "decision_power": AUTHORITY})
        resolved += 1
    return {"kind": "btc_window_resolution",
            "resolved": resolved, "pending_maturity": pending,
            "unmeasurable": unmeasurable,
            "denominator_by_cohort": denominator,
            "decision_power": AUTHORITY}


def report(outcomes: Path | None = None) -> dict:
    """Cohort base rates. Episodes = contiguous same-cohort runs;
    representative = FIRST window of the run; independence stays
    NOT_ESTIMABLE."""
    opath = outcomes or OUTCOMES
    rows = []
    if opath.exists():
        for line in opath.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "btc_window_outcome" \
                    and r.get("eligible"):
                rows.append(r)
    rows.sort(key=lambda r: r["T"])
    episodes = []                        # (cohort, first_row)
    prev = None
    for r in rows:
        if r["cohort"] != prev:
            episodes.append(r)
        prev = r["cohort"]

    def med(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(st.median(vals), 6) if vals else "NOT_ESTIMABLE"

    out = {"kind": "btc_window_report",
           "generated_utc": datetime.now(timezone.utc).isoformat(),
           "raw_windows": len(rows),
           "episodes_first_window_convention": len(episodes),
           "independent_episodes": "NOT_ESTIMABLE",
           "cohorts": {}, "decision_power": AUTHORITY,
           "law": "a weekend with no qualifying regime is valid "
                  "evidence about regime frequency; hours are not "
                  "observations; episodes are not automatically "
                  "independent"}
    for cohort in sorted({e["cohort"] for e in episodes}):
        es = [e for e in episodes if e["cohort"] == cohort]
        out["cohorts"][cohort] = {
            "episodes": len(es),
            "raw_windows": sum(1 for r in rows
                               if r["cohort"] == cohort),
            "fwd_1h_median": med([(e.get("fwd_return") or {})
                                  .get("60m") for e in es]),
            "fwd_4h_median": med([(e.get("fwd_return") or {})
                                  .get("240m") for e in es]),
            "aligned_mfe_4h_median": med([e.get("aligned_mfe_4h")
                                          for e in es]),
            "aligned_mae_4h_median": med([e.get("aligned_mae_4h")
                                          for e in es])}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--follow", action="store_true")
    a = ap.parse_args()
    if a.report:
        print(json.dumps(report(), indent=1))
        return 0
    if a.once or not a.follow:
        print(json.dumps(resolve(), indent=1))
        return 0
    beat = Heartbeat(SERVICE)
    while True:
        try:
            r = resolve()
            if r.get("resolved"):
                beat.work(f"resolved {r['resolved']} windows")
            else:
                beat.beat()
        except Exception as e:                          # noqa: BLE001
            beat.error(f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(1800)                 # windows mature 4h behind;
                                         # a half-hour pass is plenty


if __name__ == "__main__":
    sys.exit(main())
