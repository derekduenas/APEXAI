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

---

# ADDENDUM A — probabilistic state estimation, uncertainty ownership,
# predictability measurement and information acquisition

Status: **DOCUMENTED / SPECIFIED_NOT_IMPLEMENTED**. Added at `2af98967`,
after the pre-admission closure. Nothing here creates a new trading
authority, changes EXP-001B, or is implemented by this milestone. Interface
definitions live in `APEX_INTERFACES_V0.md`; activation gates live in
`IMPLEMENTATION_ROADMAP_V2.md` and `CHALLENGER_REGISTER_V0.md`.

## A0. Standing qualifications carried forward (do not lose these)

These are the closure's findings, restated because later readers will meet
this addendum first:

1. **Calendar verification covers 2016–2021 only.** Dates outside that
   window are refused (`CALENDAR_NOT_VERIFIED`).
2. **Classifier parity ≠ calendar verification.** The parity test proves the
   classification *logic* matches the governed module given identical
   tables; the reconciliation proves the *tables* against the exchange
   record. Two different pieces of evidence.
3. **File-size corroboration is not proof of session contents.** It
   corroborated 10 of 12 early closes and is silent on 2.
4. **Ordinary filesystem protection does not constrain an account with
   unrestricted sudo.** `/etc/apex/admissions` resists ordinary replacement
   by the research account; it does **not** resist that account's
   passwordless sudo. Only a non-privileged research identity makes the
   ancestor checks meaningful.
5. **Before/after source verification detects persistent change.** It does
   not prove the absence of change-and-restore within a run, nor of
   arbitrary privileged interference.
6. **EXP-001B has never executed on real data.**
7. **Evaluation remains separately blocked** (N0 not enforced on that
   branch; calendar unverified beyond 2021).

## A1. Where latent-state inference lives (and where it does not)

The split is a rule about *what a record claims*, not about code location.

| | **Digital Market Twin** | **World Model** |
|---|---|---|
| holds | sourced factual observations, their quality, timestamps and relationships | inference about latent market state from those observations |
| claim | "this was observed, from this source, valid at this time" | "given those observations, the latent state is estimated to be …" |
| carries | provenance, effective time, availability, revision history | provenance **of the inputs**, model identity, uncertainty |
| may be written back to the Twin | — | **never** |

The conceptual relation, stated once and not implemented here:

```
observations ~ observation_model(latent_state, measurement_uncertainty)
```

The latent state may include liquidity pressure, regime, positioning
proxies or participant response tendencies. **Every one of these is an
estimate with provenance and uncertainty, never a fact.** Dealer
positioning inferred from options open interest, ownership inferred from a
delayed disclosure, and "participants are trapped" are hypotheses; writing
any of them into the Twin as an observation would launder an inference into
a fact, and is forbidden by the table above.

Interface: `LATENT_STATE_ESTIMATE_V0` in `APEX_INTERFACES_V0.md` §1 —
observation-snapshot identity, inference model and version, as-of and
availability basis, estimates or weighted samples, uncertainty
representation, missing-data and out-of-distribution indicators,
assumptions and limitations. **No posterior probabilities are manufactured
and no filter is implemented in this milestone.**

## A2. World Model and Multiverse: who owns which uncertainty

The failure this section exists to prevent: simulating ten thousand paths
from one starting state that was never uncertain, and reporting the spread
of those paths as if it were the uncertainty of the forecast.

| Uncertainty | Owner | Propagated by |
|---|---|---|
| measurement / observation error | Twin (recorded), World Model (consumed) | into the starting-state distribution |
| latent state given observations | **World Model** | sampled starting states |
| model parameters | **World Model** | parameter draws per path |
| competing models (structural) | **World Model** (weights) | model index per path |
| future disturbances | **Multiverse** | innovation draws along the path |
| participant reactions, regime change | **Multiverse** (dynamics), World Model (initial regime belief) | scenario branches |

**Ownership of the distribution is single; sampling weights are a separate
thing.** (Corrected at `560fdc72`: the first version of this rule said the
Multiverse "never re-weights", which was too rigid and would have forbidden
correct Monte Carlo practice.)

The **World Model owns the forecast distribution**: the latent-state
distribution, the parameter distribution, the weights over competing
models, **and the versioned transition model** that, together with those,
*defines* the distribution. Dynamics are part of the forecast's meaning, so
their identity and version belong to the World Model contract.

The **Multiverse executes** conditional simulation under that contract. It
may use **computational sampling weights** — importance sampling,
stratification, antithetic or common random numbers, rare-event tilting —
because these are how a target distribution is estimated efficiently, not a
change to it. Every such scheme must:

- declare the **proposal** it sampled from and the **target** it estimates;
- carry the **correction** (importance weights / likelihood ratios) with the
  samples, so any consumer can recover the target expectation;
- report **effective sample size after weighting**, since a tilted sampler
  with a few dominating weights is a smaller sample than its path count;
- be **validated** — on a case with a known answer, the weighted estimator
  must reproduce the unweighted one within its stated Monte Carlo error.

What remains prohibited is a **change to the target distribution** that the
World Model did not author: silently re-weighting model or state
probabilities, tilting to make an outcome look likelier, or reporting
proposal-distribution quantities as if they were the forecast. A weight
whose provenance and correction are not recorded is not a sampling weight —
it is an unauthorised edit to the forecast.

Where the Multiverse needs a probability the World Model has not supplied,
the branch is **unweighted** and is reported as such. **Stress branches
remain entirely separate** and never acquire probability mass, weighted or
computational.

Four things stay separate and are never summed into one number:

1. **probability-weighted forecast** — the physical distribution;
2. **model disagreement** — dispersion *across* models, reported beside the
   forecast, never folded into it;
3. **unweighted stress scenarios** — no probability mass, ever;
4. **LLM-proposed causal branches** — `UNWEIGHTED` until quantitatively
   evaluated; an LLM may propose a branch, never price one.

**Ensembles must not double-count.** Two models fitted on the same data
with the same features are one piece of evidence with two labels. Before
any ensemble weight is used, the register must record: the information each
member consumes, the overlap between members, and the effective number of
independent members (a correlation-adjusted count, not the member count).
Equal weighting of eight correlated models is a fabricated confidence.

**Sample count is not validity.** More Monte Carlo paths reduce simulation
error *conditional on the model*. They say nothing about whether the model
is right. Every Multiverse output carries `simulation_error` and
`model_uncertainty` as separate fields, and the second is never reduced by
raising the first's sample count.

## A3. Empirical predictability map

Placed in **evaluation and Experience**, consumed later by PRIME. It records
where predictive skill has actually been measured — by target, horizon,
market state or regime, information tier, model version and evidence
maturity — and, just as importantly, where it has not.

Every entry requires: out-of-sample scoring against a **declared**
comparator; calibration evidence; effective sample support with the
dependence treatment named; uncertainty around the estimated improvement
(not a point estimate); the registered grouping rules that defined the cell
*before* it was scored; and research-search accounting. A cell with
insufficient support is `INSUFFICIENT_EVIDENCE` — an explicit state, never
an interpolated or optimistic one.

**What this must not become:** a machine that re-slices results until an
attractive subgroup appears. Cells are registered before scoring, the
number of cells examined is part of the search budget, and any *learned*
selection rule over the map is a separate hypothesis requiring its own
validation on its own data. The map is an estimate of *capability*, not a
promise about the next forecast. Lyapunov-style predictability measures
remain optional challengers with their own evidence requirements (C10).

Interface: `PREDICTABILITY_MAP_ENTRY_V0`, `APEX_INTERFACES_V0.md` §3.

## A4. Decision-value-driven information acquisition

Placed in **PULSE**, informed by research and decision needs. The question
is never "is this data interesting" but:

> Could obtaining this observation change a feasible decision by enough to
> justify its monetary cost, its latency and its operational burden?

**Information gain is not economic value.** An observation can sharpen a
distribution and change nothing about the preferred action; that
observation is not worth buying. Conversely a cheap observation that flips
a funding decision is worth more than a large reduction in an irrelevant
variance.

Every acquisition record names: the unresolved question; the candidate
source and the permissions it requires; expected availability and latency;
cost and request budget; the decision it could affect; the result
**including failure**; and — after the fact — whether it actually changed
the forecast or the decision.

**Not now:** no autonomous paid-data purchasing, no unrestricted browsing,
no learned acquisition policy. The first implementation is a *proposal
queue* with auditable deterministic priorities that a human approves.

**Missingness is evidence.** The record of what was requested, what was
refused, what failed and what was never asked is kept so that later
research cannot mistake selectively collected data for an unbiased sample.

Interface: `INFORMATION_ACQUISITION_REQUEST_V0`, `APEX_INTERFACES_V0.md` §4.

## A5. Attribution, extended

`Experience` already separates forecast, expression, execution and sizing
error. The addendum splits the first into causes that imply different
repairs:

| Class | Means | Repair it implies |
|---|---|---|
| observation / data quality | the input was wrong, late or missing | fix the feed, not the model |
| latent-state estimation | inputs fine, state inferred wrongly | the observation model or its uncertainty |
| dynamics / parameter | state fine, propagation wrong | the transition model |
| omitted mechanism | nothing in the model could have produced this | new mechanism, registered |
| regime change | the relationship itself moved | regime detection, not parameter tuning |
| expression / execution | the view was right, the trade was not | structure, costs, timing |
| **already represented** | the outcome sat inside the forecast distribution | **nothing — this is not an error** |

The last row matters most: a loss inside the predicted distribution is the
model working, not failing. **Every class is a diagnostic hypothesis until
independently supported.** A single losing trade does not identify its own
cause, and attribution over one outcome identifies at most one gross class.

## A6. Dashboard requirements added (not implemented here)

Added to the nine views in §4, with the same rules (source, timestamp,
version, mode; missing stays missing):

10. **observed vs inferred state**, side by side and visibly distinct;
11. **assumed vs measured availability** (EXP-001B's `ASSUMED_BAR_CLOSE`
    must never render as a measured publication time);
12. **forecast uncertainty and model disagreement**, as separate quantities;
13. **evidence behind each predictability-map cell**, including
    `INSUFFICIENT_EVIDENCE` cells;
14. **information-acquisition cost and status**, including refusals.

The dashboard is **not** implemented or restarted by this addendum.
Engineering, historical, prospective-paper and live displays stay distinct.

## A7. Overlap analysis — what each refinement reuses

Nothing here is a new subsystem; each refinement is a contract over
machinery that exists.

| Refinement | Reuses | Genuinely new | Does NOT duplicate |
|---|---|---|---|
| A1 latent state | `WorldModelForecast` uncertainty fields; `sources.admit` / real-data boundary provenance; Twin field clocks | the estimate record itself (`LATENT_STATE_ESTIMATE_V0`) | the Twin's factual records — it never writes them |
| A2 uncertainty ownership | `nulls.py`, `worlds.py`, `inference.dm_hac_rule` | a written ownership rule + `simulation_error` vs `model_uncertainty` separation | the forecast contract; no second probability owner is created |
| A3 predictability map | `grader.grade`, `inference`, `holdout`, the search-budget discipline in registrations | the cell schema and its `INSUFFICIENT_EVIDENCE` state | the courts — it scores, it does not adjudicate |
| A4 acquisition | PULSE field clocks, quality classes; the existing manifest/admission machinery for anything acquired | the request record and its missingness log | the admission boundary — acquisition proposes, admission still decides |
| A5 attribution | `organism/experience.py`, `capital/counterfactual.py`, `economic_path.attach` | the finer cause taxonomy incl. "already represented" | the existing error split, which it extends rather than replaces |
| A6 dashboard | `scripts/apex_dashboard.py` view scaffolding and quality semantics | five view requirements | the data sources; all are existing artifacts |

## A8. What this addendum explicitly does not do

No new trading authority. No implemented filter, no manufactured
posteriors, no ensemble weights, no acquisition automation, no dashboard
change, no alteration to EXP-001B's registration, scope or pending baseline
test. Every interface is `SPECIFIED_NOT_IMPLEMENTED` until a registered
hypothesis names it and its activation gate opens.
