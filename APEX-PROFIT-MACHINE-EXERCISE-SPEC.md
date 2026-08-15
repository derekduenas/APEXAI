# APEX PROFIT MACHINE — HISTORICAL DISCOVERY EXERCISE SPEC (FROZEN)

Frozen: 2026-08-15, BEFORE any realized return flows through the machine.
Hash of this file is recorded in the exercise report; any edit after the
run voids the run. DEVELOPMENT/EXPLORATION ONLY: in-sample, zero credits,
holdout sealed, nothing herein is confirmatory evidence.

## Part 0 status (reconciled from registry + live checks, 2026-08-15)

PARTICIPATING NOW: pit_data, universe (registered small-cap band), feature
factory/registry (mechanism-tagged), world_state (online classifier +
uncertainty), distribution_estimator (HISTORICAL_EMPIRICAL only),
expression engine (STOCK_ONLY), risk engine, capacity engine, cost model,
opportunity engine (tiers below), exploration accounting (denominator),
paper/reality infrastructure (untouched by this exercise), analogue layer
(diagnostic, built per Part 7 from existing state variables).
EXIST, NOT PERMITTED: ml_estimator (UNDER_CONSTRUCTION -> ML_STATUS=
NOT_ACTIVE), causal_executors (claims only -> rung mapping declared below),
options expression (no historical chain data -> STOCK_ONLY).
BLOCKED_EXTERNAL: swarm agents + LLM producers (SWARM_STATUS=
BLOCKED_EXTERNAL_AUTH -- headless CLI 'Not logged in', verified this turn).
DATA_GAP: event_data, alternative_data, options chains, macro feed (FRED).
REQUIRED+MISSING (built by this tranche): discovery_exercise_runner.
NOT REQUIRED for the exercise: execution, live_monitoring, model_registry,
backtest_engine (the exercise IS the evaluator), digital_twin_multifacet
(state fields consumed directly from apex/world).

## Frozen parameters

- **Dates** (Part 30, systematic, not outcome-selected): every 6th usable
  grid formation date in-sample (>=200 scored names), first to last. This
  spans 2008-09, 2011, 2015-16 stress and the bull runs between.
- **Universe**: the registered small-cap band [100M, 2B), as configured.
- **Horizon**: 20 trading days, single declared horizon. Multi-horizon is
  DEFERRED and recorded as such (denominator note: horizons considered = 1).
- **Candidates** (Part 2 -- mechanisms, not brute force): one candidate per
  BUILT fundamental feature in the registry (each carries its economic
  rationale, direction, PIT rule from the FeatureSpec) plus the registered
  quality-value composite (H3 lineage). No candidate without a mechanism.
  Causal rung mapping (Part 8, declared): literature-backed registry
  features -> MECHANISM_SUPPORTED; composites -> ASSOCIATIONAL. Never
  CAUSALLY CONFIRMED.
- **Signal -> distribution** (Part 10): top-decile bucket by candidate rank
  among eligible at T; conditional pmf = empirical histogram of 20d forward
  EXCESS returns of trailing bucket members over the 750 trading days
  ending at T-21 (labels fully resolved before T). Minimum 100
  observations, else INSUFFICIENT_EVIDENCE -> REFUSED. Status:
  HISTORICAL_EMPIRICAL, never upgraded.
- **State** (Part 6): classify_online(T); participates ONLY via the
  predeclared caution channels (uncertainty multiplies the edge bar x1.5;
  stress overlay recorded). NO state-conditioned alpha selection.
- **Analogues** (Part 7): 5 nearest PRIOR dates by z-distance on (trend,
  vol20, drawdown); diagnostic only; may not alter decisions in this run.
- **Economics** (Part 16): declared NAV $500k; weight 3% per TRADE;
  relative spread 0.003 (30bp -- the operator's small-cap pushback
  honored); annual turnover 1.6 (measured in the instrument study);
  capacity/impact per apex/portfolio/capacity constants. Cost waterfall
  exposed gross -> net, always.
- **Risk** (Part 14): apex/portfolio/risk declared limits, unchanged;
  portfolio state ACCUMULATES across dates (positions decay at horizon).
- **Decision + tiers** (Parts 17-19, FROZEN before results):
  - REFUSED: governance/evidence/calibration failures (engine reasons).
  - NO-TRADE: engine refusal on edge/risk/capacity/cost grounds.
  - WATCH: NO-TRADE whose ONLY failure is the edge bar missed by <1%/yr.
  - TRADE: engine TRADE.
  - **TIER A (ExceptionalOpportunityCriteria)**: TRADE and ALL of --
    net >= 8%/yr; P(negative 20d excess) <= 45%; distribution n >= 300;
    state not uncertain; no beta-cap/risk warnings; capacity >= 3x target
    notional. Strict enough that zero qualifiers is an acceptable outcome.
  - Part 28: any TIER A automatically triggers the Exceptional Audit
    fields (P&L/name/year concentration, cost sensitivity at 2x spread).
- **Ablations** (Part 24, FULL frozen first, decisions recomputed only):
  A raw-signal-only (top-decile exists -> TRADE); B no-uncertainty-raise;
  F no-risk-engine; H no-costs (gross treated as net); J no-portfolio-
  accumulation. Ablation outcomes may not tune FULL.
- **Baselines** (Part 31): universe EW; always-TRADE GP top decile (the
  conventional factor process); cash (0).
- **Metrics** (Part 25): the subset computable from stock-only, single-
  horizon development data -- discovery counts, decision counts, sign
  accuracy, realized gross/net per decision, cost drag, NO-TRADE value
  (realized outcomes of refused candidates), tier quality.
- **Search denominator** (Part 3): candidates x dates + horizons considered
  + every REFUSED/NO-TRADE retained in research memory. Nothing fitted, so
  the trial ledger records zero model fits -- stated, not hidden.
- **Research memory** (Part 22): every candidate-date decision appended to
  results/research_memory.jsonl (chained) with lineage, mechanism, state,
  decision, reasons, realized outcome. This is research_memory v1.
- **Realization loop** (Part 23): decision frozen at T; realized 20d bucket
  excess recorded beside it; original artifact never revised.
- **Stop rule**: none required; the pass is deterministic. If the panel
  fails to load or any PIT guard trips, the run aborts and reports.

## PIT invariance (Part 1)

Structural coverage already certified and cited: factory knowability
(221k obs, 0 violations), online classifier future-blindness, never-revised
labels, vintage store, exploration window guard, no-backdating. ADDED this
tranche: the DECISION-LEVEL counterfactual test -- Decision(T) computed
from inputs sliced <= T must be bit-identical when all post-T data is
wildly mutated (tests/test_discovery_exercise.py).

## The questions the report must answer

Parts 32-36 verbatim, including: does the machine add economic value
(YES/NO/NOT YET ESTABLISHED); does any current opportunity deserve
Credit 5 (expected answer NO unless every Part 35 criterion is met);
which components are ornamental vs valuable vs bottleneck; and the final
principle -- if the correct answer is NO-TRADE, say it without hesitation.
