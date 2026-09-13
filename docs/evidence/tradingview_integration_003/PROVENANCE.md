# Smoke provenance — what these artifacts are, and what they are not (2026-09-13)

The original artifacts are **preserved unchanged**:

| file | status |
|---|---|
| `smoke_calls_2026-09-13.json` | ORIGINAL, unmodified — the recording as first captured, including its `entitlement` label |
| `smoke_result_2026-09-13.json` | ORIGINAL, unmodified — the first run, including the `DELAYED_VERIFIED` label now known to be wrong |
| `smoke_result_2026-09-13_relabelled.json` | NEW — the same recording replayed with corrected provenance. **No new live calls were made.** |

## 1. Capture method: AGENT TRANSCRIPTION, not byte-exact transport capture

The MCP tools live in the Claude Code client, not in the Python process. An agent holding the authorized session
called each tool and **transcribed** the returned payload into the recording.

**There is no packet trace, no raw HTTP body, and no server-side digest to compare against.** The digests in the
result are digests **of the recording**, which is the artifact of record. A transcription error would change the
digest and nobody could tell from these files alone.

The only corroboration available is structural, and it is weak: the recorded payloads parse as JSON, and the one
long prose payload's `ast_description` parses as JSON in its own right, which a corrupted transcription of its
structural characters would not.

**A byte-exact capture would require a transport that this process controls**, which is the same missing piece as
the unattended runtime route. It does not exist yet.

## 2. Timing: CLOCK-BRACKET BOUNDS, not transport instants

The agent cannot observe the socket. Each call is bracketed by a real wall-clock reading taken **before** the
request was issued and **after** the response arrived:

```
T0 1789275563.131187   T1 1789275585.735981   T2 1789275619.470324
T3 1789275633.819387   T4 1789275648.807049
```

Group A (calls 1–3) `[T0,T1]` · B (4–6) `[T1,T2]` · C (7–8) `[T2,T3]` · D (9) `[T3,T4]`.

So `[request_start, response_receipt]` is a **true containing interval**, not the transport's own instants. Calls
were issued in groups, so a group **shares one bracket** and the interval is wider than any single call's true
round trip — `T1-T0` is 22.6s for three calls, which is emphatically not a 22.6s round trip.

`known_from` is the **later** bound. That can only ever *understate* availability, which is the safe direction: it
cannot manufacture hindsight, and that is the only property the availability contract depends on.

**No timestamp here is fabricated.** Every one is a real reading from the machine clock.

## 3. Three separate facts that were previously collapsed into one label

The first run recorded the bars observation as `entitlement: DELAYED_VERIFIED`. **That was wrong**, and the basis
string recorded alongside it said so plainly — *"the response itself states…"*. A provider's statement about its
own feed is not a verification. The three facts are now kept apart:

| field | value | meaning |
|---|---|---|
| `provider_delay_statement` | *"Market data notice: bars are delayed 15+ minutes depending on the exchange…"* | what the provider **said**, verbatim, extracted from the payload |
| `latency_measurement` | `NOT_MEASURED` | a clock bracket bounds this connection's round trip. It is not feed latency and not data age. |
| `account_entitlement` | `NOT_ESTABLISHED` | the account's market-data plan was never checked |

`entitlement` is now `PROVIDER_STATED_DELAY` — believed, not verified.

Two enforcement changes make the old label unreachable:

1. `normalize.observation()` **refuses** `DELAYED_VERIFIED` or `REALTIME_VERIFIED` unless `verification_evidence`
   is supplied. The label cannot be set by assertion again.
2. Entitlement is **derived from the payload** by `delay_statement_from_payload()`, not read from the recording.
   The recording's own `entitlement` label is carried into the result as
   `recorded_entitlement_claim` with status `DISCARDED_NOT_EVIDENCE` — visible, and unused.

A label typed into a transcription verifies nothing, so it is no longer allowed to.
