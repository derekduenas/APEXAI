"""HISTORICAL_MONSTER_DIAGNOSTIC V1 -- strict-clock replay.

Authority: DIAGNOSTIC_ONLY. NO_PROMOTION. NO_PROSPECTIVE_CREDIT.
NO_CAPITAL_AUTHORITY. Registration (with every gate PREDECLARED):
HISTORICAL-MONSTER-DIAGNOSTIC-V1-2026-08-30 on the research board.

The clock: events replay chronologically by reaction session. All
decisions for a session are computed from memory containing ONLY
previously-resolved sessions, persisted to the decision ledger, and
only then are that session's outcomes revealed and folded into
memory. The full-sample estimates (+19.6 / +23.4) never enter.

Policies (all sealed in the registration -- no rescue):
  MONSTER          A1 gates n>=30 estimable / n>=60 + (mean-SE)>cost
                   actionable; A2 increment applied only when both
                   cohorts n>=30 and (incr-SE_diff)>0
  A1_ONLY          Monster without the A2 increment
  A2_ONLY          negative events only; own gates n>=60 +
                   (neg_mean-SE)>cost
  FORCED           attack every PM event once A1 estimable (n>=30)
  NO_UNCERT        estimable(30) and mean>cost, no SE margin
  ALWAYS_PM_FADE   attack every PM event from event #1
  ALWAYS_NEG       attack every negative PM event from event #1
  GAP_DIRECTION    all events, direction = sign(gap_res), +5m entry
  MOMENTUM         all events, direction = sign(r30_res), 10:00 entry
  CASH             0

Costs: expected = expanding median of observed event RTs (prior 15
bps until 20 obs); realized = per-event observed RT else expected.
Risk: 1R = 5% adverse; risk cases 0.25/0.50/1.00 pct of equity =>
notional 5/10/20 pct; total notional capped at 100 pct per session.
decision_power: DIAGNOSTIC_ONLY.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

INP = Path("exports/replay_inputs.jsonl")
DEC = Path("results/event_sprint/historical_decisions.jsonl")
OUT = Path("results/event_sprint/historical_diagnostic.json")

COST_PRIOR = 15.0
RISK_CASES = {"r025": 0.05, "r050": 0.10, "r100": 0.20}   # notional
START = 10_000.0


class Memory:
    def __init__(self):
        self.pm = []          # +5m short pnl, PM events
        self.neg = []
        self.nonneg = []
        self.rts = []

    def cost(self):
        return (statistics.median(self.rts)
                if len(self.rts) >= 20 else COST_PRIOR)

    def a1(self):
        n = len(self.pm)
        if n < 30:
            return {"status": "NOT_ESTIMABLE", "n": n}
        mean = statistics.mean(self.pm)
        se = statistics.pstdev(self.pm) / math.sqrt(n)
        return {"status": "ESTIMABLE", "n": n,
                "mean": mean, "median": statistics.median(self.pm),
                "se": se,
                "actionable": n >= 60 and (mean - se) > self.cost()}

    def a2(self):
        if len(self.neg) < 30 or len(self.nonneg) < 30:
            return {"status": "NOT_ESTIMABLE",
                    "n_neg": len(self.neg),
                    "n_nonneg": len(self.nonneg)}
        incr = statistics.mean(self.neg) - statistics.mean(self.nonneg)
        se = math.sqrt(
            statistics.pvariance(self.neg) / len(self.neg)
            + statistics.pvariance(self.nonneg) / len(self.nonneg))
        return {"status": "ESTIMABLE", "n_neg": len(self.neg),
                "n_nonneg": len(self.nonneg), "increment": incr,
                "se_diff": se, "applies": (incr - se) > 0}

    def a2_only(self):
        n = len(self.neg)
        if n < 30:
            return {"status": "NOT_ESTIMABLE", "n": n}
        mean = statistics.mean(self.neg)
        se = statistics.pstdev(self.neg) / math.sqrt(n)
        return {"status": "ESTIMABLE", "n": n, "mean": mean,
                "se": se,
                "actionable": n >= 60 and (mean - se) > self.cost()}


def decide(policy, ev, mem):
    """Return (action, direction, entry_key, forecast dict)."""
    pnl = ev["short_pnl_bps"]
    cost = mem.cost()
    if policy == "GAP_DIRECTION":
        g = ev.get("gap_res")
        if g is None or "+5m" not in pnl:
            return ("NO_TRADE", None, None, {})
        return ("ATTACK", "FOLLOW_GAP", "+5m", {"exp": "none"})
    if policy == "MOMENTUM":
        m = ev.get("r30_res")
        if m is None or "10:00" not in pnl:
            return ("NO_TRADE", None, None, {})
        return ("ATTACK", "FOLLOW_MOM", "10:00", {"exp": "none"})

    if ev["timing"] != "pm":
        return ("NO_TRADE", None, None, {"why": "NOT_PM"})
    if "+5m" not in pnl:
        return ("NO_TRADE", None, None, {"why": "DATA_NOT_ESTIMABLE"})

    if policy == "ALWAYS_PM_FADE":
        return ("ATTACK", "SHORT", "+5m", {})
    if policy == "ALWAYS_NEG":
        return (("ATTACK", "SHORT", "+5m", {})
                if ev["surprise"] == "NEGATIVE"
                else ("NO_TRADE", None, None, {"why": "NOT_NEG"}))

    a1 = mem.a1()
    if policy == "A2_ONLY":
        if ev["surprise"] != "NEGATIVE":
            return ("NO_TRADE", None, None, {"why": "NOT_NEG"})
        g = mem.a2_only()
        if g["status"] != "ESTIMABLE":
            return ("NO_TRADE", None, None,
                    {"why": "INSUFFICIENT_SUPPORT", **g})
        if not g["actionable"]:
            return ("WATCH", None, None, g)
        return ("ATTACK", "SHORT", "+5m",
                {"exp_gross": g["mean"], "exp_cost": cost})

    if a1["status"] != "ESTIMABLE":
        return ("NO_TRADE", None, None,
                {"why": "INSUFFICIENT_SUPPORT", **a1})

    if policy == "FORCED":
        return ("ATTACK", "SHORT", "+5m",
                {"exp_gross": a1["mean"], "exp_cost": cost})
    if policy == "NO_UNCERT":
        if a1["mean"] > cost:
            return ("ATTACK", "SHORT", "+5m",
                    {"exp_gross": a1["mean"], "exp_cost": cost})
        return ("WATCH", None, None, a1)

    # MONSTER and A1_ONLY
    exp_gross = a1["mean"]
    a2 = mem.a2()
    used_a2 = False
    if policy == "MONSTER" and ev["surprise"] == "NEGATIVE" \
            and a2["status"] == "ESTIMABLE" and a2["applies"]:
        exp_gross += a2["increment"]
        used_a2 = True
    if not a1["actionable"]:
        return ("WATCH", None, None,
                {"a1": a1, "a2": a2, "why": "UNCERTAINTY_GATE"})
    return ("ATTACK", "SHORT", "+5m",
            {"exp_gross": round(exp_gross, 2), "exp_cost": cost,
             "exp_net": round(exp_gross - cost, 2),
             "a2_increment_used": used_a2,
             "a1_n": a1["n"], "a2": {k: (round(v, 2)
                                         if isinstance(v, float)
                                         else v)
                                     for k, v in a2.items()}})


def realized(ev, direction, entry_key, mem):
    pnl = ev["short_pnl_bps"].get(entry_key)
    if pnl is None:
        return None
    if direction == "FOLLOW_GAP":
        pnl = pnl if ev["gap_res"] > 0 else -pnl
    elif direction == "FOLLOW_MOM":
        pnl = pnl if ev["r30_res"] > 0 else -pnl
    rt = ev.get("observed_rt_bps")
    cost = rt if rt is not None else mem.cost()
    return pnl - cost


def main():
    events = [json.loads(l) for l in INP.open()]
    events.sort(key=lambda e: (e["session"], e["symbol"]))
    sessions = defaultdict(list)
    for e in events:
        sessions[e["session"]].append(e)

    policies = ("MONSTER", "A1_ONLY", "A2_ONLY", "FORCED",
                "NO_UNCERT", "ALWAYS_PM_FADE", "ALWAYS_NEG",
                "GAP_DIRECTION", "MOMENTUM")
    mem = Memory()
    daily = {p: [] for p in policies}      # (session, [net bps...])
    counts = {p: defaultdict(int) for p in policies}
    monster_events = []                    # full monster event log
    rejected_pm = []                       # value-of-rejection
    learning = []
    first = {}
    dec_f = DEC.open("w")

    last_q = None
    for sess in sorted(sessions):
        q = sess[:7]
        if q != last_q:
            a1, a2 = mem.a1(), mem.a2()
            learning.append({
                "month": q, "a1_n": a1.get("n"),
                "a1_mean": round(a1["mean"], 2)
                if "mean" in a1 else None,
                "a1_se": round(a1["se"], 2) if "se" in a1 else None,
                "a2_incr": round(a2["increment"], 2)
                if "increment" in a2 else None,
                "cost": round(mem.cost(), 2)})
            last_q = q
        # milestones (checked before this session's decisions)
        a1, a2 = mem.a1(), mem.a2()
        if "A1_ESTIMABLE" not in first and a1["status"] == "ESTIMABLE":
            first["A1_ESTIMABLE"] = sess
        if "A1_ACTIONABLE" not in first and a1.get("actionable"):
            first["A1_ACTIONABLE"] = sess
        if "A2_ESTIMABLE" not in first and a2["status"] == "ESTIMABLE":
            first["A2_ESTIMABLE"] = sess
        if "A2_APPLIES" not in first and a2.get("applies"):
            first["A2_APPLIES"] = sess

        # 1) decide everything for this session from PRIOR memory
        todays = {p: [] for p in policies}
        for ev in sessions[sess]:
            for p in policies:
                action, direction, ek, fc = decide(p, ev, mem)
                todays[p].append((ev, action, direction, ek, fc))
                counts[p][action] += 1
                if p == "MONSTER":
                    dec_f.write(json.dumps({
                        "session": sess, "symbol": ev["symbol"],
                        "timing": ev["timing"],
                        "surprise": ev["surprise"],
                        "action": action, "forecast": fc}) + "\n")
        # 2) reveal outcomes
        for p in policies:
            rets = []
            for ev, action, direction, ek, fc in todays[p]:
                if action != "ATTACK":
                    if p == "MONSTER" and ev["timing"] == "pm" \
                            and "+5m" in ev["short_pnl_bps"]:
                        hyp = realized(ev, "SHORT", "+5m", mem)
                        if hyp is not None:
                            rejected_pm.append(hyp)
                    continue
                net = realized(ev, direction, ek, mem)
                if net is None:
                    continue
                rets.append(net)
                if p == "MONSTER":
                    monster_events.append(
                        {"session": sess, "symbol": ev["symbol"],
                         "surprise": ev["surprise"],
                         "net_bps": round(net, 2),
                         "gross_bps": ev["short_pnl_bps"]["+5m"],
                         "open_bps": ev["short_pnl_bps"].get("open"),
                         "a2_used": fc.get("a2_increment_used",
                                           False),
                         "exp_net": fc.get("exp_net")})
            if rets:
                daily[p].append((sess, rets))
        # 3) fold outcomes into memory
        for ev in sessions[sess]:
            p5 = ev["short_pnl_bps"].get("+5m")
            if ev["timing"] == "pm" and p5 is not None:
                mem.pm.append(p5)
                (mem.neg if ev["surprise"] == "NEGATIVE"
                 else mem.nonneg).append(p5)
            if ev.get("observed_rt_bps") is not None:
                mem.rts.append(ev["observed_rt_bps"])
    dec_f.close()

    # ---- capital curves ------------------------------------------
    def curve(dl, frac):
        eq, peak, mdd, tuw, hi_sess = START, START, 0.0, 0, None
        rets_daily, years = [], defaultdict(float)
        streak, worst_streak = 0, 0
        for sess, rets in dl:
            f = frac
            if f * len(rets) > 1.0:
                f = 1.0 / len(rets)          # 100% notional cap
            r = sum(f * x / 1e4 for x in rets)
            eq *= (1 + r)
            rets_daily.append((sess, r))
            years[sess[:4]] += r
            if eq > peak:
                peak = eq
            dd = 1 - eq / peak
            mdd = max(mdd, dd)
            if dd > 0:
                tuw += 1
            if r < 0:
                streak += 1
                worst_streak = max(worst_streak, streak)
            else:
                streak = 0
        yrs = (len(rets_daily) or 1) / 252
        cagr = (eq / START) ** (1 / max(yrs, 1e-9)) - 1
        return {"end": round(eq, 0), "cagr": round(cagr, 4),
                "max_dd": round(mdd, 4),
                "worst_year": round(min(years.values()), 4)
                if years else None,
                "annual_simple": {y: round(v, 4)
                                  for y, v in sorted(years.items())},
                "longest_losing_streak_days": worst_streak,
                "time_underwater_days": tuw,
                "n_days": len(rets_daily)}, rets_daily

    results = {}
    monster_daily_r050 = None
    for p in policies:
        allr = [x for _, rs in daily[p] for x in rs]
        stat = ({"attacks": len(allr),
                 "mean_net_bps": round(statistics.mean(allr), 1),
                 "median_net_bps": round(statistics.median(allr), 1),
                 "win": round(sum(1 for x in allr if x > 0)
                              / len(allr), 3)} if allr else
                {"attacks": 0})
        curves = {}
        for rc, frac in RISK_CASES.items():
            c, rd = curve(daily[p], frac)
            curves[rc] = c
            if p == "MONSTER" and rc == "r050":
                monster_daily_r050 = rd
        results[p] = {"stats": stat, "curves": curves,
                      "actions": dict(counts[p])}

    # ---- value of rejection --------------------------------------
    avoided = -sum(x for x in rejected_pm if x < 0)
    forgone = sum(x for x in rejected_pm if x > 0)
    vor = {"rejected_pm_events": len(rejected_pm),
           "losses_avoided_bps": round(avoided, 1),
           "profits_forgone_bps": round(forgone, 1),
           "value_of_rejection_bps": round(avoided - forgone, 1)}

    # ---- forensics on Monster losers -----------------------------
    fail = defaultdict(int)
    for e in monster_events:
        if e["net_bps"] >= 0:
            continue
        if e["gross_bps"] > 0:
            fail["COST_KILLED"] += 1
        elif e.get("open_bps") is not None and e["open_bps"] > 0 \
                and e["gross_bps"] <= 0:
            fail["ENTRY_EDGE_DECAYED"] += 1
        else:
            fail["PHYSICAL_THESIS_WRONG"] += 1
        if e["a2_used"]:
            fail["A2_INCREMENT_APPLIED_ON_LOSER"] += 1

    OUT.write_text(json.dumps({
        "kind": "historical_monster_diagnostic",
        "id": "HISTORICAL-MONSTER-DIAGNOSTIC-V1-RESULT",
        "events_replayed": len(events),
        "date_range": [min(sessions), max(sessions)],
        "milestones": first,
        "policies": results,
        "value_of_rejection": vor,
        "monster_failure_forensics": dict(fail),
        "learning_curve": learning,
        "historical_options": "NOT_ESTIMABLE (12/3207 events have "
                              "same-day real NBBO; synthetic "
                              "forbidden)",
        "authority": "DIAGNOSTIC_ONLY"}, indent=1))
    Path("results/event_sprint/monster_daily_r050.json").write_text(
        json.dumps(monster_daily_r050))
    Path("results/event_sprint/monster_event_log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in monster_events))
    print(json.dumps({"events": len(events),
                      "monster": results["MONSTER"],
                      "milestones": first,
                      "value_of_rejection": vor}, indent=1))


if __name__ == "__main__":
    main()
