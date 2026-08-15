# HUNTER-001 v1 — Relative-Strength Momentum Continuation (FROZEN 2026-08-15)

Code of record: `apex/hunter/playbooks_v1.py::match_hunter_001`. This
document and that code freeze together; the birth registry stores the hash.
Any change is HUNTER-001_v2 with a new birth — v1's forward record is never
edited. LONG only in v1.

## Mechanism (why this could work, stated before any evidence)

Abnormal participation (RVOL) + sustained relative strength vs market AND
sector + a structural breakout above the opening range, in a non-hostile
market, is the signature of continued price discovery: someone with size is
absorbing supply faster than it arrives. The claim is NOT "momentum works";
it is that this *specific conjunction* distinguishes participation-driven
moves from random drift. The market will now grade that claim.

## Exact predicates (ALL required; missing input = no match, fail closed)

| # | Predicate | Threshold | Justification (outcome-free) |
|---|-----------|-----------|------------------------------|
| 1 | `or_complete` and ≥30m into session | 10:00 ET+ | RVOL/vol scales unstable in the first half hour |
| 2 | `above_vwap` AND `or_break_up` | structural | breakout without VWAP support is unconfirmed |
| 3 | `rvol_tod` | ≥ 2.0 | double the time-of-day median = participation abnormal by construction |
| 4 | `excess_market_60m` | ≥ +0.75% | exceeds typical 1h idiosyncratic dispersion of liquid large-caps; below it "strength" is noise |
| 5 | `excess_sector_60m` | ≥ +0.50% | must beat its OWN sector, not ride a sector move |
| 6 | agreement: `excess_market_15m` > 0 AND `excess_market_30m` > 0 | signs | strength that already faded at 15m is not "sustained" |
| 7 | market floor: SPY `day_return` ≥ −0.5% | prohibited below | continuation longs into a falling tape fight the dominant flow |
| 8 | risk geometry: (entry − VWAP)/entry ∈ [0.15%, 1.5%] | frozen band | tighter = stopped by noise; wider = poor R at the structural stop |

## Declared geometry

Entry = last visible 1m close. Stop = formation VWAP (thesis: VWAP loss =
invalidation). Target = entry + 2.0 × risk. Time stop 90m; max holding to
close. Horizons scored: 15/30/60/90m regardless of geometry.

## What would falsify it

Forward candidates fail to separate from the ALWAYS-TAKE-SCANNER-CANDIDATE
and RAW-RELATIVE-STRENGTH baselines at the frozen checkpoint; or
stop-before-target dominates at every horizon. Failure is recorded, not
repaired; predicates are never retuned inside v1.
