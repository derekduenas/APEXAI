# OPTIONS — MONDAY PAPER_EXPLORATORY RUNBOOK

**Authority:** `PAPER_EXPLORATORY` (granted 2026-08-23)
**Live capital:** LOCKED. This loop places no orders and touches no
account. It computes what would have filled at quoted sides.

---

## Start the session

Run on the cloud host, where both feeds and the ThetaData terminal live:

```bash
ssh apex@165.227.88.64 'cd /opt/apex && setsid nohup .venv/bin/python -u scripts/options_paper_session.py --ledger /apex-data/core/options_live_ledger.jsonl --out /apex-data/history-a/paper_$(date +%F).json --minutes 390 --interval-min 15 > /apex-data/history-a/paper_$(date +%F).log 2>&1 < /dev/null &'
```

Start it after 09:35 ET so the equity faculty has the ~30 bars it
requires. Ending near 16:00 ET lets the pre-declared session-close exit
resolve against live quotes.

## What is pre-registered

Sealed into the ledger before the first scan, and not revisable
mid-session:

| | |
|---|---|
| Universe | SPY, QQQ, AAPL, NVDA, MSFT, IWM |
| Scan cadence | every 15 minutes |
| Direction | the commissioned equity faculty's `trend_state` |
| Exit | hold to session close, resolve at quoted sides |
| Risk basis | `FULL_PREMIUM`, declared before the session |
| Size | 1 contract; stock comparator sized to the same 100 shares |
| Quota | none — `NO_TRADE` is a legitimate outcome |

## Feeds

Verified working 2026-08-23. Options quotes come from the ThetaData v3
snapshot endpoint (options entitlement confirmed); underlying bars and
**real equity NBBO** come from Alpaca SIP. The keys are data-only — the
paper trading endpoint returns 401, which is fine because we simulate
fills ourselves and never place an order.

Vendor access lives in `apex/intraday/options_feed.py`, the sensor
layer. The research package consumes it through neutral names and does
not know which vendor answered.

## What to expect, honestly

**Refusals will outnumber attacks, and that is the design.** The funnel
requires both an attackable underlying location and attackable contract
economics; either may veto. In Friday's rehearsal SPY and QQQ reached
`WAIT_FOR_ENTRY` — contracts sound, location not ready — which is the
correct reading of a market at the close.

**There is a real tension worth watching.** The bridge calls a trend
from 30-bar drift, while the equity faculty penalises distance from
session VWAP. A trend strong enough to register is often extended
enough to trip chase risk. The shape that satisfies both is a
consolidation followed by a modest advance — a genuine pullback entry.
If Monday produces zero `ATTACK_READY` across the whole session, that
tension is the first place to look, and it is a finding to report
rather than a gate to loosen.

**Do not loosen a gate because the funnel was quiet.** Any threshold
change after seeing outcomes is outcome-fitting, and this authority
level exists to collect evidence, not to manufacture activity.

## Reading the result

```bash
ssh apex@165.227.88.64 'cd /opt/apex && .venv/bin/python -c "
import json;d=json.load(open(\"/apex-data/history-a/paper_$(date +%F).json\"));
print(json.dumps(d[\"scoreboard\"],indent=1))"'
```

The two numbers that matter most:

- **`right_but_unprofitable`** — attacks whose thesis was right on mid
  and which lost anyway. High means the repair is EXECUTION, not
  forecasting.
- **`attacks_effective_lower_bound`** — the real sample size. Several
  attacks in one session are views of one day, not independent
  evidence.

`friction.friction_kill_rate` decomposes it further. The development
replay's rate was 75 of 304; whether live weeklies behave better is
precisely the open question. Friday's rehearsal showed SPY weeklies
quoting ~1.2% spreads with roughly $3 of round-trip friction on a $255
debit, which is far tighter than the 2018-2022 monthlies the replay
used — encouraging, but one closed-market observation is not evidence.

## Boundaries

- Nothing here promotes anything. Reaching `PAPER_AUTHORIZED` requires
  a separate authority review against a pre-registered standard.
- `OPTION_VS_STOCK` remains `NOT_PROVEN` for the historical corpus.
  Live sessions do carry real equity NBBO, so live comparisons are made
  on equal terms — but that does not retroactively legitimise the
  replay's stock result.
- Every record is stamped `PROSPECTIVE_PAPER`. Only these records count
  as prospective evidence; the historical replay never does.
