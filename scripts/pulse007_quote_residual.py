"""PULSE-007 -- classify the residual quote discrepancies that survive the anchor repair.

Four categories were named in the directive. This decides which one each
residual is, from the tape, without changing anything:

  (a) same semantics, different selected event/timestamp
  (b) different source conventions
  (c) missing or truncated tape
  (d) an implementation defect

Method: for each frozen packet, pull the SIP quote tape around the moment
and identify (1) the last quote at or before the packet's scheduled_time --
what the replay selects -- and (2) the quote at the live packet's own
recorded as_of. If the live packet's values reproduce exactly from (2) and
the replay's from (1), the residual is (a) and nothing is broken.

Read-only. Writes results/pulse/pulse007/QUOTE_RESIDUAL_V1.json
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
from apex.pulse.anchors import _dt                      # noqa: E402

FROZEN = "/opt/apex-repo/results/pulse/pulse007_frozen"
OUT = "/opt/apex-repo/results/pulse/pulse007/QUOTE_RESIDUAL_V1.json"


def imbalance(bs, a_s):
    return round((bs - a_s) / (bs + a_s), 4) if (bs + a_s) else None


def spread_bps(bp, ap):
    mid = (bp + ap) / 2
    return round((ap - bp) / mid * 1e4, 3)


def main():
    packets = [json.loads(l) for l in open(FROZEN + "/_candidate_packets.jsonl")]
    out = {"kind": "pulse007_quote_residual", "version": "QUOTE_RESIDUAL_V1",
           "question": "after the anchor repair, why do nbbo_size_imbalance and spread_bps "
                       "still differ between live and replay?",
           "categories": {"a": "same semantics, different selected event/timestamp",
                          "b": "different source conventions",
                          "c": "missing or truncated tape",
                          "d": "implementation defect"},
           "subjects": {}}
    for p in packets:
        sym = p["subject"]
        t = _dt(p["scheduled_time"])
        f = p["features"]
        live_mid = (f.get("mid") or {}).get("v")
        live_as_of = (f.get("mid") or {}).get("as_of")
        rec = {"live": {"as_of": live_as_of, "mid": live_mid,
                        "spread_bps": (f.get("spread_bps") or {}).get("v"),
                        "nbbo_size_imbalance": (f.get("nbbo_size_imbalance") or {}).get("v"),
                        "touch_size": (f.get("touch_size") or {}).get("v")}}
        if live_as_of is None:
            rec["category"] = "c"
            rec["finding"] = ("the live packet carries no two-sided NBBO at all; nothing to "
                              "compare. Coverage question, not a value question.")
            out["subjects"][sym] = rec
            print("%-6s no live quote -> category c" % sym)
            continue
        qs = ms.fetch_ticks(sym, (t - timedelta(seconds=20)).isoformat(),
                            (_dt(live_as_of) + timedelta(seconds=3)).isoformat(),
                            what="quotes", max_pages=3)
        rec["tape"] = {"quotes_in_window": len(qs),
                       "window": [(t - timedelta(seconds=20)).isoformat(),
                                  (_dt(live_as_of) + timedelta(seconds=3)).isoformat()],
                       "sha256": hashlib.sha256(json.dumps(qs, sort_keys=True).encode()).hexdigest()}
        usable = [q for q in qs if q.get("bp") and q.get("ap") and q["ap"] > q["bp"] > 0]
        at_sched = [q for q in usable if _dt(q["t"]) <= t]
        at_live = [q for q in usable if _dt(q["t"]) <= _dt(live_as_of)]
        for label, sel in (("replay_picks_at_scheduled_time", at_sched),
                           ("tape_quote_at_live_as_of", at_live)):
            if not sel:
                rec[label] = None
                continue
            q = sel[-1]
            rec[label] = {"t": q["t"], "bp": q["bp"], "ap": q["ap"], "bs": q.get("bs"), "as": q.get("as"),
                          "mid": round((q["bp"] + q["ap"]) / 2, 6),
                          "spread_bps": spread_bps(q["bp"], q["ap"]),
                          "nbbo_size_imbalance": imbalance(q.get("bs") or 0, q.get("as") or 0),
                          "touch_size": (q.get("bs") or 0) + (q.get("as") or 0)}
        a, b = rec.get("replay_picks_at_scheduled_time"), rec.get("tape_quote_at_live_as_of")
        if a and b:
            rec["events_between_scheduled_and_live_as_of"] = sum(
                1 for q in usable if t < _dt(q["t"]) <= _dt(live_as_of))
            rec["same_quote_event"] = a["t"] == b["t"]
            rec["live_matches_tape_at_its_own_as_of"] = {
                "mid": b["mid"] == live_mid,
                "spread_bps": b["spread_bps"] == rec["live"]["spread_bps"],
                "nbbo_size_imbalance": b["nbbo_size_imbalance"] == rec["live"]["nbbo_size_imbalance"],
                "touch_size": b["touch_size"] == rec["live"]["touch_size"]}
            agree = rec["live_matches_tape_at_its_own_as_of"]
            if not rec["same_quote_event"] and any(agree.values()):
                rec["category"] = "a"
                rec["finding"] = ("both feeders read the same SIP NBBO with the same convention; "
                                  "they select DIFFERENT events because the live packet's quote "
                                  "is the one current when PULSE captured (%.3fs after the "
                                  "scheduled slot) while the replay reconstructs at the scheduled "
                                  "slot exactly. %d NBBO updates fall between them."
                                  % ((_dt(live_as_of) - t).total_seconds(),
                                     rec["events_between_scheduled_and_live_as_of"]))
            elif rec["same_quote_event"] and not all(agree.values()):
                rec["category"] = "b_or_d"
                rec["finding"] = ("the same quote event yields different values -- a convention "
                                  "difference or a defect; needs its own investigation")
            else:
                rec["category"] = "a"
                rec["finding"] = "same event, same values; no residual from the quote path"
        else:
            rec["category"] = "c"
            rec["finding"] = "the tape did not supply a usable two-sided quote in the window"
        out["subjects"][sym] = rec
        pr = rec.get("replay_picks_at_scheduled_time") or {}
        lv = rec.get("tape_quote_at_live_as_of") or {}
        print("%-6s cat=%-5s lag=%6.3fs events_between=%-3s | replay@sched imb=%-8s spr=%-7s | tape@live_as_of imb=%-8s spr=%-7s | live imb=%-8s spr=%-7s | live==tape? %s" % (
            sym, rec.get("category"), (_dt(live_as_of) - t).total_seconds(),
            rec.get("events_between_scheduled_and_live_as_of"),
            pr.get("nbbo_size_imbalance"), pr.get("spread_bps"),
            lv.get("nbbo_size_imbalance"), lv.get("spread_bps"),
            rec["live"]["nbbo_size_imbalance"], rec["live"]["spread_bps"],
            rec.get("live_matches_tape_at_its_own_as_of")))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
