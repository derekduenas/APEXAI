# APEX Frontier Build — status

Mandate: `APEX_Frontier_Build_Mandate.md` (operator, 2026-09-11). This document is
the single build-status record; `docs/frontier_build_manifest.json` is its
machine-readable twin. **Self-review cannot set independent acceptance**: the
`ACCEPTED` state below is reserved for the independent reviewer, and the
operational states (`SHADOW_AUTHORIZED`, `DEPLOYED`) are reserved for the operator.

Scope expansion recorded: the mandate authorizes offline implementation,
isolated dependencies, synthetic qualification, documentation and reviewable
commits across M0–M6. It does not amend executed experiments (EXP-001B
NO_SIGNAL, EXP-002 INVALID_NULL_CONTROL, EXP-003 withdrawn, EXP-004
NOT_SELECTED), grant historical fitting/rescoring, open sealed data, create
admissions, change trust roots, lift the maintenance block, start services,
connect brokers or send orders.

Branch: `frontier-build` (worktree `~/apex-frontier-wt`), created from
`options-pilot-001` at `360536cb`. The authoritative host checkout stayed at
`360536cb` while this branch was built; nothing older was written over it.

| Milestone | State | Checkpoint | Evidence |
|---|---|---|---|
| M0 — four remaining recording defects | `SYNTHETIC_VERIFIED` (awaiting independent acceptance) | `360536cb` (r4) | `docs/OPTIONS_PILOT_RECORDING_BOUNDARY.md` §10; tests `test_r4_*` (boundary) and `test_f6_lifecycle_recovery_through_the_entry_point`; contained run at 360536cb: 92 pilot / 461 regression passed |
| M1 — execution accounting + operational paper loop | `SYNTHETIC_VERIFIED` | `78931c0` | `apex/options_pilot/{fees,book,risk_authority,exit_policy}.py`; boundary/session/entrypoint integration; `tests/test_options_pilot_accounting.py` (14) + the 92 r4 tests updated for fees/exit policy; local run 106 passed |
| M2 — PULSE / Twin / inference adapters | `SYNTHETIC_VERIFIED` | `d026b87` | `apex/pulse_options/{ingest,snapshot,features,inference,providers,sources}.py` + `exp002_artifact.json`; `tests/test_pulse_options_twin.py` (22); smoke script + collection request prepared, not executed |
| M3 — World Model workbench | `SYNTHETIC_VERIFIED` (foundation benchmarks `BLOCKED_RESOURCE` / `BLOCKED_LICENSE`) | `e277e4c` | `apex/worldmodel_wb/*`; `tests/test_worldmodel_wb.py` (14); `docs/evidence/garch_reference_vs_arch_OUTPUT.json` |
| M4 — Multiverse + market-implied | `SYNTHETIC_VERIFIED` | `80ea8de` | `apex/multiverse_wb/{simulator,pricing,surface,expression_war}.py`; `tests/test_multiverse_wb.py` (8) |
| M5 — fusion, supervision, learning | `SYNTHETIC_VERIFIED` | `ceb7e7f` | `apex/decision_wb/{fusion,supervision,experience,enrichment}.py`; `tests/test_decision_wb.py` (4) |
| M6 — operator view + commissioning package | `SYNTHETIC_VERIFIED` (package PREPARED; activation NOT authorized) | `9cfb70f` | `apex/options_pilot/operator_view.py`; `scripts/options_pilot_scale_check.py` + `docs/evidence/scale_check_10_sessions_OUTPUT.json`; `docs/OPTIONS_PILOT_COMMISSIONING_PACKAGE.md`; funnel trace on every decision |
| M7 — THE FUNNEL in one decision path (`FULL_FUNNEL_V1`); r2 (8 findings) + r3 (4 findings) repairs | `SYNTHETIC_VERIFIED`; r3 INDEPENDENTLY ACCEPTED within its bounded scope (the four repairs at `525340c`); live commissioning and profitability UNESTABLISHED; default policy stays `PILOT_RULE_V1`; backtest hold kept | `f0daac2` → `3cc65b0` → `525340c` |
| R4 — joint market-state forecasting | `SPECIFICATION_DRAFT_3` for review (supersedes `f848163` → `65834d0` → `cf4155f`): `docs/R4_JOINT_MARKET_STATE_SPEC.md`, with the equation-to-test checklist in §10. Operator decisions approved in principle (state family, provisional constants, collector-first, 8-run production budget, selection-by-name); acceptance of this revision outstanding. Nothing implemented, nothing fitted | this commit | `apex/decision_wb/engine.py`; `TwinSources.funnel_fn`; `session.scan(funnel_fn=)` + `FUNNEL_TRACE_V2`; `--pilot-selection-policy`; replay variant `apex/backtest_wb/funnel.py` + PILOT-REPLAY-002 contract (declared, not run); `tests/test_funnel_engine.py` (17) + replay planted-drift test; `docs/FUNNEL_INTEGRATION.md` |

## M0 — closed at `360536cb` (reconciled against the mandate's four items)

1. Expiry after quote receipt, before fill commit → `pilot_intent_expired` + refusal; exclusivity with fills and
   cancellation under the transaction protocol (`_CommitRefused.terminal_kind` → `expire_intent` in its own
   transaction, which refuses if a finishing fill or terminal record exists). No unfinished-intent state remains
   (`test_r4_expiry_between_receipt_and_commit_persists_terminal`).
2. Missing/stale exit → numbered valuation attempts, `discharges_position=false`; the obligation survives restarts;
   prior failed attempts are never overwritten (`test_r4_missing_or_stale_exit_keeps_the_position_outstanding`,
   entry-point lifecycle test using the real provider returning `None` then a stale quote).
3. Late duplicate delivery → historical receipt reconciliation needs identity/provenance + full chain/reference
   verification only; forecast currency governs a NEW fill (`test_r4_late_duplicate_delivery_reconciles…`).
4. Complete 120-s cutoff freshness + future-target policy at intent creation and new-fill commit, including the
   130-s-old-inputs / fresh-quote case (`test_r4_forecast_freshness_is_rechecked_at_intent_and_at_commit`).

## M1 — what was built

- **Fees** (`fees.py`): `FeeSchedule` with id/version/provenance/verification record; `SYNTHETIC_FEES_V1`
  (labelled invented) and `UNVERIFIED` (unknown ≠ zero). Entry fee on the fill, exit fee on the discharging
  outcome, each exactly once; `recompute_fees` for the Book. `ExecutionPolicy V1`: 0.25 s simulated latency
  (freshness measured at the simulated execution instant), 3 fill attempts (first quote + 2 re-quotes) inside
  the intent TTL, fill quantity ∈ {0, 1}, displayed size is a constraint, every fill labelled SIMULATED.
- **Certified risk authority** (`risk_authority.py`): the real `risk_certificate.certify()` recomputed from legs
  `("BUY", right, strike, max_entry_price)` and the real `risk_kernel.check()` against Book inputs. Approval
  binds to intent identity + envelope + fee schedule; `accepts()` honours only its own provenance. The
  **envelope** (`RISK_ENVELOPE_V1`) reserves `min(indicative ask × 1.1, cap $5.00) × 100`; infeasible
  envelopes (indicative ask above the cap) refuse at intent time; the executable ask is rechecked against the
  envelope at fill (`ASK_ABOVE_ENVELOPE` → WAIT).
- **Atomic reservations**: the intent record IS the reservation; the kernel is re-run against the Book
  reconstructed from the snapshot INSIDE the intent's commit transaction (`RISK_LIMIT_AT_COMMIT`), so six
  barrier-released SPY intents reserve exactly two under the $600 same-underlying cap. Reservations convert to
  positions at the actual debit on fill, and are released by a terminal REFUSE attempt, expiry, cancellation or
  re-quote exhaustion — each an exactly-once record.
- **Book** (`book.py`): reconstructed from records only — reservations, positions, closed positions, cashflows,
  session/total realized P&L, outstanding obligations (unfinished intents, unresolved positions, exit-exhausted
  positions); primary-field recomputation of debits, fees and P&L with named integrity problems; cash identity.
- **Exit policy** (`exit_policy.py`, `EXIT_AT_HORIZON_15M_V1`, frozen): due at fill + 900 s; 120-s window;
  ≤5 attempts spaced 15 s; valuation failure keeps the obligation; exhaustion records `pilot_exit_exhausted`
  and the position REMAINS an obligation (P&L unknown); early valuation is refused (`EXIT_NOT_DUE`); recovery
  runs may attempt exhausted/late positions, labelled. Declared as a NEW policy distinct from the legacy
  hold-to-close protocol.
- **Session/entry point**: `attempt_exits` drives the policy deterministically (controlled clock "sleeps" by
  advancing); an unfilled intent of the closing session is cancelled at close (terminal record, exclusive with
  fills); the close record carries the Book summary, cancelled intents, exhausted exits and failed valuation
  attempts; the report carries book, fee schedule, exit and execution policies.
- **Production route**: `ProductionSources` uses the certified authority with the UNVERIFIED fee schedule and
  LIVE_FEED provenance, so every intent is refused `FEE_SCHEDULE_UNVERIFIED` until a provider schedule is
  verified and recorded. (At M1 the forecast provider was still `NO_REVIEWED_INFERENCE_ADAPTER`; M2 replaced it with the gated twin sources.)

## Known limitations carried forward

- Kernel limits are the organism's predeclared PAPER limits ($500/trade). SPY ATM 21-DTE options usually
  price above $5.00, so the current pilot rule will refuse most SPY ATM intents as `RISK_ENVELOPE_INFEASIBLE`.
  This is a commissioning decision (strike rule, underlying, or an operator-approved limit change), not a
  software default to be tuned here.
- Fees: no provider schedule verified; production refuses. Verification is an operator task (M6 package).
- Multi-contract and spread support (integer partial fills, legging, assignment) is out of scope for the pilot.

## M2 — what was built

- **Ingestion** (`pulse_options/ingest.py`): trades → completed 1-minute bars, or provider bars; every bar carries
  `event_time`, `bar_complete`, `last_receipt`, `available = max(bar_complete, receipt)` and `publication_time`;
  dedupe, out-of-order and late prints counted; revisions retained as versions (the version visible at an as-of
  instant is the one available by then); a bar received or published before completion is refused; a missing
  minute is data.
- **Snapshot** (`snapshot.py`, `OPTIONS_TWIN_STATE_V0`): built only from inputs available by `as_of` (a future
  bar refuses); 1/5/10/15/30/60-minute returns and realized variance, session phase / minute-of-session /
  seasonality bucket (DST- and early-close-aware via `apex.intraday.sessions`), session VWAP and distance,
  range position, prior close and gap (anchors), underlying top-of-book with spread, chain freshness, permitted
  cross-market context, SCHEDULED events (schedule known-from; released values not taken). Every field is a
  `pulse.twin.Field` with quality ∈ {VALID, STALE, UNKNOWN, NOT_AVAILABLE, NOT_ESTIMABLE, SESSION_INAPPLICABLE};
  the state carries a content hash and a quality census.
- **One feature implementation** (`features.py`): `[ret_1, ret_5, rv_30]` from the snapshot; parity with
  `exp001b.bars.observable_rows` is tested to 1e-15; prefix invariance tested (later bars, a late print and a
  revision after t leave the state hash and forecast at t unchanged); replay/live parity tested.
- **Frozen-artifact adapter** (`inference.py` + `exp002_artifact.json`): EXP-002 `fit.params` copied verbatim
  from the sealed result record (sha256 `0c397d70…`); `params_hash` recomputed with the experiment's recipe
  (`ca04fc6e713e1a5c`) at load; forecasts reproduce `apex.world_model.exp002.models.forecast("L", …)` on
  controlled inputs; provenance `INVALID_NULL_CONTROL`, `validated_edge_claim: false` on every forecast; the
  heuristic direction label is recorded beside, never inside, the distribution.
- **Providers** (`providers.py`): Alpaca bars/NBBO and ThetaData chain adapters that parse the documented
  shapes (fixture-tested), keep raw timestamps and record the ET-naive → UTC conversion; `LiveGate` refuses
  before any network access unless `APEX_PILOT_LIVE_DATA=ENABLED` AND credentials are present (presence only
  is recorded). `SyntheticBarProvider` is a labelled fixture.
- **Sources / entry point** (`sources.py`): `TwinSources` supplies the boundary's injected functions for both
  provenances; `ProductionSources` now routes through gated live sources, so the production route refuses
  `LIVE_DATA_DISABLED` before contacting anything; the twin-backed synthetic run goes through the real entry
  point with the certified authority and no geometry fallback.
- **Prepared, not executed**: `scripts/options_pilot_live_smoke.py` (dry-plan only; `--execute` refuses
  without the operator gates and has no HTTP client wired) and
  `docs/OPTIONS_PILOT_LIVE_SMOKE_AND_COLLECTION_REQUEST.md`.

## M3 — what was built

- **Contracts** (`worldmodel_wb/contracts.py`): `ForecastObject` declares what it supplies (mean | variance |
  quantiles | density | paths); asking for anything else raises `UnsupportedOutput` — no synthesis from a point
  forecast. `Model` = fit / forecast / serialize / load / describe with a fit budget (input refusals do not
  consume a fit; an optimizer run does), a cutoff firewall on `fit`, and a deterministic artifact digest that
  `load` re-verifies.
- **Volatility** (`vol_models.py`): RollingVariance (frozen window), EWMA, GARCH(1,1) and GJR-GARCH(1,1) with
  STANDARDIZED Student-t innovations, zero mean, MLE by L-BFGS-B on transformed parameters; refusals for
  non-finite input, too few observations, non-stationarity, ν at a bound, optimizer failure. The convention is
  tested (unit variance of the standardized t; `t_scale_from_variance` / `variance_from_t_scale`). Three horizon
  objects are named on every forecast: next-bar variance, integrated variance (analytic recursion with its
  assumptions stated), cumulative-return variance by SIMULATION with Monte Carlo error. **Reference comparison**
  against `arch` 8.0.0 on one synthetic world (run with the system interpreter; the runner venv has no `arch`):
  |α−α_arch| = 0.0018, |β−β_arch| = 0.0012, |ν−ν_arch| = 0.14, log-likelihood difference −5.4 nats over 6000
  observations (`docs/evidence/garch_reference_vs_arch_OUTPUT.json`).
- **Quantile trees** (`quantile_tree.py`): bounded stump boosting per quantile with pinball-gradient split
  selection and scale-aware residual-quantile leaves; crossing rate measured BEFORE the predeclared
  rearrangement (sort); out-of-sample pinball loss ≤ unconditional at every level on the synthetic world; the
  forecast object says `joint_path_model: false`.
- **Distributional boosting** (`dist_boost.py`): NGBoost-style natural-gradient boosting of Normal(μ, σ) with
  stumps and the log score; improves the log score over a constant Normal and learns the scale channel
  (corr(σ̂, rv_30) > 0.5) on a heteroskedastic synthetic world.
- **Regime** (`regime.py`): two-state Gaussian Markov-switching fitted by EM on training rows; decisions see
  FILTERED probabilities only (a longer prefix cannot change the value at t — tested); smoothed is a labelled
  diagnostic; outputs carry probabilities, entropy, parameter digest, update cutoff, support counts, bars since
  last transition and an ABSTAIN flag (unsupported state or high entropy).
- **Tournament** (`tournament.py`): walk-forward folds with purge (outcome windows that intrude into validation
  removed) and embargo; `DataFirewall`; log score (Normal, t), CRPS, pinball, PIT calibration report; paired
  comparison on common rows with the coverage difference disclosed; `TrialRegistry` with a registered search
  budget that refuses overrun and retains failures.
- **Foundation benchmarks** (`foundation.py`): Chronos-2 and TimesFM 2.5 adapter interfaces (input transform,
  output semantics) report `BLOCKED_RESOURCE` (no package/weights in the authorized environment; nothing
  downloaded); TimesFM 3.0 is `BLOCKED_LICENSE` and excluded. None counts as an implemented model.
- **Study contract** (`study_contract.py`): every proposed historical study must declare target, hypothesis,
  comparator, eligible rows, null/assumptions, cadence, budgets, selection rule, reporting family, cutoff rule,
  dependence inference and planned comparisons; validation yields a digest and grants no access.
- **Not done, by mandate**: no historical fitting; no HAR (needs a trustworthy realized-variance dataset first);
  no change-point / particle-filter challengers.

## M4 — what was built

- **Simulator** (`multiverse_wb/simulator.py`): joint paths of underlying (GARCH/GJR-t or flat variance, 1-minute
  log-return recursion), variance, an IV state under a DECLARED process (fixed / stress-multiplier / drift), and
  an execution spread process; optional regime mixture sampled per path; seeds, cutoff, parameter hash and
  discretization preserved; every output lists its restrictions (e.g. "IV held fixed"); Monte Carlo error is
  reported separately from model uncertainty (fit: not propagated; regime: mixture). Validated on synthetic
  worlds: moments vs the analytic Gaussian special case, heavy tails under t, path-consistent horizon
  aggregation, consistency with the fitted GARCH's integrated variance. Unweighted stress branches carry
  `probability: None`. Jumps are not included (no declared estimator).
- **Pricing** (`pricing.py`): quote sanitation (crossed/zero/size/stale/non-finite refused, never cleaned);
  Black-Scholes-Merton European reference with continuous yield; put-call parity and finite-difference Greek
  tests; IV inversion by Brent with no-arbitrage bounds and an intrinsic-price refusal; CRR binomial American
  engine (early-exercise premium shown on a deep ITM put; convergence to BSM for the European-equivalent case);
  the European formula on an AMERICAN instrument only under a DECLARED approximation; instrument metadata with
  exercise style, settlement, multiplier 100 and refusal of adjusted contracts.
- **Surface** (`surface.py`): raw SVI slice fit to total variance under the parameter constraints (Nelder-Mead
  with restarts + Powell), Durrleman butterfly diagnostic and calendar diagnostic; violations are RECORDED on the
  surface; `iv(k, T)` refuses failed slices and out-of-range expiries; interpolation in T is labelled.
  European-only by construction.
- **Expression comparison** (`expression_war.py`): WAIT + candidates under COMMON paths and documented costs at
  the actual 15-minute exit (exit bid = model mid at (S_H, IV_H, T−H) minus half the spread scenario; entry at
  the sanitized ask; fees once per side; certified max loss = debit + fees); expected net P&L, downside quantiles,
  loss probability, MC standard error, an IV-sensitivity table, and `expected_value_established: false` while IV
  is held fixed; rejected candidates keep their reason; `selection_authority: NONE` — the pilot's deterministic
  rule still selects. `physical_vs_implied` compares at a compatible horizon and discloses the risk premium; no
  arbitrage label exists.
- **Not done, by mandate**: no fitted future-IV process (so no established expected value); no jump component;
  no spread/multi-leg certification; no change to the pilot's selection.

## M5 — what was built

- **Fusion** (`decision_wb/fusion.py`): components must share horizon and cutoff and carry lineage; a component
  without a density is refused (nothing synthesized). Weights are estimated on OUT-OF-FOLD component forecasts
  by maximizing the mixture log score on the simplex, then FROZEN with a digest that `fuse` re-verifies; the
  comparison baseline is the strongest single component on the same OOF rows; leave-one-out ablations per
  component. The fused object carries `p_return_gt_zero` with its definition and a model-disagreement ratio.
- **Supervision** (`supervision.py`, `PRIME_SUPERVISION_V0_SYNTHETIC`): ACT / ABSTAIN with named reasons
  (STALE_DATA, UNSUPPORTED_STATE, MODEL_DISAGREEMENT, QUOTE_UNCERTAINTY, VALUE_UNESTABLISHED,
  INSUFFICIENT_MARGIN, RISK_LIMIT, PREREQUISITE_MISSING); every prerequisite (forecast density, snapshot,
  expression comparison, risk decision, Book) must be present; "confidence" is P(return > 0) under the
  density, never a universal percentage; authority NONE (a proposal record).
- **Experience** (`experience.py`): read-only joins of persisted pilot records to a later realized target and
  IV, producing one primary attribution class or AMBIGUOUS (never forced); challenger PROPOSALS carry a digest
  and register nothing. The ledger bytes are unchanged by a join (tested).
- **Enrichment** (`enrichment.py`): source-linked event records with event/publication/receipt clocks,
  dedup keys, extraction uncertainty and prompt/model versions; a schedule is a known covariate, a release is
  usable only from its publication time; `NoLLMClient` refuses — this build makes no model calls.

## M6 — what was built

- **Funnel trace** (`session.funnel_trace`, stamped on every `pilot_decision`): state snapshot hash, situation/
  regime (named as NOT_AVAILABLE_IN_PILOT), model bundle (model id, params hash, family, validation status),
  simulation bundle (NOT_USED_IN_PILOT), eligible expression set with WAIT, expected economics (UNESTABLISHED),
  risk decision (provenance, authority, certified max loss, kernel approval at commit), final decision. A
  missing stage names why.
- **Operator view** (`operator_view.py`): read-only rendering of persisted records — feed age, release and
  model versions, active policies, Book, reservations, positions/unresolved exits, recent forecasts, intents,
  fills, outcomes, refusals, decisions — every item carrying the ledger seq it came from; chain verification in
  process health; no gauges, no fabricated fills. (No dashboard script exists on this branch to extend; this is
  the view layer a later reviewed change may serve read-only.)
- **Representative-scale check** (`scripts/options_pilot_scale_check.py`): 10 synthetic sessions × 3 symbols ×
  3 cycles through the real entry point with the certified authority — 470 records, 90 forecasts = intents =
  fills = decisions, 63 outcomes, 18 expired, 9 cancelled at close, 0 binding problems, chain verified, cash
  identity holds, 0 open positions, 54 s, 129 MB peak RSS. The run surfaced and fixed two loop defects (a wall-
  clock sleep between cycles on a controlled clock; open WAIT intents blocking the family cap until housekeeping
  expired them) — housekeeping and due-exit valuation now run at the start of every cycle.
- **Commissioning package** (`docs/OPTIONS_PILOT_COMMISSIONING_PACKAGE.md`): scope, blocking prerequisites
  (fee verification, kernel cap vs SPY prices, live smoke, collection, independent acceptance, deployment
  mechanics), expected records, authorities, stop conditions, recovery, operator commands, and the
  implemented / synthetically verified / accepted / authorized state table.

## M7 — the funnel (what was built)

See `docs/FUNNEL_INTEGRATION.md`. One engine (`FunnelEngine`) is used by the live session path and by the replay:
twin → artifact location → walk-forward GARCH-t variance (EWMA fallback declared) → causal regime filter → ATM
implied vol → joint simulation with declared drift → expression comparison (WAIT + near-ATM set, both rights,
risk envelope inside the set) → PRIME supervision → risk-bound intent or WAIT. The engine's result is persisted as a
`pilot_funnel` record before any intent and every decision's trace is filled from it. First contact with SPY-scale
prices makes the kernel-cap blocker explicit (all near-ATM asks rejected by the envelope).

### M7 r2 — integration repairs

The reviewer's eight findings at `f0daac2` are each repaired and pinned by a test (table in `docs/FUNNEL_INTEGRATION.md`):
truncated-t innovations with finite exponential moments (+ cap sensitivity), one variance-state convention with exact
first-step equality, quote validation before IV/ranking, calendar-vs-market clocks separated, mandatory inputs with a
named reduced mode and affordability distinguished from kernel approval, the persisted funnel bound into the intent and
rechecked at fill/recovery, GARCH refusing unsuccessful optimizer outcomes, and the per-scan evaluator population.
Layers not invoked (SVI surface, fusion, enrichment) are named on every trace.

### M7 r3 — bounded repair (four items from the independent review of `3cc65b0`)

NaN/mistyped timestamps and clocks refused before any arithmetic and proven never to reach pricing; multi-start
agreement measured on both preserved optimizer results before selection; the funnel binding now covers the canonical
proposal including `reference_ask`, checked at intent, fill and recovery; a FULL-mode synthetic acceptance test runs the
real engine through selection → persisted funnel → certified reservation → fill → reconciled exit unconditionally, with
a separate mandatory-WAIT case. Table in `docs/FUNNEL_INTEGRATION.md`.

## Backtests (development studies, exposed sessions ≤ 2021 only)

- PILOT-REPLAY-001 COMPLETED on the host: the deterministic rule did not demonstrate improvement over WAIT
  (−5.48 USD/trade, CI [−6.40, −4.50]); direction label no skill (49.6 %). `docs/PILOT_REPLAY_001_RESULT.md`.
- SHARADAR-DAILYVOL-001 COMPLETED: `docs/SHARADAR_DAILYVOL_001_RESULT.md`.
- PILOT-REPLAY-002 (FULL_FUNNEL vs POLICY vs WAIT on common rows) DECLARED, NOT RUN — held by the operator until
  the funnel is complete.

## Evidence index

**Attribution.** Every test count below is BUILDER-REPORTED (run on the Mac venv by the builder); the reviewer has not
executed the full suite or the end-to-end acceptance test. Independent acceptance of M7 r3 covers the four bounded
repairs at `525340c` only; live commissioning and profitability remain UNESTABLISHED. The 11 full-tree failures are
individually identified here and each was re-run at the parent commit `e36b7e9` in a temporary worktree, where it
fails identically (builder-reported):
`test_architecture_claims::test_no_execution_or_broker_dependency_exists` (module-closure audit over repo paths absent
on this branch); `test_null_rig_memory::test_memory_does_not_grow_linearly_with_completed_sweep_seeds`;
`test_real_data_boundary::test_a_sticky_world_writable_ancestor_is_accepted` (host-only sticky-dir probe);
`test_research_board::{test_reconciliation_root_is_deterministic_and_order_independent,
test_reconciliation_root_changes_if_a_legacy_board_changes, test_swapping_two_legacy_boards_changes_the_root,
test_audit_script_passes}` (legacy board roots / audit script not on the Mac);
`test_whole_ledger_guard::{test_every_registered_offender_still_exists, test_pulse_v1_minute_path_reads_no_ledger,
test_checkpoint_module_declares_the_law}` (offender registry and `/opt/apex-repo` paths);
`test_world_model_bootstrap::test_running_inside_research_containment` (`/proc/self/cgroup`).

**What the funnel binding does and does not establish.** Persisting the `pilot_funnel` record and binding its
canonical proposal into the intent establishes the recorded decision's ORDERING and INTEGRITY (the selection preceded
the intent; the executed terms are the selected terms; nothing was altered). It does NOT by itself establish that every
input was AVAILABLE at the decision instant (that is the per-input availability firewall: `available <= as_of` on bars,
validated quote timestamps, snapshot refusal of future bars), that fitted parameters EXCLUDED future observations (the
models' fit-cutoff firewall and the walk-forward tests), or that probabilities are CALIBRATED (PIT / scoring evidence,
which for the artifact is negative and for the funnel does not yet exist). These are separate evidence classes and are
reported separately.

- M7 r3 (`525340c`): full tree on the Mac venv 4,810 passed / 26 skipped / 11 failed in 32 min; the 11 are the SAME
  environment set as r2 and `f0daac2` (all reproduce at the parent commit `e36b7e9`); none from the r3 repairs.
  Touched suites: funnel engine 30 + worldmodel + multiverse = 63; backtest, decision, pilot boundary/entrypoint/
  accounting/operator-view, twin, Robinhood adapter = 144; all pass. CLI smoke at this pin under `FULL_FUNNEL_V1`
  (synthetic fixture): FULL mode, PRIME ACT, digest-bound intent, kernel-approved reservation, FILLED, RESOLVED, book closed clean.

- M7 r2 (`3cc65b0`): full tree on the Mac venv 4,803 passed / 26 skipped / 11 failed in 31 min; the 11 are the SAME
  environment failures listed for `f0daac2` below (all reproduce at the parent commit `e36b7e9`); none from the repairs.
  Touched suites (funnel engine 27, backtest 6, worldmodel, multiverse, decision, pilot boundary/entrypoint/accounting/
  operator-view, twin, Robinhood adapter): 200 passed.

- M7 (`f0daac2`): full tree on the Mac venv 4,784 passed / 26 skipped / 11 failed in 32 min; every one of the 11
  fails identically at the parent commit `e36b7e9` (host-only paths `/opt/apex-repo`, `/proc/self/cgroup`, the
  repo-wide ledger guard's offender registry, research-board legacy roots, sticky-dir probe, null-rig memory):
  environment/pre-existing, none from the funnel. Touched suites: funnel engine 17, backtest 5, pilot
  boundary/entrypoint/accounting/operator-view, twin, Robinhood adapter, worldmodel, multiverse, decision all pass.

- Local (Mac, repo venv): new suites 156 passed (`tests/test_options_pilot_{boundary,entrypoint,accounting,
  operator_view}.py`, `tests/test_pulse_options_twin.py`, `tests/test_worldmodel_wb.py`, `tests/test_multiverse_wb.py`,
  `tests/test_decision_wb.py`); regression set (`tests/test_options_*.py`, ledger concurrency, live book, outbox
  users, organism shadow) 497 passed.
- Contained run on the research host at the final commit: see `docs/evidence/frontier_contained_run.txt`
  (added at the final checkpoint).

## Live data channels (post-mandate, operator-authorized 2026-09-11)

- **Robinhood MCP (read-only)**: the operator authorized a read-only smoke from the agent session. Calls made:
  equity quote, option chain, option instruments, option quotes, 90 minute-bars, index handles + VIX/SPX quotes,
  one L2 book snapshot (empty after hours). No order, account, position or portfolio tool was called; no ledger
  was written. Evidence: `docs/evidence/robinhood_smoke_2026-09-11.json`. Findings: minute bars are bar-START
  labelled UTC with prices as strings; the equity quote has venue-timed bid/ask but NO sizes; option quotes carry
  sized bid/ask with one `updated_at` (the last prior-session print at night → the boundary correctly treats it as
  stale); SPY 758 CALL 21-DTE ask 11.11 confirms the kernel-cap infeasibility warning. Adapter
  `apex/pulse_options/robinhood_mcp.py` (gated; read tools only; trading/position tools refused by construction;
  interpolated bars dropped and counted) with fixture tests shaped from the observed responses. **Reach:** the MCP
  is available only inside this agent session, not to processes on the research host, so it cannot be the pilot
  service's production feed without a process-level client.
- **Alpaca data v2 / ThetaData v3**: adapters exist and are gated off; credentials and the ThetaData terminal live
  on the research host. Enabling them for the pilot process is the operator switch described in the request doc.
- **Other configured MCP servers** (bigdata.com, daloopa, LSEG, S&P Global, finance BigQuery) are present but
  unauthenticated in this session; they are candidate event/fundamental sources for the enrichment schema once
  authorized, not part of the pilot path.

## Host live smoke and collector (operator-authorized 2026-09-11)

- **§A smoke executed on the host** (contained, gated by authorization file + switch + credentials): all four
  provider steps succeeded in under 0.2 s each; 91 Alpaca bars ingested with zero rejections; NBBO carried sizes;
  ThetaData returned 332 quotes for the nearest ≥ 21 DTE expiration with ET-naive timestamps localized and their
  age at receipt recorded (≈ 6.7 h: market closed). The twin composed a snapshot whose bar fields were all STALE
  and the artifact refused to forecast — the pipeline's staleness gates fired exactly as designed. Evidence:
  `docs/evidence/host_live_smoke_2026-09-11_closed_market.json`. Note: the legacy `underlying_nbbo` helper drops
  the quote timestamp; the collector therefore uses `AlpacaBarsAdapter.nbbo`, which keeps it.
- **§B collector launched** as transient unit `apex-pilot-collector` (observation only, hash-chained records,
  heartbeat, stop rules). It is not the pilot; it writes no pilot or live ledger record. First regular session it
  will see: 2026-09-11 09:30 ET.
- **Robinhood MCP market-hours smoke** scheduled once for 2026-09-11 09:40 ET from the agent session.
