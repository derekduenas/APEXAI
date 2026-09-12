# EVENT_SOURCE_CERTIFICATION_REPORT_V0

Certification only. No experiment was run, no feature computed, no market
price row read, no event admitted, no experiment registered. Every number
below was measured on the host by `scripts/event_source_certify.py`
(read-only) at branch `event-source-001`, base `212de02`.

## 1. The verdict

**No historically admissible event source exists on this host.** One
*reference* source is historically admissible with limitations, and it is
not an event stream.

| Family | Best status | Why |
|---|---|---|
| scheduled macro releases | `UNTRACED` | nothing on the host |
| earnings dates and releases | `UNTRACED` | nothing on the host |
| SEC filings | `UNTRACED` | the ledger the code expects, `results/events/edgar_events.jsonl`, **does not exist** |
| corporate actions | `ADMISSIBLE_WITH_LIMITATIONS` | `pit_singlename` membership carries `decided_asof` 2016-04-29 → 2026-07-31 — reference data, not events |
| analyst revisions | `UNTRACED` | nothing on the host |
| **news** | **`PROSPECTIVE_ONLY`** | APEX Catalyst capture; `known_from` begins 2026-08-27 |
| options-implied events | `NOT_AN_EVENT_SOURCE` | the manifest is a dataset receipt; per-row publication lives inside the quote files |
| political / geopolitical | `UNTRACED` | nothing on the host |
| social / alternative | `UNTRACED` | nothing on the host |

## 2. The governing rule, measured

`/apex-data/core/catalyst/events.jsonl` — 5,163 records — is the clearest
possible case of the rule the brief states:

| Field | Earliest | Latest |
|---|---|---|
| `event_time` | **2015-01-21** | 2026-09-04 |
| `known_from` | **2026-08-27** | 2026-09-04 |

Event dates reach back **eleven years**. APEX could not have known any of
them before **2026-08-27**, the day capture was switched on. The eleven-year
span is a property of what the feeds republish, not of what APEX knew. Any
research joining these records to a market state before 2026-08-27 would be
reading the future, and the store is therefore `PROSPECTIVE_ONLY`.

## 3. What the capture does well

`raw_observations.jsonl` (5,209 records) is disciplined where it matters:

- `published_time` present on **5,209 of 5,209** records;
- `published_time == retrieved_time` on **0** records — retrieval time is
  never substituted for publication time;
- `known_from` earlier than publication on **0** records — no record claims
  knowledge it could not have had;
- content hashed per observation (`raw_text_hash`), and **26** distinct
  hashes repeat across sources — real duplicate detection, not an assumption;
- `known_from` is retrieval time by construction (the adapter docstring is
  explicit: a release published at 08:30 and fetched at 08:33 was not
  actionable at 08:30).

This is why the store is *prospective*, not *inadmissible*. Going forward it
produces exactly the timestamps an event study needs.

## 4. Four defects found by certification

**(a) The stream is silently stale.** `apex-catalyst.service` reports
`ActiveState=active SubState=running Result=success NRestarts=0`, and the
last event was written **2026-09-04T20:02Z** — over three days before this
certification at 2026-09-08T01:49Z. The service is up and producing nothing.
It is under no maintenance hold. A prospective event study cannot start on a
stream in this state.

**(b) Only 10.5% of observations are fact-bearing.** Source authorities:
`AGGREGATOR` 4,662 · `PRIMARY_OFFICIAL` 472 · `COMPANY_DIRECT` 75. Under the
existing contract only the last two can carry a fact on their own, so most
of the stream is admissible as `ADMISSIBLE_LEAD`, not as fact.

**(c) 44% of `event_time` values would be refused downstream.** Formats:
ISO-8601 2,879 · **RFC-2822 2,279** · unparseable 5. The admissibility gate
(`apex/catalyst/event_admissibility._t`) parses ISO only, so it would raise
`MALFORMED_TIME` on 2,284 of 5,163 records. Not a data defect — an
integration defect between two APEX components, and now a test.

**(d) The SEC path is a dangling reference.** `apex/events/catalyst.py`
declares `EVENTS_LEDGER = results/events/edgar_events.jsonl`; that file does
not exist. The module's honest design means it answers `EVENT_UNCERTAIN`
rather than guessing — but the SEC family has no data at all.

## 5. Field-level eligibility (representative)

| Source | Field | Status |
|---|---|---|
| `apex_catalyst_raw_observations` | `known_from`, `first_seen_time`, `retrieved_time` | `ADMISSIBLE` |
| | `published_time` | `ADMISSIBLE` (never equal to retrieval in this store) |
| | `raw_text_hash`, `locator`, `source`, `source_authority` | `ADMISSIBLE` |
| `apex_catalyst_events` | `event_time` | `ADMISSIBLE_WITH_LIMITATIONS` (RFC-2822 present) |
| | `expected_value`, `actual_value`, `prior_value`, `surprise` | `NOT_ADMISSIBLE` — sentinel-only (`NOT_ESTIMABLE`) throughout; there is no surprise data |
| | `directional_expectation`, `importance`, `mechanism_hypotheses` | `ADMISSIBLE_WITH_LIMITATIONS` — interpretation, never a source fact |
| `pit_singlename_membership` | `decided_asof` | `ADMISSIBLE` |

The full matrix is `results/EVENT_SOURCE_ELIGIBILITY_MATRIX_V0.json`.

## 6. Enforcement, not just labelling

`assert_usable_for(entry, purpose, window)` refuses the combination, because
a status is not a permission slip:

- a `PROSPECTIVE_ONLY` source is refused for `TRAINING`, `VALIDATION` and
  `EVALUATION` — `PROSPECTIVE_ONLY_SOURCE`;
- a window outside the coverage interval — `WINDOW_OUTSIDE_COVERAGE`;
- `NOT_ADMISSIBLE`, `UNTRACED`, `NOT_AN_EVENT_SOURCE` — refused outright.

## 7. Corrections I made to my own classifier

Reading the first output showed three misclassifications, each fixed before
this report:

1. `cycles.jsonl` was `NOT_ADMISSIBLE`; it is an **operational log**, not a
   failed event source. Roles were added, and it is now `NOT_AN_EVENT_SOURCE`.
2. The options and ETF manifests were likewise judged as event sources; they
   are **dataset manifests** whose per-row publication semantics live inside
   the data files, which this brick did not open.
3. `pit_singlename_membership` was `NOT_ADMISSIBLE` because I looked only for
   `known_from`. It carries **`decided_asof`**, a point-in-time decision date
   spanning 2016→2026 — the one historically admissible source on the host.
