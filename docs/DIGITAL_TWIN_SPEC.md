# Digital Twin Specification

**What it is not:** an AI persona, a chatbot, a simulated trader.

**What it is:** a deterministic, versioned, PIT-aware description of the
information set available at a single formation date T. `apex/research/twin.py`.

## Properties (Part 3)

| Property | Mechanism |
|---|---|
| DETERMINISTIC | same snapshot + same T → identical `TwinState.digest()` |
| VERSIONED | carries `dataset_fingerprint` and `TWIN_VERSION` ("twin-v1") |
| REPRODUCIBLE | `build_state` packages already-computed inputs; adds no data path |
| PIT-AWARE | `assert_no_future_leak` refuses any feed dated after T |

## What a twin state contains

A `TwinState` at date T records:

- `eligible_ids` — securities passing §3 eligibility at T
- `feature_ids` — the features present
- `values` — feature_id → {security_id: value}, eligible + present names only
- `knowable_asof` — feature_id → the latest input date that fed any value
- `dataset_fingerprint`, `version`, `date`

## The PIT contract

The twin is a **consumer** of the certified feature/universe machinery, not a
new pipeline. It never reaches raw data. `knowable_asof` is the load-bearing
field: for each feature it records the latest input date that contributed. If
any exceeds T, `assert_no_future_leak` raises `TwinLeak`. This is the same
discipline `nsi`'s `known_from_out` established — measured, not promised.

A twin **refuses** rather than **filters**: a state built with a future feed
raises, instead of silently dropping the row, so a look-ahead bug cannot hide
inside the drop.

## Inputs that create a twin state

`build_state(date, dataset_fingerprint, eligible_row, feature_rows,
knowable_asof)`, where `feature_rows` are cross-sections already masked to
`date ≤ T` by the feature machinery. The twin does no masking of its own; it
verifies the masking was done.

## What the twin is NOT yet

It does not model portfolio state, transaction assumptions, or live regime
state. Those are `USEFUL LATER` (Part 11) and would be additional fields on a
future `TwinState` version, gated by the same no-future-leak contract. They are
not built and not faked.
