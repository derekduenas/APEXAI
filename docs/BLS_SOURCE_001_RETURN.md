# BLS-SOURCE-001 — RETURN

Base: catalyst-stall-001 @ `01e0977`. Branch `bls-source-001`, fresh clean checkout
at `/apex-data/tmp/bls_wt`. One brick. No service restart, daemon reload, admission,
experiment, broker, or market-data action.

---

## 1. REPRODUCTION — BEFORE ANY EDIT

### The parser path

`apex/catalyst/sources.py :: fetch_bls`, one expression:

```python
try:
    series = json.loads(body)["Results"]["series"][0]["data"]
except (json.JSONDecodeError, KeyError, IndexError) as e:
    raise SourceUnavailable(f"BLS {sid}: unexpected shape ({e})")
```

### Expected schema vs observed schema

| | expected by the old code | observed on refusal |
|---|---|---|
| `status` | never read | `REQUEST_NOT_PROCESSED` |
| `message` | never read | `["...daily threshold..."]` |
| `Results` | object with `series` | `{}` — present and empty |

### Failure location

`["series"]` on an empty `Results` raises `KeyError('series')`. The handler catches
`KeyError` and reports **"unexpected shape"**. The provider had stated the real
reason in two fields the adapter never opened.

**The failure was a QUOTA refusal recorded as a SCHEMA defect.**

### Two independent lines of evidence

1. **Live single read-only GET** of the CPI series returned HTTP 200,
   `REQUEST_SUCCEEDED`, in exactly the shape the old code expected. The schema
   was never wrong.
2. **The existing cycle log**, measured across seven days, shows a narrow
   success window and failure either side of it:

   | date | ok cycles | last ok (UTC) | failed cycles |
   |---|---|---|---|
   | 2026-08-27 | 9 | 13:37:17 | 89 |
   | 2026-08-28 | 8 | 13:53:55 | 83 |
   | 2026-08-31 | 8 | 13:53:43 | 85 |
   | 2026-09-01 | 8 | 13:57:14 | 83 |
   | 2026-09-02 | 8 | 14:02:18 | 80 |
   | 2026-09-03 | 8 | 14:06:06 | 78 |
   | 2026-09-04 | 8 | 14:03:16 | 85 |

   Three series × 8 cycles = 24 requests against BLS's unregistered allowance of
   25. Roughly 90% of cycles each day report a BLS failure.

### The window is rolling, not daily

Reading 2026-09-04 cycle by cycle refines the mechanism:

```
11:00:26  FAIL CUUR0000SA0      <- first series, still exhausted
12:22:00  FAIL CUUR0000SA0
13:20:03  FAIL CUUR0000SA0
13:33:07  OK                    <- window opens
...  8 consecutive OK cycles ...
14:03:16  OK
14:08:38  FAIL CES0000000001    <- THIRD series: exhausted mid-cycle
14:12:11  FAIL CUUR0000SA0
```

Two things follow. First, the failure boundary falls **inside** a single cycle,
between its second and third request — the signature of a per-request allowance,
not of a malformed document. A schema defect would fail all three series
identically and would not wait until the third.

Second, successes resume each day at roughly the hour they were consumed the day
before, and that hour creeps steadily forward across the week (13:37 → 14:06).
That is a **rolling 24-hour allowance** releasing capacity as the previous day's
requests age out, not a calendar-day reset. The mechanism is inferred from timing;
the exhaustion itself is directly observed.

### Preserved artifacts

`tests/fixtures/bls/` — kept, hashed, and labelled by origin:

| file | origin | sha256 (16) |
|---|---|---|
| `captured_CUUR0000SA0_REQUEST_SUCCEEDED.json` | **genuinely captured**, HTTP 200, 2026-09-08T03:06:06Z | `56b2a859d381c8e8` |
| `constructed_REQUEST_NOT_PROCESSED_quota.json` | **`CONSTRUCTED_NOT_CAPTURED`** — labelled as such | — |
| `PROVENANCE.json` | origin, hashes, observed quota evidence | — |

The constructed fixture is marked constructed. It is not presented as a capture.

---

## 2. REPAIR

`apex/catalyst/bls_parse.py` — `BLS_RESPONSE_PARSER_V0`. Reads `status`, then
`message`, then the payload. Twenty named refusals; nothing unknown is accepted.
`REQUEST_NOT_PROCESSED` with quota wording becomes `BLS_QUOTA_EXCEEDED` — the one
refusal an operator can act on — rather than a generic failure.

### A defect the repair also fixes

The old adapter set `published_time` to the reference-period label, the string
`"2026-July"`. **A reference period is what a number measures, not when it was
published.** This endpoint carries no release instant, so:

- `publication_time = "NOT_AVAILABLE"`, `publication_time_basis = "UNKNOWN"`
- `reference_period` travels separately
- retrieval time is never promoted into publication time; `known_from` stays retrieval time

### What the captured fixture caught

The real response contains 31 datapoints, one of which — index 9 — has
`value: "-"`, BLS's marker for a period whose value is suppressed or unpublished.
My first validation regex refused it as malformed. That was wrong: it is a
**documented absence**. It is now recorded as `value_status = NOT_AVAILABLE_MARKER`,
never coerced to a number and never silently dropped. A period marked `latest` that
carries no value is returned as `latest_without_value` and never as a usable print.

Had the brick used only constructed fixtures, this variant would have shipped as a
crash against real traffic.

### Identity

`content_sha256` covers `series|year|period|value`, so a re-fetch of an unchanged
print is not new evidence and a revision of the same period is. The repair keeps the
**original** observation-id key shape, so it does not re-emit already-recorded
observations.

---

## 3. TESTS

36 focused tests, fixtures only, no network. 61 pass together with the existing
admissibility suite; 192 pass across the full catalyst and event regression.

Covered: empty response, malformed JSON, missing status, unsupported status, quota
refusal, non-quota refusal, empty `Results`, missing/empty/multi series, series
mismatch, missing/non-list/empty data, malformed datapoint, bad year, bad period,
bad value, duplicate period, multiple `latest`, the `"-"` marker, clock separation,
content identity, and admissibility routing.

The network guard is **AST-based**, not substring-based. A guard that greps its own
source matches its own forbidden list — that mistake has been made three times in
this programme and is not repeated here.

---

## 4. THE GATE'S ACTUAL VERDICT

Output is routed through `apex.catalyst.event_admissibility` via `to_source_record`.
No second event model was created; APEX has one `CatalystEvent` and does not grow a rival.

**A BLS datapoint carries no publication instant, so it cannot become a dated fact.**
This is measured by test, not asserted. BLS observations are retrieval-only until a
BLS release calendar supplies real release instants.

That is a data-acquisition finding and it is stated rather than papered over. The
honest repair makes the source *less* immediately usable than the broken one
appeared to be, because the broken one was fabricating a publication time.

---

## 5. VERIFICATION

| check | result |
|---|---|
| focused parser tests | 36 passed |
| parser + admissibility | 61 passed |
| catalyst + event regression | 192 passed |
| protected surfaces | **57 files, 0 drifted, 0 missing** |
| source identity | `01e09778634844e6319e8f55240a33606ce73690` + the four files of this brick |
| service action | none — `NRestarts=0`, running since 2026-09-02 06:19:35 UTC |
| real event admission | none — `/etc/apex/admissions` does not exist on this host |
| market rows | none read; fixtures only |
| alpha claim | **none made** |

The repair is **not deployed**. The running release still carries the old parser.
Deployment is a separate authorized action.

---

## 6. FOLLOW-UPS — RECORDED, NOT DONE

**LLM-OUTPUT-001** — LLM timeout and malformed-output handling in the catalyst
interpretation path. Out of scope here by instruction. Not investigated.

**CATALYST-OBSERVABILITY-001** — heartbeat legibility. Not implemented by
instruction. Scope: `idle_reason`, `work_expected_next_utc`, source-contact health,
and accepted/refused counters, so that a correctly idle service is legible as idle.
`bls_parse.diagnostic()` provides the per-source record shape this would consume,
but nothing is wired to emit it.

**QUOTA-001** (new, found here) — the root cause is unfixed. The repair makes the
service *report* quota exhaustion correctly; it does not obtain more quota. Three
series polled every few minutes consume the unregistered allowance of 25 in about
thirty minutes, leaving the source unavailable for roughly 23.5 hours of each
rolling day. Registering an API key raises the allowance; polling at release
cadence rather than every few minutes would fit inside it. Both are operator
decisions and neither was taken.

The economic point: BLS publishes monthly. Polling a monthly series ~90 times a day
cannot produce information ~90 times a day. The current cadence spends the entire
allowance to learn nothing, and then cannot read the one release that matters.

---

## 7. CORRECTION CARRIED FORWARD

The withdrawn claim from EVENT-SOURCE-001 — that catalyst capture was "silently
stale" and an "operational integrity failure" — remains in the record as a
**withdrawn inference**. CATALYST-STALL-001 proved the service was correctly idle
across a weekend and a public holiday. This brick found a real defect in the same
component, and that does not retroactively make the withdrawn claim correct: the
staleness reasoning was wrong on its own terms, having compared a last-write time
to wall-clock without consulting the exchange calendar.
