# MARKET_TWIN_STATE_V0 → WORLD_MODEL_INPUT_V0 — DESIGN ONLY, NOT WIRED

No adapter is implemented in WM-0B. This records how one *would* map,
so the contract can be judged against a real intended use rather than
against an imagined one.

## What exists on the production side

`MARKET_TWIN_STATE_V0` — PULSE_V0 emitted 192,500 packets of it in one
commissioning session, each with a `state_id`, a self-covering
`packet_hash`, and `decision_power: NONE_STATE`. `MARKET_CONTEXT_STATE_V0`
does **not** exist yet: it is registered in `PHASE2_CROSS_SECTIONAL_CONTEXT`
and PULSE currently emits no breadth, dispersion, leadership or
cross-sectional rank at all.

## The mapping

| WORLD_MODEL_INPUT_V0 | source |
|---|---|
| `subject` | twin packet subject |
| `source_state_id` | packet `state_id` |
| `source_state_hash` | packet `packet_hash` — **referenced, never re-derived** |
| `state_time` | the market instant the packet describes |
| `scheduled_time` | the PULSE slot the cycle was scheduled for |
| `state_complete_time` | cycle persistence-complete |
| `known_from` | the cycle's authoritative availability boundary |
| `components[]` | one per twin field, each keeping its own `as_of` / `known_from` / `quality` |
| `market_context_state_id` / `_hash` | the future `MARKET_CONTEXT_STATE_V0`, by reference |
| `feature_family_versions` | the enrichment rule version in force |

## Four rules the adapter must not break

**1. Reference, never duplicate.** The input carries `source_state_hash`;
it does not copy the twin's factual values into a second authoritative
home. Two copies of a fact become two facts the moment one is edited.

**2. Per-component timing survives.** The twin's asynchrony is the
signal, not noise. Collapsing every component onto the cycle timestamp
would assert that a daily bar and an NBBO became known together — which
is false, and unrecoverable once flattened.

**3. Quality survives verbatim.** PULSE's census counted `VALID 8,879,871`,
`NOT_AVAILABLE 650,141`, `STALE 176,288`, `SESSION_INAPPLICABLE 304,970`,
`NOT_ESTIMABLE 148,935`, `UNKNOWN 111,863`. Those distinctions cost real
engineering; mapping any of them to `0.0` throws that away silently.

**4. Tier identity is derived from what was AVAILABLE, not from what
was requested.** A cycle where options were `SESSION_INAPPLICABLE` is
`A0_CORE`, not a degraded `A1_OPTIONS`. Otherwise A0-vs-A1 comparisons
would silently pool states with different information.

## Two blockers this adapter inherits

- **MIRROR-001 / MIRROR-002 remain CONFIRMED and unrepaired.** Prior-close
  is off by one session and the regular-session window admits premarket.
  A historical corpus built through this adapter today would inherit both.
- **`MARKET_CONTEXT_STATE_V0` does not exist**, so `market_context_state_id`
  will be `None` for every currently-producible input. The field exists so
  that fact is *visible* rather than absent.
