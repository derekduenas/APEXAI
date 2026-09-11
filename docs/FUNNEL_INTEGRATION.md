# The Funnel — every intelligence layer in ONE decision path (M7, `FULL_FUNNEL_V1`)

State: `SYNTHETIC_VERIFIED` on branch `frontier-build`. Not deployed, not activated, no orders. Independent
acceptance pending. The deterministic pilot rule (`PILOT_RULE_V1`) remains the default selection policy; the
funnel is selected explicitly (`--pilot-selection-policy FULL_FUNNEL_V1`).

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
