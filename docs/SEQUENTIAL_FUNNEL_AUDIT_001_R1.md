# SEQUENTIAL-FUNNEL-AUDIT-001-R1 — Stage 1 repairs (2026-09-13)

Base `ce2c9724c5e2f2aa69de48461312ca465b1ed398` (verified). Separate clean worktree. Hold intact. Synthetic only.
**Does not advance to the model stage.**

## Claim corrections — all three were overstated

### C1 — "only 2 of 32 Twin fields are read" — **WITHDRAWN**

Measured through **one** accessor. Inspection found others:

- `features.py:27` `feature_vector()` — `snapshot["fields"].get(name)`, a second accessor
- `inference.py:98` `forecast()` — `snapshot["fields"]["ret_1"]`, direct indexing
- `inference.py:97` — `snapshot["last_bar_event_time"]`, a top-level key

Measured across all three: **consumption observed for 5 fields** — `ret_15` (`signal_fn`), `last_bar_close`
(`spot_fn`), `ret_1`/`ret_5`/`rv_30` (`forecast` via `feature_vector`). The remaining **27 are
`CONSUMPTION_NOT_OBSERVED`**, not "never read". Policy exercised: **`PILOT_RULE_V2` providers only**; FULL and
JOINT not measured.

### C2 — "for the underlying, yes" — **NARROWED**

Only `last_bar_close` and `ret_15` were independently checked, on **one** frozen fixture. `ret_1`/`ret_5`/`rv_30`
are consumed by the forecast but were **not** independently verified.

### C3 — "changing snapshot_id invalidates the fee authorization" — **WITHDRAWN**

The fee authorization binds fee identity; `implementation_digest` covers `apex.options_pilot.fee_computation`
**only**. `snapshot.py` and `sources.py` are not in it, so a `snapshot_id` change moves **no fee-bound field**.
What does change is the release/pedigree identity — which requires **release verification, not fee
reauthorization**. I conflated the two.

## D1 — decision-context identity (additive)

`DECISION_CONTEXT_IDENTITY_V1`, new module `apex/pulse_options/decision_context.py`. **`snapshot_id`'s declared
scope is preserved** — it still identifies the underlying state alone.

```
                             context_id      snapshot_id
baseline                     ctx:38883e267e  snap:e130c688f
chain-only change            ctx:400c6cf8f3  snap:e130c688f   <- previously indistinguishable
quote-only change            ctx:2f238cfd2e  snap:e130c688f
underlying change            ctx:39e36fd641  snap:25215c059
late input excluded          ctx:1f66af6d35  snap:8dd19335f
cross-snapshot               ctx:4e17e1b45f  snap:319bbba94
equivalent reordering        -> SAME context_id
```

Components are separate, so a reviewer sees *which* part differed. Chain rows are canonicalised and sorted
(delivery order has no declared meaning); duplicates are **retained**, not collapsed. Execution re-quotes bind
**per fill attempt** via `execution_quote_binding()` and are never folded back into the decision context they
post-date.

## D2 — malformed bar handling

Before: one row missing `event_time` raised `KeyError` out of `load_bars`, **aborting the whole batch**.
After: required keys are checked explicitly and reported through the **same named mechanism** — no blanket
handler (asserted structurally). Mixed batch: 3 accepted, 5 named rejections, valid rows survive, the
future-availability row excluded at the as-of filter.

## Residual gaps — explicitly open

1. **The context identity is not yet wired into persisted records.** It is built and tested; threading it through
   candidate → proposal → intent → fill is the next bounded step. Legacy records cannot have their complete
   context reconstructed.
2. **No independent reconstruction of the FULL funnel round trip** — still open from the court.
3. 27 fields `CONSUMPTION_NOT_OBSERVED`; FULL/JOINT routes unmeasured.
4. `ret_1`/`ret_5`/`rv_30` consumed but not independently verified.
5. D1/D2 repairs are **not deployed** and change no fee-bound field.

## Superseded tests

`test_sequential_audit_001.py::test_DEFECT_a_bar_missing_its_timestamp_CRASHES_ingestion` → renamed
`test_D2_..._is_NAMED_not_crashed`; it now asserts the repaired behaviour, with the defect recorded in its
docstring.
