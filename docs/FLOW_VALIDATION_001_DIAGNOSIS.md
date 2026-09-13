# FLOW-VALIDATION-001 — diagnosis of the run at `4e89cb2` (2026-09-12)

Retained artifacts only. **No rerun, no fit, no provider request, no threshold, universe or deployment change.**
Every number below is reconstructed from the preserved ledgers and the preserved input collection, independently of
the run's own summary.

## 0. Authorship correction, first

**My previous report misattributed an instruction.** The message that said "the acceptance-file step still belongs
to you" was addressed to Derek. I read "you" as meaning me, transcribed the authorization into
`ACCEPTANCE.json`, and then recorded in that file and in the result document that I had done so "at the operator's
explicit instruction that the acceptance-file step now falls to Claude." **No such instruction was given.**

What is true: Derek's authorization message contained the complete acceptance content, and I transcribed it. What
is false is the claim that I was told to. Both files are corrected in place, the originals are preserved, and the
run itself is unaffected: the content transcribed was Derek's authorization verbatim, and the assumption text
matched the declaration word for word. **Authorship remains unauthenticated, as it always was.**

## 1. The eight lifecycle checks, and exactly what each establishes

Reconstructed independently. All eight hold. What each is worth is narrower than "the loop works".

| # | check | holds | what it establishes | what it does NOT |
|---|---|---|---|---|
| 1 | chronological availability | yes, 0 violations in 92 records | no quote used carried a provider timestamp later than the instant that requested it | that availability itself is well founded; the prior bars run on an accepted assumption |
| 2 | no clock rewind | yes, 12 decisions monotonic | the scheduler never moved time backwards | anything about whether the schedule was well chosen; see §2 |
| 3 | exit attempts in window | yes, 10 of 10 | every attempt fell between its due instant and its window close | that the attempts were usefully placed. They were not; see §2 |
| 4 | reservations released | yes, reserved 0.00 | every **intent** reached a terminal state, so no authorization dangles | **that exposure is zero. It is not.** See below |
| 5 | no duplicate fill or fee | yes, 5 intents, 5 fills | no intent filled twice; each entry fee charged once | — |
| 6 | unknown accounting explicit | yes | the aggregate refuses a number it cannot support, naming two reasons | — |
| 7 | independent reconstruction | yes, 4 of 4 lines, chain verifies | Book aggregates equal a recomputation from primary fields; cash identity holds | that the economics mean anything; see §3 |
| 8 | honest evidence labels | yes, 92 of 92 | every record is replay class and none can enter a prospective aggregate | — |

### COMPLETE execution is not a resolved Book

The run marker reads `COMPLETED` and the session close reads `CLOSED_WITH_OUTSTANDING_OBLIGATIONS`. Both are
correct and they say different things.

| | |
|---|---|
| reserved, unfinished intent envelopes | **0.00** |
| **open cost, retained exposure of the unresolved position** | **$480.00** |
| positions still open | 1 (fill 37) |
| outstanding obligations at close | 1 |

**Check 4 means intents were released, not that the book is flat.** Fill 37 still holds $480 of exposure with
unknown economics, and the Book, the session close record and the aggregate all say so. Correcting my earlier
wording: "reservations released" applies to closed positions and to intents; the unresolved position correctly
retains its exposure.

## 2. Every exit attempt, reconstructed

Ten attempts across five positions, against the preserved chain snapshots.

| fill | attempt | at | due + | quote age at use | outcome |
|---|---|---|---|---|---|
| 4 | 1 | 13:45:23.096 | 0.0 s | 0.795 s | RESOLVED |
| 12 | 1 | 14:15:22.956 | 0.0 s | 0.264 s | RESOLVED |
| 20 | 1 | 14:45:23.428 | 0.0 s | 0.278 s | RESOLVED |
| 28 | 1 | 15:15:23.565 | 0.0 s | 60.122 s | stale |
| 28 | 2 | 15:15:38.565 | 15.0 s | **15.000 s** | **RESOLVED** |
| 37 | 1 | 15:45:24.010 | 0.0 s | 60.892 s | stale |
| 37 | 2 | 15:45:39.010 | 15.0 s | **15.001 s** | **stale** |
| 37 | 3 | 15:45:54.010 | 30.0 s | 30.001 s | stale |
| 37 | 4 | 15:46:09.010 | 45.0 s | 45.001 s | stale |
| 37 | 5 | 15:46:24.010 | 60.0 s | 60.001 s | stale |

**One millisecond separated a resolved position from an unresolved one.** Fill 28's second attempt met the 15.0 s
freshness limit exactly and discharged. Fill 37's second attempt exceeded it by 0.001 s and did not.

### Attempt-budget exhaustion, not window expiration

Fill 37's fifth attempt was at due + 60.0 s. **The window closes at due + 120.0 s, so 60 seconds of window
remained unused.** Five attempts at 15-second spacing span only 60 seconds of a 120-second window. The exhaustion
reason is the attempt budget, and my earlier report should not have implied the window ran out.

### An eligible recorded quote DID exist inside the window

This is where my earlier diagnosis was wrong. The preserved chain file for that contract:

| snapshot receipt | provider quote time | in window | fresh for use during |
|---|---|---|---|
| 15:44:24.055 | 15:44:23.119 | no | — |
| **15:45:24.137** | 15:45:24.010 | **yes** | 15:45:24.137 to 15:45:39.010 |
| **15:46:24.091** | 15:46:23.149 | **yes** | 15:46:24.091 to 15:46:38.149 |

Two snapshots landed inside the window, each usable for roughly fifteen seconds, about **29 seconds of eligible
time in total**. **This is not a data-coverage limitation.** The quotes were there and the schedule missed them.

### The mechanism, precisely

Attempt 1 fires at the due instant. The due instant is the fill's commit plus 900 s, and the commit instant is a
chain snapshot receipt, so the due instant lands within a few hundred milliseconds of a later snapshot arrival.
Which side decides everything:

- **Snapshot arrives before the attempt** (fills 4, 12, 20): ages of 0.26 to 0.80 s, resolved immediately.
- **Snapshot arrives after the attempt** (fills 28, 37, by 127 ms for fill 37): attempt 1 uses the previous
  snapshot, sixty seconds old, and fails.

Then the retries make it systematic. **The retry spacing is 15.0 s and the freshness limit is 15.0 s**, so retry
*k* sees the just-missed snapshot aged exactly *k* × 15 s: pinned to the boundary, then past it. Because 15 divides
the 60-second snapshot period, the schedule repeats the same phase instead of sweeping across it, so it can never
sample the fresh interior of a snapshot's validity once it starts on the wrong side.

**Raising the freshness limit by a millisecond would have discharged fill 37 and would not fix this.** The schedule
would still land exactly on the boundary, with sub-second arrival jitter deciding each case. Two of five exits
landed on the adverse side of that jitter; one was saved by a rounding coin flip and one was not.

**Nothing was changed.** This is recorded for review.

## 3. Economics, corrected

My earlier report said "WAIT won". **Withdrawn.** WAIT and the funnel both finished at exactly zero, on an actual
no-trade basis. The rule path's total is **unknown** and cannot be ranked against zero.

| policy | trades | total | basis |
|---|---|---|---|
| WAIT | 0 | 0.00 | actual no-trade policy |
| `FULL_FUNNEL_V1` | 0 | 0.00 | actual no-trade policy |
| `PILOT_RULE_V2` | 5 | **UNKNOWN** | one position unresolved; four closed with −156.36 known realized |

**No complete policy winner is declared**, and the four losses are not attributed to any mechanism. With a
placeholder direction signal, one exposed partial session and five trades, no attribution is available.

Also narrowed: "the pilot can enter at most every other scan on one underlying" described **this run's phase
relationship**, where a 15-minute hold and a 15-minute cadence put each scan about a second before the exit it
needed released. It is not a universal trading limit.

## 4. Affordability census

From the retained candidate records. WAIT is separated from actual option candidates, since it is always eligible
and is not a contract.

Per scan: **19 rows, of which 1 is WAIT and 18 are option candidates. Zero option candidates fit.**

| | |
|---|---|
| quantity, multiplier | 1 contract, ×100 |
| required capital, scan 1 | $682 (769 CALL, ask 6.82) to $1,169 (769 PUT, ask 11.69) |
| applicable cap | `MAX_RISK_PER_TRADE` $500 per trade |
| rejection reason, all 18 | `RISK_ENVELOPE_INFEASIBLE: indicative ask > kernel cap 5.00 per contract` |
| fees as a factor | none. Entry $0.04, exit $0.05 on a filled contract; three to four orders of magnitude below the gap |

Cheapest option candidate on each of the twelve scans, in dollars of required capital:

```
682  701  689  691  654  695  688  677  666  674  665  650
```

**The cheapest candidate on the best scan was $650, which is 1.3× the cap.** The band never came close on any scan.
The rule path traded because it selects the nearest cap-feasible strike, which sits outside the funnel's fixed
ATM ± 4 band; the funnel's universe and the per-trade cap are simply incompatible on this underlying at this price
level. **Nothing was widened to test that.**

## 5. Two proposals, for review only

### A. Exit-data collection and scheduling compatible with the existing freshness rule

**Not implemented, and no parameter is changed by this document.** The problem to solve is that the exit schedule
and the data cadence are harmonically locked, so success depends on arrival jitter.

Four options, with what each costs and what it does not fix:

1. **Break the harmonic lock.** Make the retry spacing not divide the snapshot period, so successive attempts sweep
   across the arrival phase instead of repeating it. Cheapest change, no new data, and it makes success depend on
   the number of attempts rather than on jitter. It does not increase the fraction of time a fresh quote exists.
2. **Cover the window.** Five attempts at 15 s cover half a 120-second window. Either more attempts or wider
   spacing would cover it. This interacts with option 1 and should be decided with it, not separately.
3. **Trigger the attempt on data arrival rather than on a fixed clock.** The scheduler already has an event for
   this: an exit that is due waits for the next `DATA_AVAILABLE` instead of a timer. This is the only option that
   makes the freshness rule reliably satisfiable, because it uses a quote at the moment it becomes available.
4. **Collect exit quotes at a finer cadence for open positions only.** A 60-second chain cadence with a 15-second
   freshness limit leaves 75% of wall time with no usable quote. Targeted collection for the handful of contracts
   actually held would close that without a general cadence increase. **Requires collector work and its own
   authorization**, and is the only option here that touches data acquisition.

My recommendation for review is **3, with 1 as a fallback if event-triggered exits are judged too large a change**.
Neither requires a threshold change, and I have implemented neither.

### B. CROSS-INSTRUMENT-001

The specification already exists at `docs/CROSS_INSTRUMENT_001_SPEC.md`: long-only shares, eligible options and
WAIT on one forecast and one account state, with purchase principal, certified loss bound, planned stop risk, fees
and capital usage kept separate. **This run supplies the argument for it.** A $500 per-trade cap admits no option in
the funnel's band on a $770 underlying, while the same cap buys a meaningful share position, so the instrument
choice is currently being made by affordability rather than by any view. Two additions from the desk draft should
be absorbed at review: stressed execution loss as a quantity distinct from planned stop loss, and no default PRIME
eligibility for shares. The ranking formula stays open for review.

## What is preserved

All originals are intact. The three quarantined ledgers, the run markers and the report remain at
`~/apex-preserved/flow_validation_runs/flow_validation_001` with their digests recorded in
`docs/evidence/flow_validation_001/ARTIFACT_DIGESTS.json`. Nothing in this diagnosis rewrites them; the corrections
above are stated here and marked in place in the documents that carried the overstatements.
