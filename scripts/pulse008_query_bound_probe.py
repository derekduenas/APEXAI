"""PULSE-008 -- is the vendor `end` bound excluding the requested instant?

quotes_as_of queries the tape with end = t and then takes the last usable
quote. The PULSE-007 residual probe queried with end = t + 3s and filtered
LOCALLY to <= t, and it reproduced the live values exactly. Same selection
rule, different query bound. If the vendor's `end` excludes events at or
immediately before the boundary, the two disagree -- and the reconstruction
never sees the event live actually used.

This tests exactly that, per subject, with the query bound as the only
variable. Read-only. Writes results/pulse008/QUERY_BOUND_PROBE_V1.json
"""
import hashlib
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, "/opt/apex-repo")
for _v, _f in (("APCA_API_KEY_ID", "ALPACA_API_KEY_ID"),
               ("APCA_API_SECRET_KEY", "ALPACA_API_SECRET_KEY")):
    if not os.environ.get(_v):
        _p = "/home/apex/.apex-secrets/" + _f
        if os.path.exists(_p):
            os.environ[_v] = open(_p).read().strip()

from apex.organism import microstructure as ms          # noqa: E402
from apex.pulse import observation as OBS               # noqa: E402

OUT = "/opt/apex-repo/results/pulse008/QUERY_BOUND_PROBE_V1.json"
MARGINS_S = [0, 1, 3]


def imb(q):
    bs, a = q.get("bs") or 0, q.get("as") or 0
    return round((bs - a) / (bs + a), 4) if (bs + a) else None


def main():
    packets = [json.loads(l) for l in open("/opt/apex-repo/results/pulse007_frozen_packets.jsonl")]
    out = {"kind": "pulse008_query_bound_probe", "version": "QUERY_BOUND_PROBE_V1",
           "variable": "the vendor query's `end` bound only; the selection rule "
                       "(last usable quote with t <= observation instant) is identical",
           "subjects": {}}
    for p in sorted(packets, key=lambda x: x["subject"]):
        sym = p["subject"]
        rec = OBS.observation_time(p)
        if rec["status"] != OBS.RESOLVED:
            out["subjects"][sym] = {"skipped": rec["status"]}
            continue
        want = OBS._dt(rec["observation_time"])
        f = p["features"]
        live = {"imbalance": (f.get("nbbo_size_imbalance") or {}).get("v"),
                "touch": (f.get("touch_size") or {}).get("v"),
                "mid": (f.get("mid") or {}).get("v"),
                "spread_bps": (f.get("spread_bps") or {}).get("v"),
                "as_of": rec["observation_time"]}
        rows = []
        for margin in MARGINS_S:
            end = want + timedelta(seconds=margin)
            qs = ms.fetch_ticks(sym, (want - timedelta(seconds=20)).isoformat(),
                                end.isoformat(), what="quotes", max_pages=3)
            usable = [q for q in qs if q.get("bp") and q.get("ap") and q["ap"] > q["bp"] > 0
                      and OBS._dt(q["t"]) <= want]
            sel = usable[-1] if usable else None
            exact = [q for q in qs if q["t"] == live["as_of"]]
            mid = round((sel["bp"] + sel["ap"]) / 2, 6) if sel else None
            rows.append({
                "query_end_margin_s": margin, "quotes_returned": len(qs),
                "usable_at_or_before_instant": len(usable),
                "exact_event_present": bool(exact),
                "selected_t": (sel or {}).get("t"),
                "gap_to_instant_ms": round((want - OBS._dt(sel["t"])).total_seconds() * 1000, 3) if sel else None,
                "selected_imbalance": imb(sel) if sel else None,
                "selected_touch": ((sel.get("bs") or 0) + (sel.get("as") or 0)) if sel else None,
                "selected_mid": mid,
                "matches_live": {"imbalance": imb(sel) == live["imbalance"] if sel else None,
                                 "touch": ((sel.get("bs") or 0) + (sel.get("as") or 0)) == live["touch"] if sel else None,
                                 "mid": mid == live["mid"] if sel else None},
                "response_sha256": hashlib.sha256(json.dumps(qs, sort_keys=True).encode()).hexdigest()})
            r = rows[-1]
            print("%-5s end=+%ss returned=%-6s exact_present=%-5s sel=%-32s gap=%-9s imb=%-8s (live %-8s) touch=%-6s (live %-6s) match=%s"
                  % (sym, margin, r["quotes_returned"], r["exact_event_present"], r["selected_t"],
                     r["gap_to_instant_ms"], r["selected_imbalance"], live["imbalance"],
                     r["selected_touch"], live["touch"], r["matches_live"]))
        out["subjects"][sym] = {"live": live, "instant": rec["observation_time"], "configs": rows}
        print()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
