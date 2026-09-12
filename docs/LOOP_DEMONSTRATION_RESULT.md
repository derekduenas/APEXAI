> **SUPERSEDED on five points by docs/LOOP_DEMONSTRATION_CORRECTIONS.md (2026-09-12).** Retained unedited. The
> eleven consecutive refusals were a DRIVER defect, not the kernel working correctly; the historical-prevalence
> claim about the timestamp defect is withdrawn; the 32-percent cost attribution is withdrawn; agreement is 11 of 12
> on trade-versus-no-trade; and the loss attribution is UNRESOLVED, not ordinary uncertainty.

# LOOP_DEMONSTRATION_RESULT — one fully traceable funnel-to-outcome run (2026-09-12)

Under `docs/LOOP_EVALUATION_CONTRACT.md`, frozen and committed at `c1d40e5` **before** this ran. Evidence:
`docs/evidence/loop_demo/loop_demonstration.json` plus three quarantined replay ledgers. Retained artifacts only,
no provider request. Driver `scripts/loop_demonstration.py`.

## The loop closed, on all three policies, on identical instants

12 scan instants, 09:30–12:15 ET, one underlying. Same boundary, risk authority, kernel, envelope, fee schedule,
execution policy, exit policy and Book for all three. Only the selection policy differs. Every scan recorded,
including every WAIT and refusal. All three books reconcile with **zero integrity problems** and zero unresolved
exits.

| | WAIT | PILOT_RULE_V2 | FULL_FUNNEL_V1 |
|---|---|---|---|
| scans | 12 | 12 | 12 |
| trades | 0 | **1** | **0** |
| WAITs / refusals | 12 policy-WAIT | 11 `KERNEL_REFUSED` | 12 `NO_ELIGIBLE_CANDIDATE` |
| gross | 0 | −22.00 | 0 |
| fees | 0 | 0.09 | 0 |
| **net** | **0.00** | **−22.09** | **0.00** |
| exposure | 0 | $495 | 0 |
| unresolved exits | 0 | 0 | 0 |
| integrity problems | none | none | none |

**WAIT won.** That was the pre-registered expectation and it is not a finding about the funnel.

## The one trade, end to end

`SPY 2026-10-02 749 PUT`, chosen by `PILOT_RULE_V2` at 13:30:23Z: 16 strikes from ATM, 2.06% out of the money,
ask 4.95, debit $495 against the $500 cap. Intent-time expected toll $7.10. Entry fee $0.04, exit fee $0.05
(decimal cents, SEC from actual sale principal). Exited at the recorded bid: credit $473. **Gross −22.00, net
−22.09.** One trade, one loss, classified below.

## The two findings this run produced

**1. A timestamp-granularity defect that silently discarded half of every controlled-clock evaluation.**
`created_utc` is serialized as a microsecond string; parsing it back can return a value up to half a microsecond
**larger** than the epoch it was written from, and the boundary's check `created > now` then refused a forecast
created at exactly the current instant. The first run of this demonstration lost **7 of 12 scans** to
`FORECAST_FROM_THE_FUTURE: created X > clock X`, printing two identical numbers. Live running masks it, because the
clock advances between creation and the check. **Every replay, backtest and controlled-clock test has been silently
losing about half its scans.** Repaired: the comparison is now made at the record's own serialization granularity,
which is a well-typed comparison, not a loosened gate. Re-run: 12 of 12 scans processed on every policy.

**2. The same-underlying cap binds, on real data, for the first time.** `PILOT_RULE_V2` traded once and was then
refused on **all 11 remaining scans**: `KERNEL_REFUSED: SPY risk would reach 995.00 > 600.00`. With a 15-minute
hold and a 15-minute scan cadence, a position is open at exactly the moment the next scan runs, so the
same-underlying limit permits **at most one position at a time** on this symbol. That is the kernel working
correctly, and it is a structural property of the cadence nobody had observed: the pilot's maximum trade rate on
one underlying is one per exit, not one per scan.

## Model identity at every stage, or UNAVAILABLE

Recorded on every scan of every policy. No stage silently substituted a placeholder.

| Stage | PILOT_RULE_V2 | FULL_FUNNEL_V1 |
|---|---|---|
| signal | `HEURISTIC_DIRECTION_V1`, **PLACEHOLDER_NOT_A_SIGNAL** | same |
| forecast | `EXP002_L`, `NOT_VALIDATED: INVALID_NULL_CONTROL`, `drives_selection: false` | same |
| variance | **UNAVAILABLE** — the rule path runs no variance model by design | GARCH-t/EWMA, fit **READY** |
| regime | **UNAVAILABLE** by design | `CAUSAL_REGIME_FILTER_V1`, ran |
| simulation | **UNAVAILABLE** by design | `ConditionalSimulator`, 2,000 paths |
| ranking | `PILOT_RULE_V2` deterministic rule | expression war |
| joint engine (R4) | **UNAVAILABLE** — no authorized fit (R4-FIT-001/002 not granted) | **UNAVAILABLE**, same |
| risk | certificate + kernel + envelope + `ROBINHOOD_RHF_2026` | same |
| exit | `EXIT_AT_HORIZON_15M_V1` | same |

## Head to head

The two policies **agreed on 0 of 12 scans**. Not because they picked different contracts: because
`FULL_FUNNEL_V1` picked none. Its 18 ATM ± 4 candidates cost $734–1,226 against a $500 cap on every scan, while the
rule path reached a $495 contract 16 strikes out. **The integrated funnel contributed nothing measurable, because
it never produced a proposal to measure.** Whether its intelligence would help remains unknown and unmeasured.

## Error classification, per the frozen contract

The single −$22.09 loss:

- **Not an implementation error.** The trade reconstructs, the fees are exact, the Book reconciles, the exit used
  the actual recorded bid.
- **Not attributable to forecast error.** One observation cannot establish a repeated pattern, and the direction
  came from a labelled placeholder.
- **Execution cost measured, and it is not the story.** Predicted toll $7.10 against a $22.09 loss: costs are 32%
  of it, the rest is the underlying moving against a long put. The cost model can now be compared to observation,
  which is what this run makes possible.
- **Classified: ORDINARY UNCERTAINTY.** The loss is retained. **No parameter, threshold, limit, universe or fee was
  changed in response to it, and none will be.**

## What this establishes, and what it does not

Established: the loop closes end to end on real data, every stage records what it used or why it could not,
refusals are named and correct, three policies can be compared on identical opportunities under identical
machinery, and the resulting books reconcile exactly.

Not established: anything about edge. One session, one underlying, 12 overlapping scans, one trade, a placeholder
signal, and an expected-negative result. **§4 of the milestone — repeated chronological sessions — cannot be run:
one partial session exists.** Multi-session comparison needs either the collector restarted (operator) or an
authorized historical grant (`R4-FIT-001`/`002`, not granted). That is the binding constraint on the next step, and
it is not a technical one.
