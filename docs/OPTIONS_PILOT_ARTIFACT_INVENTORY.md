# OPTIONS-PILOT-001 — inventory of the retained forecast parameter artifact

Read-only inventory, taken from code and saved records only. No fitting, no
rescoring, no sealed-holdout access. This document answers three questions
the review asked: **what** the artifact is, **whether it is technically
complete** for a later reviewed inference adapter, and **what it is not**.

## 1. What is retained, and where

| Item | Value / location |
|---|---|
| Experiment | EXP-002, run `20260909T193814Z-exp002-ca450243` |
| DEVELOPMENT result | **INVALID_NULL_CONTROL** (the N0 null control did not hold; see `docs/EXP002_N0_CLOSURE.md`). The observed-period *report* line reads NOT_SELECTED; the experiment's status is INVALID_NULL_CONTROL and must not be renamed. |
| Sealed result file | the run's sealed result JSON, sha256 `0c397d70…`, source commit `2a09d1ed` |
| Parameter set hash | `params_hash = ca04fc6e713e1a5c`; recipe `sha256(json.dumps(params_without_hash, sort_keys=True, default=float))[:16]` — recomputed from the saved parameters, matches |
| Registered arm | L: linear location on standardised features with intercept |
| Features | `[ret_1, ret_5]`, standardised with the saved `mean = [2.9590e-07, 1.7807e-06]`, `sd = [3.2303e-04, 7.0448e-04]` |
| Location coefficients | `beta = [4.9212e-06, -4.3851e-06, -1.4745e-05]` (intercept, ret_1, ret_5) |
| Scale law | `scale = rv_30 · s`, `s = 3.287952250006828`; base `k = 2.932…` |
| Family | Student-t, `nu = 6.384478029123821` |
| Target | `log(close[t+15m] / close[t])`, 1-minute bars, 15-minute horizon |
| Feature construction | `exp001b.bars.observable_rows` at `2a09d1ed` (30-bar warm-up; `rv_30` = RMS of the last 30 one-minute log returns) |
| Source files (sha256 at `2a09d1ed`) | models.py `37a8351b…`, studentt.py `d211424f…`, bars.py `68b1125e…`, registration.py `6620c604…` |

## 2. Is it technically complete for a later reviewed inference adapter?

**Complete for inference, in the narrow sense:** every number needed to turn a
row of `[ret_1, ret_5, rv_30]` into a Student-t distribution is saved
(coefficients, standardisation constants, scale multiplier, degrees of
freedom), the feature recipe is in versioned code, and the horizon/target are
registered. `apex/options_pilot/synthetic_harness.forecast_from_params`
implements exactly that shape and the boundary accepts its output, which is
the **provider contract** proven in this brick — with *synthetic* numbers, on
purpose.

**Incomplete for a live adapter, in three named ways:**

1. **Live-bar semantics equivalence is unproven.** The saved features were
   computed from the historical bar table by `observable_rows`. Nobody has
   shown that live 1-minute bars from the options-session feed produce the
   same `ret_1`, `ret_5`, `rv_30` (bar boundaries, completeness, late prints,
   the 30-bar warm-up at the open). Until that is shown, a live forecast is not
   "the artifact applied live"; it is a new, unreviewed pipeline.
2. **No reviewed adapter exists.** The production route in
   `apex/options_pilot/entrypoint.py` names this: the forecast provider raises
   `NO_REVIEWED_INFERENCE_ADAPTER` and every scan is a persisted REFUSE.
3. **The model specification is not statistically established.** EXP-002's
   development result was INVALID_NULL_CONTROL; EXP-003 was withdrawn as
   FWL-identical; EXP-004 did not demonstrate improvement. A fully specified
   distribution is not proof that the specification is right. Every forecast
   record carries `specification_note` saying so.

## 3. What the distribution does NOT do in the pilot

The forecast is **recorded** and **not used to choose the expression**. The
expression rule (`expression_rule.py`) takes a heuristic direction label
(LONG/SHORT), a spot, and the available chain. Every forecast record carries
`drives_expression_selection: false`; every intent carries `signal_used`, the
label the rule actually consumed, and the boundary refuses an intent whose
`signal_used` disagrees with the forecast record's `direction_signal`.

The 15-minute forecast is **not extrapolated** to the hold-to-close horizon.
`records.HORIZON_RELATIONSHIP` is stamped on forecasts and intents, and an
intent that asks to use the forecast as a hold-horizon expectation is refused
(`HORIZON_EXTRAPOLATION_REFUSED`).

## 4. What was corrected

The recording-boundary document and the readiness audit previously described
EXP-002 as "a NOT_SELECTED experiment". That was the observed-period report
line, not the experiment's result. Corrected everywhere to: **DEVELOPMENT
result INVALID_NULL_CONTROL; observed-period report NOT_SELECTED**.
