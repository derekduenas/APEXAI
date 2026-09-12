# Arm register (per-experiment arms)

**Role.** One line per concrete arm ever proposed or fitted on historical data,
with its actual fit window, status, and the exposure it created. This register
is *descriptive*. It sets no rules. Rules for challenger *methods* live in
`CHALLENGER_REGISTER_V0.md`, subject to the supersession note recorded there.
Exposure is cumulative and never reset.

| Arm | Experiment | Mean | Dispersion | **Actual fit window** | Status | Exposure created |
|---|---|---|---|---|---|---|
| M0 | EXP-001B | 0 | Gaussian, `k·rv_30` | **train 2016-01-04 → 2019-12-31** | registered baseline | validation 2020–21 |
| M1 | EXP-001B | linear `ret_1, ret_5` | Gaussian, `k·rv_30` | **train 2016-01-04 → 2019-12-31** | registered; **EXP-001B verdict: M1 − M0 = NO_SIGNAL** (`t = 0.7525`, n = 165,958) | validation 2020–21 |
| M0, M1 | EXP-002 (re-fitted, registered form) | as above | as above | **fit 2016-01-04 → 2018-12-31** | result invalidated (INVALID_NULL_CONTROL) | development 2019; observed 2020–21 |
| S | EXP-002 | 0 | Student-t, `rv_30·s`, shared `ν` | fit 2016-01-04 → 2018-12-31 | result invalidated | 2019; 2020–21 |
| L | EXP-002 | linear `ret_1, ret_5` | Student-t, shared | fit 2016-01-04 → 2018-12-31 | result invalidated; **legacy reference only** — its lead over M1 conflated mean with dispersion family | 2019; 2020–21 |
| C | EXP-002 | quadratic in `ret_1, ret_5` | Student-t, shared | fit 2016-01-04 → 2018-12-31 | result invalidated; disclosed C − L on 2019 development `t = −2.312` | 2019; 2020–21 |
| "orthogonalised increment" | EXP-003 (withdrawn) | — | — | **none** | **identical predictor to C** (FWL; 4.3e-16 rel. out of sample); withdrawn as a model; not to be re-screened | none |
| A1–A4 | EXP-004 v1 (superseded) | — | — | **none** | feature algebra collapsed to one aggregate; A4 removed | none |
| L | EXP-004 v2 (proposed) | `ret_1, ret_5` | shared D0 / D1 | none yet | legacy context only | none |
| A | EXP-004 v2 (proposed) | `ret_1, ret_5, B̄̃, P̃` | shared | none yet | additive arm | none |
| **A×** | EXP-004 v2 (proposed) | A + `B̄̃·P̃` | shared | none yet | **primary comparator** | none |
| **C₄** | EXP-004 v2 (proposed) | **A× + `F̃`** | shared | none yet | **challenger; P1 = C₄ vs A×** | none |

EXP-004 registration **FROZEN 2026-09-09**, hash `9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9` (`apex/world_model/exp004/registration.py`). Implementation and admission are subsequent reviewed bricks.

Sealed: evaluation 2022-01-01 → 2024-12-31 and reserve 2025-01-01 → 2026-08-28,
never opened by any arm; the one disclosed 60-byte metadata read of
`SPY_2022-01-03.json` (`EVALUATION_READ_INCIDENT_001`) is on record.
