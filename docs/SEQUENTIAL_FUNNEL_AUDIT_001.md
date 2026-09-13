# SEQUENTIAL-FUNNEL-AUDIT-001 — Stage 1: data intake → PULSE → Twin (2026-09-13)

Base `cb184fc0189a40d011b66caebcf13c9d39d397c6` (verified). Separate clean worktree. Hold intact throughout.
Synthetic only. **This brick ends at the Twin.**

## Corrections to the previous report, accepted

1. **`USED` was overstated.** Finding an id in a downstream record proves a **reference was recorded** — not that
   any calculation read it. The court now reports three separate claims, ordered by strength:
   `REFERENCED_IN_RECORD` → `CONSUMED` (observed at an instrumented real reader, naming field and operation) →
   `BEHAVIORAL_EFFECT` (a controlled perturbation changed a named downstream value).
2. **The $19.91 reconstruction covers `PILOT_RULE_V2` only.** Every `reconstruct()` call in the court is on a
   rule-route run; **zero funnel runs were independently reconstructed.** The funnel reaching TRADE and the
   reconstruction agreeing were two different routes, and presenting them together was misleading.
3. **EWMA fallback is not yet diagnosed** — deferred to the model stage, not assumed to be a failure.

## Two production defects

### D1 — `snapshot_id` does not cover the option chain or the quotes

`TwinSources.snapshot()` calls `compose(symbol, as_of, bars, source, book)` and **never passes `chain_meta`**,
although `compose()` accepts it. `chain_quote_count` and `chain_expirations` are therefore `NOT_AVAILABLE` and
contribute nothing to `state_hash`, and `snapshot_id` is `state_hash[:32]`.

Two scans differing only in the chain — `650 CALL @ 2.45` versus `900 PUT @ 88.00` — produce the **same**
`snapshot_id`. The decision record uses that id to name *the market state the decision was made on*, and the
decision is made on the chain and the selected quote.

The id's own `snapshot_id_basis` is **accurate** about what it hashes. The defect is the gap between that basis and
the role the id is given downstream.

**Bounded repair proposal (not applied):** pass `chain_meta` from `chain_fn` into `compose()` in
`TwinSources.snapshot()`, so the chain fields populate and enter `state_hash`; and bind the *selected quote*
identity into the decision context separately, since the quote reaches the intent via `quote_fn` and never touches
the snapshot. Either fix changes every `snapshot_id`, so it must be sequenced against the fee authorization.

### D2 — `load_bars` crashes on a bar missing its timestamp

`providers.load_bars` documents *"malformed bars are counted and named, never dropped silently"* and catches
`IngestRefused` — but a missing key raises `KeyError` straight out of the loop, so **one malformed bar aborts the
whole batch** instead of being recorded.

**Bounded repair proposal (not applied):** catch `(KeyError, TypeError)` alongside `IngestRefused` and record the
bar as a named problem.

## Two audit errors, recorded rather than quietly amended

- **`ret_15` is a LOG return.** My first expectation used a simple return and disagreed at the 6th decimal
  (`0.00249004` vs `0.00248694`). **The Twin was right; the audit was wrong.**
- **`receipt_time`, not `available`, governs availability** in `load_bars`. My first late-input proof changed the
  wrong field and observed no effect — which I would have reported as the guard failing.

## Stage 1 results

| | |
|---|---|
| Ingestion | clean fixture 40/40 accepted; NaN price, negative price and conflicting duplicate all **refused by name**; future-availability **excluded** at the as-of filter |
| `last_bar_close` | expected `603.90` = actual `603.90` |
| `ret_15` | expected `0.00248694` = actual `0.00248694` (log return) |
| Missing vs zero | `chain_quote_count`, `chain_expirations`, `next_scheduled_event_type` all `None`/`NOT_AVAILABLE` |
| **CONSUMED** | **2 of 32** Twin fields are read by this route: `ret_15` by `signal_fn`, `last_bar_close` by `spot_fn` |
| BEHAVIORAL_EFFECT | a +$1.00 perturbation produced the independently expected `ret_15` and changed `snapshot_id` |

**30 of 32 Twin fields are built and carried but never read by this route.**

## Verdicts

| | |
|---|---|
| **Correctness** (fields inspected) | **PASS** — both agree exactly with independent computation |
| **Coverage** | **INCOMPLETE** — 2 of 32 fields consumed; chain and quotes absent from the state identity (D1) |
| Ingestion robustness | **ONE DEFECT** (D2) |

Do we know exactly what market state the models are handed? **For the underlying, yes. For the chain and the
quotes, no** — they are not in the identity that claims to name it.
