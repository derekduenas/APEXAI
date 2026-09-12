# JOIN_COVERAGE_LIST — where the next defect lives (2026-09-12)

From the standing rule: **components are tested, joins are not.** Every defect found by source reading in the last
four review rounds was a join. This is the list of joins on the pilot decision path with **no contract-written
test** — a test that asserts the two sides agree, not that each side works. Nothing here is built. The list is the
deliverable.

Ranked by what a failure costs.

## Risk-bearing joins (a failure admits or mis-sizes a position)

| # | Join | What must agree | Test today |
|---|---|---|---|
| 1 | **kernel inputs ↔ Book state** | `risk_inputs()` must describe the same positions and reservations the Book holds at the same instant | each side tested; **no test asserts they describe the same book** |
| 2 | **certificate `certified_max_loss` ↔ envelope `envelope_debit`** | the certified bound and the reserved capital must be the same number for the same intent | both computed, never compared in a test |
| 3 | **kernel check at approval ↔ kernel re-check at commit** | the same intent against a Book that may have changed; only the second binds | the re-check is tested; **no test makes the Book change between them** |
| 4 | **reservation lifecycle ↔ intent lifecycle** | a reservation must exist exactly while its intent is unfinished | `intent_finished` tested; no test asserts the reservation count tracks it across expiry, cancel, fill and recovery |
| 5 | **`same_underlying_risk` / `same_family_risk` ↔ actual positions** | the family classifier and the Book's symbols | `beta_family` tested alone; no test with two symbols in one family and a cap that binds |
| 6 | **exit obligation ↔ Book open positions** | every unresolved fill must appear as an open position and be exit-scheduled | the stranding finding is exactly this join failing across releases |

## Identity joins (a failure lets two things that must be one differ)

| # | Join | What must agree | Test today |
|---|---|---|---|
| 7 | **forecast artefact hash ↔ the artefact actually loaded** | the sealed `artifact_digest` and the object that produced the numbers | digest recorded; **never recomputed from the loaded artefact** |
| 8 | **execution policy hash on the intent ↔ the policy the fill used** | latency, attempts, size rule | hash sealed; no test alters the policy between intent and fill |
| 9 | **exit policy hash on the intent ↔ the policy `attempt_exits` runs** | due time, window, attempts | same shape as 8, untested |
| 10 | **release / runtime identity ↔ the code that produced the record** | `runtime_identity` vs the modules actually imported | identity is measured; no test asserts a changed module changes it |
| 11 | **`contract_id` ↔ the contract inside every record that references it** | intent, fill, outcome, Book position | each validates its own; no test alters one and asserts the others refuse |
| 12 | **funnel `rule_id` ↔ the engine that produced the proposal** | policy identity on the funnel path | rule path covered by the policy-identity tests; **the funnel path's equivalent is not** |

## Economic joins (a failure produces a wrong number that looks right)

| # | Join | What must agree | Test today |
|---|---|---|---|
| 13 | **intent-time `expected_toll` ↔ realised toll from the sealed quotes** | the formula's prediction and what happened | both recorded; **never compared** — this is Part 3's subject and has no test |
| 14 | **funnel modelled exit fee ↔ the fee actually charged at exit** | `EXIT_PRINCIPAL_EQUALS_ENTRY` assumption vs the real principal | assumption now declared; no test measures its error |
| 15 | **modelled candidate P&L ↔ Book realised P&L for the same contract** | the simulator's expectation and the outcome | never compared; the funnel has never selected anything |
| 16 | **`gross_pnl` + fees ↔ `realized_pnl`** | the three must reconcile on every closed position | now tested for known and unknown fees; **not tested for a partial-fill quantity ≠ 1** |
| 17 | **cashflow ledger ↔ Book cash** | the sum of cashflows and the reported cash | `gross_cash` reconciles; no test asserts it against an independently computed sum across mixed known/unknown fees |

## Temporal joins (a failure lets the system see the future)

| # | Join | What must agree | Test today |
|---|---|---|---|
| 18 | **bar `available_time` ↔ the scan clock** | no bar visible before it was receivable | tested in the R4 state composer; **not on the pilot's own snapshot path** |
| 19 | **event `known_from` ↔ the decision instant** | the firewall | tested in fixtures; **never on real event data** (none has flowed) |
| 20 | **quote `timestamp_epoch` ↔ receipt ↔ simulated execution instant** | three clocks that must be ordered | freshness tested at each stage; no test asserts the ordering across all three at once |
| 21 | **forecast `input_cutoff` ↔ the bars the features used** | the forecast may not use a bar after its own cutoff | cutoff recorded; **never asserted against the actual feature window** |

## Recording joins (a failure breaks reconstruction)

| # | Join | What must agree | Test today |
|---|---|---|---|
| 22 | **`prev_hash` chain ↔ file order** | the chain and the physical lines | `verify_chain` tested; no test asserts a reordered file fails |
| 23 | **receipt `seq` ↔ the record at that position** | receipts index into the ledger | verified at read; no test inserts a record and asserts stale receipts refuse |
| 24 | **`funnel_ref.proposal_digest` ↔ the funnel record's proposal** | binding across records | tested; **the equivalent for `forecast_ref.forecast_hash` after a forecast rewrite is not** |

**24 joins with no contract-written test.** Six are risk-bearing. The three defects found by reading source in the
last two rounds were joins 1-class, 13-class and 2-class respectively, which is the argument for the list.
