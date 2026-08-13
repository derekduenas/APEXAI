# APEX-002 ERRATUM-001 — decile orientation in the recorded validation artifact

**Date:** 2026-08-12
**Applies to:** `results/validation_APEX-002.json` (recorded 2026-08-13T00:37:12Z)
**Affects the verdict:** **NO.**
**Artifact altered:** **NO, and it will not be.** The recorded result is
immutable. This document sits beside it.

---

## Statement

> The recorded decile spread and downstream attribution figures use the
> inherited APEX-001 convention of decile 10 minus decile 1. Under APEX-002's
> registered convention, decile 1 is the top portfolio. Therefore the recorded
> spread is sign-inverted relative to the intended long-top / short-bottom
> interpretation. This does not affect the §13 IC-based verdict.

## Why the verdict is unaffected

§13 is IC-based. `cross_sectional_ic` correlates forward returns against the
continuous `apex_score`, re-ranks it internally, and never reads the decile
label — `grep decile apex/evaluate/ic.py` returns nothing. The score's
orientation was correct: lowest NSI scores 100, which is what makes the
pre-registered relationship positive.

```
recorded verdict   FAILURE
failing criterion  t-statistic +0.653827 fails t_stat >= 2.92
mean IC            +0.011654821132   (PASS, > 0)
robustness         +0.776291198021   (PASS, agrees in sign)
```

None of those three numbers touches a decile label. The verdict stands exactly
as recorded.

## What IS inverted

`apex/evaluate/deciles.py` computed `spread = per_period[n_deciles] -
per_period[1]`, hardcoding APEX-001's *10-is-best*. APEX-002 §9, ruled
2026-08-11, makes **decile 1 the top portfolio**.

From the recorded artifact:

```
mean_by_decile   1: +0.003614574874    <- top decile, largest net repurchasers
                10: +0.004744499687    <- bottom decile, largest net issuers

spread_mean_per_period   +0.001129924813  =  decile10 - decile1
spread_annualised_gross  +1.4330729595%
spread_t_stat            +0.145431561297
hit_rate                  0.551020408163
monotonic_top_over_bottom true
```

Read under APEX-002's convention:

| Recorded field | Recorded value | Intended long-short reading |
|---|---|---|
| `spread_mean_per_period` | +0.001129924813 | **−0.001129924813** |
| `spread_annualised_gross` | +1.4330729595% | **−1.4330729595%** |
| `spread_t_stat` | +0.145431561297 | **−0.145431561297** |
| `hit_rate` | 0.551020408163 | the complement, on the inverted spread |
| `monotonic_top_over_bottom` | `true` (deciles 8–10 over 1–3) | **false** under 1-is-top |

The §9 attribution block inherits the same inversion: `by_sector`
contributions, `top_winners` / `top_losers`, `spread_with_all_sectors`
(+1.4331%), `spread_that_sector_removed` (+1.5311%) and
`share_of_spread_from_it` (−6.8%) are all computed from the inverted spread.

**Anyone reading the recorded decile or attribution figures for the direction
of the effect will read them backwards.** The magnitudes are correct.

## Provenance

The risk was identified and reported before the validation run, at the point
the decile convention was ruled, and the fix was deferred because it required
modifying shared APEX-001 evaluation machinery that §15 inherits "unchanged".
It then materialised in the recorded artifact. The sequence is preserved in
the commit history rather than tidied away.

## Remediation for future experiments

`evaluation.top_decile_label` is now a registered configuration value read by
`evaluate_deciles`, which no longer assumes an orientation and refuses a value
that is not one end of the ranking. `config/experiment.yaml` registers `1`, per
APEX-002 §9.

`tests/test_decile_orientation.py`, 7 tests:

- the two conventions produce exactly opposite spreads
- `top_decile_label = n_deciles` reproduces the old hardcoded behaviour, so
  APEX-001's closed numbers cannot move
- `monotonic_top_over_bottom` flips with the convention, proving the flag
  reports the convention and not the fixture
- a middle-decile label is refused; a missing label raises rather than
  defaulting
- the recorded APEX-002 artifact is pinned as matching `decile10 - decile1`,
  so this erratum cannot silently drift from the file it describes

APEX-001 is closed and its recorded result is unchanged.
