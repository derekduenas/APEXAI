# APEX Causal Governance — association is not causation

**Status:** governance text. No causal code exists. The layer's purpose is to
make it **impossible for the system to emit "causal effect confirmed" because a
coefficient is significant.**

## What our data actually supports — and does not

Sharadar SF1 is observational panel data with **no exogenous shocks, no
announcement dates (filing dates only), and no instrument.** Therefore:

- **JUSTIFIED:** placebo/falsification tests (does the signal "predict"
  pre-formation returns it cannot cause?), sector/size-neutralised re-tests
  (is the effect a mechanical confound?), subperiod sensitivity.
- **NOT SUPPORTED, must not be pretended:** instrumental variables,
  difference-in-differences, regression discontinuity, structural causal
  identification. The data cannot carry them; claiming otherwise is the exact
  false confidence this layer forbids.

## The evidence ladder (a causal dossier must state its rung)

```
descriptive association  →  conditional association  →  causal HYPOTHESIS
   →  identification assumptions  →  falsification/placebo  →  sensitivity
```

A causal dossier may claim a rung only if it has cleared the ones below it, and
must state the assumptions that the claim depends on. "Causal effect confirmed"
is not a rung and is not emittable.

## The twelve specifications (firewall contract `causal`)

| | |
|---|---|
| **1. Purpose** | Distinguish a plausibly causal predictive relationship from a stable correlation, using only data-justified tests. |
| **2. Inputs** | A validated (or in-sample) signal; treatment/exposure, outcome, and confounder definitions; an explicit identification strategy and its assumptions. |
| **3. Outputs** | A rung on the ladder above, the assumptions it rests on, placebo/sensitivity results — never a bare "confirmed". |
| **4. Allowed dependencies** | `apex.features`, `apex.evaluate`, `apex.research.twin`. |
| **5. Forbidden dependencies** | screening, discovery internals, the holdout before registration. Firewall contract `causal.forbidden`. |
| **6. Governance boundary** | A post-validation causal claim is a **new hypothesis** and consumes a credit. A discovery-stage causal *critique* (is this feature a collider?) is free and produces only a dossier note. |
| **7. Provenance** | dataset fingerprint, protocol/config hash, feature signature, identification strategy id, assumption set, seed, repo SHA. |
| **8. What is a new hypothesis** | Any causal *claim* to be validated. A critique of an existing hypothesis is not. |
| **9. What consumes a credit** | Validating a causal claim against the locked period. |
| **10. What can never access holdout** | Every causal test is in-sample or inside a registered experiment; the holdout stays the single validation look. |
| **11. What can never optimize** | The layer may not search over confounder sets or specifications for the one that yields significance — that manufactures a false positive. The confounder set and identification strategy are pre-registered. |
| **12. Tests before activation** | a "no bare causal claim" type test (the output type cannot express 'confirmed' without a rung + assumptions); a placebo-fires test; a specification-is-frozen test. |

## The interfaces (design only, not implemented)

```
Treatment / exposure        - the feature or event, PIT-defined
Outcome                     - forward excess return, existing definition
Confounders                 - a PRE-REGISTERED set (sector, size, ...); not searched
Identification strategy     - named; today only 'neutralised re-test' / 'placebo'
Assumptions                 - explicit, machine-readable, part of the dossier hash
Placebo / falsification     - required; a claim with no placebo is incomplete
Sensitivity analysis        - how fragile is the result to an unobserved confounder
Provenance                  - as row 7 above
```

A `CausalClaim` object, when built, must carry a rung, an assumption set, and a
placebo result, or fail construction — the same structural discipline that stops
`ScreenOutcome` from carrying a score.
