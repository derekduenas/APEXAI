# Brick 2 — event awareness as factual context (weekend commissioning, 2026-09-12)

## Inventory before adding anything

| Existing | What it is | Used here |
|---|---|---|
| `apex/catalyst/events.py` | `CatalystEvent`: four clocks (event_time, published_time, first_seen, known_from), source-authority tiers, dedup key (one event per story cluster), `EVENT_UPDATE` for additional sources, `VERIFIED/UNVERIFIED/CONFLICTED` | yes: the unscheduled stream |
| `apex/catalyst/sources.py` | stdlib adapters for official feeds (Federal Reserve press, BLS, SEC EDGAR, Treasury, Federal Register, IR feeds); every source isolated; `known_from` = retrieval time | yes, as the only unscheduled source set |
| `apex/catalyst/pipeline.py` | fetch → durable raw record → dedupe → interpret → event; ledgers `results/catalyst/{raw_observations,events,cycles}.jsonl`; interpreter optional and self-labelled | yes: the snapshot reads its ledgers |
| `apex/catalyst/event_admissibility.py` | content hashes, syndicated-copy detection, forbidden probability/trade language, publication-time basis | referenced; not re-implemented |
| `apex/events/capture.py` + `scripts/event_capture.py` (Mac launchd every 15 min) | EDGAR 8-K archive | not a decision input; inventoried |
| Host timers `apex-event-shadow`, `apex-event-optshadow-*` | event shadow experiments under release `5f561448…` | not touched |

**No new package.** Added: `apex/catalyst/twin_snapshot.py` (the Twin join + `EVENT_GATE_V0`) and
`apex/catalyst/calendars/scheduled_2026-09.json` (an official-calendar snapshot with provenance).

## Two streams, honestly scoped

| Stream | Source | Latency / access | Outage behaviour |
|---|---|---|---|
| Scheduled | FOMC calendar (federalreserve.gov, page last updated 2026-08-19), BLS release schedule (bls.gov), transcribed 2026-09-12 with `known_from` = retrieval time and a content digest | polled on demand; a calendar is not a breaking-news service | a missing/unreadable snapshot → `UNAVAILABLE`; a snapshot whose `known_from` is after the decision → `NOT_YET_KNOWN`, its events invisible |
| Unscheduled | catalyst official feeds only | feed cycle cadence; **no entitled wire service exists** and none was bought or credentialed; reported as `wire_service: UNAVAILABLE` on every snapshot | ledger missing → `UNAVAILABLE`; last successful cycle older than 30 min → `STALE`; relevant `CONFLICTED` event → `CONFLICTING`; feeds read and nothing relevant → `NONE_OBSERVED` |

On the Mac the catalyst ledgers hold one dry-run cycle (2026-08-26) in which all 8 sources failed on the Mac's SSL
trust store. The host holds `/apex-data/core/catalyst`. Until a cycle succeeds on the host that will serve the pilot,
the unscheduled stream reads `STALE` or `UNAVAILABLE`, and the proposed gate would veto new entries for that reason.
That is the correct reading of a dead sense.

Scheduled events found for the pilot's first week: **FOMC 2026-09-15/16, CRITICAL** (statement by convention 14:00 ET
Wednesday; the page lists dates only and says "details pending", so the time is labelled a convention, not a page
fact), plus four LOW BLS releases. Monday 2026-09-14 is a regular full NYSE session (holiday list checked).

## The event record (per handoff)

source ID/URL ✓ (`observations[].source_ref`), raw-content digest ✓ (admissibility `content_sha256`; pipeline raw
ledger hash), source publication time ✓, first receipt ✓ (`first_seen`), revision receipt time ✓ (`event_update`
rows carry their own `known_from`), scheduled/effective time ✓ (`event_time` / calendar `scheduled_time_utc`),
entities ✓ (`affected_symbols/sectors/assets`), category ✓ (`event_type`), story-cluster ID ✓ (`event_id` from the
dedup key), revision links ✓ (`revisions[]` on the snapshot), factual assertions ✓ (`factual_summary`, marked data),
verification ✓ mapped reported/confirmed/disputed/**retracted** (an additive `event_retraction` row; the original is
never edited). Multiple syndicated copies attach to one event as observations, never as confirmations.

Facts and interpretation stay separate: `directional_expectation` may only come from an LLM interpretation and is
never a source fact (catalyst invariant, unchanged). The snapshot carries no probabilities, fills no timestamps,
computes no surprise, scores no political figure, issues nothing. Retrieved text is data: a headline containing
instructions is flagged `hostile_text_flagged` and the gate treats it as a reason to refuse new entries, never as
something to do.

## Join into the Twin and the record

`TwinSources.event_context(symbol, as_of)` → sealed into `pilot_forecast.inputs.event_context` before any quote or
intent on both the rule path and the funnel path; the funnel trace carries it under `inputs.event_context`; every
`pilot_decision.funnel_trace.situation_regime.event_context` records scheduled status, unscheduled status, counts
and the gate evaluation. A twin with no event stream records `EVENT_STREAM_NOT_WIRED`, never "no events".

## EVENT_GATE_V0 — proposed, versioned, shadow by default

Rules R1–R5 in `twin_snapshot.GATE_SPEC`: veto **new entries** during a CRITICAL scheduled window for the symbol's
market; when the unscheduled stream is `UNAVAILABLE`/`STALE`; when a relevant event is `CONFLICTING` or hostile-text
flagged. **Never applies to exits** (R4): the acceptance test opens a position under SHADOW, refuses the next entry
under ACTIVE at the intent stage before any proposal, and then discharges the open position through its exit
obligation. Stage: intent (rule path); candidate eligibility (funnel path, not yet enforced there). Not decided here:
window widths per event class, relevance beyond the symbol's market, cancellation of open intents. Authority is
`SHADOW` in every production constructor; `ACTIVE` exists only where explicitly configured, and is not configured.

The pinned R4 statistical contract is untouched. News-driven forecasts, event-conditioned selection and
event-specific probabilities remain challenger work; this layer proves none of them.
