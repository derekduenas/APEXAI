"""PULSE-008 -- why does the replay select an event EARLIER than the requested instant?

quotes_as_of pages FORWARD from t - lookback_s with max_pages=2. On a liquid
name the window can hold more quotes than two pages carry, so the scan never
reaches the requested instant and `usable[-1]` is wherever the pages ran out.
This measures that directly, per subject, at several window widths, and
reports whether the EXACT event the live packet recorded is reachable.

Read-only. Writes results/pulse008/TAPE_REACH_PROBE_V1.json
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

OUT = "/opt/apex-repo/results/pulse008/TAPE_REACH_PROBE_V1.json"
CONFIGS = [(60, 2), (60, 10), (20, 3), (5, 2), (2, 2)]


def imb(q):
    bs, a = q.get("bs") or 0, q.get("as") or 0
    return round((bs - a) / (bs + a), 4) if (bs + a) else None


def main():
    packets = [json.loads(l) for l in open("/opt/apex-repo/results/pulse007_frozen_packets.jsonl")]
    out = {"kind": "pulse008_tape_reach_probe", "version": "TAPE_REACH_PROBE_V1",
           "question": "can quotes_as_of reach the instant the live packet recorded, and at "
                       "which (lookback_s, max_pages)?",
           "current_defaults": {"lookback_s": 60, "max_pages": 2},
           "subjects": {}}
    for p in sorted(packets, key=lambda x: x["subject"]):
        sym = p["subject"]
        rec = OBS.observation_time(p)
        if rec["status"] != OBS.RESOLVED:
            out["subjects"][sym] = {"skipped": rec["status"]}
            print("%-5s skipped (%s)" % (sym, rec["status"]))
            continue
        want = OBS._dt(rec["observation_time"])
        f = p["features"]
        live = {"imbalance": (f.get("nbbo_size_imbalance") or {}).get("v"),
                "touch": (f.get("touch_size") or {}).get("v"),
                "mid": (f.get("mid") or {}).get("v"),
                "as_of": rec["observation_time"]}
        rows = []
        for look, pages in CONFIGS:
            qs = ms.fetch_ticks(sym, (want - timedelta(seconds=look)).isoformat(),
                                want.isoformat(), what="quotes", max_pages=pages)
            usable = [q for q in qs if q.get("bp") and q.get("ap") and q["ap"] > q["bp"] > 0
                      and OBS._dt(q["t"]) <= want]
            sel = usable[-1] if usable else None
            exact = [q for q in qs if q["t"] == live["as_of"]]
            rows.append({
                "lookback_s": look, "max_pages": pages, "quotes_returned": len(qs),
                "usable": len(usable),
                "truncated": len(qs) >= pages * 10000,
                "selected_t": (sel or {}).get("t"),
                "gap_to_requested_ms": round((want - OBS._dt(sel["t"])).total_seconds() * 1000, 3) if sel else None,
                "selected_imbalance": imb(sel) if sel else None,
                "selected_touch": ((sel.get("bs") or 0) + (sel.get("as") or 0)) if sel else None,
                "exact_event_present": bool(exact),
                "exact_event_imbalance": imb(exact[0]) if exact else None,
                "matches_live_imbalance": (imb(sel) == live["imbalance"]) if sel else None,
                "response_sha256": hashlib.sha256(json.dumps(qs, sort_keys=True).encode()).hexdigest()})
            print("%-5s look=%-3s pages=%-3s returned=%-6s trunc=%-5s sel=%-32s gap=%-9s imb=%-8s live_imb=%-8s match=%s exact_in_page=%s"
                  % (sym, look, pages, len(qs), rows[-1]["truncated"], rows[-1]["selected_t"],
                     rows[-1]["gap_to_requested_ms"], rows[-1]["selected_imbalance"],
                     live["imbalance"], rows[-1]["matches_live_imbalance"], rows[-1]["exact_event_present"]))
        out["subjects"][sym] = {"live": live, "requested": rec["observation_time"], "configs": rows}
        print()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
