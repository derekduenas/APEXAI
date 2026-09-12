#!/usr/bin/env python3
"""Date-by-date reconciliation of the EXP-001B exchange calendar against the
PRIMARY exchange announcements, for the proposed admission window 2016-2021.

The table below is transcribed from NYSE Group's own holiday-and-early-close
announcements (published through ICE investor relations) and the exchange's
announcement of the 2018-12-05 closure. Each year cites its release. Nothing
here is derived from the corpus, and no market row is read: the corpus
cross-check uses ONLY the committed manifest's file names, session dates and
byte sizes, which are metadata, never bar content.

    PYTHONPATH=. python scripts/si002_calendar_reconciliation.py <out.json>
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

from apex.world_model.exp001b import exchange_calendar as C

MANIFEST = "/apex-data/governance/admissions/manifests/etf_continuous_SPY_manifest_v0.json"
WINDOW = ("2016-01-04", "2021-12-31")

SOURCES = {
    "2016": "NYSE Group 2016 Holiday Calendar and Early Closings -- ICE IR, released 2014-12-08 "
            "(ir.theice.com/press/news-details/2014/NYSE-Group-2016-Holiday-Calendar-and-Early-Closings)",
    "2017": "NYSE Group Announces 2017 Holiday and Early Closings Calendar -- ICE IR, released 2016-02-02",
    "2018": "NYSE Group Announces 2018, 2019 and 2020 Holiday and Early Closings Calendar -- ICE IR, released 2017-11-27",
    "2019": "NYSE Group Announces 2019, 2020 and 2021 Holiday and Early Closings Calendar -- ICE IR, released 2018-12-04",
    "2020": "NYSE Group Announces 2019, 2020 and 2021 ... (2018-12-04) SUPERSEDES the 2017-11-27 release "
            "for 2020: the earlier release listed no Independence Day closure and an early close on "
            "Friday 2020-07-03; the later release lists Friday 2020-07-03 as the full closure and no "
            "July early close. The LATER release is used.",
    "2021": "NYSE Group Announces 2019, 2020 and 2021 Holiday and Early Closings Calendar -- ICE IR, released 2018-12-04",
    "2018-12-05": "New York Stock Exchange to Honor President George H. W. Bush -- ICE IR, 2018 "
                  "(national day of mourning; NYSE, NYSE American, NYSE National, NYSE Arca closed)",
    "conflict_noted": "A secondary aggregator reports a 2:00 p.m. close on 2016-11-25. That is SIFMA's "
                      "recommended BOND-market close; the NYSE equities release for 2016 states 1:00 p.m. "
                      "(crossing session to 1:30 p.m.). The primary equities source is used.",
}

# ---- transcribed primary record -----------------------------------------
AUTH_HOLIDAYS = {
    2016: ["2016-01-01", "2016-01-18", "2016-02-15", "2016-03-25", "2016-05-30", "2016-07-04",
           "2016-09-05", "2016-11-24", "2016-12-26"],
    2017: ["2017-01-02", "2017-01-16", "2017-02-20", "2017-04-14", "2017-05-29", "2017-07-04",
           "2017-09-04", "2017-11-23", "2017-12-25"],
    2018: ["2018-01-01", "2018-01-15", "2018-02-19", "2018-03-30", "2018-05-28", "2018-07-04",
           "2018-09-03", "2018-11-22", "2018-12-05", "2018-12-25"],
    2019: ["2019-01-01", "2019-01-21", "2019-02-18", "2019-04-19", "2019-05-27", "2019-07-04",
           "2019-09-02", "2019-11-28", "2019-12-25"],
    2020: ["2020-01-01", "2020-01-20", "2020-02-17", "2020-04-10", "2020-05-25", "2020-07-03",
           "2020-09-07", "2020-11-26", "2020-12-25"],
    2021: ["2021-01-01", "2021-01-18", "2021-02-15", "2021-04-02", "2021-05-31", "2021-07-05",
           "2021-09-06", "2021-11-25", "2021-12-24"],
}
AUTH_EARLY_CLOSES = {
    2016: ["2016-11-25"],
    2017: ["2017-07-03", "2017-11-24"],
    2018: ["2018-07-03", "2018-11-23", "2018-12-24"],
    2019: ["2019-07-03", "2019-11-29", "2019-12-24"],
    2020: ["2020-11-27", "2020-12-24"],
    2021: ["2021-11-26"],
}
UNSCHEDULED_CLOSURES_SEARCHED = {
    "result": "none found in 2016-2021 beyond 2018-12-05",
    "note": "the 2020 COVID floor closure did not close the market: electronic trading continued, "
            "so no session is absent for it",
}


def _dates(lo: str, hi: str):
    d, end = date.fromisoformat(lo), date.fromisoformat(hi)
    while d <= end:
        yield d
        d += timedelta(days=1)


def main(out_path: str) -> int:
    auth_h = {d for y in AUTH_HOLIDAYS for d in AUTH_HOLIDAYS[y]}
    auth_e = {d for y in AUTH_EARLY_CLOSES for d in AUTH_EARLY_CLOSES[y]}
    lo, hi = WINDOW
    rows, mismatches = [], []
    for d in _dates(lo, hi):
        s = d.isoformat()
        if d.weekday() >= 5:
            continue
        a_hol, a_early = s in auth_h, s in auth_e
        c_hol, c_early = s in C.HOLIDAYS, s in C.EARLY_CLOSES
        if (a_hol, a_early) != (c_hol, c_early):
            row = {"date": s, "authoritative": {"holiday": a_hol, "early_close": a_early},
                   "code_table": {"holiday": c_hol, "early_close": c_early}}
            mismatches.append(row); rows.append(row)
    weekdays = sum(1 for d in _dates(lo, hi) if d.weekday() < 5)

    rec = {"window": list(WINDOW), "calendar_version": C.CALENDAR_VERSION, "sources": SOURCES,
           "unscheduled_closures": UNSCHEDULED_CLOSURES_SEARCHED,
           "authoritative_counts": {"holidays": len(auth_h & {d.isoformat() for d in _dates(lo, hi)}),
                                    "early_closes": len(auth_e)},
           "code_table_counts": {"holidays": len([x for x in C.HOLIDAYS if lo <= x <= hi]),
                                 "early_closes": len([x for x in C.EARLY_CLOSES if lo <= x <= hi])},
           "weekdays_examined": weekdays, "mismatches": mismatches,
           "date_by_date_agreement": not mismatches,
           "law": "every weekday in the window is compared on BOTH attributes; a match on counts "
                  "alone would not be a reconciliation"}

    # ---- corpus cross-check from METADATA only (names, dates, byte sizes) --
    man = Path(MANIFEST)
    if man.exists():
        m = json.loads(man.read_text())
        files = {v["session_date"]: v for v in m["files"].values()
                 if v["symbol"] == "SPY" and lo <= v["session_date"] <= hi}
        expected = {d.isoformat() for d in _dates(lo, hi)
                    if d.weekday() < 5 and d.isoformat() not in auth_h}
        present = set(files)
        sizes = sorted((v["size"], k) for k, v in files.items())
        med = statistics.median([s for s, _ in sizes]) if sizes else 0
        small = [{"date": k, "size": s, "ratio_to_median": round(s / med, 3)}
                 for s, k in sizes if med and s < 0.72 * med]
        smalldates = {x["date"] for x in small}
        rec["corpus_cross_check"] = {
            "source": MANIFEST, "reads": "file names, session dates and byte sizes ONLY; no bar parsed",
            "sessions_expected_from_authoritative_calendar": len(expected),
            "sessions_present_in_corpus": len(present),
            "authoritative_session_missing_from_corpus": sorted(expected - present),
            "corpus_session_on_an_authoritative_holiday": sorted(present & auth_h),
            "median_file_bytes": med,
            "short_files_below_72pct_of_median": small,
            "short_files_that_are_authoritative_early_closes": sorted(smalldates & auth_e),
            "authoritative_early_closes_not_short": sorted(auth_e - smalldates),
            "short_files_not_authoritative_early_closes": sorted(smalldates - auth_e),
            "early_close_size_ratios": {k: round(files[k]["size"] / med, 3)
                                        for k in sorted(auth_e) if k in files and med},
            "full_session_ratio_quantiles": (lambda r: {"min": round(min(r), 3), "p05": round(sorted(r)[len(r) // 20], 3),
                                                        "median": round(statistics.median(r), 3)})(
                [v["size"] / med for k, v in files.items() if k not in auth_e and med]),
            "limitation": "byte size is a proxy for session length only; it cannot by itself "
                          "establish a close time, and a day with unusually light trading can be "
                          "short without being an early close"}
    else:
        rec["corpus_cross_check"] = {"status": "MANIFEST_ABSENT", "path": MANIFEST}

    Path(out_path).write_text(json.dumps(rec, indent=1, sort_keys=True, default=str))
    cc = rec.get("corpus_cross_check", {})
    print(json.dumps({"date_by_date_agreement": rec["date_by_date_agreement"],
                      "mismatches": len(mismatches), "weekdays_examined": weekdays,
                      "counts": {"auth": rec["authoritative_counts"], "code": rec["code_table_counts"]},
                      "corpus": {k: cc.get(k) for k in
                                 ("authoritative_session_missing_from_corpus",
                                  "corpus_session_on_an_authoritative_holiday",
                                  "short_files_that_are_authoritative_early_closes",
                                  "authoritative_early_closes_not_short",
                                  "short_files_not_authoritative_early_closes")}}, indent=1))
    return 0 if rec["date_by_date_agreement"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
