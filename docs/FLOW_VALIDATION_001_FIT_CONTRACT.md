# FLOW-VALIDATION-001 — the fit contract, enumerated from the caller through the models

Read from the code at `f87113a`. Nothing here was run against recorded data. This document exists because the
engine's constructor default of **400 model-fit calls** has nothing to do with what this evaluation needs, and a
budget should be the run's, not the constructor's.

## Who calls `fit()`, and when

| | |
|---|---|
| caller | `TwinSources._fit_funnel_for_day`, `apex/pulse_options/sources.py:129` |
| trigger | `apex/pulse_options/sources.py:181` — `if self._funnel_fitted_day.get(symbol) != day` |
| frequency | **once per symbol per session day**, on the first scan of that day |
| this run | one symbol, one session day, one `FunnelEngine` instance → **exactly one `fit()` call** |

`WAIT` and `PILOT_RULE_V2` construct no engine and fit nothing.

## Training rows and the availability cutoff

```
hist  = bar_source.bars(symbol, start_epoch=day_start - 7*86400, end_epoch=day_start)
load_bars(store, hist)
rows  = returns_rows(store.bars_available_by(day_start))
info  = engine.fit(rows, cutoff_epoch=day_start, label=f"{symbol} {day}")
```

| | |
|---|---|
| history window | `funnel_history_days = 7` days before the session day start |
| cutoff | `day_start`, the session day's start instant |
| availability gate | `BarStore.bars_available_by(day_start)`: a bar is a training row only if its recorded availability is at or before the cutoff |
| firewall | `apex/worldmodel_wb/contracts.py:112` raises `ModelRefused("FIREWALL: N row(s) available after cutoff ...")` if any row leaks past it |
| minimum | `MIN_TRAIN_BARS = 400`. Fewer rows and `fit()` returns `INSUFFICIENT_HISTORY` **without consuming any budget** |

**The prior-bar artifact's availability is formulaic, not measured** (`docs/FLOW_VALIDATION_001_AUDIT.md`), so what
the cutoff admits from it rests on the declared assumption in P3, not on recorded evidence.

## What one `fit()` call consumes

The counter is `self.fits`, incremented once per model-fit attempt and never reset. Per call:

| order | model | counter | condition |
|---|---|---|---|
| 1 | `GARCH()` | +1 | always, if budget remains |
| 2 | `MarkovSwitching2(iters=40)` | +1 | always, if budget remains |
| 3 | `EWMA()` | +1 | **only if** GARCH produced no model, its refusal was not a `FIREWALL`, and budget remains |

**Maximum three per call. There is no fourth path.** The budget check is a skip, not a raise: an exhausted budget
records `FIT_BUDGET_EXHAUSTED` against that model and continues, so it is visible in the trace rather than silent.

## Behaviour after an unsuccessful fit

| failure | recorded | consequence |
|---|---|---|
| GARCH refuses | `garch: "REFUSED: <reason>"` | the EWMA fallback is attempted, unless the reason contains `FIREWALL` |
| GARCH refuses with `FIREWALL` | same | **no fallback**: a leakage refusal is not retried with another model |
| regime refuses | `regime: "REFUSED: <reason>"` | in `FULL` mode `status = REGIME_UNAVAILABLE`, the engine is not ready, and every funnel scan WAITs |
| EWMA refuses too | `ewma_fallback: "REFUSED: ..."` | `status = VARIANCE_UNAVAILABLE` |
| fewer than 400 rows | `status = INSUFFICIENT_HISTORY` | no model is attempted at all |

The fallback is **declared and recorded**, not silent: `variance_kind` reads
`EWMA_FALLBACK (GARCH-t refused: <reason>)` on every scan of the run. **Its policy is unchanged here.**

## Internal attempts, which the counter does NOT see

This is the part a budget of 3 does not bound, so it is enumerated rather than assumed.

**`GARCH.fit`** (`apex/worldmodel_wb/vol_models.py:160`)

| step | bound |
|---|---|
| primary optimization, L-BFGS-B | 1 `scipy.optimize.minimize` |
| Nelder-Mead polish, only if the primary terminated unsuccessfully | 1 more, `maxiter = 6000` |
| search for a feasible second start | up to **8** candidate draws, no optimization |
| independent second start, L-BFGS-B | 1 more |

At most **three `minimize` calls and eight candidate draws** per GARCH fit. It refuses rather than accepting a
doubtful optimum: `OPTIMIZER_FAILED` when both the primary and the polish fail, `NOT_CONVERGED` when no feasible
second start exists, when the second start fails, or when the two starts disagree on the negative log likelihood by
more than `1e-4` relative.

**`MarkovSwitching2.fit`** (`apex/worldmodel_wb/regime.py`): expectation-maximization for **`iters = 40`**, the
value `FunnelEngine` passes (the class default of 60 is not used). No restarts, no retries.

**`EWMA.fit`** (`apex/worldmodel_wb/vol_models.py:106`): one deterministic recursion over the training returns. **No
optimizer, no retries.**

## The budget for this run

**`fit_budget = 3`, pinned in the driver and reported on the run.**

It is the exact maximum one `fit()` call can consume, and this run makes exactly one. It is not a throttle on
anything: a run needing a fourth fit would have to be fitting a second day or a second symbol, neither of which is
in scope, and it would show as `FIT_BUDGET_EXHAUSTED` in the trace rather than quietly proceeding.

Enforcement and what remains unbounded:

- **Enforced:** three model-fit attempts, checked before each, recorded in `engine.fits` and `engine.fit_budget` on
  every persisted `pilot_funnel` record. A test asserts both on the run's own records.
- **Bounded but not counted:** the internal optimizer attempts above, at most three `minimize` calls and eight
  draws for GARCH, forty EM iterations for the regime model, one pass for EWMA. **Enumerated, not throttled**, and
  no unspecified retry exists on any of these paths.
- **Not changed:** the fallback policy, `MIN_TRAIN_BARS`, `funnel_history_days`, `regime_iters`, and every
  optimizer tolerance. Altering any of them is a separate reviewed change.
