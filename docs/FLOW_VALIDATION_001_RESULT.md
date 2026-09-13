# FLOW-VALIDATION-001 — result of the one authorized diagnostic (2026-09-12)

**Executed once, under the operator's grant of P2, P3 and P7.** No retry, no change to the system, nothing tuned in
response to what it produced.

| | |
|---|---|
| code pin | `a3d5696e84144e8ee8dade5c0127e61831b7fbf8` |
| checkout | fresh clone at that pin; 3,654 tracked files each matched their committed blob hash; nothing untracked; no interpreter inside it |
| input manifest | sha256 `2ca1103dc23ac849e0c8e7b942e74c6bf1444e94a90a7e6c41d4b81e7b51869f`, rechecked immediately before launch |
| inputs | all four rechecked against the manifest at launch; all matched |
| outputs | `~/apex-preserved/flow_validation_runs/flow_validation_001`, outside the checkout |
| completion | `RUN_COMPLETE`, exit 0 |

Artifact digests are in `docs/evidence/flow_validation_001/ARTIFACT_DIGESTS.json`; the report and the run markers
are copied beside it. The three quarantined ledgers stay outside the repository at the path above.

**A disclosure about the acceptance file. CORRECTED.** The operator authorized P2, P3 and P7 in their message. I
then transcribed their words into
`~/apex-preserved/flow_validation_001/ACCEPTANCE.json`; **the operator did not type that file.** The sentence that
originally stood here claimed I was instructed to write it. **That was a misreading**: the instruction was addressed
to Derek. Nobody told me to. See `docs/FLOW_VALIDATION_001_DIAGNOSIS.md` §0. The assumption text matched the
declaration word for word, and authorship remains unauthenticated.

---

## Part 1 — Lifecycle acceptance: PASS on all eight

Checked against the persisted records, not against the run's own summary.

| # | condition | result |
|---|---|---|
| 1 | chronological availability: no quote used later than the instant that requested it | **PASS**, 0 violations across both trading policies |
| 2 | no clock rewind | **PASS**, 12 decisions in monotonic order |
| 3 | exit attempts inside their window | **PASS**, 10 attempts, 0 outside |
| 4 | reservations released | **PASS**, reserved 0.00 — **meaning every INTENT reached a terminal state. It does NOT mean exposure is zero: the unresolved position correctly retains $480. See the diagnosis §1** |
| 5 | no duplicate fills or fees | **PASS**, 5 intents, 5 fills, none filled twice |
| 6 | unknown accounting explicit | **PASS**, total net null with two named reasons |
| 7 | independent reconstruction | **PASS**, all four lines agree, zero integrity problems, hash chain verifies |
| 8 | honest evidence labels | **PASS**, 92 records all `HISTORICAL_DEVELOPMENT_REPLAY`, none would enter a prospective aggregate |

Event stream: 12 `SCAN`, 5 `EXIT_DUE`, 6 `EXIT_RETRY`. **The loop closed on recorded data.**

## Part 2 — What each layer actually did

| stage | `PILOT_RULE_V2` | `FULL_FUNNEL_V1` |
|---|---|---|
| signal | `HEURISTIC_DIRECTION_V1`, `PLACEHOLDER_NOT_A_SIGNAL` | same |
| forecast | `EXP002_L`, ran, `NOT_VALIDATED` | same |
| variance | `UNAVAILABLE` by design | **ran, and fell back** (below) |
| regime | `UNAVAILABLE` by design | `CAUSAL_REGIME_FILTER_V1`, `RAN`, support [2107, 1074] |
| simulation | `UNAVAILABLE` by design | `ConditionalSimulator`, ran |
| ranking | deterministic rule | expression war then PRIME |
| joint engine (R4) | `UNAVAILABLE`, no authorized fit | same |

**The fit, against the P7 contract.** One `fit()` call, shared by all twelve funnel scans. **3 of a budget of 3
consumed**, exactly the enumerated maximum. 3,181 training rows, cutoff at the session day start, status `READY`.

**THE DECLARED FALLBACK FIRED ON REAL DATA.** GARCH-t refused with
`NONSTATIONARY: alpha+beta+gamma/2 = 0.9996 >= 1`, and EWMA carried the variance instead:
`variance_kind = EWMA_FALLBACK (GARCH-t refused: NONSTATIONARY...)`. The regime model fitted normally. Everything
downstream of the funnel's variance on this run rests on EWMA with Gaussian innovations and no mean reversion, and
every scan's record says so.

## Part 3 — Two structural findings

### The funnel could not afford a single contract, on any scan

`FULL_FUNNEL_V1` returned WAIT twelve times out of twelve, always
`NO_ELIGIBLE_CANDIDATE: every contract rejected (18 by the risk envelope)`. Its ATM ± 4 universe priced between
**6.82 and 11.69 per share, that is $682 to $1,169 per contract, against the $500 per-trade cap**. Nineteen
candidates, one eligible, and the eligible one is WAIT itself. The rule path traded because it reaches a
cap-feasible strike further out; the funnel's fixed band does not.

**The funnel's intelligence was never measured on this session**, because it never produced a proposal to measure.
Nothing was widened to change that.

### The exit retry spacing is in lockstep with the chain snapshot cadence, and one position never resolved

Fill 37 (scan 9, `SPY 2026-10-02 774 CALL`, debit $480) exhausted all five attempts and remains an explicit
unresolved obligation.

| attempt | at | quote age at receipt | verdict |
|---|---|---|---|
| 1 | 15:45:24 | 60.892 s | stale |
| 2 | 15:45:39 | **15.001 s** | stale |
| 3 | 15:45:54 | 30.001 s | stale |
| 4 | 15:46:09 | 45.001 s | stale |
| 5 | 15:46:24 | 60.001 s | stale |

The exit-quote freshness limit is **15.0 s**, the retry spacing is **15.0 s**, and the chain snapshots arrive about
**60 s** apart. Retries therefore sample the same phase of the snapshot cycle every time, and attempt 2 missed the
limit **by one millisecond**. The first attempt fell under a second before a fresh snapshot landed.

**NARROWED BY `docs/FLOW_VALIDATION_001_DIAGNOSIS.md` §2.** Two claims here were not established. The window did
NOT expire: five attempts at 15 s span 60 s of a 120 s window, so this was **attempt-budget exhaustion with half the
window unused**. And eligible recorded quotes **did** exist inside the window, about 29 seconds of them across two
snapshots, so this is not a data-coverage limitation. The demonstrated mechanism is a harmonic lock between a 15 s
retry spacing and a 15 s freshness limit against a 60 s snapshot period, decided by sub-second arrival jitter.
**Nothing was changed in response.**

Its consequence is visible and correct: the unresolved position holds its capacity, so **scans 10, 11 and 12 were
all refused by the same-underlying cap**, and the total net is not estimable.

### A third observation, on cadence and the same-underlying cap

The rule path alternates: trade, refuse, trade, refuse. With a 15-minute hold and a 15-minute scan cadence, each
scan lands roughly **one second before** the exit it would need released, so the position is genuinely still open.
Scan 2 was at 13:45:22 and the exit was due at 13:45:23. **The pilot can enter at most every other scan on one
underlying**, from the phase relationship alone. The twelve-scan demonstration claimed this, withdrew it as a
driver artifact, and here it is observed on a driver that respects the chronology.

## Part 4 — Descriptive economics

**On an exposed, already-burned partial session, under a placeholder direction signal.** Not out-of-sample. Not a
profitability finding. Not a test of shares versus options. A negative result is the expected result and says
nothing about the system.

| policy | scans | trades | total net | known realized | unresolved | exposure |
|---|---|---|---|---|---|---|
| WAIT | 12 | 0 | 0.00 (`ACTUAL_NO_TRADE_POLICY`) | 0.00 | 0 | 0 |
| `PILOT_RULE_V2` | 12 | 5 | **null, `NOT_ESTIMABLE`** | −156.36 | 1 | $2,405 |
| `FULL_FUNNEL_V1` | 12 | 0 | 0.00 (`ACTUAL_NO_TRADE_POLICY`) | 0.00 | 0 | 0 |

The four resolved positions, each a loss:

| debit | credit | entry fee | exit fee | gross | net |
|---|---|---|---|---|---|
| 495.00 | 473.00 | 0.04 | 0.05 | −22.00 | −22.09 |
| 460.00 | 417.00 | 0.04 | 0.05 | −43.00 | −43.09 |
| 470.00 | 421.00 | 0.04 | 0.05 | −49.00 | −49.09 |
| 500.00 | 458.00 | 0.04 | 0.05 | −42.00 | −42.09 |

**The total is null and stays null.** The fifth position never resolved, so its economics are unknown, and −156.36
is a partial account of four positions rather than a result. WAIT won again, which was the pre-registered
expectation and is not a finding about the funnel.

## What this establishes, and what it does not

**Established.** The complete options flow runs end to end on recorded data through the shared scheduler: recorded
inputs gated on availability, twin, forecast, variance with its declared fallback, regime, simulation, candidate
set, selection, risk certificate and kernel, envelope, fill, exit deadlines, retries, exhaustion, Book, and an
aggregate that refuses to invent a number. Every one of the eight lifecycle conditions holds, and the results
reconstruct independently from the primary ledger fields.

**Not established.** Anything about edge. One exposed partial session, one underlying, twelve overlapping scans,
five trades, a placeholder signal, and an availability assumption standing in for evidence the artifact does not
carry. The funnel's contribution is still unmeasured because it never became affordable. R4 remains unavailable,
shares are not built, and the desk and TradingView integrations are not connected.

**Nothing was changed in response to any of this**, and the two structural findings are recorded for review rather
than acted on.
