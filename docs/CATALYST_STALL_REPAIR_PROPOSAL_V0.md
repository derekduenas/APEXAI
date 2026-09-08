# CATALYST_STALL_REPAIR_PROPOSAL_V0 — proposed, NOT implemented

Nothing here has been built. No code was changed in this brick and no
service was acted on. The diagnosis found **no stall**; what follows repairs
the two real defects and the one legibility gap it did find.

## 1. Immediate containment

**None required.** The capture is not broken, no data is at risk, and the
next working phase (`OVERNIGHT_SCAN`, 07:00 ET, 2026-09-08) will run without
intervention. Deliberately **not** proposed: restarting the service, which
would destroy the only evidence of the current state and prove nothing.

The one containment worth having is procedural: **no freshness alarm on this
service should fire without consulting the session calendar**, because the
first such alarm — mine — was a false positive.

## 2. Liveness and useful-work instrumentation

The heartbeat already carries `beat_utc` and `last_work_utc` separately.
What it lacks is *why* and *when next*, both of which `phase_at()` already
computes and discards:

| Field to add | Source | Answers |
|---|---|---|
| `phase` | `phase_at()["phase"]` | IDLE / OVERNIGHT_SCAN / … |
| `idle_reason` | `phase_at()["why"]` | "2026-09-07 is not a trading day" |
| `work_expected_next_utc` | next phase boundary from the calendar | when silence stops being expected |
| `silence_is_expected` | derived | the single boolean an alarm should read |
| `sources_failed_last_cycle` / `_names` | cycle record | surfaces BLS without reading the ledger |
| `events_refused_last_cycle` | cycle record | surfaces the fabrication guard |

With those, a stale-output alarm becomes: fire only when
`silence_is_expected` is false **and** `now > work_expected_next_utc + grace`.

## 3. Failure escalation

Today a per-source failure and a per-event refusal live only in
`cycles.jsonl`; `last_error` on the heartbeat stays `null`. Proposed, in
increasing severity:

- **persistent single-source failure** — same source failing N consecutive
  cycles (BLS: essentially all of them) should raise a named, visible state,
  not a silent 16/17.
- **interpreter refusal rate** — refusals in ~66% of cycles is a property of
  the interpreter, not an incident; it belongs in a rolling counter, and only
  a *change* in that rate should escalate.
- **hard errors** (`brain did not return JSON`, timeouts) — already caught
  into `beat.error`; they should also increment a durable counter.

## 4. Retry and backoff behaviour

No change proposed. There is no retry storm: the loop polls on a fixed
schedule and a failed source simply fails that cycle. Adding backoff to BLS
would hide the defect rather than fix it (§6).

## 5. Source recovery — the BLS parser

`BLS CUUR0000SA0: unexpected shape ('series')` — the adapter expects a shape
the BLS API is not returning. Proposed as a **separate small brick**:
capture one raw response to disk, compare it against the adapter's expected
shape, and repair the parser against the recorded artifact. Until then the
macro family has no working source, which matters because EVENT-SOURCE-001
named scheduled macro releases as the best first event family.

## 6. Parser and schema repair

Two are known and must stay separate:

1. **BLS response shape** — above, in scope for the next brick.
2. **RFC-2822 vs ISO event times** — 2,284 of 5,163 `event_time` values
   would be refused by `event_admissibility`. **Explicitly out of scope
   here**, recorded as a downstream integration defect, to be its own
   compatibility brick as instructed.

## 7. Data-loss risk

**No loss from the idle period.** No poll was scheduled, so nothing was
fetched and discarded. What is genuinely unknown, and stated as unknown:
whether anything newsworthy happened over the weekend that a 24/7 capture
would have caught. This host cannot answer that, and no amount of log
reading will.

The real, ongoing loss is elsewhere and is *by design*: events whose cited
sources were never retrieved are refused (≈66% of cycles refuse at least
one). That is the anti-fabrication guard working. Whether those refusals
discard recoverable signal is a research question, not an incident.

## 8. Replay and recovery strategy

**No replay is warranted** — there is nothing to replay. Should a genuine
outage occur later, replay is constrained by the contract that already
governs this data: a re-fetched item's `known_from` is the *re-fetch* time,
not the original publication. Backfilling an outage therefore produces
records that are honest but late, and they must never be presented as though
they had been known at publication. Any future replay must write
`known_from = replay retrieval time` and carry an explicit `backfilled: true`.

## 9. Sequencing

1. Heartbeat instrumentation (§2) + escalation counters (§3) — one narrow brick.
2. BLS parser repair from a captured raw response (§5).
3. RFC-2822 compatibility (§6.2) — separate.

None of these blocks the other, and none requires new data, an admission or
an experiment.
