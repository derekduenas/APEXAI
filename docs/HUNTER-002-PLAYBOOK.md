# HUNTER-002 v1 — Failed-Extension Structural Reversion (FROZEN 2026-08-15)

Code of record: `apex/hunter/playbooks_v1.py::match_hunter_002`. Hash in the
birth registry; any change is v2 with a new birth. Symmetric: SHORT a failed
up-extension, LONG a failed down-extension. Deliberately OPPOSES Hunter-001
so the forward ledger can learn continuation-vs-exhaustion rather than
inheriting a permanent momentum bias.

## Mechanism

An extreme extension whose structure then FAILS — retraces half the leg,
loses VWAP, loses relative strength — looks like reflexive/forced flow
completing (stop cascades, chases, liquidations) rather than new
information being priced. Completed forced flow tends to revert toward
intraday equilibrium. The claim is graded forward, never assumed.

## Leg definition (frozen)

Extreme = session high/low, timed at its LAST touch (the extension was
still alive then). Leg start = the min (up) / max (down) close in the 60m
before that last touch. Leg z = (leg / leg_start) ÷ (atr_frac/√13) — the
ATR-implied 30m scale, from PRIOR days only. All from the same as-of
visible-bars frame (`forward_pass.extension_geometry`).

## Exact predicates (ALL required; described for the SHORT side, mirrored for LONG)

| # | Predicate | Threshold | Justification (outcome-free) |
|---|-----------|-----------|------------------------------|
| 1 | leg z | ≥ 2.5 | the extension itself must be tail-extreme vs the name's own daily scale |
| 2 | extreme's last touch age | ∈ [5m, 45m] | older is stale; a sub-5m extreme is a falling knife, not a failure |
| 3 | retrace of the leg | ∈ [50%, 100%] | half back = structural failure; past the leg start the reversion already happened |
| 4 | below VWAP now | structural | reversion thesis requires the equilibrium side |
| 5 | `excess_market_15m` < 0 | sign | relative strength lost, not merely index-dragged |
| 6 | `rvol_tod` | ≥ 1.5 | the extension was participated, not an illiquid print |
| 7 | risk geometry: (extreme − entry)/entry ∈ [0.2%, 4%] | frozen band | the stop of a ≥2.5z leg is naturally a multiple of the 30m scale; ~2× a typical daily ATR caps it |

≥30m into session (shared scanner floor). Up side evaluated before down;
predicates 4–5 make simultaneous two-sided matches impossible.

## Declared geometry

Entry = last visible 1m close. Stop = the session extreme (a new extreme =
invalidation). Target = entry ∓ 1.5 × risk. Time stop 60m (reversion is
fast or wrong); max holding to close. Horizons scored: 15/30/60/90m.

## What would falsify it

No separation from RANDOM/MARKET-DIRECTION baselines at the checkpoint, or
continuation (new extremes) dominating at every horizon. Recorded, not
repaired; no retuning inside v1.
