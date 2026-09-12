# LOOP_EVALUATION_CONTRACT — frozen before execution (2026-09-12)

One fully traceable funnel-to-outcome demonstration. **Committed before the run.** No result informs this
document; an amendment after results exist is a dated amendment, never an edit.

## What is being demonstrated

That the same opportunity set, put through three policies under identical engine, risk, fee, fill, exit and Book
machinery, produces a complete traceable record for **every** scan — including WAITs, refusals and unresolved
exits — and that the integrated funnel's contribution against the simple policy and against WAIT is measurable
after costs.

This is **not** an edge claim. See §7.

## 1. Policies compared, on identical scan instants

| Policy | What it is |
|---|---|
| `WAIT` | the null: never trades. Its P&L is exactly 0 and it is the floor every other policy must clear |
| `PILOT_RULE_V2` | the simple policy: signal → right, first expiry ≥ 21 DTE, nearest cap-feasible strike on the signal's side |
| `FULL_FUNNEL_V1` | the integrated policy: variance fit → regime filter → conditional simulation → expression war over ATM ± 4 → envelope → PRIME |

Same scan instants, same chain snapshots, same NBBO, same bars, same clock. Only the selection policy differs.

## 2. Frozen machinery (identical across all three)

Recording boundary and ledger; `CertifiedRiskAuthority` + `risk_kernel` (limits **unchanged**: $500/trade,
$1,500 aggregate, $600 same-underlying, $1,000 family, $1,000 session drawdown halt); `RISK_ENVELOPE_V1`;
`ROBINHOOD_RHF_2026` v2026-09-12b fee schedule with decimal-cent arithmetic; `EXECUTION_POLICY_V1` (0.25 s
simulated latency, ≤ 3 attempts); `EXIT_AT_HORIZON_15M_V1` (due + 900 s, 120 s window, ≤ 5 attempts); `Book`.

**Nothing is tuned, no threshold moved, no limit raised, no universe widened, no fee altered.** If a policy
produces zero trades, that is the result.

## 3. Data and its status

The burned 2026-09-11 SPY session (`docs/evidence/EVIDENCE_REGISTER.json`), plus the retained prior-bar file
obtained outside authorization (`SCOPE_DEVIATION_001.md`) which the funnel's variance fit requires. **Both are
already burned; this run consumes nothing new and contacts no provider.** Quarantined replay: separate ledgers,
never merged, records carry the known label defect (the boundary cannot label a replay).

**One partial session. 12 scan instants. That is the entire opportunity set.**

## 4. What every scan must record, without exception

Every scan of every policy, whether it trades or not:

- stage-by-stage **model identity**: for each of forecast, variance, regime, simulation, ranking, risk — the model
  or rule actually used, its version/hash, or the literal `UNAVAILABLE` with the reason. **A missing model appears
  as unavailable and never as a placeholder.**
- inputs consulted at each stage (counts, identities, ages)
- output of each stage
- the reason for continuing **or refusing**, by name
- for a trade: intent, fill, exit attempts, outcome, Book state
- for a WAIT or refusal: the named reason and the stage it fired at

## 5. Reported metrics (exhaustive; fixed now)

Per policy: scans; trades; WAITs by named reason; refusals by named reason; unresolved exits; gross P&L; fees;
**net P&L**; per-trade net; worst; best; win count; exposure (contracts × debit); and the count of scans where the
policy could not act because a stage was `UNAVAILABLE`.

Head to head on the same instants: where the policies agree, where they differ, and **which contract each chose**.

## 6. Chronological discipline

Scans are processed in time order. No scan sees a quote, bar or event later than its own instant. Exits use the
actual recorded quote at the exit instant; a missing quote is `UNRESOLVABLE`, never interpolated.

## 7. What this cannot establish, stated before the numbers exist

- **Not an edge claim.** One session, one underlying, one regime, 12 overlapping scans, a placeholder direction
  signal (`SIGNAL_STATUS_001.md`). Excluded from expectancy, calibration and alpha.
- **The expected result is negative for any trading policy**: a 15-minute long single leg pays the spread once and
  theta, roughly 0.90% of premium, against a required 55–63% directional accuracy
  (`docs/SIGNAL_HURDLE_001.md`). `HEURISTIC_DIRECTION_V1` has no established accuracy.
- **WAIT is expected to win**, and that would not be a finding about the funnel.
- **Repeated chronological sessions are NOT possible** with one session of data. §4 of the milestone requires
  multiple sessions; this run cannot supply them and does not pretend to. What it establishes is that the loop
  closes and is traceable, not whether the intelligence pays.

## 8. Error classification, fixed in advance

Any loss observed is classified, before any change is contemplated, as one of:

1. **Implementation error** — repair it and reproduce the failure first.
2. **Forecast error** — only claimable with a repeated pattern, which one session cannot supply.
3. **Execution-cost error** — predicted cost versus observed cost, which this run measures directly.
4. **Ordinary uncertainty** — retain the loss, change nothing.

**No parameter is adjusted against these observations.** Any proposed improvement becomes a challenger: fitted on
earlier data, frozen, evaluated on later untouched data.
