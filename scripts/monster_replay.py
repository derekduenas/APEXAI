"""MONSTER V1 acceptance test -- honest replay of one real event.

Subject: AAPL FQ1-2023, reported PM 2023-02-02, reaction session
2023-02-03 -- a real negative surprise inside the sealed historical
dataset, replayed through the full Monster pathway with:

  * only formation-time information handed to the experts,
  * the MEASURED event-time friction for this exact event
    (observed SIP NBBO, results/event_sprint/event_friction_obs),
  * option expressions NOT_ESTIMABLE (the options corpus holds no
    same-day executable quotes; IV is never guessed),
  * the realized outcome computed separately, AFTER the decision,
    for scoring only.

decision_power: SHADOW_REPLAY.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apex.monster.consult import consult                  # noqa: E402
from apex.monster.event_expert import EventRecord         # noqa: E402

DATASET = Path("exports/event_dataset.jsonl")
FRICTION_OBS = Path("results/event_sprint/event_friction_obs.jsonl")
SN_BARS = Path("/apex-data/history-b/pit_singlename/bars")
ETF_BARS = Path("/apex-data/history-b/etf_continuous/bars")
NY = ZoneInfo("America/New_York")

SYM, RDATE, SESSION = "AAPL", "2023-02-02", "2023-02-03"


def measured_rt():
    for l in FRICTION_OBS.read_text().splitlines():
        o = json.loads(l)
        if o["symbol"] == SYM and o["session"] == SESSION \
                and o.get("rt_exec_bps"):
            return o["rt_exec_bps"], o
    return None, None


def realized_short_pnl_bps():
    def load(base, sym):
        bars = json.loads(
            (base / f"{sym}_{SESSION}.json").read_text())["bars"]
        rth = []
        for b in bars:
            t = datetime.fromisoformat(
                b["event_time_utc"].replace("Z", "+00:00")
            ).astimezone(NY)
            m = t.hour * 60 + t.minute
            if 570 <= m < 960:
                rth.append((m, b))
        return rth
    a, s = load(SN_BARS, SYM), load(ETF_BARS, "SPY")
    e = next(b["close"] for m, b in a if m >= 575)
    se = next(b["close"] for m, b in s if m >= 575)
    return -((a[-1][1]["close"] / e - 1.0)
             - (s[-1][1]["close"] / se - 1.0)) * 1e4


def main():
    ev_row = next(json.loads(l) for l in DATASET.open()
                  if json.loads(l)["symbol"] == SYM
                  and json.loads(l)["report_date"] == RDATE)
    rt, rt_obs = measured_rt()
    ev = EventRecord(
        symbol=SYM, report_date=RDATE, timing=ev_row["timing"],
        eps_estimate=ev_row["eps_estimate"],
        eps_actual=ev_row["eps_actual"],
        consensus_provenance="BROKER_REPORTED_CONSENSUS_RH_MCP",
        known_from=f"{RDATE}T21:35:00Z",   # PM release evening
        reaction_session=SESSION)
    decision = consult(ev, rt_cost_bps=rt, short_allowed=False,
                       put_quotes=None)
    decision["event_time_friction_observation"] = rt_obs
    decision["replay_note"] = ("realized outcome computed AFTER the "
                               "decision, for scoring only")
    decision["realized_short_pnl_res_bps_from_0935"] = round(
        realized_short_pnl_bps(), 1)
    out = Path("results/event_sprint/monster_replay_decision.json")
    out.write_text(json.dumps(decision, indent=1, default=str))
    print(json.dumps(decision, indent=1, default=str))


if __name__ == "__main__":
    main()
