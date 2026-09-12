# LOOP_DEMONSTRATION_CORRECTIONS — closing the evidence for the 12-scan run (2026-09-12)

Five corrections to `docs/LOOP_DEMONSTRATION_RESULT.md`. That document is **superseded on every point below** and
is retained unedited so the original claims and their corrections both stand on the record. No new evaluation was
run, no model fitted, no provider contacted, no universe, limit or selection rule changed.

## 1. Identity of the runs, and a preservation failure

| | Original run | Corrected run |
|---|---|---|
| driver | `scripts/loop_demonstration.py` | same file, unchanged |
| code revision | `c1d40e5` (contract frozen; timestamp defect present) | `c1d40e5` + the timestamp amendment, committed at `235587b` |
| inputs | burned 2026-09-11 SPY collection; retained prior bars sha `e6985762…` | identical |
| configuration | `PILOT_RULE_V2` / `FULL_FUNNEL_V1` / WAIT; `ROBINHOOD_RHF_2026` v2026-09-12b; limits unchanged | identical |
| output | **NOT PRESERVED** | `docs/evidence/loop_demo/loop_demonstration.json` + three ledgers |

**Preservation failure, stated plainly.** The driver writes to a fixed output directory and unlinks its ledgers on
start, so the corrected run **overwrote the original run's JSON and all three ledgers**. The contract required both
outputs; only the corrected one exists as an artifact. What is known of the original is transcript-sourced: 7 of 12
scans refused `FORECAST_FROM_THE_FUTURE` on the rule path and the same 7 on the funnel path, with the identical
printed-equal timestamps. That is testimony, not evidence, and it is labelled so. The driver should write to a
run-scoped directory; not repaired here.

**The timestamp repair is a post-contract implementation amendment**, not part of the frozen contract: the contract
was frozen at `c1d40e5`, the defect was found during execution, and the repair landed after. Recorded as such.

## 2. Timestamp comparison at the declared precision

The claim "every previous controlled-clock evaluation lost about half its scans" is **withdrawn**. It was inferred
from one fixture, not measured. What is established: **7 of 12 scans in this run**, on both trading policies.
Retained refusal records elsewhere were checked for the signature and no other run's persisted records were
available to search: the trace-replay ledger predates the demonstration and contains no `FORECAST_FROM_THE_FUTURE`
refusal, and no other controlled-clock run retained a ledger. **Historical prevalence: unknown, and not claimed.**

Declared precision: **records serialize epochs as microsecond strings, and comparisons are made at 1 microsecond**
(`records.TIMESTAMP_GRANULARITY_S`). `tests/test_loop_lifecycle_and_precision.py` covers equal instants; a
serialization round trip that rounds upward (the demonstration's exact failure); the immediately preceding
representable instant; timezone-equivalent instants; invalid timestamps (empty, malformed, `None`, out-of-range);
and **genuinely future instants at 1e-5, 1e-4, 1 ms, 1 s and 60 s, every one of which is still refused**. The
tolerance is exactly one granularity and no more: +1e-6 is accepted, +1e-5 is refused. It does not hide a future
timestamp.

## 3. The eleven refusals were a DRIVER defect. My explanation was wrong.

Reconstructed from the persisted ledger alone (`docs/evidence/loop_demo/scan_reconstruction.json`):

| Fact | Value |
|---|---|
| fill committed | 13:30:23.097Z, debit $495 |
| **exit due** | **13:45:23.097Z** |
| exit window closes | 13:47:23.097Z |
| scan 2 | 13:45:22.389Z — **0.71 s BEFORE the exit was due** |
| scans 3–12 | 14:00:22Z onward — all **after the window closed** |
| housekeeping runs before any scan | **never** |

`apex/options_pilot/entrypoint.run_pilot` performs `S.resume` + `S.attempt_exits` at the start of every cycle after
the first (`entrypoint.py:167-172`). **My driver omitted that step**, ran all twelve scans, and only then attempted
exits — and in doing so **rewound the clock** from 16:15Z back to 13:45Z, violating the frozen contract's own
chronological discipline (§6).

Consequently:

- **Scan 2's refusal is correct and stands.** The exit was genuinely not yet due.
- **Scans 3–12 are void as evidence about the system.** The position was never valued because nothing valued it.
- **"The kernel permits at most one position at a time" is WITHDRAWN.** It was never tested.
- **"The same-underlying cap binds on real data" is narrowed** to scan 2 only.
- Not an unreleased reservation and not an unresolved exit: the reservation derives from a genuinely open fill, and
  the exit RESOLVED on attempt 1 the moment it was attempted.

Reproduced synthetically, as required, before any repair scope was expanded
(`tests/test_loop_lifecycle_and_precision.py::TestHousekeepingReleasesTheBlock`): with the same debit condition,
**without** housekeeping a due position blocks the next scan; **with** `S.resume` + `S.attempt_exits` the exit
discharges, capacity is released and the next scan trades; an exit attempted before its due time correctly does not
resolve; and the real entry point provably runs housekeeping before its scans. **The driver is the defect. The
system behaved correctly at every step it was actually asked to perform.**

## 4. Decision taxonomy, agreement, and cost attribution

**Decisions separated by kind**, computed from persisted decisions
(`docs/evidence/loop_demo/decision_taxonomy.json`):

| Policy | TRADE | policy abstention | candidate exclusion | risk refusal | input failure |
|---|---|---|---|---|---|
| WAIT | 0 | **12** | 0 | 0 | 0 |
| PILOT_RULE_V2 | 1 | 0 | 0 | **11** | 0 |
| FULL_FUNNEL_V1 | 0 | 0 | **12** | 0 | 0 |

A funnel scan where every candidate fails the envelope is a **candidate exclusion**, an eligible WAIT, not an
integrity failure. No integrity failure occurred in any policy.

**Agreement, defined and computed.** On *trade versus no-trade*, the two trading policies agreed on **11 of 12**
scans. On the exact decision label they agreed on 0 of 12 (`REFUSE` versus `WAIT`). The earlier "zero agreement"
used the label definition without saying so; the informative number is 11 of 12, and it is high only because the
rule path was blocked by the driver defect for 11 of them.

**Cost attribution, corrected.** The claim "costs are 32% of the loss, the rest is the underlying" is
**withdrawn**. Reported separately, without inference:

| Quantity | Value | What it is |
|---|---|---|
| predicted toll at intent time | **$7.10** | `TOLL_FORMULA_V1`, an estimate from the indicative quote |
| observed fees | **$0.09** | measured, entry $0.04 + exit $0.05 |
| entry spread crossed | ask 4.95 vs mid 4.925 → **$2.50** | reconstructed from the sealed entry quote |
| exit spread crossed | not independently reconstructible | the outcome record seals the executed bid, not the contemporaneous ask |
| realized net | **−$22.09** | measured |

The residual is **not attributed**. An option's value also moves with implied volatility, elapsed time and other
pricing effects, and this run separated none of them.

## 5. Loss attribution: UNRESOLVED

The earlier classification of "ordinary uncertainty" is **withdrawn**. A reconciled trade establishes accounting
consistency, not the absence of an upstream defect. With one trade, a placeholder direction input, a driver that
omitted housekeeping and rewound the clock, and no decomposition of the price move, the honest classification is
**UNRESOLVED**. It stays unresolved until there are repeated observations under a driver that respects the
contract's chronology. **Nothing was changed in response to the loss, which remains the case.**

## What this does not resolve

The funnel's trading value is still untested: it abstained on every scan because its candidate set was
unaffordable. The current comparison varies **both** the intelligence and the available contracts, so it cannot
attribute any difference to the intelligence. Either the policies must receive the same eligible opportunities
under a declared comparison, or the report must state that whole policies with different universes are being
compared. This document states it.
