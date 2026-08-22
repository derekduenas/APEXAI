"""PATTERN SUPPORT ACCUMULATOR -- closes the evidence-accumulation loop.

THE BUG THIS FIXES. From the moment the Observatory was born
(2026-08-20T01:39:33Z) until this module existed, `pattern_state.build()`
was called with no `support=` argument anywhere in the runtime. Every
`PatternState` therefore carried `prospective_n=0, distinct_sessions=0,
distinct_regimes=0, distinct_symbols=0` forever, regardless of how many
days of real observation accumulated in `pattern_ledger.jsonl`. The
probability gate (`support_sufficient()`) could never open -- not
tomorrow, not in a year -- because nothing ever read the Observatory's
own history back into itself.

This module is that read-back. It is deliberately small: read the
ledger, filter, count. It does not compute similarity/novelty/OOD
(those remain NOT_ESTIMABLE/UNKNOWN, exactly as before -- out of scope
for this fix and not requested).

THE KNOWN_FROM-SAFETY LAW (operator's explicit requirement). Support for
a pattern observed AT TIME T may only be built from prior evidence whose
OWN `known_from <= T`. The ledger file is not a snapshot frozen at T --
by the time anything reads it, later cycles may already have appended
rows with `known_from` values greater than T. Counting those would let a
pattern "know" at 10:00 how much evidence existed at 14:00, which is
lookahead of exactly the kind `apex.pattern_observatory.publication_lag`
exists to prevent for external sources. The law is identical here, just
applied to the Observatory's own memory instead of a third-party feed:

    a fact may never be used before its own known_from.

This matters far beyond today's live runtime -- it is what makes this
aggregator SAFE TO REUSE UNCHANGED for a future historical-discovery
pass over the accumulated ledger, where every row from every day already
sits on disk and an unfiltered read would silently look ahead across the
whole file.

THE HISTORICAL/PROSPECTIVE SEPARATION IS PERMANENT. `historical_n` and
`prospective_n` are computed from disjoint row sets and are never
combined, added, or allowed to substitute for one another --
`PatternState.support_sufficient()` already only reads `prospective_n`;
this module's job is only to make sure that number is ever real.

EPISODES, NOT CYCLES. The runtime persists one PatternState row roughly
every cycle a conjunction stays alive -- a 40-minute-long pattern sampled
every 20 seconds would otherwise contribute ~120 rows for ONE underlying
market episode. Counting raw rows as `prospective_n` would be
pseudo-replication: the same episode voting many times. An episode is
identified by (pattern_id, first_seen) -- `first_seen` only changes when
a conjunction newly forms, so this key is stable across an episode's
whole lifetime and distinct across genuinely separate occurrences (same
day or different days).

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from apex.pattern_observatory import OBSERVATORY_POWER
from apex.pattern_observatory.birth import (
    BACKFILLED_NEVER_PROSPECTIVE, HISTORICAL_CONTEXT, PROSPECTIVE_OBSERVATION,
)
from apex.pattern_observatory.memory import PATTERN_LEDGER, read as _read


def load_ledger(path=None) -> list:
    """Read once per cycle and share across every family's aggregation --
    not once per family. Re-parsing a growing multi-thousand-row ledger
    once per matching family per cycle would be wasted, avoidable work."""
    return _read(path or PATTERN_LEDGER)


def _episode_key(row: dict):
    return (row.get("pattern_id"), row.get("first_seen"))


def _session_date(row: dict) -> str | None:
    """The calendar (ET) date an episode started, used to count DISTINCT
    SESSIONS. Derived from first_seen so a pattern spanning midnight UTC
    is still attributed to the session it actually began in."""
    fs = row.get("first_seen")
    if not fs:
        return None
    import pandas as pd
    try:
        ts = pd.Timestamp(fs)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        return str(ts.tz_convert("America/New_York").date())
    except (ValueError, TypeError):
        return None


def aggregate(rows: list, *, family_id: str, as_of) -> dict:
    """Real cross-session support for `family_id`, as it stood AT `as_of`.

    Returns exactly the shape `pattern_state.build(support=...)` expects.
    `similarity`/`novelty`/`ood` are left at their honest defaults -- this
    module does not compute them; nothing requested that it should.
    """
    import pandas as pd

    cutoff = pd.Timestamp(as_of)
    if cutoff.tz is None:
        cutoff = cutoff.tz_localize("UTC")

    def _visible(row: dict) -> bool:
        kf = row.get("known_from")
        if not kf:
            return False
        try:
            k = pd.Timestamp(kf)
        except (ValueError, TypeError):
            return False
        if k.tz is None:
            k = k.tz_localize("UTC")
        return k <= cutoff          # THE KNOWN_FROM-SAFETY LAW

    family_rows = [r for r in rows
                  if r.get("family_id") == family_id and _visible(r)]

    prospective = {}
    historical = {}
    for r in family_rows:
        cls = r.get("birth_classification")
        key = _episode_key(r)
        if cls == PROSPECTIVE_OBSERVATION:
            # last-write-wins per episode: the most current row for an
            # ongoing episode, not a running total of its own cycles
            prospective[key] = r
        elif cls == HISTORICAL_CONTEXT:
            historical[key] = r
        # BACKFILLED_NEVER_PROSPECTIVE rows are counted in NEITHER bucket.
        # A reconstructed record must never inflate either count -- that
        # is the entire reason the birth law distinguishes it at all.

    prospective_episodes = list(prospective.values())
    sessions = {_session_date(r) for r in prospective_episodes} - {None}
    symbols = {r.get("subject") for r in prospective_episodes} - {None}
    regimes = {r.get("regime") for r in prospective_episodes} - {None}

    return {
        "kind": "pattern_support_aggregation",
        "family_id": family_id, "as_of": str(cutoff),
        "prospective_n": len(prospective_episodes),
        "historical_n": len(historical),
        "distinct_sessions": len(sessions),
        "distinct_symbols": len(symbols),
        "distinct_regimes": len(regimes),
        "similarity": {"status": "NOT_ESTIMABLE"},
        "novelty": "UNKNOWN",
        "ood": "NOT_ESTIMABLE",
        "rows_considered": len(family_rows),
        "rows_excluded_future_known_from": sum(
            1 for r in rows if r.get("family_id") == family_id
            and not _visible(r)),
        "law": "known_from-filtered: a fact is never used before it was "
               "knowable; historical_n and prospective_n are permanently "
               "disjoint and prospective_n alone gates the probability "
               "engine",
        "decision_power": OBSERVATORY_POWER,
    }
