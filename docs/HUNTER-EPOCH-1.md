# HUNTER FORWARD EPOCH 1 — v1.5 (DECLARED Saturday 2026-08-15)

Epoch 1 begins with the first forward observation (Monday 2026-08-17
09:30 ET) and runs until a decision-affecting version change ends it.

## Frozen for the epoch (the complete decision surface)

| Artifact | Version | Birth |
|---|---|---|
| Forward protocol | v1 (hash bf4db439) | 2026-08-15 18:43Z |
| Feature schema | hunter_feature_schema_v1 | 18:43Z |
| Hunter-001 | v1 | 18:43Z |
| Hunter-002 | v1 | 18:43Z |
| Baselines | v1 | 18:56Z |
| Analog engine | v1.1 (in model artifact) | 20:35Z |
| Decision model (scanner, playbooks, forward pass, birth law, capital, forecast, memory, swarm iface, contracts, calendar) | hunter_rule_model_v1.5 | 20:35Z |
| Graduation criteria | frozen doc | committed pre-observation |
| N_effective rules | protocol §8 | 18:43Z |
| Simulation semantics | UNCALIBRATED_SCENARIO_WEIGHT, diagnostic | v1.4+ |

## The epoch law

Engineering bugs may still be fixed. ANY decision-affecting change:
mints **hunter_rule_model_v1.6** (new birth, append-only), and begins a
NEW forward lineage — Epoch 2. Epoch 1 observations are never casually
merged into a later epoch's statistics: epochs are compared side by
side (e.g., thin-Twin Epoch 1 vs richer-Twin Epoch 2), never blended.
The WEEK1-OBSERVATION-FREEZE remains in force on top of this: no
predictive-logic changes at all in the first week, defect or no defect
verdicts notwithstanding.

## What runs during Epoch 1 in parallel (build ≠ deploy)

Twin 2.0 (intraday regime PMF, per-facet freshness, correlation, event
load) may be BUILT during Epoch 1 but enters the pipeline only as a new
birth opening Epoch 2. The Swarm chair activates within Epoch 1 only
prospectively from its own birth after CLI auth + smoke test — its
assessments never backfill. Phase 3 (ML/distributions) activates at the
frozen checkpoint (≥40 sessions AND ≥100 effective across ≥2 regimes) —
when the data arrives, not when we are bored, and not sooner because we
are impatient.
