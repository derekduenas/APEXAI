# EVENT_INTELLIGENCE_ADMISSIBILITY_V0 — contract

Status: **IMPLEMENTED and TESTED** (`apex/catalyst/event_admissibility.py`,
25 tests). Authority: **none**. No event admitted by this contract may reach
PRIME, ARENA, RISK, BOOK or the execution boundary.

## 1. Why this is a gate and not an event model

APEX already holds the event model. `apex/catalyst/events.py` defines
`CatalystEvent` and `SourceObservation` with the four clocks, source
authority tiers, the event-type vocabulary, dedup, `CONFLICTED`, surprise
fields with expectation provenance, mechanism hypotheses and uncertainty.

This contract adds the one thing missing: **a decision, per record, about
whether it may enter research**, together with the checks that decision
requires. It reads `CatalystEvent`; it never mutates it (tested).

## 2. Record

```
EventAdmission
  contract                    EVENT_INTELLIGENCE_ADMISSIBILITY_V0
  event_id                    from CatalystEvent
  status                      ADMISSIBLE_FACT | ADMISSIBLE_LEAD | ADMISSIBLE_CONFLICTED
  reason                      why that status, in words
  event_type, event_time      from CatalystEvent (vocabulary enforced there)
  known_from                  the only clock a research join may use
  extraction                  ExtractionProvenance
  sources                     [SourceRecord]
  entities                    symbol -> RESOLVED (anything else refuses)
  independent_source_count    distinct CONTENT, not distinct names
  fact_bearing_source_count
  conflict                    bool
  surprise                    expected / actual / prior / surprise + expectation provenance
  mechanism_hypotheses        hypotheses, never findings
  uncertainty                 stated
  authority                   all NONE
  record_sha256               over a canonical, sorted serialisation
```

`ExtractionProvenance`: `extractor`, `model`, `model_version`,
`prompt_contract_sha`, `extraction_time`, and
`extractor_authority` which must be `NON_AUTHORITATIVE_OBSERVATION`.

`SourceRecord`: `source_id`, `source_authority`, `source_ref`,
`published_time`, `retrieval_time`, **`content_sha256`**,
`publication_time_basis ∈ {MEASURED, DECLARED_BY_SOURCE, UNKNOWN}`.

## 3. Refusals

| Refusal | Meaning |
|---|---|
| `MISSING_KNOWN_FROM` | without it, no research join can be checked for leakage |
| `FUTURE_TIMESTAMP` | any clock ahead of the decision instant |
| `KNOWN_FROM_PRECEDES_PUBLICATION` | knowing it before anyone published it |
| `MALFORMED_TIME` | unparseable, never defaulted |
| `PUBLICATION_TIME_UNKNOWN` | the basis is not declared — usually retrieval in disguise |
| `PUBLICATION_IS_RETRIEVAL` | published == retrieved without a `MEASURED` basis |
| `DUPLICATE_SOURCE_CONTENT` | one wire story republished is one observation |
| `SOURCE_CONTENT_MUTATED` | the source changed under the record |
| `SOURCE_CONTENT_UNHASHED` | mutation could not have been detected |
| `UNVERIFIED_SOURCE_IDENTITY` | no id or no stable reference |
| `NO_SOURCE` | an event with no publication is not an observation |
| `ENTITY_NOT_RESOLVED` | unresolved or ambiguous symbol; a wrong attribution is worse than an honest unknown |
| `MISSING_EXTRACTION_PROVENANCE` | model, version, prompt contract or time absent |
| `EXTRACTOR_CLAIMS_AUTHORITY` | an extractor produces observations, not findings |
| `LLM_PROBABILITY_PRESENT` | recursive scan; probability belongs to a fitted estimator |
| `TRADE_FIELD_PRESENT` | recursive scan; no direction, size, order or level |

## 4. Statuses

- **`ADMISSIBLE_FACT`** — at least one fact-bearing source, no conflict.
- **`ADMISSIBLE_LEAD`** — only non-fact-bearing sources: usable to know that
  *something* happened, never to assert *what*.
- **`ADMISSIBLE_CONFLICTED`** — credible sources disagree; kept as a state
  rather than collapsed to one side, which would be inventing certainty.

## 5. The baseline ships with the contract

`keyword_baseline_event_type()` is a deterministic keyword map with a
declared rule order and `UNKNOWN` for no match. It exists so that any LLM
extractor must beat something, and it passes through the same gate — so a
future comparison is between two audited records, not one audited and one
not.

## 6. Limitations, stated

- It gates **records**, not truth. An admitted record can still be wrong;
  it is merely checkable.
- `independent_source_count` counts distinct content, which does not prove
  editorial independence: two outlets rewriting one wire story in different
  words still count as two.
- Entity resolution is supplied by the caller; this contract checks the
  status, it does not resolve.
- `publication_time_basis` is a declaration by the ingester. `MEASURED`
  means a timestamp was read from the source, not that it is correct.
- No event has been admitted yet: there is no admitted event corpus. The
  gate is built before the stream, deliberately.
