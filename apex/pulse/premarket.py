"""PREMARKET / OVERNIGHT PATH — how the subject arrived here.

A cash-session snapshot is not enough. Day 1 produced the proof:
AXTI printed roughly -1,191 bps premarket and then reversed about
1,660 bps. A packet that knew only "AXTI is up today" would have
described a completely different security from the one that actually
existed.

So the Twin carries the PATH into the session: where the subject
opened relative to yesterday, how far it travelled before the bell,
how much of that was on real volume, and what it did through the open.

THE ACCUMULATOR IS FED BY PULSE'S OWN OBSERVATIONS, not by a vendor
aggregate. That is deliberate: a provider's "premarket high" is
computed by rules we cannot see, whereas this one is exactly the high
of what PULSE actually observed, with the observation count attached
so a thin path announces its own thinness.

This is factual path information. It is NOT an alpha rule -- nothing
here says a reversal is good or bad.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.intraday.sessions import Session, classify

PREMARKET_CONTRACT = "PULSE_PREMARKET_PATH_V0"
# below this many observations the path is reported but flagged thin
MIN_OBSERVATIONS = 5


def _dt(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _session_date(t) -> str:
    """The trading date this observation belongs to, in exchange
    local terms -- a 23:00 UTC observation is still the same US day."""
    from zoneinfo import ZoneInfo
    return str(_dt(t).astimezone(ZoneInfo("America/New_York")).date())


class PremarketPath:
    """Per-subject, per-session premarket accumulation."""

    def __init__(self, journal: Path | None = None):
        self.journal = Path(journal) if journal else None
        if self.journal:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
        self._p: dict[tuple, dict] = {}

    def observe(self, subject, *, at, price, volume=None,
                persist=True):
        """Record one premarket observation. Ignored outside the
        premarket session -- the path is defined by the session, not
        by the clock."""
        t = _dt(at)
        if classify(t) is not Session.PREMARKET:
            return None
        key = (subject, _session_date(t))
        p = self._p.setdefault(key, {
            "subject": subject, "session_date": key[1],
            "first_price": price, "first_at": t.isoformat(),
            "high": price, "low": price, "last_price": price,
            "last_at": t.isoformat(), "observations": 0,
            "last_volume": volume})
        p["high"] = max(p["high"], price)
        p["low"] = min(p["low"], price)
        p["last_price"] = price
        p["last_at"] = t.isoformat()
        p["observations"] += 1
        if volume is not None:
            p["last_volume"] = volume
        if persist and self.journal:
            with self.journal.open("a") as fh:
                fh.write(json.dumps({"subject": subject,
                                     "t": t.isoformat(), "p": price,
                                     "v": volume}) + "\n")
        return p

    def restore(self) -> int:
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
            if self.observe(r["subject"], at=r["t"], price=r["p"],
                            volume=r.get("v"), persist=False):
                n += 1
        return n

    def path(self, subject, *, at, prior_close=None) -> dict:
        """The premarket path for the session `at` belongs to.

        Returns a REASON when there is no path, never an empty shape
        that could be mistaken for a flat premarket."""
        key = (subject, _session_date(at))
        p = self._p.get(key)
        if not p:
            return {"contract": PREMARKET_CONTRACT,
                    "status": "NO_PREMARKET_OBSERVATIONS",
                    "why": "PULSE observed this subject zero times "
                           "during the premarket session; that is an "
                           "absence of observation, not a flat "
                           "premarket"}
        out = {"contract": PREMARKET_CONTRACT, "status": "OBSERVED",
               "observations": p["observations"],
               "thin": p["observations"] < MIN_OBSERVATIONS,
               "first_price": p["first_price"],
               "first_at": p["first_at"],
               "high": p["high"], "low": p["low"],
               "last_price": p["last_price"], "last_at": p["last_at"],
               "range_bps": (round((p["high"] / p["low"] - 1) * 1e4, 2)
                             if p["low"] else None),
               "premarket_volume": p["last_volume"],
               "source": "PULSE_OWN_OBSERVATIONS",
               "note": "accumulated from PULSE's own premarket "
                       "observations, not a vendor aggregate whose "
                       "inclusion rules are unpublished"}
        if prior_close:
            out["overnight_first_gap_bps"] = round(
                (p["first_price"] / prior_close - 1) * 1e4, 2)
            out["premarket_return_bps"] = round(
                (p["last_price"] / prior_close - 1) * 1e4, 2)
            out["premarket_travel_bps"] = round(
                (p["last_price"] / p["first_price"] - 1) * 1e4, 2)
        return out
