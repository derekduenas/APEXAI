# Challenger register

One line per arm ever proposed or fitted on historical data. Status is what the
record supports, not what was hoped. Exposure is cumulative and never reset.

| Arm | Experiment | Mean | Dispersion | Historical fits | Status | Exposure created |
|---|---|---|---|---|---|---|
| M0 | EXP-001B, EXP-002 | 0 | Gaussian, `k·rv_30` | fit 2016–18 | registered baseline; NO_SIGNAL vs M1 (001B) | 2019 (dev), 2020–21 |
| M1 | EXP-001B, EXP-002 | linear `ret_1, ret_5` | Gaussian, `k·rv_30` | fit 2016–18 | registered baseline; NO_SIGNAL (001B) | 2019 (dev), 2020–21 |
| S | EXP-002 | 0 | Student-t, `rv_30·s`, shared `ν` | fit 2016–18 | result invalidated (INVALID_NULL_CONTROL) | 2019, 2020–21 |
| L | EXP-002 | linear `ret_1, ret_5` | Student-t, shared | fit 2016–18 | result invalidated; **legacy reference only** — its lead over M1 conflated mean with dispersion family | 2019, 2020–21 |
| C | EXP-002 | quadratic in `ret_1, ret_5` | Student-t, shared | fit 2016–18 | result invalidated; disclosed negative C−L on 2019 (`t = −2.312`) | 2019, 2020–21 |
| "orthogonalised increment" | EXP-003 (withdrawn) | — | — | **none** | **identical predictor to C** (FWL; 4.3e-16 rel.); withdrawn as a model; not to be re-screened | none |
| A1–A4 (metaorder state) | EXP-004 v1 (superseded) | — | — | **none** | superseded: feature algebra collapsed to one aggregate; A4 removed | none |
| **A** (additive) | EXP-004 v2 | `ret_1, ret_5, B̄̃, P̃` | shared D0 / D1 | **none yet** | proposed **primary comparator** | none |
| **A×** | EXP-004 v2 | A + `B̄̃·P̃` | shared | none yet | proposed secondary | none |
| **C₄** | EXP-004 v2 | A + `F̃` (signed body-volume) | shared | none yet | proposed **challenger**; P1 = C₄ vs A | none |

Sealed data: evaluation 2022–2024 and reserve never opened by any arm, with the
disclosed 60-byte metadata read of `SPY_2022-01-03.json` on record.
