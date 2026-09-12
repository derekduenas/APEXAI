# AI-DESK-001 — chart, captain, and cross-instrument integration

Status: DRAFT_FOR_REVIEW. Documentation-only setup; not implemented, tested, deployed, or an admission.
Base inspected: trace-replay-001 at 1b86541ebb03bcdd362d2230e9728f7d97a10050.
User objective: a continuously operating intraday desk that compares shares, options and WAIT, records every forecast and paper intent before outcomes, and evaluates challengers without retrospective promotion.

## 1. Delivery order and authority

OPERATING-LOOP-001 remains the active implementation brick. This draft does not replace it or authorize parallel changes to its code.
Known open issues include lifecycle servicing between scans, timestamp canonicalization, replay evidence classes, output preservation, cross-release recovery, and final-candidate regression adjudication. Their current status must be established, not inferred from this document.

After that brick is reviewed:
1. AI-DESK-001A: read-only projection API and chart on synthetic fixtures.
2. AI-DESK-001B: read-only captain adapter with recorded responses and no external model calls during synthetic acceptance.
3. CROSS-INSTRUMENT-001: reviewed shares/options comparison and risk contract, then implementation in its own brick.
4. Separate authorization for market-data connection, model-provider calls, prospective observation and paper execution.

No real-money path, default-policy change, fee authorization, limit increase, sealed-data read, service activation or collector restart is authorized by this document.

## 2. One information set

The chart and captain consume the same immutable Twin snapshot. The chart is a projection, not a second trading data feed.
Every response carries schema_version, snapshot_id, source record references, event_time, received_at, available_at, as_of, revision identity, quality and freshness status.
Fit artifacts additionally carry model/configuration digests, fit cutoff and training authorization references. Historical-looking dates alone do not establish point-in-time availability.

At replay time t, only records available by t are visible. Revisions remain additive; later corrections may be displayed in an explicitly separate revised-data view, never substituted into the historical decision snapshot.
Server enforces scope, symbol permissions, time bounds and response budgets. Model-supplied as_of values cannot expand authorization.

Missing data, unavailable models and stale projections are explicit. No fabricated candles, default probabilities or silent fallback models.
Chart snapshots, if added, carry the same snapshot_id, visible time bounds, renderer version and indicator definitions. Visual interpretations are hypotheses until checked against numeric records.

## 3. Projection API contract (proposed; map to existing interfaces before coding)

Read methods:
- get_market_snapshot(symbol, as_of): factual Twin state plus quality.
- get_chart_series(symbol, interval, start, end, as_of): available bars and revision metadata.
- get_model_trace(snapshot_id): actual model invocations, inputs, artifacts, outputs, failures and timing.
- get_forecasts(snapshot_id): native targets/horizons and distributions, including calibration evidence status.
- get_candidates(snapshot_id, policy_id): frozen candidate set, quantities, expected economics, uncertainty, cost assumptions and exclusions.
- get_positions(): persisted positions, reservations, exit obligations and unresolved amounts.
- get_decision_trace(decision_id): verified references from forecast to Book.
- get_event_context(snapshot_id): events, source availability, revisions, uncertainty and feed status.

Implement against existing persisted records. If the base lacks a field, report a schema gap; do not synthesize a value.
Use ordered stream sequence numbers, deduplication and gap detection. On disconnect, show last-update time and STALE; reconnect via a consistent snapshot plus sequence cursor. Rendering cannot mutate trading records.

## 4. Operator display

A chart library may render APEX's own data; verify the installed version, license and attribution requirements before selection.
Reuse the existing frontend if suitable; do not build a competing dashboard without first documenting why it cannot support these views.

Views:
- underlying candles and volume;
- option bid/ask where available, contract identity and quote age;
- forecast overlays labelled with native horizon, creation time and calibration status;
- regime/catalyst context with actual availability;
- live model trace with NOT_RUN/UNAVAILABLE/FAILED states;
- candidate economics, affordability and named refusals;
- intent, reservation, simulated fill and exit markers;
- position/exit countdowns and unresolved obligations;
- reconciliation and realized net-estimability status.

Clicking a marker retrieves the persisted evidence. Observed prices and simulated futures must remain visually distinct. Path illustrations are model-conditioned, not promises.
Animate only actual recorded stage events. Rendering completion is not model completion. No trade buttons or order endpoints in the read-only brick.

## 5. Captain contract

Initial authority: READ_ONLY_SHADOW. The quantitative engine owns probabilities, pricing, risk and declared selection rules.
The captain can summarize state, identify assumptions, propose research hypotheses and explain an existing ranking. It cannot fabricate numerical evidence, change a model, alter a limit, mark an artifact authorized, or create a broker order.

Structured response:
captain_record_id, snapshot_id, policy_id, model_provider/model_version,
prompt_template_digest, generation_parameters, request/response timestamps,
tool_call references and digests, candidate_set_digest,
hypotheses[{claim, evidence_ids, uncertainty, contradiction_ids}],
suggested_candidate_id_or_WAIT, reason_codes,
unavailable_inputs, validation_status, authority=READ_ONLY_SHADOW.

Candidate suggestions must reference the frozen candidate set; they do not override deterministic selection.
No free-form executable code, arbitrary URL fetches, shell tools, credential access or direct ledger writes.
Headlines and chart text are untrusted data. Embedded instructions cannot change tools, policy or authority.
Record actual requests and outputs with secrets removed; do not claim rerunning an LLM reproduces its output. Reconstruction uses the stored response.

External calls require explicit approved provider, cost budget and data-sharing scope. Until configured: CAPTAIN_UNAVAILABLE, with deterministic engine behavior unchanged.
Timeouts, malformed responses, unsupported claims or stale snapshot responses have zero decision authority.
The lifecycle scheduler must continue servicing exits independently of UI, inference latency and captain availability. A suggested policy change is a challenger proposal for later review, never an online self-update.

## 6. Future paper proposal boundary

A later reviewed policy may permit submit_paper_proposal(candidate_id, snapshot_id, candidate_set_digest, policy_id, idempotency_key, evidence_ids).
This is a proposal, not an order. The server re-reads persisted inputs, checks authorization and freshness, binds canonical economic terms, obtains a current quote, rechecks costs/capital/risk atomically and records its result.
Proposal expiry, same-key conflicting payloads, unknown candidates, stale evidence, unverified fees and changed terms must refuse.
Existing exits do not require captain approval. No broad human authorization can be inferred from a captain response.

## 7. Shares/options/WAIT design requirements

Start with fully funded long-only shares and currently eligible options; no short stock, borrowing or leverage in V1.
One snapshot, forecast horizon and account state feed all expressions. Candidate universe, sizing, tie rules, cost models and ranking objective must be frozen before an evaluation.
Use common underlying paths where mathematically applicable. Options need their declared pricing/IV assumptions; an underlying return forecast alone does not establish option exit-value accuracy.

For shares, distinguish purchase principal, price-to-zero loss bound under stated assumptions, planned stop loss, fees and stressed execution loss. Stops do not guarantee fills at their level.
Do not automatically classify shares as PRIME eligible; reconcile with actual risk-certificate semantics and reviewed limits.
For options, retain contract multiplier, exercise/expiry assumptions, premium and declared maximum-loss computation.
Unknown costs are not zero. Missing share or option adapters exclude that instrument with a reason; they cannot cause silent policy substitution.

The ranking formula is OPEN_FOR_REVIEW: specify account-level after-cost utility, uncertainty, capital usage and loss constraints. Do not default to largest expected dollars or a claimed top-trader heuristic.
Compare whole-policy economics separately from intelligence ablations on identical opportunities. Record every scan, WAIT, refusal, missing outcome and unresolved position.

## 8. Acceptance for the read-only desk and captain

Synthetic evidence only:
A1. Chart/API/captain share snapshot identity and agree on the numeric candles.
A2. Future availability and later revisions cannot enter an as-of view.
A3. Stream gaps/reconnects never silently duplicate or reorder markers.
A4. Model never invoked is displayed NOT_RUN rather than animated as success.
A5. Displayed decision and amounts reconstruct from persisted evidence.
A6. Missing fee or outcome yields unknown net, never zero.
A7. Chart actions and captain tools cannot call order or ledger-write capabilities.
A8. Hostile headline text cannot obtain forbidden tools or change authority.
A9. Captain response for an old snapshot or unknown candidate is rejected.
A10. Captain unavailable, slow or malformed does not delay a due exit.
A11. Replay views cannot appear as prospective performance evidence.
A12. Declared response/data budgets and symbol/time scope are server-enforced.

These prove software behavior, not profitability or calibration. External model behavior requires separately scoped evidence after a provider is configured.
Do not require a positive trade merely to make a demo impressive.

## 9. Learning

Persist forecast, selected policy, candidate set, decision and intent before outcomes.
After outcomes, classify implementation, data, forecast, pricing and execution errors separately; unknown attribution remains unknown.
Challenger changes require a versioned hypothesis, search-budget entry, earlier-data fit and later-data evaluation. No repeated tuning against the same loss sequence and no silent online promotion.
Dashboard exposes proposed/tested/accepted/active states separately.

## 10. Claude Code handoff

Continue OPERATING-LOOP-001 to its review boundary first. Read this draft afterward.
For the next desk brick, map the read-only API and acceptance cases to the actual frontend, Twin and ledger code. Return schema gaps and a bounded change list for review; do not implement other numbered bricks together.
Use an isolated checkout and an external interpreter. Preserve records, defaults, admissions, services and risk limits.
Deliver exact source pin, tests actually executed, a synthetic chart-to-record demonstration and remaining blockers. No claims of live commissioning or edge from fixtures.
