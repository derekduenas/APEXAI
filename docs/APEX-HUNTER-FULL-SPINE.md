# APEX HUNTER — FULL INTELLIGENCE SPINE (2026-08-15)

One pipeline. Every intelligence source has a typed seat; absent evidence
is a typed absence, never a fabricated number. Built ≠ proven: the machine
is architecturally complete, and its proof starts Monday 2026-08-17 09:30 ET.

## 1–2. Architecture and dependency graph (as implemented)

```
EODHD live feed
  -> forward clock (launchd 900s; fast-exit off-session)
  -> TwinSnapshot / market-state record        [apex/world + clock]
  -> scan universe (frozen liquidity top-150)  [context_builder]
  -> ChartState (as-of choke point)            [chartstate.py]
  -> RelativeStrengthState                     [relstrength.py]
  -> abnormality scanner (attention, funnel)   [scanner.py]
  -> playbook match (H-001 / H-002; catalyst DORMANT)
  -> birth-time forward-eligibility gate       [birth.py]
  -> DECISION record (chained)
  -> per candidate, fault-isolated:
       Analog Engine   [apex/analog/engine.py]  (frozen schema, leakage law)
       ML Engine       [apex/ml/hunter_models.py] (UNTRAINED, refuses)
       Swarm           [hunter/swarm.py]        (BLOCKED_EXTERNAL_AUTH)
       -> ForecastBundle + disagreement        [hunter/forecast.py]
       -> APEX CAPITAL (risk/cost/capacity/portfolio/monotone caution)
          [hunter/capital.py -> portfolio.risk/capacity, one law]
       -> OBSERVE / WATCH / NO_TRADE / REFUSED (PAPER_ELIGIBLE unreachable)
  -> [dormant seats: World Simulator (on-demand diagnostic),
      distribution engine (source REFUSED), options iface (STOCK only),
      paper execution (NOT_AUTHORIZED), trade manager (certified, idle)]
  -> POSTMARKET: deterministic realizations -> scoreboard (baselines,
     N_eff, three relationships, capital view) -> Research Memory
     (= the chained ledger + lineage API [hunter/memory.py])
```

No side path bypasses this spine; there is no ML bot, Swarm bot, chart
bot, options bot, capital bot, or detached paper trader.

## 3–4. Component statuses

| Component | Status |
|---|---|
| PIT intraday foundation, replay | CERTIFIED |
| Forward clock + state archive | ACTIVE (launchd verified) |
| Twin snapshot / market state | ACTIVE |
| Regime | PARTIAL (crude intraday proxy, conservative-only; daily classifier not yet in intraday loop) |
| ChartState / RS / Scanner | ACTIVE |
| Playbooks H-001/H-002 | ACTIVE (frozen; catalyst DORMANT) |
| Birth law / eligibility | ACTIVE (10 births, append-only) |
| Baselines / N_eff / scoreboard | ACTIVE |
| Analog Engine | BUILT / DATA_GATED (forward memory empty) |
| ML Engine | BUILT / DATA_GATED (UNTRAINED; refuses < 40 effective) |
| ForecastBundle + disagreement | ACTIVE (typed absences) |
| Distribution engine | BUILT / DATA_GATED (status REFUSED without evidence) |
| World Simulator | BUILT / OBSERVE_ONLY (on-demand; not in 15-min hot path) |
| Swarm | BUILT / AUTH_GATED (CLI login; no fabricated responses) |
| Causal/mechanism status | ACTIVE (playbooks = ASSOCIATIONAL) |
| Calibration | DATA_GATED (INSUFFICIENT_FORWARD_EVIDENCE) |
| Opportunity/Capital | ACTIVE (monotone caution proven) |
| TradeThesis / paper engine | BUILT / NOT_AUTHORIZED in production |
| Trade manager | BUILT / CERTIFIED by counterexamples |
| Research Memory | ACTIVE (ledger lineage + structural time firewall) |
| Options | DORMANT (interface only; V1 = STOCK) |
| Live execution | SEALED (BrokerAdapter law unchanged) |

## 5. Evidence class per prediction source

Analog: per-result class, never mixed; historical-exploratory always
carries the survivorship limitation and cannot graduate anything. ML:
trains only on FORWARD_ELIGIBLE decisions joined to realizations. Swarm:
qualitative, never numeric evidence. Simulation: UNCALIBRATED_SCENARIO_
WEIGHT, authorization power NONE.

## 6. Analogue design

Frozen ANALOG_FEATURE_SCHEMA_V1 (14 economically meaningful state
dimensions, fixed declared scales — normalization cannot leak). Distance
= mean absolute scaled difference over mutually present features (≤4
missing). Structural time firewall before distance: formed-before-as_of
AND resolved-before-as_of. Neighbour identities frozen from state alone;
outcomes joined after (counterexample-tested). Sparse = ANALOG_SUPPORT_
LOW / NO_VALID_ANALOGS; low support can never claim a probability
downstream (bundle nulls it).

## 7. ML design

Interpretable only (deterministic L2 logistic/IRLS), horizons 15/30/60/
90m separate, features = the same frozen analog schema (state cannot
drift between retrieval and prediction), outcome-token guard, N_effective
gate at 40, lifecycle UNTRAINED→EXPLORATORY→FORWARD_EVALUATING→PAPER_
GRADE→CALIBRATED (+DEGRADED/RETIRED). Search registers in the existing
ModelSearchLedger; denominators = attempts, not keepers.

## 8. ForecastBundle

Sources independently inspectable; disagreement measured (direction,
dispersion, swarm flags) and first-class; distribution source status
DERIVED never asserted; NO fake ensemble — combination rules must be
declared/versioned/calibration-aware before existing.

## 9. World simulation

TwinSnapshot / TwinTransitionModel / WorldSimulation never conflated.
Source = conditional_block_bootstrap_v1: contiguous 15m blocks of the
symbol's own PRIOR sessions, time-of-day conditioned (clustering and
seasonality survive; no Gaussian shortcut). Future-blind through the same
visibility choke point (poison-test). Branch outputs are SCENARIO
FREQUENCIES (UNCALIBRATED_SCENARIO_WEIGHT), diagnostic only, deterministic
seed = sha256(candidate|version|twin-hash|config). Reweighting = new
appended simulation; the old one is never mutated.

## 10. Swarm

Nine specialist roles defined; SwarmAssessment contract enforces: non-OK
status carries zero claims (no fabricated views). Fast path never waits;
NOT_AVAILABLE_IN_TIME instead of delayed decisions. Auth marker
(ops/swarm_auth_ok) is operator-managed; even with the marker present the
transport refuses until a real-auth smoke test has run.

## 11. Calibration

Existing machinery (Brier/log/reliability/PIT, mint_calibrated as the only
mint) + hunter scoreboard. Graduation uses frozen criteria and N_effective;
Monday's correct answer is INSUFFICIENT_FORWARD_EVIDENCE.

## 12. Capital

One law: risk limits from portfolio.risk (position/sector/heat/drawdown),
capacity participation, declared paper template. MONOTONE CAUTION: regime
uncertainty ×0.5, HIGH disagreement ×0.5, low analog support ×0.75 — all
factors ≤ 1; a more uncertain system can never get bigger. Simulation has
no factor (diagnostic sources move nothing).

## 13–15. Paper execution, trade management, memory

Paper: production requires PAPER_ELIGIBLE (unreachable until Phase 3
commissions the forecast slot); SyntheticTestAuthorization cannot exist
outside pytest. Fills: CERTAIN (opened through) / PLAUSIBLE (traded
through +ε) / AMBIGUOUS (bare touch — no P&L may be asserted) / NO_FILL.
Management: stop never widens, PARTIAL monotone down, ADD needs fresh
Capital authorization and refuses under rising uncertainty, LLM/Swarm
actors refused before any rule runs. Thesis health = deterministic
violated-condition counts. Memory: the chained ledger is the store;
lineage API + structural time firewall; BEFORE records never mutated.

## 16. Options future interface

`select_expression`: V1 allows NO_TRADE/STOCK; anything else demotes with
reasons (dormant, uncalibrated, no chain data). No fabricated chains.

## 17. Monday production behavior (expected, successful)

Candidate → bundle{analog: NO_VALID_ANALOGS, ml: UNTRAINED, swarm:
BLOCKED_EXTERNAL_AUTH, distribution: REFUSED} → capital OBSERVE (WATCH
under caution) → realization → scoreboard/memory. NO paper trades. That
IS the design working.

## 18–20. Blocked, limited, unproven

Blocked by auth: Swarm (CLI login). Blocked by data: analog support, ML
training, calibration, distribution statuses, simulator calibration,
options. Known limitations: scan universe = top liquidity tier only;
regime = crude intraday proxy; no measured spreads (COST_UNKNOWN); EODHD
delisted-coverage gap (frozen finding); Sharadar snapshot as-of lag.
Scientifically unproven: EVERYTHING about alpha — selection, prediction,
calibration, asymmetry, durability. The graduation criteria are frozen;
the market grades from Monday.
