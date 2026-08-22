"""OUTCOME RESOLUTION LOOP -- the organ that closes the learning cycle.

THE DEFECT THIS FIXES (living-organism diagnostic, 2026-08-21).
`outcomes.resolve()` was complete, no-lookahead-guarded, tested -- and
had ZERO live callers. The fourth instance of the same defect class in
this repo (expire(), rank(), persist_all() were the others): an organ
built, proven in vitro, and never connected to blood supply. The
consequence was total: every prospective episode stayed OUTCOME_PENDING
forever, the outcome corpus stayed empty forever, information lead
could never compute, the probability gates could never matter (nothing
would have asked even if they opened), and the forecast layer would
have had nothing to estimate from. The organism could see and decide
but could never LEARN.

WHAT THIS MODULE DOES each cycle:

  1. read the pattern ledger, collect episodes (pattern_id, first_seen,
     subject, family_id)
  2. for each episode x each declared horizon not yet resolved, call
     outcomes.resolve() against the subject's canonical bars
  3. persist RESOLVED / NO_EVENT / UNRESOLVABLE results to the outcome
     ledger, exactly once per (pattern_id, first_seen, horizon) --
     PENDING results are not persisted (they will be retried next
     cycle; persisting them would bloat the ledger with non-answers)

RESOLUTION IS EVIDENCE, NOT JUDGMENT. A resolved outcome says what the
market did after the pattern; whether the pattern PREDICTED it is
decided later by baselines and calibration, never here.

known_from on a resolution = when the resolution was computed (the
horizon must already have elapsed IN THE BARS, enforced inside
outcomes.resolve's no-lookahead guard).

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from apex.pattern_observatory import OBSERVATORY_POWER
from apex.pattern_observatory import memory as mem
from apex.pattern_observatory import outcomes as ocmod

# the horizon whose resolution triggers the once-per-episode information
# lead measurement (30 min: long enough for obviousness, short enough to
# resolve within a session)
LEAD_HORIZON_MIN = 30

# a horizon still uncovered this long after its end crossed a session
# boundary is terminally UNRESOLVABLE (V1 patterns are intraday)
NEVER_COVERABLE_AFTER_H = 18


def already_resolved(outcome_rows: list) -> set:
    """Keys (pattern_id, first_seen, horizon_minutes) that have a
    TERMINAL resolution on disk. PENDING never lands on disk, so
    presence == terminal."""
    done = set()
    for r in outcome_rows:
        key = (r.get("pattern_id"), r.get("episode_first_seen"),
               r.get("horizon_minutes"))
        if None not in key:
            done.add(key)
    return done


def episodes_from_ledger(pattern_rows: list) -> dict:
    """{(pattern_id, first_seen): latest row} -- one entry per episode,
    any kind (live pattern_state or episode_end), family-scoped ids."""
    out: dict = {}
    for r in pattern_rows:
        pid, fs = r.get("pattern_id"), r.get("first_seen")
        if pid and fs:
            out[(pid, fs)] = r
    return out


def run_cycle(*, bars_by_subject, now, horizons=ocmod.HORIZONS_MIN,
              pattern_rows: list | None = None,
              outcome_rows: list | None = None,
              persist=True) -> dict:
    """One resolution sweep. `bars_by_subject`: {subject: DataFrame of
    canonical bars} -- the caller supplies bars it already loaded so
    this module never invents its own data access path.

    Returns counters; persists terminal outcomes to OUTCOME_LEDGER.
    """
    pattern_rows = (pattern_rows if pattern_rows is not None
                    else mem.read(mem.PATTERN_LEDGER))
    outcome_rows = (outcome_rows if outcome_rows is not None
                    else mem.read(mem.OUTCOME_LEDGER))
    done = already_resolved(outcome_rows)
    eps = episodes_from_ledger(pattern_rows)

    counters = {"episodes": len(eps), "checked": 0, "resolved": 0,
                "no_event": 0, "unresolvable": 0, "pending": 0,
                "no_bars_for_subject": 0}
    # episodes whose LEAD_HORIZON resolution landed THIS sweep -- the
    # caller measures information lead exactly once per episode on this
    # signal (re-measuring every cycle would pseudo-replicate).
    newly_terminal: list = []

    for (pid, fs), row in eps.items():
        subject = row.get("subject")
        bars = bars_by_subject.get(subject)
        if bars is None or not len(bars):
            counters["no_bars_for_subject"] += 1
            continue
        for h in horizons:
            if (pid, fs, h) in done:
                continue
            counters["checked"] += 1
            oc = ocmod.resolve(
                pattern_id=pid, family_id=row.get("family_id", "?"),
                subject=subject, observed_at=fs, horizon_minutes=h,
                bars=bars,
                input_quality=(row.get("input_quality", {}) or {}).get(
                    "combined_quality", "UNKNOWN"),
                now=now)
            if oc.status == "PENDING":
                # SESSION-BOUNDARY TERMINAL (found by this module's own
                # test suite before first deploy): a horizon that
                # crossed the close stays PENDING forever in the
                # resolver's eyes -- its bars will never arrive -- and
                # would be re-checked every cycle for all time. Once a
                # full overnight has passed with the window still
                # uncovered, the honest terminal is UNRESOLVABLE
                # (intraday patterns do not resolve across sessions in
                # V1), persisted once, never fabricated from
                # extrapolation.
                import pandas as pd
                t1 = (pd.Timestamp(fs)
                      + pd.Timedelta(minutes=h))
                if (pd.Timestamp(now) - t1) > pd.Timedelta(
                        hours=NEVER_COVERABLE_AFTER_H):
                    oc = ocmod.resolve(
                        pattern_id=pid,
                        family_id=row.get("family_id", "?"),
                        subject=subject, observed_at=fs,
                        horizon_minutes=h,
                        bars=bars.iloc[0:0],       # force UNRESOLVABLE
                        input_quality=(row.get("input_quality", {})
                                       or {}).get("combined_quality",
                                                  "UNKNOWN"),
                        now=now)
                else:
                    counters["pending"] += 1
                    continue
            if oc.status == "NO_EVENT":
                counters["no_event"] += 1
            elif oc.status == "UNRESOLVABLE":
                counters["unresolvable"] += 1
            else:
                counters["resolved"] += 1
            if h == LEAD_HORIZON_MIN and oc.status in ("RESOLVED",
                                                       "NO_EVENT"):
                newly_terminal.append(
                    {"pattern_id": pid, "first_seen": fs,
                     "subject": subject,
                     "family_id": row.get("family_id"),
                     "status": oc.status})
            if persist:
                rec = oc.as_dict()
                # episode identity: first_seen IS the episode key half;
                # store it under its own name so already_resolved() and
                # the support/lead consumers never have to guess which
                # timestamp field means what.
                rec["episode_first_seen"] = fs
                rec["known_from"] = str(now)
                rec["birth_classification"] = row.get(
                    "birth_classification")
                rec["regime"] = row.get("regime")
                rec["decision_power"] = OBSERVATORY_POWER
                mem.append(mem.OUTCOME_LEDGER, rec)
    counters["newly_terminal"] = newly_terminal
    return counters


def outcome_corpus(outcome_rows: list, *, family_id: str,
                   horizon_minutes: int, as_of) -> dict:
    """The empirical corpus one family+horizon has EARNED, known_from-
    filtered (the same anti-lookahead law as support.py): returns,
    MFE/MAE, directions -- raw material for information lead and,
    eventually, the forecast layer. Never emits a probability."""
    import pandas as pd
    cutoff = pd.Timestamp(as_of)
    if cutoff.tz is None:
        cutoff = cutoff.tz_localize("UTC")

    # QUALITY FLAGS are append-only correction records (the ledger is
    # never rewritten): a flag row referencing (pattern_id,
    # episode_first_seen, horizon) marks named fields of an earlier
    # outcome as contaminated. First use: 2026-08-21, 16 MAE/MFE values
    # poisoned by a bad-print bar low (SPY 14:02, -3.9% single print).
    # Flagged fields are EXCLUDED from the corpus; the row's clean
    # fields (returns) still count.
    flagged: dict = {}
    for r in outcome_rows:
        if r.get("kind") == "pattern_outcome_quality_flag":
            key = (r.get("pattern_id"), r.get("episode_first_seen"),
                   r.get("horizon_minutes"))
            flagged.setdefault(key, set()).update(
                r.get("contaminated_fields", ()))

    rows = []
    for r in outcome_rows:
        if r.get("kind") == "pattern_outcome_quality_flag":
            continue
        if r.get("family_id") != family_id:
            continue
        if r.get("horizon_minutes") != horizon_minutes:
            continue
        if r.get("status") not in ("RESOLVED", "NO_EVENT"):
            continue
        kf = r.get("known_from")
        try:
            k = pd.Timestamp(kf)
            if k.tz is None:
                k = k.tz_localize("UTC")
        except (ValueError, TypeError):
            continue
        if k <= cutoff:
            bad = flagged.get((r.get("pattern_id"),
                               r.get("episode_first_seen"),
                               r.get("horizon_minutes")), set())
            if bad:
                r = {k2: (None if k2 in bad else v)
                     for k2, v in r.items()}
            rows.append(r)

    rets = [r["ret"] for r in rows if r.get("ret") is not None]

    # SAMPLE-INDEPENDENCE ACCOUNTING (operator law, 2026-08-21): one
    # corpus query is already one horizon, so horizons never multiply
    # inside it -- but ten SPY episodes in one afternoon regime are not
    # ten independent observations. n_raw and the clustering dimensions
    # are persisted so no consumer can quietly treat raw count as
    # independent count; n_effective_lower_bound = distinct sessions is
    # the pre-registered CONSERVATIVE floor (episodes within one session
    # count as one independent observation), explicitly a lower bound
    # and never a fitted effective-sample formula.
    def _sess(r):
        fs = r.get("episode_first_seen") or r.get("observed_at")
        try:
            ts = pd.Timestamp(fs)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            return str(ts.tz_convert("America/New_York").date())
        except (ValueError, TypeError):
            return None

    sessions = {_sess(r) for r in rows} - {None}
    episodes = {(r.get("pattern_id"), r.get("episode_first_seen"))
                for r in rows}
    subjects = {r.get("subject") for r in rows} - {None}

    return {
        "kind": "pattern_outcome_corpus",
        "family_id": family_id, "horizon_minutes": horizon_minutes,
        "as_of": str(cutoff), "n": len(rows),
        "n_raw": len(rows),
        "n_effective_lower_bound": len(sessions),
        "clustering": {"distinct_sessions": len(sessions),
                       "distinct_episodes": len(episodes),
                       "distinct_subjects": len(subjects)},
        "n_events": sum(1 for r in rows if r["status"] == "RESOLVED"),
        "n_no_event": sum(1 for r in rows if r["status"] == "NO_EVENT"),
        "returns": rets,
        "mfe": [r["mfe"] for r in rows if r.get("mfe") is not None],
        "mae": [r["mae"] for r in rows if r.get("mae") is not None],
        "directions": [r.get("direction") for r in rows],
        "law": "known_from-filtered; corpus is raw evidence, never a "
               "probability; n_raw never implies independence",
        "decision_power": OBSERVATORY_POWER,
    }
