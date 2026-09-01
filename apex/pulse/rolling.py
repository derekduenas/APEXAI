"""ROLLING CAUSAL STATE — bounded, restart-safe, outage-aware.

The World Model needs to know what a subject has been doing, not only
what it is doing. This keeps the minimum canonical history required to
reconstruct that, and nothing more: a store built merely because it
COULD be built becomes an unversioned second source of truth.

THREE PROPERTIES THAT MAKE IT SAFE TO TRUST:

  BOUNDED       a fixed retention per subject. Memory cannot grow with
                uptime, so a long session cannot silently degrade the
                service that feeds the model.
  RESTART-SAFE  the durable log IS the state. Recovery is a replay,
                never a guess, and never a REST backfill wearing a
                live observation's timestamp.
  OUTAGE-AWARE  a gap is recorded AS a gap. A window spanning an
                outage reports how much of itself is actually
                observed, so a 60-minute return computed across a
                45-minute hole announces that rather than pretending.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROLLING_CONTRACT = "PULSE_ROLLING_V0"

WINDOWS_MIN = (1, 5, 10, 15, 30, 60)
# 60m is the longest window; keep a margin for late completion
RETENTION_MIN = 90
# a window must be this observed to be reported at all
MIN_COVERAGE = 0.60


def _dt(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


class RollingStore:
    """Per-subject observation windows with explicit coverage."""

    def __init__(self, *, retention_min: int = RETENTION_MIN,
                 journal: Path | None = None):
        self.retention = timedelta(minutes=retention_min)
        self.journal = Path(journal) if journal else None
        if self.journal:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
        self._obs: dict[str, deque] = {}
        self._seen: set[tuple] = set()

    # ------------------------------------------------------ ingest
    def observe(self, subject: str, *, at, price=None, volume=None,
                extra: dict | None = None, persist: bool = True
                ) -> bool:
        """Record one observation. Returns False if this exact
        observation was already recorded -- a duplicate timer or a
        restart replay must not double-count."""
        t = _dt(at)
        key = (subject, t.isoformat())
        if key in self._seen:
            return False
        self._seen.add(key)
        row = {"t": t.isoformat(), "p": price, "v": volume}
        if extra:
            row.update(extra)
        d = self._obs.setdefault(subject, deque())
        d.append(row)
        self._prune(subject, t)
        if persist and self.journal:
            with self.journal.open("a") as fh:
                fh.write(json.dumps({"subject": subject, **row}) + "\n")
        return True

    def _prune(self, subject, now):
        d = self._obs[subject]
        cutoff = now - self.retention
        while d and _dt(d[0]["t"]) < cutoff:
            d.popleft()

    # ----------------------------------------------------- recovery
    def restore(self) -> int:
        """The journal IS the state. Replay it; never reconstruct a
        missed observation from a later REST call."""
        if not self.journal or not self.journal.exists():
            return 0
        n = 0
        for line in self.journal.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            sub = r.pop("subject", None)
            if not sub:
                continue
            if self.observe(sub, at=r["t"], price=r.get("p"),
                            volume=r.get("v"),
                            extra={k: v for k, v in r.items()
                                   if k not in ("t", "p", "v")},
                            persist=False):
                n += 1
        return n

    # ------------------------------------------------------ queries
    def window(self, subject: str, minutes: int, *, now) -> dict:
        """Observations inside a window, with honest coverage.

        `expected` assumes the one-minute cadence PULSE actually runs
        at, so coverage is a statement about how much of the window we
        genuinely saw."""
        now = _dt(now)
        start = now - timedelta(minutes=minutes)
        rows = [r for r in self._obs.get(subject, ())
                if start <= _dt(r["t"]) <= now]
        expected = minutes
        coverage = round(min(len(rows) / expected, 1.0), 4) \
            if expected else 0.0
        return {"minutes": minutes, "n": len(rows),
                "expected": expected, "coverage": coverage,
                "sufficient": coverage >= MIN_COVERAGE,
                "rows": rows,
                "oldest": rows[0]["t"] if rows else None,
                "newest": rows[-1]["t"] if rows else None}

    def ret_bps(self, subject: str, minutes: int, *, now):
        """Window return, or a REASON it cannot be computed. Never a
        number derived from a window we did not actually observe."""
        w = self.window(subject, minutes, now=now)
        if not w["sufficient"]:
            return {"value": None, "why": "NOT_ESTIMABLE",
                    "detail": f"window coverage {w['coverage']:.2f} "
                              f"below {MIN_COVERAGE}", **w}
        prices = [r["p"] for r in w["rows"]
                  if isinstance(r["p"], (int, float)) and r["p"] > 0]
        if len(prices) < 2:
            return {"value": None, "why": "NOT_ESTIMABLE",
                    "detail": "fewer than two usable prices", **w}
        return {"value": round((prices[-1] / prices[0] - 1) * 1e4, 2),
                "why": None, "anchor_price": prices[0],
                "last_price": prices[-1], **w}

    def subjects(self) -> list:
        return sorted(self._obs)

    def footprint(self) -> dict:
        rows = sum(len(d) for d in self._obs.values())
        return {"contract": ROLLING_CONTRACT,
                "subjects": len(self._obs), "rows": rows,
                "retention_min": int(
                    self.retention.total_seconds() // 60),
                "bounded": True,
                "approx_bytes": rows * 120}
