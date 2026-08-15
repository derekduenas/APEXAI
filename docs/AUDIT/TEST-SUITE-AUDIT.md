# TEST SUITE AUDIT (2026-08-15, frozen)

Baseline: 847 passed / 1 skipped across ~60 test modules.

## Classification (hunter-relevant modules, by inspection)

- COUNTEREXAMPLE (the load-bearing class): monster-bar/visibility, analog
  outcome-poisoning + time firewall, simulator future-blindness, birth
  boundaries, evidence mixing, stop-widening, synthetic-auth firewall,
  fill ambiguity, monotone caution — ~45 tests. These are the tests that
  caught 7/8 mutations.
- INVARIANT: chain roundtrip, dedupe, N_eff caps, schema/status enums —
  ~25.
- INTEGRATION: full-stack synthetic proof, production Monday-truth,
  degradation-under-fire, e2e spine — ~8.
- HAPPY_PATH: feature-value fixtures (AMD example, VWAP/OR numerics) —
  ~30; these DO validate numerics against hand-worked values, not just
  self-consistency.
- ARCHITECTURE/GUARDS: repo integrity, prose-vs-code, firewalls,
  broker-sealed — ~20.
- The remaining ~700 belong to APEX Core (factor pipeline, governance,
  MVPM, reality loop) — previously audited in their own tranches.

## Mutation results (the real quality metric)

8 deliberate sabotages of critical guards: **7 caught, 1 survived**
(analog formed-at line, shadowed by resolved-at line — F-10). Conclusion:
the hunter suite is genuinely behavioral, not ornamental, with one
identified single-mutation tolerance to close.

## Weaknesses found

1. F-10: no adversarially-shaped row isolates the formed-at firewall.
2. Reproducibility asserts are canon-stripped around uuid4 ids (F-09) —
   tests tolerate nondeterminism that a content-derived id would remove.
3. No property-based/fuzz layer yet (Phase 30): position arithmetic,
   distribution normalization, and timestamp handling would benefit;
   recorded as post-freeze work.
4. No latency regression test for the 900s tick budget (measure Monday).
5. Chaos coverage exists for enrichment-seat failure and missing
   benchmark, but not for mid-tick vendor outage of the PRIMARY market
   feed (state record degrades honestly by design — untested end-to-end).

## Verdict

The suite proves behavior for the safety-critical laws (visibility,
births, caution, evidence, sealing) and representation for feature
numerics. Meaningful behavioral coverage of the Monday-critical path:
HIGH. Known gaps enumerated above; none threaten Monday's observational
validity after F-10 is closed.
