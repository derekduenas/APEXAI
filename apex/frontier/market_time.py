"""MARKET_TIME_V1 — market time is authoritative; local time is an implementation detail of the scheduler.

THE HAZARD THIS EXISTS FOR. Every premarket stage target is a NEW YORK wall-clock instant: 08:15 ET means 08:15
in the exchange's timezone, on the exchange's calendar, through both daylight transitions. launchd's
`StartCalendarInterval` knows nothing about that -- it fires at a LOCAL wall-clock time on the host. R4 generated
those local times by assuming the host tracks US Eastern, verified the assumption at two probe instants, and
wrote it in a comment. A comment is not a guard. Someone flying to London with this laptop, or macOS switching
zones automatically on a network change, would silently move the entire premarket morning by hours, and every
stage would still be labelled correctly.

SO, TWO SEPARATE MECHANISMS, because one is not enough:

  1. THE DECISION IS ALWAYS MADE IN NEW YORK TIME. A stage's disposition is computed from the market instant, never
     from the local hour that happened to trigger it. A trigger that fires at the wrong local time therefore lands
     outside its market window and is refused as TOO_EARLY or MISSED_WINDOW -- it cannot absorb at a shifted
     market time even if the guard below is missing entirely.

  2. THE GENERATED SCHEDULE IS BOUND TO A TIMEZONE, AND THE BINDING IS CHECKED. Generation records the host zone
     the local triggers were computed for. A runner whose live host zone differs refuses with a named
     TIMEZONE_CONFIGURATION_MISMATCH rather than running an hour off and recording it as ordinary lateness.

A host whose zone does not track New York across DST needs MORE THAN ONE local trigger per stage -- a UTC host
needs 12:15 in summer and 13:15 in winter for one 08:15 ET target. `local_triggers()` returns the whole set, so
launchd fires in both seasons and the out-of-season one is refused by (1). That is why the return type is a set.
"""
from __future__ import annotations

import os
import pathlib

SCHEMA = "MARKET_TIME_V1"
MARKET_TZ = "America/New_York"

ZONEINFO_MARKERS = ("/zoneinfo/", "/zoneinfo.default/")


class TimezoneConfigurationMismatch(RuntimeError):
    """The host is not in the timezone the installed schedule was generated for. Named, never silent."""


def host_timezone() -> dict:
    """The host's IANA zone, with the operating-system evidence it came from.

    Sources, in the order a Unix process is entitled to trust them:
      TZ            an explicit process-level override; if it is set, it IS the timezone for this process;
      /etc/localtime  on macOS a symlink into the zoneinfo database, which names the zone directly;
      time.tzname   a last resort, and an ABBREVIATION (PDT), not a zone -- reported as UNRESOLVED_ABBREVIATION
                    rather than guessed at, because several zones share an abbreviation.
    """
    import time as _t
    tz = os.environ.get("TZ")
    if tz:
        return {"name": tz, "source": "TZ", "evidence": "TZ=%s" % tz, "resolved": True}
    p = pathlib.Path("/etc/localtime")
    if p.is_symlink():
        target = os.readlink(str(p))
        for marker in ZONEINFO_MARKERS:
            if marker in target:
                return {"name": target.split(marker, 1)[1], "source": "/etc/localtime",
                        "evidence": "/etc/localtime -> %s" % target, "resolved": True}
    return {"name": "UNRESOLVED_ABBREVIATION:%s" % (_t.tzname[0] if _t.tzname else "?"),
            "source": "time.tzname", "evidence": "tzname=%r" % (_t.tzname,), "resolved": False}


def market_instant(date: str, h: int, m: int):
    """A stage target, as the exchange means it."""
    import pandas as pd
    return pd.Timestamp("%s %02d:%02d" % (date, h, m), tz=MARKET_TZ)


def to_local(instant, tz: str):
    return instant.tz_convert(tz)


def offset_hours(date: str, tz: str) -> float:
    """market_utcoffset - host_utcoffset, in hours. NEGATIVE means the market clock is BEHIND the host clock:
    for a UTC host in January this is -5.0, because 08:15 in New York is 13:15 for that host. The name says
    which way round it is because a bare 'offset' in a schedule is exactly the kind of field a reader guesses
    wrong."""
    import pandas as pd
    a = pd.Timestamp("%s 12:00" % date, tz=MARKET_TZ)
    return (a.utcoffset() - a.tz_convert(tz).utcoffset()).total_seconds() / 3600.0


def offset_is_stable(tz: str, year: int = None) -> bool:
    """Does this host zone track New York through BOTH daylight transitions? If not, one local trigger cannot
    cover the year."""
    import pandas as pd
    y = year or pd.Timestamp.now(tz="UTC").year
    return offset_hours("%d-01-15" % y, tz) == offset_hours("%d-07-15" % y, tz)


def local_triggers(h: int, m: int, tz: str, year: int = None) -> list:
    """Every distinct LOCAL (hour, minute) needed so a NY target of h:m fires correctly all year on this host.

    One entry for a host that tracks New York. Two for a host that does not -- and both are emitted, because the
    market-time window refuses the out-of-season one rather than absorbing at the wrong instant."""
    import pandas as pd
    y = year or pd.Timestamp.now(tz="UTC").year
    out = []
    for probe in ("%d-01-15" % y, "%d-07-15" % y):
        loc = market_instant(probe, h, m).tz_convert(tz)
        if (loc.hour, loc.minute) not in out:
            out.append((loc.hour, loc.minute))
    return out


def schedule_table(stages, tz: str, date: str) -> list:
    """market stage / local trigger / UTC instant / offset, for one concrete date."""
    rows = []
    for name, h, m in stages:
        inst = market_instant(date, h, m)
        loc = inst.tz_convert(tz)
        rows.append({"stage": name, "market_tz": MARKET_TZ,
                     "market_time": "%02d:%02d" % (h, m),
                     "local_tz": tz, "local_time": loc.strftime("%H:%M"),
                     "utc_instant": inst.tz_convert("UTC").isoformat(),
                     "market_minus_local_hours": offset_hours(date, tz),
                     "triggers_all_year": local_triggers(h, m, tz)})
    return rows


def next_market_session(after=None) -> str:
    """The next NYSE trading date, from the one calendar in the repo."""
    import pandas as pd
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import is_trading_day
    t = pd.Timestamp(after) if after is not None else pd.Timestamp.now(tz=MARKET_TZ)
    d = t.tz_convert(MARKET_TZ) if t.tz is not None else t.tz_localize(MARKET_TZ)
    for _ in range(10):
        if is_trading_day(str(d.date())):
            return str(d.date())
        d = d + pd.Timedelta(days=1)
    return "UNRESOLVED"


# ------------------------------------------------------------------ the binding
BINDING_NAME = "timezone_binding.json"


def binding_body(tz: str, stages, *, generated_for_year=None) -> dict:
    import pandas as pd
    y = generated_for_year or pd.Timestamp.now(tz="UTC").year
    return {"schema": SCHEMA, "market_tz": MARKET_TZ, "host_tz": tz,
            "offset_stable_vs_market": offset_is_stable(tz, y), "generated_for_year": y,
            "triggers": {name: local_triggers(h, m, tz, y) for name, h, m in stages},
            "why": ("launchd fires StartCalendarInterval in the HOST's local time. These local triggers were "
                    "computed for host_tz. If the host moves zones they are wrong, and the runner refuses with "
                    "TIMEZONE_CONFIGURATION_MISMATCH rather than running at a shifted market time.")}


def verify_binding(binding: dict, host: dict = None) -> dict:
    """Compare the live host zone with the one the installed schedule was generated for."""
    h = host if host is not None else host_timezone()
    if binding is None:
        return {"status": "UNBOUND", "host_tz": h["name"], "evidence": h["evidence"],
                "note": ("no timezone binding is installed; stage decisions are still made in market time, so a "
                         "wrong local trigger is refused rather than absorbed, but the mismatch is not named")}
    if not h.get("resolved"):
        raise TimezoneConfigurationMismatch(
            "TIMEZONE_CONFIGURATION_MISMATCH: the host timezone could not be resolved to an IANA zone (%s); the "
            "installed schedule is bound to %r and an unverifiable host is not a match"
            % (h["evidence"], binding.get("host_tz")))
    if h["name"] != binding.get("host_tz"):
        raise TimezoneConfigurationMismatch(
            "TIMEZONE_CONFIGURATION_MISMATCH: host is %r (%s) but the installed premarket schedule was generated "
            "for %r. Its local triggers now fire at the wrong market time. Regenerate and reinstall the schedule; "
            "this run is refused rather than executed %.0fh off."
            % (h["name"], h["evidence"], binding["host_tz"],
               abs(offset_hours("%d-07-15" % binding.get("generated_for_year", 2026), h["name"])
                   - offset_hours("%d-07-15" % binding.get("generated_for_year", 2026), binding["host_tz"]))))
    return {"status": "BOUND", "host_tz": h["name"], "evidence": h["evidence"],
            "offset_stable_vs_market": binding.get("offset_stable_vs_market")}


def load_binding(path=None):
    import json
    if path is None:
        path = os.environ.get("APEX_PREMARKET_TZ_BINDING")
    p = pathlib.Path(path) if path is not None else pathlib.Path("ops") / BINDING_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"host_tz": "UNREADABLE", "schema": SCHEMA}
