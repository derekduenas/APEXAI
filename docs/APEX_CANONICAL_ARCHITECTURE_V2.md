# APEX CANONICAL ARCHITECTURE V2 — strategic integration

Status: **DOCUMENTED**. This document reconciles the operator's expanded
vision with the governed architecture already built. It supersedes nothing
that was decided by evidence; it records where an earlier statement is
narrowed or extended, and it grants no runtime authority. An interface
written here is a contract to build against, not permission to activate.

Objective (unchanged): **maximize capacity-adjusted, after-cost geometric
capital growth subject to survival constraints.** Survival is a constraint.
Aggression is earned by prospective evidence. Funding creates no evidence.

APEX is the alpha engine. Its intended advantage is the integrated
transformation — causal information → future-path distributions → market
disagreement → best expression → capital competition → independent risk →
execution → experience — not any single layer. Nothing below claims the
architecture is unique, that institutions ignore these opportunities, or
that predictive or economic superiority has been shown. Small-capacity
opportunity is a research hypothesis. Conversational examples and
illustrative probabilities in prior discussion are design intent, not
numerical requirements.

## 1. The chain, with authorities

```
REALITY
 → PULSE                       senses; sealed packets with per-field clocks       authority: NONE
 → DIGITAL MARKET TWIN         sourced, time-valid state and relationships        authority: NONE
 → WORLD MODEL                 calibrated conditional forecasts (distributions)   authority: NONE
 → MULTIVERSE                  conditional joint-path simulation, stress branches authority: NONE
 → MARKET-IMPLIED COMPARISON   physical vs implied, after premia and frictions    authority: NONE
 → EXPRESSION WAR              candidate structures with full lifecycle economics authority: NONE
 → PRIME                       selection under rules; may only choose CASH or a candidate
 → ARENA                       capital competition; FUND / PARTIAL / REFUSE        authority: allocation of PAPER/authorized capital only
 → RISK                        independent certification; may REFUSE anything     authority: VETO
 → BOOK                        the only funding site; accounting of record         authority: ledger
 → EXECUTION BOUNDARY          ORDER_READY → human authorization → sealed dispatch authority: SEALED (live)
 → EXPERIENCE                  graded, calibrated, attributed outcomes             authority: NONE
 → ERROR ATTRIBUTION           forecast / expression / execution / sizing / luck   authority: NONE
 → CHALLENGER LEARNING         registered, repeated evidence before promotion      authority: NONE (promotion is a human decision)
 → improved WORLD MODEL
```

Rules that no layer may rearrange:

- **1R must mean 1R.** Certified max loss is the loss at the certified
  exit, including the round-trip cost; a stock with a stop has no certified
  max loss and is not PRIME-eligible. Relabeling does not change this.
- **The Book is the single funding site**, reached only after Risk
  certifies. Research paths use isolated ledgers.
- **Execution is sealed.** Research and paper outputs carry
  `ORDER_AUTHORITY: NONE`; the broker boundary is reachable from no
  research module (AST-verified in tests).
- **Organs are senses, not traders.** PULSE, Twin, World Model,
  Multiverse, Comparison, Expression and Experience propose; PRIME
  selects; Arena allocates; Risk vetoes; Book records.

## 2. Execution and position-management lifecycle (documented, not rearranged)

| Phase | Owner | Boundary crossed | Present state |
|---|---|---|---|
| candidate → certified | Risk (`apex/organism/risk_certificate.py`) | none; veto only | tested |
| certified → funded | Arena → Book (`apex/capital/arena.py` → `apex/organism/book.py`) | ledger | tested; paper history |
| funded → ORDER_READY | Execution gateway (`apex/execution/gateway.py`) | intent sealed | live placement SEALED |
| ORDER_READY → dispatched | human authorization + `apex/execution/robinhood.py` | broker | NOT_AUTHORIZED |
| open position → managed | management policy declared WITH the expression (exit rule, interim valuation model) | none | option management policy NOT_IMPLEMENTED |
| managed → closed | Book attaches outcome | ledger | tested |
| closed → attributed | Experience (`apex/organism/experience.py`, `apex/capital/counterfactual.py`) | none | tested (engineering) |

An expression is not complete without its management policy. Early option
exits require an explicit interim valuation and execution model; terminal
underlying prices alone are insufficient (§4.6).

## 3. Expanded capabilities — placed, with interfaces and authorities

Each capability below states: responsibility, prohibited authority,
inputs/outputs, where it lives in the chain, and its evidence gate. None is
activated by this document.

### 3.1 Participant and Causal Transmission Model

Two responsibilities, kept apart:

- **Twin (sourced):** entity relationships and exposure *measurements* —
  companies, suppliers, customers, competitors, institutions, countries,
  commodities, currencies, policy exposure, observable participant cohorts.
  Every edge carries `provenance`, `effective_from`, `effective_to`,
  `availability` (publication and receipt), `revision_history`, and
  `uncertainty` where applicable.
- **World Model / Multiverse (inferred):** behavioral responses and
  counterfactual transmission hypotheses — how a shock at one node is
  expected to move another, with a fitted or hypothesized strength and a
  stated basis.

Prohibitions: inferred dealer positioning, delayed ownership disclosures
and suspected participant intentions are **hypotheses**, never observed
facts; the same underlying evidence reached through several graph paths is
counted once (`evidence_id` de-duplication at the Twin).

Interface (Twin): `Relationship{src, dst, kind, measure, provenance,
effective_from, effective_to, publication_time, receipt_time,
revision_history[], uncertainty, evidence_id}`.
Interface (World Model): `TransmissionHypothesis{edge, response_model,
fitted_on, basis: OBSERVED_FIT | ANALOGUE | STATED, strength, uncertainty}`.

Evidence gate: an interface is built only when a registered hypothesis
names what the model improves; the first candidate is index/sector
transmission for scheduled macro releases (see FIRST_ECONOMIC_PROGRAM).

### 3.2 Event Surprise and Transmission

`Event{content, event_time, source, publication_time, receipt_time,
expected_outcome, expectation_provenance, channels[]}`.

"Event minus expectation" is a framework, not a universal scalar.
Published consensus is one estimate of expectation; the market's complete
expectation is not observable and is not assumed. Three things are kept
distinct and separately timestamped: the **pre-event conditional forecast**
(uses only information with `known_from` before the event), the
**post-release interpretation**, and the **subsequent cross-asset or
participant response**. Information received after the event never enters
a pre-event forecast; the boundary enforces `known_from` on every row.

### 3.3 Premarket Intelligence

Built on PULSE (`apex/pulse/`): overnight state, premarket paths, scheduled
catalysts, public disclosures, cross-asset changes, available options
information — each a `Field` with quality, `as_of` and `known_from`.
Prior-session options observations are labelled `PRIOR_SESSION`, never
presented as executable quotes. The intelligence agent (Catalyst,
`apex/catalyst/`) extracts sourced facts and proposes hypotheses; it holds
no probability authority and no trading permission
(`SHADOW_CONTEXT_ONLY` remains).

### 3.4 Historical Analogue Retrieval

Retrieve *neighborhoods* of comparable causal states, not chosen success
stories. Representations and retrieval rules are fit on permitted training
information only; overlapping outcomes are protected (embargo); future
observations are excluded by `known_from`. Output: `AnalogueSet{query_state,
neighbors[], similarity, salient_differences, effective_n (dependence-
adjusted), ood_flag}`. Analogues inform forecasts; they do not dictate them.
Existing substrate: EdgeForge causal analogs (`apex/edgeforge/`), shadow only.

### 3.5 Multiverse

Quantitative conditional simulation is primary: joint paths of returns,
volatility, jumps, dependence and liquidity where supported. Output
separates **estimated-probability scenarios** from **unweighted stress
branches**. More paths reduce simulation noise; they do not reduce model
uncertainty, which is reported separately. LLM-proposed scenarios enter as
`UNWEIGHTED` until quantitatively evaluated; they never receive probability
mass by assertion. Present state: null worlds and synthetic worlds exist in
the laboratory; a real-data path generator is NOT_IMPLEMENTED and is gated
on a registered need.

### 3.6 Market Comparison and Expression War

Compare the calibrated physical forecast with market-implied distributions
after risk premia and frictions. A distributional disagreement is a
**candidate**, not proof of mispricing. Every expression is evaluated with
its entry, management and exit policies together, including spread, fees,
liquidity, fill uncertainty, contract granularity, volatility exposure,
expiration, exercise and assignment. Early exits need an interim valuation
and execution model. Shares remain research comparators; stock-with-stop is
not made PRIME-eligible by relabeling risk. Existing substrate:
`apex/expression/engine.py` (pricing, structures from a pmf and chain),
`apex/option_analytics/`, `economic_path.py` (stock comparators).

### 3.7 Experience and Challenger Learning

Persist the full decision lineage — forecasts, scenarios, candidates,
rejections, cash decisions — where feasible. Attribution separates forecast
error, expression error, execution error, sizing error and ordinary outcome
randomness; a single outcome identifies at most one gross class. Challenger
promotion requires registered, repeated evidence; there is no automatic
live-model rewrite after individual trades. The challenger register
(`CHALLENGER_REGISTER_V0.md`) is the only entry point.

## 4. Dashboard — read-only observability layer (specified, not redesigned)

The dashboard is part of the canonical plan as a **read-only** operational
and economic observability layer. Required views, each item carrying
`source`, `timestamp`, `version`, and `mode ∈ {ENGINEERING, HISTORICAL,
PROSPECTIVE_PAPER, LIVE}`:

1. Data freshness, provenance and coverage (present: Market Data view).
2. Layer readiness and actual authority (present: partial, Command Center).
3. Forecast distributions and calibration — model-implied probabilities are
   never labelled realized calibration.
4. Scenario provenance and stress branches.
5. Candidate rejection reasons and cash decisions.
6. Expression comparisons and execution assumptions.
7. Certified risk, positions and accounting — backtest P&L is never
   labelled realized account P&L.
8. Forecast-to-outcome attribution.
9. Research budget and challenger evidence.

Missing remains missing (`NOT_AVAILABLE` / `NOT_READY` rendered as such).
Present dashboard v0 (`scripts/apex_dashboard.py`, loopback only) covers 1
and part of 2; the rest are NOT_READY and shown so.

## 5. Supersession record

- "Full program execution" (broad mandate) was superseded by the focused
  economic mandate; this document keeps the focus: one governed route to
  real historical research, one registered experiment, one recommended
  first opportunity family.
- The laboratory's real-data prohibition (`WORLD_MODEL_SOURCE_BOUNDARY_V0`)
  is **not** superseded; a separate route (`WORLD_MODEL_REAL_DATA_BOUNDARY_V0`)
  is added beside it.
- The readiness map (`MILESTONE1_CHAIN_READINESS_MAP.md`) remains the
  inspected-caller record; `IMPLEMENTATION_ROADMAP_V2.md` extends it with
  the expanded components and the sequenced route.
