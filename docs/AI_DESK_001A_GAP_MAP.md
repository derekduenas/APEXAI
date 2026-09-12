# AI-DESK-001A — schema gaps and bounded change list, mapped to the code that exists

Response to `docs/AI_DESK_INTEGRATION_001.md` at `5c068475b43df5f37c76ec0cb4c0cb9a933f93b1`
(branch `ai-desk-integration-draft-001`). **Nothing in this document is implemented.** It maps the draft's read-only
projection API, chart views and captain contract onto the actual frontend, Twin, model traces and ledger, names the
schema gaps, and proposes a bounded change list for review.

Base surveyed: `operating-loop-001` at `e8ebbee`, which is `trace-replay-001` `1b86541` plus OPERATING-LOOP-001.
That brick's evidence is `docs/OPERATING_LOOP_001.md`. **That branch is not merged here and this branch changes none
of its code.** No provider activation, deployment, risk-limit change or trading authorization is implied.

## Summary: three of the draft's requirements are already built, five are real gaps

| draft requirement | status |
|---|---|
| replay views cannot appear as prospective evidence (A11) | **BUILT** by OPERATING-LOOP-001 |
| missing fee or outcome yields unknown net, never zero (A6) | **BUILT** by OPERATING-LOOP-001 |
| captain unavailable/slow does not delay a due exit (A10) | **BUILT** — exits are scheduler events, not UI or inference callbacks |
| ordered stream sequence, dedup, gap detection (§3) | **PARTLY BUILT** — the ledger's `seq` + hash chain give ordering and integrity, not a reconnectable stream. See GAP 9 |
| chart tools cannot reach order capability (A7) | **BUILT** — the structural placement seal already exists |
| one `snapshot_id` joining state, trace, candidates and inputs | **GAP 1** |
| a queryable as-of bar/candle store | **GAP 2** |
| a candidate set for the DEFAULT policy | **GAP 3** |
| uniform availability and revision identity on chain and NBBO | **GAP 4** |
| a closed model-run state vocabulary | **GAP 5** |
| `schema_version` on pilot records | **GAP 6** |
| any HTTP read surface for this data | **GAP 7** |
| server-enforced scope, symbol, time bounds and response budgets | **GAP 8** |

## What exists, by draft section

### §3 read methods → existing records

| draft method | backing that exists | verdict |
|---|---|---|
| `get_market_snapshot` | `apex/pulse_options/snapshot.py` `compose()`, `OPTIONS_TWIN_STATE_V0`. Per-field `{value, quality, source, as_of, known_from, age_ms}`; `quality_census`, `missingness`, `causality`, `state_hash`. Refuses a future bar outright | **near-complete**; needs GAP 1 and a persisted copy |
| `get_chart_series` | `apex/pulse_options/ingest.py` `BarStore.bars_available_by(as_of)` and `versions()` — as-of visibility and revision history are already correct | **GAP 2**: the store is in-memory. The only persisted bars are the collector's raw payloads on a host-only path |
| `get_model_trace` | `pilot_funnel.trace` (variance, regime, simulation, expression war, prime, fees) plus `engine` = `FunnelEngine.describe()` with `fit_info`, and `funnel_trace` on every `pilot_decision` (`FUNNEL_TRACE_V1/V2`, eight named stages, each a value or a named absence) | **strong**; needs GAP 5 |
| `get_forecasts` | `pilot_forecast`: family, location, scale, nu, native target and horizon, `model_id`, `model_hash`, `params_hash`, `artifact_digest`, six causal instants, `validation_status` | **complete** |
| `get_candidates` | `trace.expression_war.table` inside `pilot_funnel` — per row `label, status, expected_net_pnl, p_loss, q05, entry_ask, iv_sensitivity, why`, with risk-envelope demotion renaming the economics out of reach | **GAP 3**: exists only for `FULL_FUNNEL_V1`, and only inside a trace |
| `get_positions` | `Book` (reservations, positions, closed, cashflows, integrity problems), `session.recover_positions`, `pilot_fill.exit_schedule`, and the new `accounting.net_result` for estimability | **complete** |
| `get_decision_trace` | `pilot_decision` with `forecast_id`, `intent_id`, `fill_id`, `funnel_trace`, plus `seq` + `entry_hash` receipts and `L.verify_receipt` / `L.verify_chain` | **complete**; only needs `decision_id` defined as `scan_id` |
| `get_event_context` | `apex/catalyst/twin_snapshot.py` `event_snapshot()` — scheduled and unscheduled events, `revisions[]`, retractions, verification state, `feed_age_s`, `hostile_text_flagged`, and `EVENT_GATE_V0` | **complete** |

### §4 operator display → the frontend that exists

Two loopback HTTP scripts exist and **neither can support these views**:

- `scripts/flight_deck.py` (`127.0.0.1:8787`, `GET /api/state`) with `scripts/flight_deck.html`. It renders a
  hand-written canvas candlestick chart with **no JavaScript dependency and no CDN**, which settles the draft's
  library/license question in the simplest way: the precedent in this repo is to render APEX's own data with no
  third-party chart library. But its data sources are the crypto arena, hunter forward and execution-intent
  ledgers. **It never reads the options pilot ledger, the twin snapshot or any funnel trace.** Reusing the page
  means reusing its rendering approach, not its data path.
- `scripts/apex_dashboard.py` (`127.0.0.1:8790`). Reads host absolute paths (`/apex-data/core`, `/opt/apex/current`)
  and shells out to `systemctl`. It is an operations console, not a market view. Its `metric(value, source, as_of,
  quality, unit)` / `not_ready(source, why)` pattern is, however, exactly the explicit-absence discipline the draft
  asks for and should be adopted verbatim.

The read model that should sit behind the API already exists and has no server:
`apex/options_pilot/operator_view.py` `build_view(...)` returns model versions, feed, policy, book, reservations,
positions, unresolved exits and recent forecasts/intents/fills/outcomes/refusals/decisions, **each item carrying its
ledger `seq` and truncated `entry_hash`**. Its own docstring anticipates being served read-only.

### §5 captain contract → what is reusable

The structural placement seal already enforces most of the tool restrictions: `apex/execution/robinhood.py` defines
no place or submit function, `ALLOWED_TOOLS` is 22 read/review tools, `FORBIDDEN_TOOL_MARKERS` and
`sealing.assert_no_placement_surface()` fail the build on a placement surface, and the gateway's terminal state is
`ORDER_READY`. A captain adapter inherits that seal rather than re-deriving it. `candidate_set_digest` does not
exist and is GAP 3.

## The eight gaps, concretely

### GAP 1 — there is no `snapshot_id`, and three competing state hashes

| where | what it hashes |
|---|---|
| `apex/pulse/twin.py:272` `TwinState.state_id()` | `(schema, evidence_class, tier, subject, scheduled_time, universe_version)`, sha256[:32]. Designed to be recompute-stable |
| `apex/pulse_options/snapshot.py:196` `state_hash` | `{schema_version, symbol, as_of_epoch, fields, n_bars_available}` — **this is the one that flows into `pilot_funnel.trace.state_hash`** |
| `apex/joint_wb/state.py:213` `state_hash` | `{symbol, t_d, identity, x_iv, x_sk, x_sp, x_sz}` |

The literal field name `snapshot_id` appears only on the scheduled-events calendar files
(`apex/catalyst/twin_snapshot.py`, alongside `content_sha256` and `known_from`).

Two problems beyond the naming. First, **nothing joins** a twin `state_hash`, a `pilot_funnel` ledger seq, a
candidate table and a `pilot_collection_*` receipt into one identity for a single instant — the draft's whole
"one information set" requirement rests on that join. Second, the options twin's `state_hash` covers only *derived*
fields, so two different chain snapshots at the same `as_of` that produce the same derived fields hash identically.
It is a content hash of a feature vector, not an identity for an instant of market state.

**Proposed:** `snapshot_id = canonical_hash({schema_version, symbol, as_of_canonical_us, twin_state_hash,
chain_receipt, nbbo_receipt, bars_watermark})`, using the canonical microsecond from
`apex/options_pilot/instant.py`. Recompute-stable, and it changes when the inputs change even if the features do not.

### GAP 2 — no queryable as-of bar store

`BarStore` gets as-of visibility and revisions exactly right (`bars_available_by(as_of)` hides a revision received
after `as_of` and returns the earlier version; `versions()` keeps the history). It is **in-memory only**. The
persisted options bars are the collector's raw `pilot_collection_bars` payloads under `/apex-data/pilot_collection/`
— a host path, raw provider shape, not indexed by symbol and interval. `data/live/equity_fabric/bars` does not exist
in this checkout. `get_chart_series` therefore has nothing to read.

### GAP 3 — the default policy produces no candidate set, and there is no `candidate_set_digest`

`PILOT_RULE_V2` is the default and it emits **only the chosen contract** plus its strike-selection record. There is
no table of what it considered and rejected. The candidate table exists only for `FULL_FUNNEL_V1`, and only nested
inside `pilot_funnel.trace.expression_war.table`. So `get_candidates(snapshot_id, policy_id)` cannot answer for the
policy the system actually runs, and the captain has nothing frozen to reference. The draft's requirement that a
captain suggestion "must reference the frozen candidate set" is unimplementable until the rule path emits one.

### GAP 4 — availability and revision identity are not uniform across the three feeds

| feed | event | availability | revision |
|---|---|---|---|
| bars | `event_time`, `bar_complete` | `available` = max(complete, last receipt) | `revision_count`, `revised_at` — **complete** |
| NBBO | `as_of` | `available` | **none** |
| chain rows | `timestamp_epoch` (provider ET-naive, localized) | **none** — only `receipt_time` | **none** |

The draft requires every response to carry `event_time, received_at, available_at, as_of, revision identity`. Chain
rows are the weakest: no availability instant distinct from receipt, and no way to express that a quote was
corrected. This matters for A2 more than anything else on the list.

### GAP 5 — model-run state is a free-text string, not a closed vocabulary

The states exist and are honest, but as prose: `{"missing": "NOT_AVAILABLE_IN_PILOT: no regime model is
activated"}`, `{"missing": "NOT_REACHED: <why>"}`, `fit.status = "INSUFFICIENT_HISTORY: n < m bars"`,
`garch = "REFUSED: <msg>"`, `"FIT_BUDGET_EXHAUSTED"`, `variance_kind = "EWMA_FALLBACK (GARCH-t refused: ...)"`. The
draft's A4 requires a model never invoked to display `NOT_RUN` rather than be animated as success. A UI cannot
distinguish those cases by substring matching. **Proposed:** a closed enum `RAN | NOT_RUN | UNAVAILABLE | FAILED |
NOT_REACHED`, emitted alongside the existing prose reason, never replacing it.

### GAP 6 — pilot records carry no `schema_version`

Every pilot record carries `evidence_class`, `decision_power`, `data_provenance`, `execution_mode`, `live_capital`,
`live_promotion_eligible` and `signal_status`, and after OPERATING-LOOP-001 the replay records carry three more
exclusion flags. None carries `schema_version`. The twin snapshots do (`OPTIONS_TWIN_STATE_V0`,
`MARKET_TWIN_STATE_V0`). Adding it to `records.LABELS` touches every record kind and every hash that covers a label
block, so it is the one change here that is not locally contained and needs its own review.

### GAP 7 — nothing exposes any of this over HTTP

No Flask, FastAPI, aiohttp or uvicorn anywhere in the repo; the only HTTP surface is the two loopback
`http.server` scripts above, and `apex/pulse_options/http_policy.py` is outbound only. There is no read API, no
auth, no scope enforcement and no stream.

**CORRECTED 2026-09-12.** An earlier version of this document claimed the ledger's sequence and hash chain were
"better than what the draft asks for" and that "nothing new needs inventing for §3's stream requirements." That
overstated it, and the overstatement is now GAP 9 below.

What the ledger genuinely supplies: `seq` is a monotonic ordered sequence number, `entry_hash` chains every record
to its predecessor so a gap or a tamper is detectable cryptographically, and `L.verify_receipt` lets a client prove
a rendered marker matches the persisted record. That is **ordering and integrity**, and it is the right cursor to
build on.

### GAP 9 — ordering and integrity are not a reconnectable stream

The draft's §3 asks for a stream that a disconnected client can rejoin: show the last-update time and `STALE` on
disconnect, then reconnect via a consistent snapshot plus a sequence cursor, with no silently duplicated or
reordered markers. The ledger gives none of that by itself. Missing: any push or long-poll transport; a consistent
snapshot to rejoin at, which needs GAP 1's `snapshot_id`; a defined `STALE` presentation with a last-update time; a
dedup rule for markers already rendered before the disconnect; and a bound on how far back a cursor may reach. A
reader tailing a file is not a client that can rejoin a stream mid-session and know what it missed. **The seq
cursor is the foundation, not the feature**, and the feature has to be built in item 5 of the change list.

### GAP 8 — no server-enforced scope, symbol, time bound or response budget

Nothing exists. It has to be built with the server, and it is the part a captain's `as_of` must not be able to widen.

## Bounded change list for AI-DESK-001A (read-only, synthetic fixtures)

Seven new files, two touched, **no change to boundary, session, kernel, risk or exit semantics.**

| # | change | kind |
|---|---|---|
| 1 | `apex/desk/identity.py` — `snapshot_id` per GAP 1, over `instant.canonical_micros`; recompute-stable, tested | new |
| 2 | `apex/desk/projection.py` — the eight read methods, over persisted records only. A field the base lacks is reported as a schema gap, never synthesized | new |
| 3 | `apex/desk/model_state.py` — the closed vocabulary of GAP 5, mapping existing prose to an enum without replacing it | new |
| 4 | `apex/desk/bar_store.py` — a persisted, as-of queryable bar view with revision history, reading the collector's records; `BarStore`'s existing visibility rules reused unchanged | new |
| 5 | `apex/desk/server.py` — loopback read-only HTTP, **and the reconnectable stream of GAP 9**: last-update time and `STALE` on disconnect, rejoin by consistent snapshot plus ledger-seq cursor, dedup of already-rendered markers, a bounded cursor reach. **No write routes exist in the module at all**, enforced by a structural test like the placement seal. Scope, symbol, time bounds and response budget enforced server-side | new |
| 6 | `apex/desk/page.html` — the views of §4, rendering APEX's own data with no third-party chart library, following `flight_deck.html`'s precedent and `apex_dashboard.py`'s explicit-absence pattern | new |
| 7 | `tests/test_ai_desk_001a.py` — A1 to A12 as synthetic acceptance | new |
| 8 | `apex/options_pilot/expression_rule.py` — the rule path emits its considered-and-rejected set so GAP 3 closes for the default policy. **This is the only change that touches the decision path**, and it is additive: the selection is unchanged and the emitted set is recorded, not consulted | modified |
| 9 | `apex/options_pilot/records.py` — `schema_version` in the label block (GAP 6). **Proposed separately**: it changes every record and every label hash, so it should be its own reviewed change rather than a line inside a desk brick | modified |

Items 8 and 9 are the two that leave the desk's own boundary. If the reviewer prefers a strictly non-invasive
brick, both can be deferred: AI-DESK-001A then ships with `get_candidates` answering only for `FULL_FUNNEL_V1` and
reporting `SCHEMA_GAP: the rule path records no candidate set` for the default policy, which is the honest behaviour
the draft asks for anyway.

## What the shares/options/WAIT requirement needs from this, preserved

`docs/CROSS_INSTRUMENT_001_SPEC.md` is the specification for that brick, written under OPERATING-LOOP-001 and
unchanged here. Two of its requirements depend on the desk work and are recorded so neither is lost:

- The comparison record it defines (`pilot_instrument_comparison`, one row per candidate with purchase principal,
  certified loss bound, planned stop risk, fees and capital usage, separated) is what closes GAP 3 for **both**
  instruments, and its digest is the `candidate_set_digest` the captain contract needs.
- The draft's §7 adds two requirements the specification should absorb at review time: **stressed execution loss**
  as a quantity distinct from planned stop loss, since a stop does not guarantee a fill at its level; and an
  explicit refusal to classify shares as PRIME-eligible by default. Both strengthen the separation the
  specification already insists on. The ranking formula stays `OPEN_FOR_REVIEW` in both documents.

## Blockers carried forward, unchanged

Cross-release recovery is open. `DEPLOYMENT_DIVERGENCE_001` stands. There is no validated directional signal
(`SIGNAL_STATUS_001.md`). The fee schedule is `CANDIDATE` and `LIVE_DEFAULT_FEES = UNVERIFIED_FEES`. The
recorded-replay route has never been exercised on recorded data. APEX has no order placement capability.
