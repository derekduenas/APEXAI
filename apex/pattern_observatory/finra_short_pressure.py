"""FINRA DAILY SHORT-SALE VOLUME -- short PRESSURE, not short INTEREST.

THE DISTINCTION THAT MUST NEVER BLUR, and FINRA itself says so on the
dataset page: short-sale VOLUME is not short INTEREST, and this file is
not a consolidated view of all trading. It covers FINRA-reported
OFF-EXCHANGE (ATS + non-ATS OTC) executions only.

  short volume    how much of today's off-exchange tape was sold short.
                  A market maker hedging a customer buy prints a short.
                  High short volume is often LIQUIDITY PROVISION, not
                  bearish conviction.
  short interest  how many shares are actually held short. Bi-monthly,
                  ~2 weeks lagged, and APEX does not have it.

So this module produces a `ShortPressureState`, never a "crowded short"
verdict. Crowding requires short INTEREST plus borrow, and both remain
UNAVAILABLE. Reporting one as the other would be the single easiest way
for this system to fool itself about who is trapped.

SOURCE: cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt --
verified live 2026-08-19, 12,274 symbols, pipe-delimited.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from apex.pattern_observatory import OBSERVATORY_POWER, WRITE_ROOT
from apex.pattern_observatory import publication_lag as plag

URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
CACHE_DIR = Path(WRITE_ROOT) / "positioning" / "finra"
CA_BUNDLE = "/etc/ssl/cert.pem"
# FINRA's CDN returns 403 to a bare urllib request but 200 to curl --
# it filters on User-Agent. Identifying the client honestly is the
# correct fix; spoofing a browser would be both fragile and rude to a
# free public data source.
USER_AGENT = "APEX-PatternObservatory/1.0 (research; contact via repo)"

SCOPE = "FINRA_OFF_EXCHANGE_ONLY"
NOT_SHORT_INTEREST = ("short-sale VOLUME is not short INTEREST and this feed "
                      "is off-exchange only; it does not measure how many "
                      "shares are held short")

STATES = ("ELEVATED_SHORT_PRESSURE", "NORMAL", "LOW_SHORT_PRESSURE",
          "NOT_ESTIMABLE")

# DECLARED, pre-registered. The typical off-exchange short ratio sits
# near 0.5 because market-making prints both sides; these bands describe
# deviation from that structural baseline, not conviction.
ELEVATED = 0.60
LOW = 0.38
MIN_VOLUME = 50_000
MIN_HISTORY_DAYS = 20


class FinraError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShortPressureState:
    symbol: str
    session_date: str
    short_volume: float | None
    total_volume: float | None
    short_ratio: float | None
    short_exempt: float | None
    ratio_percentile: float | None
    ratio_change_1d: float | None
    state: str
    scope: str
    history_days: int
    known_from: str
    caveat: str = NOT_SHORT_INTEREST

    def as_dict(self) -> dict:
        return {"kind": "short_pressure_state", **self.__dict__,
                "is_short_interest": False,
                "is_crowding_verdict": False,
                "consolidated_tape": False,
                "decision_power": OBSERVATORY_POWER}


def latest_published(*, as_of, max_lookback_days: int = 6) -> dict:
    """The most recent FINRA file that has LEGITIMATELY published.

    THE CORRECTION THIS IMPLEMENTS. During a live session the file for
    TODAY does not exist yet -- it publishes after the close. Treating
    that as a fetch failure writes noise into the error ledger that looks
    operationally meaningful the next morning. Expected publication
    latency is NOT an error.

    So: ask the publication policy which sessions could possibly have
    published, walk back from the most recent one, and report the state
    honestly. A genuine network or parse fault is still a failure and is
    still reported as one -- the point is to separate the two, not to
    swallow both.
    """
    import pandas as pd

    a = pd.Timestamp(as_of)
    if a.tz is None:
        a = a.tz_localize("UTC")
    a_et = a.tz_convert("America/New_York")
    today = a_et.normalize()

    attempted, failures = [], []
    for back in range(0, max_lookback_days + 1):
        d = today - pd.Timedelta(days=back)
        if d.weekday() >= 5:                     # weekend, no session
            continue
        state = plag.classify_source_state(
            "FINRA_SHORT_VOLUME", latest_event_date=None, as_of=a_et,
            requested_date=d)
        if state["source_state"] == plag.NOT_YET_PUBLISHED:
            attempted.append({"date": str(d.date()),
                              "state": plag.NOT_YET_PUBLISHED,
                              "publishes_at": state["publishes_at"]})
            continue
        try:
            rows = fetch_day(d.strftime("%Y%m%d"))
        except FinraError as e:
            # distinguish "the file is not there" (expected on a holiday)
            # from a real transport fault
            failures.append({"date": str(d.date()), "error": str(e)[:120]})
            attempted.append({"date": str(d.date()),
                              "state": plag.FETCH_FAILED})
            continue
        cls = plag.classify_source_state(
            "FINRA_SHORT_VOLUME", latest_event_date=d, as_of=a_et)
        return {"kind": "finra_latest_published", "rows": rows,
                "market_date": str(d.date()),
                "known_from": str(plag.publication_time(
                    "FINRA_SHORT_VOLUME", d)),
                "source_state": cls["source_state"],
                "is_expected": cls["is_expected"],
                "is_error": plag.is_error(cls["source_state"]),
                "staleness_days": cls.get("staleness_days"),
                "attempted": attempted, "failures": failures,
                "symbols": len(rows),
                "decision_power": OBSERVATORY_POWER}

    # nothing published in the whole window -- THAT is a real failure
    return {"kind": "finra_latest_published", "rows": {},
            "market_date": None, "known_from": None,
            "source_state": (plag.FETCH_FAILED if failures
                             else plag.SOURCE_UNAVAILABLE),
            "is_expected": False, "is_error": True,
            "attempted": attempted, "failures": failures, "symbols": 0,
            "decision_power": OBSERVATORY_POWER}


def fetch_day(date_yyyymmdd: str, *, timeout: float = 25.0) -> dict:
    """{symbol: row}. Raises rather than returning empty -- an empty dict
    is indistinguishable from a market holiday."""
    url = URL.format(date=date_yyyymmdd)
    ctx = ssl.create_default_context(cafile=CA_BUNDLE)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
    except Exception as e:                                  # noqa: BLE001
        raise FinraError(f"FINRA fetch failed for {date_yyyymmdd}: "
                         f"{type(e).__name__}: {e}") from e
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        raise FinraError(f"FINRA returned {len(lines)} lines for "
                         f"{date_yyyymmdd} -- holiday or bad date")
    out = {}
    for line in lines[1:]:
        p = line.split("|")
        if len(p) < 5 or p[0] == "Date":
            continue
        try:
            out[p[1].upper()] = {
                "date": p[0], "symbol": p[1].upper(),
                "short_volume": float(p[2]), "short_exempt": float(p[3]),
                "total_volume": float(p[4]),
                "market": p[5] if len(p) > 5 else None}
        except ValueError:
            continue
    return out


def assess(symbol: str, rows_by_day: dict, *, session_date: str,
           known_from) -> ShortPressureState:
    """`rows_by_day`: {YYYYMMDD: {symbol: row}} chronological history."""
    days = sorted(rows_by_day)
    today = rows_by_day.get(session_date.replace("-", ""), {}).get(symbol.upper())

    def _mk(state, **kw):
        base = dict(short_volume=None, total_volume=None, short_ratio=None,
                    short_exempt=None, ratio_percentile=None,
                    ratio_change_1d=None)
        base.update(kw)
        return ShortPressureState(
            symbol=symbol.upper(), session_date=session_date, state=state,
            scope=SCOPE, history_days=len(days), known_from=str(known_from),
            **base)

    if today is None:
        return _mk("NOT_ESTIMABLE")
    tv = today["total_volume"]
    if tv < MIN_VOLUME:
        return _mk("NOT_ESTIMABLE", short_volume=today["short_volume"],
                   total_volume=tv, short_exempt=today["short_exempt"])
    ratio = today["short_volume"] / tv

    hist = []
    for d in days:
        r = rows_by_day[d].get(symbol.upper())
        if r and r["total_volume"] >= MIN_VOLUME:
            hist.append(r["short_volume"] / r["total_volume"])
    pct = (sum(1 for h in hist if h < ratio) / len(hist)
           if len(hist) >= MIN_HISTORY_DAYS else None)
    ch1 = (ratio - hist[-2]) if len(hist) >= 2 else None

    state = ("ELEVATED_SHORT_PRESSURE" if ratio >= ELEVATED else
             "LOW_SHORT_PRESSURE" if ratio <= LOW else "NORMAL")
    return _mk(state, short_volume=today["short_volume"], total_volume=tv,
               short_ratio=ratio, short_exempt=today["short_exempt"],
               ratio_percentile=pct, ratio_change_1d=ch1)


def market_wide(rows: dict, *, session_date: str, known_from) -> dict:
    """Aggregate off-exchange short ratio across the whole tape.

    More robust than any single name: a market-wide shift in the
    off-exchange short ratio is harder to explain away as one desk's
    hedging.
    """
    tot_s = sum(r["short_volume"] for r in rows.values())
    tot_v = sum(r["total_volume"] for r in rows.values())
    return {"kind": "market_wide_short_pressure", "session_date": session_date,
            "symbols": len(rows), "short_volume": tot_s,
            "total_volume": tot_v,
            "short_ratio": (tot_s / tot_v if tot_v else None),
            "scope": SCOPE, "caveat": NOT_SHORT_INTEREST,
            "is_short_interest": False, "known_from": str(known_from),
            "decision_power": OBSERVATORY_POWER}
