# TRACE_ONE_TRADE — one trade, full lineage, through the real path (2026-09-12)

> **CORRECTION NOTICE (2026-09-12, added later; this document is otherwise unchanged).** The −36.10 figure below is
> what the burned run recorded. Under the repaired fee arithmetic the same quotes give **−36.09**, which belongs to
> the CORRECTED FIXTURE in `docs/evidence/trace_replay/part1_correction.json`, **not** to this burned trade. The
> burned ledger and this trace are unchanged. Findings A and B below were repaired in
> `docs/PART1_REPAIR_BRICK.md`; finding C (the boundary cannot label a replay) and the cross-release stranding
> finding remain **OPEN**.

**Mechanism validation, NOT a backtest.** One entry, one exit, on the recorded 2026-09-11 SPY session. No parameter
tuned, no threshold touched, HOLDOUT and CREDIT 5 untouched. Nothing here may inform a parameter choice; two
temptations that arose are recorded in §11 instead of acted on.

**Data burn.** The Thursday SPY chain session (`/apex-data/pilot_collection/2026-09-11/`) is consumed by this block.
It was **never clean**: it was first used on 2026-09-12 for the Stage 0 census
(`docs/evidence/stage0_census_2026-09-11.json`), and again here. Registered BURNED as of 2026-09-12 in
`docs/evidence/EVIDENCE_REGISTER.json`. It remains usable for mechanism work and can never again support a claim
about edge.

**What was real and what was recorded.** Real: `TwinSources`, `Boundary`, `records` validators, `CertifiedRiskAuthority`
+ kernel, ledger, `Book`, `EXIT_AT_HORIZON_15M_V1`, `PILOT_RULE_V2`, `ROBINHOOD_RHF_2026` fees. Recorded (adapters
only): bars, NBBO, chain snapshots, per-contract quotes, and the clock. Driver `scripts/trace_replay_one.py`.

**Ledger:** `REPLAY_QUARANTINED_ledger.jsonl` in the scratchpad, 61 records, chain verified. **Not** under
`/apex-data` or `results/`, and never merged into a pilot ledger (see finding C).

## The ten steps, with ledger seq and record hash

**Scan:** `TRACE-REPLAY-2026-09-11:0028:SPY`, decision instant **2026-09-11T13:57:22.510Z**.

| # | Step | Seq | Hash | Content |
|---|---|---|---|---|
| 1 | raw rows → normalized chain | — | — | 331 provider rows in the snapshot received 13:57:22.510Z; **331 valid, 0 excluded, 0 conflicted** under `DUPLICATE_POLICY_V1` (see §"refused row") |
| 2 | forecast | 56 | `9266de4b4b94` | `EXP002_L`, Student-t, location −1.8566e-05, scale 1.2434e-03, ν 6.3845; `direction_signal LONG`; `validation_status: NOT_VALIDATED … INVALID_NULL_CONTROL … no edge claim`; 31 bars available, NBBO as-of 13:57:22.266Z |
| 3 | candidate census | (sealed on 57) | — | 160 strikes; **70 on the LONG side**, 70 with an indicative ask, **62 cap-feasible**; ATM K=766 ask 8.94 **rejected: above the $5.00 envelope**; 0 rejected by the selector, 0 by the provider |
| 4 | strike selection | (sealed on 57) | — | `PILOT_RULE_V2`; spot 765.7314; **strike 774.0**, distance +8.2686 (+1.0798%), **8 strikes from ATM**; cap 5.00; *"V1 would have chosen K=766.0 (ask 8.94), which the envelope refuses"* |
| 5 | certification | (sealed on 57) | — | `CERTIFIED_KERNEL`, authority `RISK_CERTIFICATE_V0+ORGANISM_PAPER_V1`, **approved**, `certified_max_loss 500.0`, certificate hash `11ea81d2…`, envelope `KERNEL_CAP` max entry 5.00 / debit 500.00; kernel re-check at commit approved, basis `SUM_OF_VERIFIED_CERTIFIED_MAX_LOSS`, `gap_exposed: false`, `label_equals_bound: true` |
| 6 | intent | **57** | `ff237373213a` | `LONG_CALL` SPY 2026-10-02 774.0, qty 1, `intent_id 1eb0412e49a88559b67f89ec`, contract id `SPY\|2026-10-02\|774.0\|CALL`; reference quote 4.86/4.90 sizes 59×50 @13:57:22.471Z; TTL 120 s; pins: exit policy `EXIT_AT_HORIZON_15M_V1` `9f9784f7…`, execution policy `a3d80ad8…`, fees `ROBINHOOD_RHF_2026` `PROVIDER_VERIFIED`, toll formula `17060e97…`; doctrine: footprint **0.02** (1 contract / ask size 50), tail_asymmetry `UNKNOWN`, five fields `NOT_MEASURED`; **expected_toll 4.10** = 100×(4.90−4.86) + 0.04 + 0.06 |
| 7 | fill | **58** | `1e700a696074` | quote 4.86/4.90 @13:57:22.471Z, **age 0.039 s at receipt**, 0.289 s at the simulated execution instant; side crossed ASK; **price 4.90, net debit 490.00**; entry fees **0.0403** (commission 0.00, ORF+OCC 0.04, CAT 0.0003) → 0.04; `simulated: true` |
| 8 | exit at +15 min | 60, **61** | `f59e448f611a`, `b04cdc0d63f6` | **attempt 1 at 14:12:22.510Z REFUSED** `NOT_ESTIMABLE: STALE_SELECTED_CONTRACT: BID side 59.694 s old at receipt` (the recorded snapshot was 14:11:22.85Z, bid 4.65); **attempt 2 at 14:12:37.510Z RESOLVED** against the 14:12:22.81Z snapshot, **bid 4.54** |
| 9 | Book | — | — | credit 454.00, exit fees 0.06, **realized P&L −36.10**; 1 closed, 0 open, `fees_unknown: false`, integrity problems `[]` |
| 10 | scoring / attribution | — | — | the outcome record is the scored observation; gross −36.00, fees −0.10, **net −36.10** |

Expected toll at intent time **4.10** against a realized loss of **36.10**: the spread was crossed once at entry and
once at exit, and the underlying moved against the position in the 15 minutes. Decomposition is Part 3's job and is
not done here.

## Reconstruction proof

`scripts/trace_reconstruct.py`, separate process, reads **only** the ledger file. **19 of 19 checks clean, 0
mismatches** (`reconstruction.json`): chain verified over 61 records and every entry hash recomputed from its own
content; `contract_id`, `intent_id`, the forecast reference hash, the fill's intent binding and the canonical
proposal digest all re-derived; the named fee schedule's hash matched and entry/exit fees recomputed; net debit,
credit and realized P&L re-derived from the sealed quotes; the Book reloaded by the real loader agreed on every
figure; the intent-time toll recomputed to 4.10 from the sealed reference quote. **The trade is rebuildable from the
ledger alone.**

## Findings (Part 4, reported early because two are defects)

**A. SEVERE — the fee-provenance gate checks the wrong object.** `CertifiedRiskAuthority.approve` gates on
`self.fee_schedule.provenance`; the schedule sealed on the intent (`body["fees"]`) and the one the Book uses both
come from `Boundary.fee_schedule`. **Nothing cross-checks them.** The first run of this driver passed the authorized
schedule to the authority and left the boundary at its `UNVERIFIED` default: the authority **approved a LIVE_FEED
intent** whose own record read `fees: {schedule_id: UNVERIFIED, known: false}`, whose `expected_toll` read
`NOT_ESTIMABLE: fee schedule unknown`, and whose exit fees were `null`. The gate whose entire purpose is "an unknown
cost is not zero" was satisfied while the record said the cost was unknown. Same failure class as the PRIME spread
gate: a gate that checks a property of a different object than the one that reaches the record. Not repaired here
(this block forbids it); proposed repair: the authority must refuse unless the schedule it gates on is *identical by
hash* to the schedule the boundary will seal.

**B. The `x or 0` idiom again, in the Book.** `book.py:109`: `pnl = round(credit - debit - (fee_total or 0.0) - (fx
or 0.0), 2)`. With fees unknown this substitutes **zero** for an unknown cost and still produces a realized P&L. In
the first run it printed `session_realized_pnl: -36.00` with `fees_unknown: True`. The flag exists and
`_check_fee` runs, so it is not silent, but the number itself is computed as though an unknown fee were free. Third
site of this idiom found in three blocks. Not repaired here.

**C. The boundary cannot label a replay.** `records.assert_prospective` refuses `HISTORICAL_DEVELOPMENT_REPLAY` and
`EXECUTION_MODES` contains only `PROSPECTIVE_ORCHESTRATION`, so every record this trace wrote claims
`execution_mode: PROSPECTIVE_ORCHESTRATION` and `evidence_class: PROSPECTIVE_PAPER` — **both false for a replay**.
The firewall that keeps replay out of prospective evidence works by making replay records unwritable, which means a
mechanism trace through the real boundary can only be produced by writing records that lie about their own class.
Mitigated procedurally: quarantined ledger path, never merged, registered. Proposed amendment (not applied): a
`MECHANISM_REPLAY` execution mode that is refused by every scoring path.

**D. My own driver defect, recorded.** The first version kept the *last* receipt per bar; the collector's 5-minute
request window returns each bar about five times, so every bar looked 262 s stale and **all 166 scans refused**
`ret_1 is STALE`. The causally correct choice is the *earliest* receipt (when APEX could first have known the bar).
Fixed in the driver, not in APEX. Worth noting because the live path does not have this problem (it receives each
bar once) but any future replay driver will.

**E. The 15-minute exit policy is enforced by code, not convention.** Confirmed: attempt 1 fired exactly at
fill + 900 s and was **refused** for a 59.7 s-stale bid; attempt 2 inside the 120 s window resolved. The policy's
window, attempt count and staleness rule all executed. No interpolated price was used anywhere.

**F. Refusal reasons observed.** `FEATURE_UNAVAILABLE: ret_1 NOT_ESTIMABLE/STALE` on the 27 scans before warm-up
completed (correct); `RISK_ENVELOPE` rejecting the ATM strike on every scan (correct, and the reason V2 exists);
`STALE_SELECTED_CONTRACT` on exit attempt 1 (correct). **Never fired in this session:** `DUPLICATE_CONFLICT`,
`RIGHT_NOT_DECLARED`, `QUOTE_CROSSED`, `INDICATIVE_STALE` — the recorded ThetaData snapshots contained **no malformed
or conflicting row at all** (0 exclusions across all 166 snapshots × 331 rows). The block asked for a REFUSED row in
step 1; the data contains none, so none is shown. That is a fact about the vendor's data quality on one session, not
evidence the refusals work; their tests cover that.

## Configuration used (unchanged, and unchanged by anything here)

`PILOT_RULE_V2`, cap $500/contract, `EXIT_AT_HORIZON_15M_V1` (900 s + 120 s window, ≤5 attempts),
`EXECUTION_POLICY_V1` (0.25 s simulated latency), `ROBINHOOD_RHF_2026` fees, 65-minute warm-up, 21-DTE minimum.
Monday's live run proceeds under exactly this configuration.
