# EQUITY QUOTE DATA PLAN
Written 2026-08-22 (Predator v2 Phase 2 §16). **PLAN ONLY — not
implemented.** Implementing it would touch the intraday fabric, which
Monday's foundation acceptance depends on; the fabric stays frozen
until that gate passes.

## The gap, precisely

The persisted intraday store holds 1m bars only:
```
open high low close volume trades coverage_status gap_duration_ms
event_time_utc transport
```
Nothing about the executable market is retained. Therefore, by the
semantic honesty law:
```
TRUE_LIQUIDITY = NOT_ESTIMABLE
SPREAD         = NOT_ESTIMABLE
DEPTH          = NOT_ESTIMABLE
```
and no bar-derived proxy may occupy the canonical `liquidity` Curve
dimension or claim `STRONG` entry quality.

## What must be persisted

| field | why it is needed |
|---|---|
| bid, ask | the executable envelope; the only honest spread |
| quote timestamp | quote/trade alignment; staleness detection |
| bid size, ask size | size available at the touch |
| spread (derived) | chase quality, execution realism |
| depth beyond touch (if entitled) | absorption, liquidity withdrawal |

Each needs the same discipline the bar store already has:
`event_time` + `known_from`, coverage status, gap accounting, and a
declared transport.

## What it unlocks

1. **`liquidity` Curve dimension** — the LIQUIDITY_FLOW dependency
   group is currently dark on both its members (`liquidity`, `flow`).
   Quotes light the first one, adding a *fourth* independent group.
2. **`STRONG` entry quality** — presently unreachable by design.
3. **Execution realism** — real spread instead of an assumed one;
   slippage measured rather than modelled.
4. **Chase quality** — extension measured against the executable
   market, not only against VWAP.

## What it does NOT block

**It does not block the first paper attack.** The live Captain
predicate accepts `entry_quality in (STRONG, GOOD)`. Attack Geometry
v1 already produces `GOOD` — 311 times across 4,141 real review
instants (7.5%). Quotes are an *intelligence upgrade*, not a
prerequisite for PAPER_EXPLORATORY.

## Sequencing (recommended, unauthorized)

```
1. Monday foundation acceptance          <- must complete first
2. freeze L0-L6
3. add a quote subscription alongside the existing bar path,
   written to a SEPARATE store (never mutating the bar schema)
4. natural acceptance of the quote stream in its own right
5. only then: liquidity dimension + STRONG entry tier
```

Adding a quote subscription before step 2 would perturb the very
foundation Monday is meant to certify.
