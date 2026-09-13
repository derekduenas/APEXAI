# TRADINGVIEW-INTEGRATION-003 — the live catalog, the first real smoke, and the production snapshot join (2026-09-13)

Branch `tradingview-integration-003`, based on `tradingview-integration-002` at
`4682e4f7a29d09f74699dbc8815cdcdb465e529d` (itself based on `be626bbc42a5a9ae359994191baaf3165617be41`).
TradingView modules originate on `tradingview-connector-001` at `39fbd21`.

**Observation-only boundary preserved. Nothing is connected to order placement, execution, risk authorization or
options quotes.**

## Status in one line

**The live catalog was observed and reconciled, the bounded smoke RAN (9 real read-only calls, 9/9 `OK`), and the
snapshot join is now wired into the real pilot decision path — a decision record names the market state it was made
on and what each external observation contributed. Production integration is NOT claimed: the join is wired and
tested, but no live trading session has run through it.**

---

## 1. The catalog, as exposed

The two previous bricks could not see a single TradingView tool. CONNECTOR-001 diagnosed why (the server is
registered under `project /Users/derekduenas`, not under the worktree) and prescribed a remedy it could not test:
start the session from `/Users/derekduenas` and work on the worktree from there. **That is what was done, and it
worked.** This session was exposed **27** tools.

Recorded verbatim in `docs/evidence/tradingview_integration_003/live_catalog_2026-09-12.json`. Every tool is named
`mcp__mcp-tradingview__mcp-tv-<kebab>`.

`/mcp` itself could not be run — it is a terminal-dialog command, unavailable in the desktop Code tab. The catalog
was enumerated from the session's own tool registry, and the full JSONSchema of each of the nine tools this
connector calls was then fetched and read verbatim. That is the same underlying catalog, and it is what is
recorded; nothing is reported as observed that was not.

**What is NOT there:** no watchlist tool of any kind, and no order, position, portfolio, execution or
options-quote tool of any kind.

## 2. Reconciliation — live, and it found three defects

`apex/tradingview/allowlist.py` was written in bare snake_case against the published documentation. The server
speaks kebab-case under two prefixes. Reconciling the two exposed three real defects:

| # | Defect | Consequence | Fix |
|---|---|---|---|
| 1 | All nine `ALLOWED_TOOLS` were refused in their live spelling | The connector could not call **anything**. It failed safe, which made it invisible: a connector that denies everything looks exactly like one that is idle. | Names are canonicalized before any check; one tool has one reviewed identity in either spelling |
| 2 | `mcp-tv-stop-alerts` slipped the `FORBIDDEN_MARKERS` belt | The marker is `stop_`; the live spelling has no underscore, so it matched nothing and only default-deny stood between it and the wire | Markers are matched on the canonical name |
| 3 | `normalize` keyed `EXTERNAL_CONTEXT_TOOLS` off the raw string | A live-spelled news call was stamped `OBSERVATION_ONLY` — the same headline carrying **more authority** because of how it was addressed | The canonical name governs the authority stamp |

**Result: 27 live = 9 allowed + 18 denied, 0 unclassified.** `reconcile()` exists to make an unclassified live
tool *visible*; default-deny already makes it *safe*.

Every mutating, alert, webhook, watchlist, order, execution and unknown tool remains denied. The eight watchlist
denials — `get_active_watchlist` among them — were written from documentation and are **not in the live catalog**;
they are now labelled `DOCUMENTED_NOT_LIVE` and **stay denied**, because a tool absent today can appear tomorrow.

## 3. The bounded live smoke — 9 calls, 9/9 `OK`

Recording: `docs/evidence/tradingview_integration_003/smoke_calls_2026-09-13.json`
Result: `docs/evidence/tradingview_integration_003/smoke_result_2026-09-13.json`

| # | tool | args | disposition |
|---|---|---|---|
| 1 | `search-symbols` | `query=SPY, type_filter=etf` | resolved **AMEX:SPY** |
| 2 | `get-screener-columns` | `search=volatility, market=etf` | 1 column |
| 3 | `get-economic-calendar` | `countries=US, min_importance=1` | empty (a Sunday) — recorded as a successful observation, **not** a provider error |
| 4 | `get-ohlcv` | `AMEX:SPY, 1D, count=5` | 5 bars, all `COMPLETE` |
| 5 | `get-technicals-rating` | `AMEX:SPY, 1D` | `EXTERNAL_CONTEXT_ONLY` |
| 6 | `get-news` | `AMEX:SPY, limit=3` | 3 headlines of 200 |
| 7 | `get-earnings-calendar` | `[AMEX:SPY, NASDAQ:NVDA]` | NVDA only (an ETF has no earnings) |
| 8 | `get-dividends-calendar` | `[AMEX:SPY]` | 1 row |
| 9 | `get-news-story` | id from #6 | full text |

### How the instants were obtained, stated precisely

**The agent is the transport and cannot observe the socket.** So each call is bracketed by a genuine wall-clock
reading taken *before* the request was issued and *after* the response arrived:

```
T0 1789275563.131187   T1 1789275585.735981   T2 1789275619.470324
T3 1789275633.819387   T4 1789275648.807049
```

Group A (calls 1–3) is bracketed `[T0,T1]`, B (4–6) `[T1,T2]`, C (7–8) `[T2,T3]`, D (9) `[T3,T4]`. Every bracket
is a **true containing interval** for its calls. `known_from` is the *later* bound, which can only ever
**understate** availability — it can never manufacture hindsight, which is the direction that matters.

**No timestamp here is fabricated.** "Verbatim payload" means: the payload as delivered to the agent by the MCP
client, transcribed into the recording; the digests in the result cover that recording, which is the artifact of
record. The transcription of the one long prose payload is checked structurally — its `ast_description` must
itself parse as JSON, which it does.

**No OAuth credential was persisted, read, exported or inferred.** The adapter takes an injected transport and
holds no credential by construction.

### What the live data changed

- **The server states its own delay**: *"bars are delayed 15+ minutes depending on the exchange."* Entitlement for
  bars is therefore `DELAYED_VERIFIED`, not `UNKNOWN`. The connector had no verified-delay case before, because no
  server had ever answered it.
- **Symbol discovery resolved `AMEX:SPY`** rather than a caller guessing an exchange prefix.
- **The live technicals payload literally contains `recommendation: "BUY"`.** It reaches the record as an
  observation with `EXTERNAL_CONTEXT_ONLY` authority and `calibrated: False`, and nothing else. A test asserts it.
- **News text is untrusted data.** The retrieved story carries third-party stock promotion. It is recorded, never
  interpreted as an instruction, and cannot widen the allowlist, change authority or reach a tool.

## 4. The production seam

Previously `seam.py` said, accurately, that it was *not wired*. It is wired now — narrowly.

- **`TwinSources.snapshot()` emits a deterministic content-addressed `snapshot_id`** (`apex/pulse_options/snapshot.compose`).
  Derived from `state_hash`, so there is exactly **one** content digest in the system and a short id can never
  disagree with the long one.
- **Every decision record carries `external_inputs_used`** — including when empty, with a named status. An omitted
  field would let a broken connector read as a considered abstention.
- **Every observation records `USED` / `RETRIEVED_UNUSED` / `REFUSED_LATE_ARRIVING`.** Retrieval is not use.
- **Premarket is `PRIOR_CONTEXT` only**, referenced against the premarket packet, never against the decision
  snapshot, and never counted as decision-time evidence.
- **TradingView stays `EXTERNAL_CONTEXT_ONLY`** — never a calibrated probability, never a standalone signal.

### A fourth defect, found by wiring it

The seam **minted a competing `snapshot_id`**. It content-addressed the snapshot itself, unconditionally — correct
when written, because the options-path snapshot had no id. Once the snapshot emitted its own, there were **two
identities for one market state**, and a decision record would have named an id no snapshot carries: *a join that
looks joined and is not*. The seam now adopts the state's own id and records `snapshot_id_source`. Pinned by test.

## 5. The join, proved through the real pilot path

`tests/test_tradingview_pilot_seam_003.py` runs a real `session.scan` through a real `Boundary` onto a real ledger
file, with observations normalized from the **actual recorded live payloads**, and asserts the full chain on the
record that was *persisted*:

```
observation -> snapshot_id -> market state -> model inputs -> candidate set -> decision record
get_technicals_rating   snap:…   state_hash   model_bundle   eligible_expressions   pilot_decision
```

TradingView bars are **never** used to build the market state. The twin's state comes from the twin's own feed;
TradingView is external context and never a price of record.

## 6. Independence

Every failure — no tools, timeout, auth, rate limit, budget, denial, malformed payload, stale data, a raised
exception, a missing snapshot — produces a **named** unavailable state on a returned packet. `external_context()`
never raises, and the scan catches anything that bypasses it anyway.

Proved through real scans: with a timing-out provider, a raising provider, and a provider returning nothing, the
scan still reaches and persists a decision. `exit_policy`, `risk_authority`, `risk_gate` and `book` contain no
reference to the connector at all. The decision path imports it **lazily**, inside the branch that uses it, so
`session` imports and runs with no TradingView module resolved.

## 7. What this does NOT establish

1. **No live trading session has run through the seam.** The join is wired and tested; it has not been exercised
   by a real scan on a live feed. Production integration is not claimed.
2. **No unattended runtime route exists.** The OAuth session belongs to the interactive client. A service route
   needs its own reviewed credential with a stated owner and refresh lifecycle; that has not been designed,
   authorized or built, and Claude's tokens are never exported, copied or inferred.
3. **The daily-bar close model is an approximation.** `INTERVAL_SECONDS["1D"]` treats a daily bar as closing 24h
   after its open; a US equity session closes at 20:00Z. No bar in the smoke was near enough the boundary for this
   to change any `COMPLETE`/`PARTIAL` classification, but a same-day 1D fetch could misclassify.
4. **Entitlement is `UNKNOWN` for eight of the nine tools.** Only the bars response states a delay.
5. **Nothing has been measured about whether this context is any use.** No edge claim, no calibration, no
   attribution. The seam records what the eyes contributed so that question can *later* be asked from the record.
6. **The catalog is a point-in-time observation** (2026-09-12). A tool added tomorrow is denied by default;
   `reconcile()` is what makes it visible.

## 8. Test results

| suite | tests |
|---|---|
| `tests/test_tradingview_connector_001.py` | 52 |
| `tests/test_tradingview_seam_002.py` | 21 |
| `tests/test_tradingview_catalog_003.py` (new) | 61 |
| `tests/test_tradingview_pilot_seam_003.py` (new) | 53 |
| **TradingView total** | **187** |

**Full regression: 5745 passed, 30 failed, 26 skipped** (`tests/test_validation_observer.py` excluded — it fails at
collection trying to `mkdir /apex-data` on a read-only root, and fails identically at the base commit).

**None of the 30 failures is caused by this branch.** Verified by running the same eleven files at the candidate
commit `3092a0f` in a separate worktree: **14 failed there, 16 here**, and the two extra were
`test_repo_integrity.py::test_every_python_module_in_the_package_is_tracked` and `::test_every_test_module_is_tracked`
— the repo-integrity guard correctly flagging `apex/tradingview/context.py` and
`tests/test_tradingview_pilot_seam_003.py` as untracked *before they were committed*. Both pass once committed.

The remaining 14 are pre-existing and environmental: research-containment and world-writable-ancestor checks, NKLA
sealed-packet fixtures, research-board reconciliation, the whole-ledger guard, and a memory-growth test. The
difference between 30 in the full run and 16 in the subset is test-ordering side effects in the `exp002`/`exp004`
historical paths, which also reproduce without this branch.

---

# REVIEW CORRECTIONS (2026-09-13) — four claims that were weaker than they sounded

Raised at independent review, all four correct, all four now closed in code and evidence.

## R1. Regression reconciliation — see `docs/evidence/tradingview_integration_003/REGRESSION_RECONCILIATION.md`

The first report gave 30 failures in the full run and then a 14-vs-16 subset comparison, which does not account
for all 30. Reconciled per test ID under matching conditions on the final committed candidate, in isolated
checkouts. That document is the record.

## R2. Exit independence, against a provider that never returns

Raising `TimeoutError` inside a fixture establishes exception handling and nothing more: control came back. A
provider that **never returns** cannot be caught by `try`/`except` at all.

- `context._fetch_with_deadline` runs the provider on a worker with a hard wall-clock deadline
  (`DEFAULT_DEADLINE_S = 5.0`). On expiry the packet says `TIMEOUT` and names `PROVIDER_DID_NOT_RETURN`.
- **The worker is abandoned, not killed** — Python cannot kill a thread. It is a daemon, it holds no lock, no
  ledger handle and no resource the decision, exit or lifecycle paths need, and the record says so. If a future
  consumer ever needs a lock, this deadline stops being safe and must be revisited.
- **Proved through the real `LifecycleRunner`**: a scan opens a position with the provider blocked from the moment
  it is called; the exit falls due and is serviced and **RESOLVED**; the provider has *still not returned* when the
  run ends (asserted, not assumed). Whole run: 0.43s.
- Structural: `lifecycle.py` reaches external context from `_on_scan` **only**; a test walks every other function
  and asserts none names it.

## R3. `USED` now requires a named, implemented consumer

The first version set `USED` whenever the caller passed a non-empty `feeds` list. That proved a label was written,
not that anything read the observation.

- New disposition **`ATTACHED_CONTEXT`**: recorded against the decision, bound to the snapshot, and *nothing read
  it*. A caller-supplied `feeds` list is now `declared_feeds` — an intent, carried with a note saying it is not
  evidence of a read.
- `USED` requires a consumer from `apex/tradingview/consumers.py` to have actually run and returned a value. The
  record carries the consumer's name, its real implementation path, the derived value and a digest, so a reviewer
  can re-run it and reproduce the read.
- **The production registry is empty, and that is the correct state.** Nothing in APEX may act on external
  context, so there is no legitimate consumer to register and **no production decision record can report `USED`**.
  `register(production=True)` refuses any name not in `REVIEWED_PRODUCTION_CONSUMERS` (empty).
- The join evidence now reads `USED=0, ATTACHED_CONTEXT=2, RETRIEVED_UNUSED=1, REFUSED_LATE_ARRIVING=1`.

## R4. Provenance labelled; claim separated from verification

`DELAYED_VERIFIED` asserted a verification that was never performed — the basis string recorded beside it even said
*"the response itself states…"*.

- New entitlement state **`PROVIDER_STATED_DELAY`**: believed, not verified. Entitlement is now **derived from the
  payload** (`delay_statement_from_payload`), never read from a label in the recording; the recording's own claim
  is carried into the result as `recorded_entitlement_claim` with status `DISCARDED_NOT_EVIDENCE`.
- `observation()` **refuses** `DELAYED_VERIFIED`/`REALTIME_VERIFIED` without `verification_evidence`.
- Three facts kept apart: `provider_delay_statement` (verbatim), `latency_measurement` = `NOT_MEASURED`,
  `account_entitlement` = `NOT_ESTABLISHED`.
- **Original artifacts preserved unchanged**, including the wrong label — the first run is evidence, mistake
  included. `PROVENANCE.md` states that capture was **agent transcription, not byte-exact transport capture**
  (no packet trace, no raw body, no server-side digest; digests are of the recording), and that timings are
  **clock-bracket bounds, not transport instants** — groups share a bracket, so `T1-T0 = 22.6s` covers three calls
  and is not a round trip. `smoke_result_2026-09-13_relabelled.json` is a **replay of the same nine recordings —
  no new live calls.**

## 9. What this branch does not do

It does not connect TradingView to order placement, execution, risk authorization or options quotes. It does not
change a selection policy, risk limit, fee schedule or model promotion. It deploys nothing, and no order exists.
