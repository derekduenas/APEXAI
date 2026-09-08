# EVENT-SOURCE-001 — return

```text
BRANCH:                 event-source-001, fresh worktree from 212de02, clean at start
HISTORICAL EVENT SOURCE: NONE. 6 of 9 families UNTRACED; news is PROSPECTIVE_ONLY
ONLY HISTORICALLY ADMISSIBLE SOURCE: pit_singlename membership (decided_asof 2016-04-29..2026-07-31),
                        which is REFERENCE data, not an event stream
EVENT-DRIVEN EXPERIMENT: NOT CURRENTLY FEASIBLE (historical); prospective blocked by a stale stream
TESTS:                  20 certification + 25 admissibility; smallest relevant regression 10/10 modules
PROTECTED SURFACES:     unchanged; bound tree 616a1912 unchanged; EXP-001B untouched
```

## 1. Artifacts

| Artifact | Location |
|---|---|
| `EVENT_SOURCE_REGISTRY_V0` | `results/EVENT_SOURCE_REGISTRY_V0.json` |
| `EVENT_SOURCE_ELIGIBILITY_MATRIX_V0` | `results/EVENT_SOURCE_ELIGIBILITY_MATRIX_V0.json` |
| `EVENT_SOURCE_MANIFEST_V0` | `results/EVENT_SOURCE_MANIFEST_V0.json` (content hashes, coverage, field eligibility, admission status) |
| `EVENT_SOURCE_CERTIFICATION_REPORT_V0` | `docs/EVENT_SOURCE_CERTIFICATION_REPORT_V0.md` |
| certifier | `scripts/event_source_certify.py` (read-only) |
| tests | `tests/test_event_source_certification.py` |

## 2. The answers the brief asks for

**Best source family for the first event-driven experiment.**
**Scheduled macro releases** — and it is `UNTRACED`, so it must be acquired.
It wins on the one criterion that decides admissibility: the release
instant is *published in advance and measured*, not inferred. BLS and the
Federal Reserve announce exact release times months ahead, so
`publication_time_basis = MEASURED` is achievable rather than aspirational;
the affected instrument (SPY) is already admitted for EXP-001B's window; and
the event count is small enough to enumerate and audit by hand.

Earnings is the natural second: also scheduled, but per-issuer, with a
messier publication surface (wire vs IR page vs 8-K) and a survivorship
question the macro calendar does not have.

**Exact information it could add beyond A0 price state.** A0 knows only the
path. A certified macro release adds three things the path does not contain:
(i) that a scheduled information event is *about to* occur at a known
instant — available before the fact, unlike everything else here; (ii) the
published consensus, with its own provenance and `known_from`; and (iii) the
released value, timestamped at the release instant. The conditioning
variable is *time-to-release* and *surprise*, neither of which is recoverable
from bars.

**Simplest competing baseline.** Time-of-day and calendar dummies — a model
that knows only "it is 08:30 ET on the first Friday" already captures much
of the release-window volatility pattern without any event data. Any event
feature must beat that before it is worth acquiring anything.

**What data acquisition remains necessary.** A macro release calendar with,
per release: scheduled instant, actual release instant, published consensus
with its source and its own publication time, and the released and revised
values kept apart. Nothing on this host has any of it.

**Is an event-driven experiment currently feasible?** **No, historically.**
There is no historical event stream, and the one historically admissible
source is universe-membership reference data. Prospectively it is *not yet*
feasible either, for an operational reason: the capture has written nothing
since **2026-09-04T20:02Z** while `apex-catalyst.service` reports
`active/running, Result=success, NRestarts=0`. A prospective event study
cannot begin on a stream that is silently producing nothing.

**Smallest next brick.** Diagnose and repair the Catalyst capture stall —
read-only diagnosis first, exactly as the orchestrator OOM was handled. It is
small, it is blocking both event paths, and it needs no new data, no
admission and no experiment. Only after the stream is demonstrably producing
should the macro-calendar acquisition brick follow.

## 3. Tests

`tests/test_event_source_certification.py` — **20 passed**, disposable JSONL
fixtures only, covering every case the brief lists: publication time missing;
retrieval time substituted; a revision claiming the original's `known_from`;
future leakage; timezone and DST (including the same instant in two spellings
and the same wall clock across a DST boundary); RFC-2822 vs an ISO-only
consumer; duplicate content from two providers; conflicting values counted
rather than collapsed; source mutation; entity ambiguity (through the
existing gate); corporate-action back-adjustment as PIT-at-decision-date;
event date without publication date; and prospective-only refusal for every
historical purpose.

The existing `event_admissibility` suite (25) and `CatalystEvent` are reused;
**no second event schema was created**.

Smallest relevant regression — every module importing `apex.catalyst`,
`apex.events`, or the new certifier, one contained shard each:

```text
10 modules, 10 rc=0, 252 passed, 0 failed, 0 skipped, 0 errors, 0 OOM; MemoryMax=1400M per shard, User=apex
test_aurelius 17 | test_catalyst_capital 39 | test_catalyst_commissioning 61 | test_catalyst_eyes 10
test_event_admissibility 25 | test_event_capture 3 | test_event_source_certification 20
test_frontier1 25 | test_organism_integration 28 | test_parallax 24
```

Scope: every test module importing `apex.catalyst`, `apex.events` or the new
certifier. The full World Model regression was **not** rerun: nothing under
`apex/world_model` changed and the bound tree is identical.

## 4. Protected surfaces

Recorded before and after with the same hash script:

```text
world_model_surface   a35afdd54ddbc6dc21eb48bfce94ffad9acb2d31b820d941a37f9038adb402f3
registrations         47b33a1247cd264ab5312d7ae32391c89be7b479aff4d5d2b1eeb12c107ab514
twin_contracts        dd904e978bd2a43ec293cb30c7b1ba0617ea89c057b4ee3f452f2ee70e7577f9
catalyst_events       303a8c2d8bc9fd7640acb4bfc9843be276a1ab535248fb15ec74b1674efa75dd
risk_book             8ba6574d66683df2683a5ea45e2229cddfe914f9ee26f69bf8fe762fa638bc0d
real_data_boundary    7612e5dde3c39705971c15dc7a18789192f990444ea417a86860608a5c738e6f
chain_ledger          f802d77b118fced57e6f08cd74bd4fbc181cf4398c0f5b23e5e633dda549024d
```

`PROTECTED_SURFACES_UNCHANGED: True`. Bound source tree
`616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545`
unchanged; `exp001 1a3f55a5…`, `exp001b b3930727…` unchanged. Nothing under
`apex/world_model`, the sealed courts, Risk, Book or the real-data boundary
was touched.

## 5. Not done, by instruction

No FinGPT or Anthropic plugin installed, no StockSharp clone, no proprietary
text copied, no Robinhood connection, no admitted market row read into any
experiment, EXP-001B unaltered, no experiment registered, no probability
assigned, no trading signal generated, and nothing wired into PRIME,
Multiverse, Expression War or execution.
