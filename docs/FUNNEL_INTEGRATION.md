# The Funnel — the intelligence layers in ONE decision path (M7 r3, `FULL_FUNNEL_V1`)

State: `SYNTHETIC_VERIFIED` on branch `frontier-build` (r2 = the integration-repair milestone after the reviewer's
eight findings at `f0daac2`; r3 = the bounded repair of the four items found in the independent review of `3cc65b0`). Not deployed, not activated, no orders. Independent acceptance pending. Layers this
engine does NOT invoke are named on every trace: the SVI surface (ATM IV only), learned fusion, enrichment, jumps. The deterministic pilot rule (`PILOT_RULE_V1`) remains the default selection policy; the
funnel is selected explicitly (`--pilot-selection-policy FULL_FUNNEL_V1`).

## r3 — bounded repair of the four items from the independent review of `3cc65b0`

| # | Finding | Repair | Test |
|---|---|---|---|
| 1 | `NaN` timestamps bypassed quote validation (comparisons against NaN are False); six NaN-stamped quotes produced TRADE | `sanitize_quote` requires a finite, correctly typed timestamp, clock and max-age BEFORE any subtraction (`QUOTE_TIMESTAMP_INVALID`, `CLOCK_INVALID`, `MAX_AGE_INVALID`); bid size ≥ 0 | `test_multiverse_wb::test_sanitize_quote_refuses_non_finite_or_mistyped_timestamps_before_arithmetic`; `test_funnel_engine::test_nan_timestamps_are_refused_and_never_reach_pricing` (all-NaN → WAIT with nothing priced; a NaN/valid mix → IV inversion and the candidate set see only the validated quotes, asserted by recording every pricing call; inf / str / bool / None stamps) |
| 2 | Multi-start agreement compared the second result with itself (1000 vs 900 accepted, gap 0) | Both results preserved; the gap `|NLL_a − NLL_b|` is measured FIRST against the declared rule (≤ 1e-4 relative), refusal otherwise; only then is the better of two AGREEING optima selected. Each start's termination status, message and objective are recorded separately (`convergence.start_a/start_b/selected`) | `test_worldmodel_wb::test_garch_multi_start_disagreement_is_measured_before_selection` (injected 1000 vs 900 → `NOT_CONVERGED … 1000 vs 900`) |
| 3 | Binding ignored the proposal's economic terms (`reference_ask` 2.45 → 4.50 widened the envelope from 2.70 to 4.95 while the checked fields stayed identical) | `Boundary.canonical_proposal` / `proposal_digest`: symbol, expiration, strike, right, expression, action, quantity, policy AND `reference_ask`. Verified at intent creation (against the caller's terms), at every fill attempt and on recovery (against the intent's OWN persisted terms, plus the stored `proposal_digest` and the envelope's recorded reference ask) | `TestFunnelBinding::test_changed_reference_ask_is_refused_at_intent_and_at_execution` (refused at intent with the field named; with the record-time check bypassed, refused at the fill and on recovery); `test_canonical_proposal_covers_every_execution_relevant_term` |
| 4 | End-to-end evidence was reduced-mode and conditional | `test_full_mode_acceptance_selection_to_reconciled_exit`: FULL mode → the REAL engine selects (regime supplied, PRIME ACT) → persisted funnel → intent bound by digest with the kernel's certified reservation at commit → FILLED → RESOLVED exit that discharges the position → book closed with zero positions and no integrity problems; every step asserted unconditionally, no stub. Separate: `test_full_mode_mandatory_wait_when_no_quote_is_valid` (real engine, all quotes 1000 s old → WAIT persisted, no intent) and the existing refusal cases | as named |

The 8-sd truncation remains a modelling assumption: it makes the payoff expectation exist under the bounded simulator; it does not establish that the tail model represents markets. The cap sensitivity travels with every decision for that reason.

## r2 — integration repairs (reviewer findings at `f0daac2` → what changed → the test that pins it)

| # | Finding | Repair | Test |
|---|---|---|---|
| 1 | Student-t log returns → `E[exp(σZ)]` infinite; expected call payoff ill-defined | `simulator.draw_innovations`: standardized t **truncated at ±cap sd (8 by default) and renormalized** to unit variance — an explicit model choice, in the parameter hash and the restrictions; Gaussian innovations untouched. Engine records `tail_sensitivity` (selected candidate's expected value at caps 6 and 12). | `test_multiverse_wb::test_innovations_have_finite_exponential_moments…`; `test_funnel_engine::test_tail_truncation_is_declared_with_sensitivity` |
| 2 | GARCH variance advanced an extra step at the handoff | ONE state convention: the simulator takes `h_next` (= `next_bar_variance`) as the variance of the FIRST simulated bar; the old `h_last/e_last` form is refused (`VARIANCE_STATE_CONVENTION`). The engine asserts exact first-step equality before using the paths. | `test_fitted_garch_feeds_the_simulator_consistently` (exact equality); `test_simulator_first_bar_variance_equals_the_forecast_exactly` |
| 3 | Quote freshness bypassed upstream (missing timestamps defaulted; day-old ATM quotes supplied the IV) | Sources carry quote fields AS RECEIVED (no timestamp default). The engine runs `sanitize_quote` (timestamp present and ≤ 120 s old, sides, sizes, not crossed) on EVERY quote before IV inversion or ranking; rejected quotes are listed on the trace and can supply nothing. | `test_quotes_without_timestamps_are_rejected_not_defaulted`, `test_stale_atm_quotes_cannot_supply_the_iv`, `test_crossed_or_sizeless_quotes_are_rejected` |
| 4 | Two clocks mixed (calendar T, trading-time horizon subtraction) | Expiry decay on CALENDAR time from timestamps (expiry = 16:00 ET; exit = as_of + 900 s; `HORIZON_15M_CALENDAR_YEARS = 900/(365·86400)`); variance on MARKET time. `physical_vs_implied` allocates `iv²·T_calendar` over trading minutes to expiry (declared). Identity `T_entry − horizon == T_exit` recorded per decision. | `test_expiry_decay_is_calendar_time_from_timestamps` |
| 5 | Missing regime could still `ACT`; risk `approved=True` from the envelope; empty book substituted | FULL mode requires the regime model AND a ≥ 5-bar prefix; `REDUCED_NO_REGIME` must be selected by name and is labelled on the trace. Book summary is mandatory (no substitution); integrity problems abstain. The envelope check is labelled `PRELIMINARY_AFFORDABILITY`; the trace says kernel approval happens at intent commit. | `test_missing_regime_cannot_act_in_full_mode`, `test_short_prefix_blocks…`, `test_reduced_mode_is_selected_by_name…`, `test_book_summary_is_mandatory…` |
| 6 | Persisted funnel not an execution dependency | `record_intent(funnel_receipt=)` verifies the `pilot_funnel` record and requires it to authorize exactly this scan, session, forecast, contract, expression and policy; the binding (`funnel_ref`) is stored on the intent and RECHECKED in `_history_problem` for every fill attempt and on recovery. | `TestFunnelBinding`: missing persistence, WAIT funnel, another scan's funnel, changed proposal / policy, altered record, execution-time recheck with the record-time check bypassed, healthy recovery |
| 7 | GARCH accepted `success=False` (ABNORMAL) | Unsuccessful termination refused unless a Nelder–Mead polish from that point converges; a second feasible start must reach the same NLL; gradient norm recorded (`convergence` on the params). | `test_garch_refuses_an_unsuccessful_optimizer_outcome` |
| 8 | Evaluator compared the wrong population (dropped WAIT rows) | `evaluate.paired_per_scan`: COMMON SCAN population, resolved TRADE = net, WAIT = 0, unresolved/refused EXCLUDED and counted; session-block bootstrap CI. The trades-only view is kept as SUPPLEMENTARY and labelled. | `test_per_scan_population_keeps_wait_as_zero_and_excludes_unresolved` (reviewer's 3-scan fixture: +6/scan vs −2 on the overlap) |

## What is wired (one path, one trace)

```
PULSE bars ─► Twin snapshot ─► World Model ─► Market-implied ─► Multiverse ─► Expression War ─► PRIME ─► Risk ─► Book
  (M2)          (M2)            (M2 artifact     (ATM IV +        (joint paths,   (WAIT + every      (super-    (envelope in
                                 + M3 GARCH-t     spread from      regime mix,     eligible contract  vision)    the candidate
                                 + M3 regime)     the quotes)      drift)          on common paths)              set; kernel at
                                                                                                                 intent commit)
```

- `apex/decision_wb/engine.py` — `FunnelEngine`: PURE (no ledger, no network, no clock). `fit(rows, cutoff)` is
  walk-forward and caller-timed (GARCH-t + 2-state regime; a DECLARED EWMA/Gaussian fallback when GARCH-t refuses,
  never past a firewall violation). `decide(...)` returns `TRADE` (an intent-shaped proposal) or `WAIT`, plus a
  `trace` naming what every layer used: fit digests, filtered regime probabilities (with the engine's own thin-state
  mass rule), rolled-forward variance, ATM implied vol and the physical-vs-implied comparison, simulation parameter
  hash / seed / restrictions, the full candidate table (expected net P&L, p_loss, q05, IV sensitivity, rejection
  reasons incl. `RISK_ENVELOPE`), the PRIME verdict with reasons and policy digest, and the selected candidate.
- `apex/pulse_options/sources.py` — `TwinSources(selection_policy="FULL_FUNNEL_V1")` supplies `funnel_fn`: fits the
  engine once per session day on bars strictly before the day (consecutive-minute returns only, calendar gaps
  yield no return), builds the causal prefix, takes indicative quotes from the chain (bid+ask) and completes the
  near-ATM set through the quote provider. Under the funnel the forecast record carries `direction_signal=None`:
  the heuristic label is recorded on the funnel trace and is NOT the selector.
- `apex/options_pilot/session.py` — `scan(..., funnel_fn=)`: the engine's result is persisted as a `pilot_funnel`
  record BEFORE any intent; `WAIT` ends the scan as a WAIT decision carrying the whole trace; `TRADE` goes through
  the same risk-bound intent (kernel re-check under the ledger lock) and numbered-attempt fill path as the rule.
  Every decision's `funnel_trace` is now `FUNNEL_TRACE_V2`: regime, model bundle (forecast + variance + implied),
  simulation bundle, eligible set, expected economics (`established: False`), PRIME, risk — each with a value or a
  named `NOT_REACHED` reason. Failures fail closed (`FUNNEL_PROVIDER_FAILED`, `FUNNEL_RESULT_MALFORMED`,
  `FUNNEL_NOT_PERSISTED` → persisted refusals).
- `apex/options_pilot/entrypoint.py` — `TwinProvider`; `run_pilot` passes `funnel_fn`; the report carries
  `selection_policy` and the engine description. `scripts/options_paper_session.py --pilot-selection-policy`.
- `apex/backtest_wb/funnel.py` + `contract2.py` + `scripts/pilot_replay_002.py` — the SAME engine as a
  `FULL_FUNNEL` variant inside the replay (PILOT-REPLAY-002, declared; NOT RUN — the operator asked for no more
  backtests until the funnel is complete). `evaluate.summarize` reports FULL_FUNNEL vs POLICY on common rows,
  vs WAIT (session-block bootstrap), abstention census, rights census, coverage.

## Declared choices (each recorded on the trace)

| Choice | Value | Why |
|---|---|---|
| Selection rule | best model-conditional expected net P&L > 0 among ELIGIBLE candidates, else WAIT | pre-declared; no threshold varied |
| Expected value | `established: False` (IV_FIXED) with an IV sensitivity table (−10 %, 0, +10 %) | M4 rule: no credible future-IV process yet |
| Candidate set | first expiry with DTE ≥ 21; nearest-ATM ± 4 strikes; both rights; WAIT always eligible | finite, recorded, no "best option" claim |
| Risk envelope | inside the candidate set: an ask above the kernel cap is `REJECTED: RISK_ENVELOPE` (unconstrained value kept for the record) | the comparison ranks only what the book could hold |
| Regime abstention | engine abstains when filtered mass on thin training states > 0.20 or entropy is high (model's raw verdict kept) | a well-supported state we are almost surely in is supported |
| Disagreement | `abs(log(artifact variance / GARCH integrated variance))` > 1.0 → abstain | artifact vs conditional variance at one horizon |
| Variance fallback | EWMA + Gaussian innovations when GARCH-t refuses (NU_AT_BOUND, non-stationary); never after a firewall violation | thin-tailed fixtures; declared on every trace |
| Fits | one GARCH + one regime per session day, prior days only; budget 400 | walk-forward; data firewall in the models |

## Tests (synthetic; all pass locally)

`tests/test_funnel_engine.py` (17): planted ±60 bps location → CALL / PUT, zero drift → WAIT; every layer in the
trace; max-expected-value selection; SPY-scale asks all rejected by the envelope with the cheaper feasible strike
selected when one exists; stale snapshot abstains; no eligible expiry / missing spot named; unfitted engine waits;
firewall row refuses without fallback; Gaussian data → EWMA fallback declared; seed determinism; calendar-gap returns;
session wiring (funnel record precedes intent, WAIT carries the trace, failures fail closed, a proposal that
disagrees with a labelled forecast is refused by the record contract); end to end through `run_pilot` on the
synthetic twin under `FULL_FUNNEL_V1`. `tests/test_backtest_wb.py::test_full_funnel_on_planted_drift`: the replay
variant on a drifting corpus — first sessions WAIT (`INSUFFICIENT_HISTORY`), later sessions buy CALLs with positive
net, summary carries the FULL_FUNNEL comparisons.

## What the funnel found on first contact (the blockers are now explicit, not hidden)

1. **Kernel cap vs SPY prices.** At SPY ≈ 645 every near-ATM ask (13–19 USD) exceeds the 5 USD envelope, so the
   funnel's candidate table is all `RISK_ENVELOPE` rejections and it WAITs. PILOT-REPLAY-001 shows the same: 591 of
   the rule's non-trades are `RISK_ENVELOPE_INFEASIBLE`. Operator decision: raise `max_risk_per_trade`, allow
   further-OTM strikes (the funnel would rank them), or pick an underlying whose ATM fits the cap.
2. **Fee schedule** is still SYNTHETIC / UNVERIFIED (LIVE_FEED intents refuse).
3. **Live chain/quote adapters** are not commissioned into `live_twin_sources` (smoke proved the parsers).
4. **Expected values are model-conditional** (IV_FIXED). A declared IV process is the next World-Model item.

## Baseline the funnel must beat (PILOT-REPLAY-001, completed on the host, 82 exposed sessions ≤ 2021)

Deterministic rule: 1,179 trades, mean net −5.48 USD/trade, session-block bootstrap CI [−6.40, −4.50] →
`DID_NOT_DEMONSTRATE_IMPROVEMENT_OVER_WAIT`; indistinguishable from RANDOM (−0.53 paired diff) and REVERSED
(−0.71); the heuristic direction label agrees with the realized sign 49.6 % of the time (p = 0.72): no skill;
friction 6,586 USD against −4,140 gross. Artifact PIT KS p = 0.007 (mis-calibrated at n = 1,804). See
`docs/PILOT_REPLAY_001_RESULT.md`.
