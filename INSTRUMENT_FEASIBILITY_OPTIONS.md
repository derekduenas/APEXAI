# INSTRUMENT_FEASIBILITY_OPTIONS — what a $500 per-trade cap actually admits

Date: 2026-09-11. Feasibility and arithmetic only. No recommendation to build, no code, no order.

**Data.** `/apex-data/pilot_collection/2026-09-11/chain_SPY.jsonl`, already collected, read-only, zero vendor
credits. Mid-session snapshot 14:53:23Z. Expiry **2026-10-02** (21 DTE, the pilot's first eligible expiry), 171
strikes, implied spot **763.94** by put-call parity. Cap: `MAX_RISK_PER_TRADE = $500`, multiplier 100, so **$5.00
per share** of certified maximum loss.

## 1. The claim on record was half right

"A $500 cap blocks the options sleeve against $13-19 near-ATM SPY asks." Today the ATM call asks **9.20** and the
ATM put **9.26**, so a long ATM single leg costs $920 and is indeed blocked. But that is a statement about the ATM
strike, not about the sleeve.

**63 of 160 SPY call strikes and 74 of 171 put strikes are feasible today** under the cap — positive bid, quoted
size, ask ≤ $5.00. The nearest feasible call is **K = 773, 1.19 % out of the money, ask 4.63, spread 0.9 %, sizes
58 × 139**. The nearest feasible put is **K = 749, 1.96 % out, ask 4.88, spread 0.8 %, sizes 153 × 64**. Fourteen
call strikes and eight put strikes sit within 3 % of spot.

**The cap does not block the sleeve. It blocks the ATM strike.** Single-leg expressions slightly out of the money
are feasible today, in size, at sub-1 % spreads, and are already the only expression the recording boundary and the
risk certificate admit. Liquidity degrades fast further out: median relative spread across the whole feasible call
set is 7.4 % and the worst is 66.7 %, so the usable band is the near strikes, not the cheap tail.

## 2. Verticals: the cap admits them, and something else refuses them

Actual debits from the same snapshot (buy at ask, sell at bid; max loss at expiry = debit × 100):

| Structure | Long / short | Debit | Max loss | Max gain | Verdict vs the $500 cap |
|---|---|---|---|---|---|
| Call vertical, 1 wide | 764 / 765 | 0.63 | $63 | $37 | feasible |
| Call vertical, 2 wide | 764 / 766 | 1.21 | $121 | $79 | feasible |
| Call vertical, 5 wide | 764 / 769 | 2.80 | $280 | $220 | feasible |
| Call vertical, 10 wide | 764 / 774 | 5.01 | $501 | $499 | **blocked by $1** |
| Put vertical, 5 wide | 764 / 759 | 1.88 | $188 | $312 | feasible |
| Put vertical, 10 wide | 764 / 754 | 3.30 | $330 | $670 | feasible |
| Call butterfly, 5 wide | 759/764/769 | 0.69 | $69 | $431 | feasible |
| Call butterfly, 10 wide | 754/764/774 | 2.13 | $213 | $787 | feasible |

So the arithmetic in the review is right: a defined-risk vertical lands in the $63-330 range at ATM on SPY and
clears a $500 cap comfortably. **But the vertical is not blocked by the cap, and it was not "never revisited."**
`apex/organism/risk_certificate.py:25-35, 113-121` already considered it and refuses to certify it, for a reason
that has nothing to do with the cap:

> a debit vertical is bounded by its debit ONLY AT EXPIRY. The pre-declared exit rule closes at session close at
> quoted sides, which requires BUYING BACK the short leg: the close realises (long bid − short ask), which can be
> negative, and the loss then exceeds the debit by two bid/ask spreads that are NOT KNOWABLE from state available
> at decision time. **Under a hold-to-expiry exit rule this same structure WOULD be DEFINED_MAX_LOSS.**

Priced on today's real book, that exposure is small: on the 5-wide 764/769 call vertical the debit is 2.80 and an
immediate close at quoted sides realises 2.70, a gap of **0.10, or 3.6 % of the debit**, giving a $290 loss against
a $500 cap. Small today is not the same as bounded, and the certificate's objection is that the bound is not
knowable at decision time, not that it is usually large. That objection is correct as stated.

## 3. What is and is not feasible, summarised

| Expression | Cap | Boundary vocabulary | Risk certificate | Net |
|---|---|---|---|---|
| Long single call/put, ATM | blocked ($920) | admitted | DEFINED_MAX_LOSS | **not feasible** |
| Long single call/put, ≥ ~1.2 % OTM | **feasible** (63 call / 74 put strikes) | admitted | DEFINED_MAX_LOSS | **FEASIBLE TODAY** |
| Debit vertical, any width ≤ 5 | feasible ($63-330) | **refused**: `records.py:267` admits only `LONG_CALL`/`LONG_PUT` | **refused** under the session-close exit rule; would be `DEFINED_MAX_LOSS` under hold-to-expiry | not feasible without an exit-rule change |
| Debit vertical, 10 wide calls | blocked ($501) | refused | refused | not feasible |
| Butterfly | feasible ($69-213) | refused | refused, same buy-back exposure on two short legs | not feasible |
| Credit structures (iron condor etc.) | max loss = width − credit, sizeable | refused | not analysed | not feasible |

Fees are not the constraint at any of these sizes: the synthetic schedule is $0.97 per contract to buy and $0.05 to
sell, so a two-leg round trip is about **$2.04**, which is 0.6-3.2 % of the debits above. It does bite the 1-wide
vertical, where $2.04 is 5.5 % of the $37 maximum gain.

## 4. The actual decision this puts in front of you

The blocker is **the exit rule, not the cap**. Three routes, and they are yours to choose:

1. **Trade OTM single legs.** Feasible today with no code change, no certificate change and no exit-rule change.
   Costs nothing to attempt. Buys the least convexity of the three.
2. **Change the exit rule to hold-to-expiry for multi-leg only.** The certificate says in its own words that the
   vertical would then be `DEFINED_MAX_LOSS`. This is a governance change to the exit policy plus new boundary
   vocabulary for two-leg expressions, and it lengthens the horizon from 15 minutes to weeks, which invalidates
   every 15-minute forecast artefact built so far.
3. **Model the exit spread rather than bounding it.** The R4 engine already forecasts the spread state and carries
   its uncertainty. That converts "not knowable" into "modelled with a declared distribution" — but a modelled
   bound is not a certified bound, and the certificate would have to be amended to accept one. That amendment is a
   larger governance question than anything in this memo.

## 5. Data needed to evaluate payoff geometry, and whether we hold it

| Need | Held? |
|---|---|
| Full chain quotes with both sides and sizes, near-dated | **Yes.** 166 one-minute snapshots for 2026-09-11, 09:30-12:15 ET, SPY/QQQ/IWM, 12.3 MB for SPY alone |
| Realised 15-minute outcome for a two-leg structure | **Yes, for one session only.** The 166 snapshots support roughly 150 overlapping 15-minute windows on 2026-09-11 |
| Multi-session history for any statistical claim | **Yes but gated.** `HIST-A-OPTIONS` holds full chains; the ≤ 2021 partitions are TRAIN/VALIDATION and any read needs `R4-FIT-001`, which has not been requested |
| A pricing model that can value two legs from one state | **Yes.** The anchored slice in `apex/joint_wb/accounting.py` prices any strike from the same state, so a vertical is two calls to code that already exists |
| Borrow or financing data | Not needed for defined-risk options; that was the equities fork |
| Assignment and early-exercise modelling for American shorts | **No.** Nothing in the repository models early assignment on a short leg, which route 2 would require |

Nothing here recommends building any of it. The one-session limit is the binding evidence constraint: a single
session cannot support a claim about payoff geometry, and the collector that would produce more sessions is
stopped.
