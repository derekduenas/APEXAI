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
| M3 — World Model workbench | `SYNTHETIC_VERIFIED` (foundation benchmarks `BLOCKED_RESOURCE` / `BLOCKED_LICENSE`) | see manifest (`M3.commit`) | `apex/worldmodel_wb/*`; `tests/test_worldmodel_wb.py` (14); `docs/evidence/garch_reference_vs_arch_OUTPUT.json` |
| M4 — Multiverse + market-implied | `NOT_STARTED` | — | — |
| M5 — fusion, supervision, learning | `NOT_STARTED` | — | — |
| M6 — operator view + commissioning package | `NOT_STARTED` | — | — |

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
  verified and recorded. The forecast provider is still `NO_REVIEWED_INFERENCE_ADAPTER` (M2).

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
