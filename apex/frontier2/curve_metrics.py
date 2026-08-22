"""Curve observational metrics — MEASUREMENT ONLY, NO BEHAVIOR CHANGE.

The 2026-08-18 session showed Curve flipping state dozens of times per
subject (SPY 42, QQQ 58, IWM 76 state changes). The explicit standing
instruction is: DO NOT smooth it, DO NOT change thresholds, DO NOT make
it "less noisy." Instead measure duration and persistence, so Research
Memory can later determine whether they carry information.

This module reads a Curve ledger and computes descriptive statistics.
It does not import curve.py's thresholds, cannot alter a Curve state,
and produces no signal -- only counts and durations.

decision_power: NONE_FRONTIER_SHADOW.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER


@dataclass(frozen=True)
class CurveObservationalMetrics:
    subject: str
    session_date: str
    n_records: int
    state_flip_count: int
    state_durations_s: dict          # state -> total seconds occupied
    mean_state_duration_s: float | None
    median_state_duration_s: float | None
    longest_state_duration_s: float | None
    longest_state: str | None
    time_since_last_flip_s: float | None
    same_direction_duration_s: dict  # direction -> total seconds
    transition_reversal_count: int   # A->B->A round trips
    transition_persistence: float | None   # mean run length, in records
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return {"kind": "curve_observational_metrics", **asdict(self)}


def _read(path: Path, subject: str) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("subject") == subject:
            out.append(r)
    return sorted(out, key=lambda r: r.get("as_of", ""))


def compute(*, subject: str, session_date: str, ledger_path: Path,
            now) -> CurveObservationalMetrics:
    import pandas as pd
    recs = _read(Path(ledger_path), subject)
    now = pd.Timestamp(now)
    if not recs:
        return CurveObservationalMetrics(
            subject=subject, session_date=session_date, n_records=0,
            state_flip_count=0, state_durations_s={},
            mean_state_duration_s=None, median_state_duration_s=None,
            longest_state_duration_s=None, longest_state=None,
            time_since_last_flip_s=None, same_direction_duration_s={},
            transition_reversal_count=0, transition_persistence=None,
            known_from=str(now), as_of=str(now))

    times = [pd.Timestamp(r["as_of"]) for r in recs]
    states = [r.get("high_level_state") for r in recs]
    directions = [r.get("transition_direction") for r in recs]

    state_durations: dict = {}
    direction_durations: dict = {}
    for i, (t, s, d) in enumerate(zip(times, states, directions)):
        dt = ((times[i + 1] - t).total_seconds() if i + 1 < len(times) else 0.0)
        state_durations[s] = state_durations.get(s, 0.0) + dt
        direction_durations[d] = direction_durations.get(d, 0.0) + dt

    # runs of identical consecutive state
    runs, run_states = [], []
    cur, start_i = states[0], 0
    for i in range(1, len(states)):
        if states[i] != cur:
            runs.append((times[i] - times[start_i]).total_seconds())
            run_states.append(cur)
            cur, start_i = states[i], i
    runs.append((times[-1] - times[start_i]).total_seconds())
    run_states.append(cur)

    flips = len(runs) - 1
    last_flip_time = times[start_i] if flips > 0 else times[0]

    reversals = 0
    for i in range(2, len(run_states)):
        if run_states[i] == run_states[i - 2] and run_states[i] != run_states[i - 1]:
            reversals += 1

    srt = sorted(runs)
    median = (srt[len(srt) // 2] if len(srt) % 2 == 1
              else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2)
    longest_i = max(range(len(runs)), key=lambda i: runs[i])

    # mean run length measured in RECORDS (how many consecutive
    # observations a state survives) -- a persistence proxy that is
    # independent of cycle cadence.
    run_lengths, cnt = [], 1
    for i in range(1, len(states)):
        if states[i] == states[i - 1]:
            cnt += 1
        else:
            run_lengths.append(cnt)
            cnt = 1
    run_lengths.append(cnt)

    return CurveObservationalMetrics(
        subject=subject, session_date=session_date, n_records=len(recs),
        state_flip_count=flips,
        state_durations_s={k: round(v, 3) for k, v in sorted(state_durations.items())},
        mean_state_duration_s=round(sum(runs) / len(runs), 3),
        median_state_duration_s=round(median, 3),
        longest_state_duration_s=round(runs[longest_i], 3),
        longest_state=run_states[longest_i],
        time_since_last_flip_s=round((now - last_flip_time).total_seconds(), 3),
        same_direction_duration_s={k: round(v, 3)
                                   for k, v in sorted(direction_durations.items(),
                                                      key=lambda kv: str(kv[0]))},
        transition_reversal_count=reversals,
        transition_persistence=round(sum(run_lengths) / len(run_lengths), 4),
        known_from=str(times[0]), as_of=str(now))
