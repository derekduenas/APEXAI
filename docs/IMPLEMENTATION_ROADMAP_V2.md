# IMPLEMENTATION ROADMAP V2 — dependency-ordered route to a paper Predator

Extends `MILESTONE1_CHAIN_READINESS_MAP.md` (inspected callers as of
`dc321587`/`ec1bfc50`) with the expanded components and the sequenced
route. Statuses: implemented · integrated · tested · historically evaluated
· prospectively validated · authorized for production. Nothing here is
above "tested" except the orchestrator (authorized for production under
conditions). Engineering duration is stated where meaningful; **the
observations needed for evidence are stated separately and carry no
calendar promise.**

## 1. Component records

| Component | Existing code and actual callers | Responsibility / prohibited authority | Inputs → outputs | Dependencies | Missing implementation | Acceptance evidence | Activation gate |
|---|---|---|---|---|---|---|---|
| PULSE / Twin (state) | `apex/pulse/*`; callers `scripts/pulse*`, `runtime_v1.py`, mirrors | sense and seal; **no probabilities, no permissions** | vendor snapshot → sealed packet w/ per-field clocks | vendors | live collector commissioning; NKLA coverage; per-field availability (D1) | mirror consistency; prospective freshness stats | Phase-2 data gate |
| Twin (relationships) — NEW | none | sourced edges with time validity; **no inference** | sources → `Relationship` records | provenance store | interface + first sourced edge set (index/sector) | edges reproducible from sources; de-duplicated evidence ids | EXP-002 registration names it |
| Event Surprise — NEW | none; Catalyst extracts live facts (`apex/catalyst/`) | represent events + expectations with provenance; **no probability authority** | calendar + published expectation → `Event` | event corpus (to acquire) | corpus acquisition with publication time; eligibility; admission | boundary admission of the calendar; pre/post separation tests | dataset admission |
| Premarket Intelligence — NEW | PULSE fields; Catalyst | assemble overnight state; label PRIOR_SESSION options | PULSE packets → premarket state | PULSE commissioning | assembly layer; freshness clocks | engineering tests; prospective packet log | after PULSE live |
| Analogue Retrieval — NEW | EdgeForge causal analogs (shadow) | neighborhoods; **inform, not dictate** | state → `AnalogueSet` | admitted history | train-only representation; embargo; OOD flag | negative control: shuffled neighbors add nothing | registered use |
| World Model | `apex/world_model/*`, `exp001/*`; callers `exp001.run`, courts | calibrated conditional forecasts; **no trading authority** | admitted rows → `WorldModelForecast` | real-data boundary | real run of EXP-001 (train+validation); daily-horizon models for EXP-002 | DM-HAC on validation; N0 NO_SIGNAL; calibration | admission decision |
| Real-data boundary — NEW, this milestone | `apex/world_model/real_data/*`; caller `scripts/exp001_real_execute.py` | admit under bound decision; **grants nothing itself** | decision + manifest → `Grant` | admission key, admission root | key issuance (operator) | 26 negative controls; refusals on real proposal | decision issued |
| Multiverse | `nulls.py`, `worlds.py` (lab) | conditional joint paths; stress unweighted | forecast + state → paths | World Model | real-data path generator (C3) | tail coverage on sealed period | EXP-002 |
| Market-implied comparison | `apex/expression/engine.py`, `option_analytics/` | implied distribution, premium adjustment; **candidate, not proof** | chain snapshot → implied pmf | option chains admitted | daily-horizon estimator from per-minute chain (C6) | agreement with published implied moves; N0 | EXP-002 |
| Expression War | `economic_path.expressions` (stock), `expression_v2.py` (options, not wired) | full-lifecycle economics per structure | forecast + implied + chain → candidates | comparison | option structures w/ management policy + interim valuation | engineering path tests; Risk certifies option payload | EXP-002 economic stage |
| PRIME | `economic_path.prime_select` | select or CASH; **may not fund** | candidates → selection w/ rules fired | — | consume evidence maturity from registry | E3 layer-removal | registered |
| Arena | `apex/capital/arena.py` | FUND / PARTIAL / REFUSE | candidates + portfolio → allocation | — | multi-candidate exercise | 17 test files; E6 capacity | paper |
| Risk | `apex/organism/risk_certificate.py` | certify or refuse; **veto** | expression + payload → certificate | — | none for stock; option leg wiring in path | refuses stock-with-stop (tested) | — |
| Book | `apex/organism/book.py` | ledger of record; single funding site | env + action + kernel → funding/outcome | Risk | none | 57 test files | — |
| Execution boundary | `apex/execution/*` | ORDER_READY → human → sealed dispatch | intents → sealed | Book | none; keep sealed | AST unreachability | NOT_AUTHORIZED |
| Experience / attribution | `organism/experience.py`, `capital/counterfactual.py`, `economic_path.attach` | grade, calibrate, attribute; **no auto-rewrite** | forecast + outcome → attribution | Book | population-level attribution classes | E1–E6 | registered |
| Challenger learning | `CHALLENGER_REGISTER_V0.md` | registered challengers; promotion by human | register + results | Experience | — | repeated registered evidence | human decision |
| Dashboard | `scripts/apex_dashboard.py` (loopback) | read-only observability | artifacts → views | — | views 3–9 | source/timestamp/version/mode on every item | not a service |
| Orchestrator | `scripts/apex_orchestrator.py` R2–R4 | supervise; truthful launch states | roster → reconciliation | systemd | RTH evidence | commissioning (quiet period PASS) | authorized under conditions |

## 2. Sequenced route to the paper Predator

| Step | Content | Critical path? | Engineering duration | Evidence required (no calendar) |
|---|---|---|---|---|
| 1 Remaining operational and Phase-2 data gates | RTH commissioning artifact; options-paper hold stays; PULSE live collector; D1 per-field availability | yes (data) | days | RTH window observed; freshness measured over sessions |
| 2 Separate governed historical admission | **this milestone**: boundary + proposal; key issuance; decision for ETF/SPY; later decisions for chains and event calendar | **yes** | done (boundary); acquisition of the calendar: days | decision issued by the admission authority |
| 3 Chronological forecasting and sealed evaluation | EXP-001 real train+validation; if SIGNAL, separate unsealing decision; EXP-002 registration | yes | hours to run; registration: days | validation DM-HAC; N0; sealed evaluation consumed once |
| 4 Market comparison and expression economics | implied estimator (C6), option structures with management policy, Risk certification of legs | yes | 1–2 weeks | E1–E6 on sealed data; after-cost readouts |
| 5 Experience and challenger evaluation | attribution classes on a population; register activations | parallel after 3 | 1 week | repeated registered evidence |
| 6 Prospective forecasting and paper selection | sealed prospective forecasts; PRIME selection on paper; isolated ledger | after 4 | 1 week | ≥ 20 independent sessions before calibration is *reported*; more before it is *relied on* |
| 7 End-to-end adversarial commissioning | independent review of the full chain in paper mode; kill-switch and hold verification | last | days | adversarial review PASS with stated scope |

Safe to develop independently, without claiming downstream readiness:
Twin relationship interface, Event schema, implied estimator on already-
admitted chains (once admitted), option management-policy valuation,
dashboard views 3–9 in ENGINEERING mode, challenger C7 on EXP-001 outputs.

Critical path: **admission key → ETF decision → EXP-001 real
train/validation → event-calendar acquisition and admission → EXP-002
registration → implied estimator → option expression with Risk
certification → prospective paper selection.**

## 3. What is not on this route

Live brokerage, capital deployment, model promotion, hold removal, and any
real-data execution without an issued decision.

## 4. Addendum A components (added at `2af98967`; all SPECIFIED_NOT_IMPLEMENTED)

| Component | Existing code and actual callers | Responsibility / prohibited authority | Inputs → outputs | Dependencies | Missing implementation | Acceptance evidence | Activation gate |
|---|---|---|---|---|---|---|---|
| Latent-state estimate (A1) | none; `WorldModelForecast` uncertainty fields exist and are reused | infer latent state; **may never write the Twin**, holds no trading authority | Twin snapshot → `LATENT_STATE_ESTIMATE_V0` | admitted real data; a justified observation model | estimator, uncertainty representation, OOD measure | DM-HAC vs direct-feature comparator + state-shuffled control (C11) | a registered hypothesis naming the latent variable it improves |
| Uncertainty ownership (A2) | `nulls.py`, `worlds.py` (synthetic) | propagate uncertainty; **assigns no probabilities of its own** | weighted starting states + parameters → `MULTIVERSE_PATH_SET_V0` | a real-data forecast to start from | path generator, `simulation_error` vs `model_uncertainty` split, ensemble overlap measure | tail coverage on a sealed period; duplicate-member negative control (C12) | after a real-data World Model forecast exists |
| Predictability map (A3) | `grader`, `inference`, `holdout` | measure where skill exists; **`SELECTION_AUTHORITY: NONE`** | sealed scores → `PREDICTABILITY_MAP_ENTRY_V0` | ≥ 1 completed registered experiment | cell schema, registered grouping rules, search accounting | cells reproduce from sealed evidence; `INSUFFICIENT_EVIDENCE` where support is thin | ≥ 1 completed registered experiment with sealed scores |
| PRIME consumption of the map | `economic_path.prime_select` | use maturity/skill in selection | map + forecast → selection | the map | a *separately validated* selection rule | E3-style layer-removal on sealed data | the map exists **and** the selection rule passes its own validation |
| Information acquisition (A4) | PULSE field clocks and quality classes | propose acquisitions by decision value; **no purchasing, no browsing, no learned policy** | question → `INFORMATION_ACQUISITION_REQUEST_V0` | a decision worth informing | proposal queue, deterministic priority rule, missingness log | ≥ 10 recorded outcomes with decision-change scoring (C13) | the first acquisition question a human wants ordered |
| Attribution taxonomy (A5) | `organism/experience.py`, `capital/counterfactual.py` | separate causes of forecast error incl. "already represented" | forecast + outcome → attribution classes | a population of outcomes | the finer taxonomy | classes distinguishable on a population, not one outcome | after the first real-data experiment produces outcomes |
| Dashboard views 10–14 (A6) | `scripts/apex_dashboard.py` | display; read-only | artifacts → views | the above | five views | source/timestamp/version/mode on every item | when the underlying records exist; **not** restarted for this addendum |

**Critical path unchanged.** None of these is on it. The route to the first
interpretable historical result remains: operator setup → signed admission
decision → EXP-001B train+validation → evidence. Addendum A components are
developed only after that evidence exists, except where a registered
hypothesis names one earlier.

---

## 5. Recorded priorities (operator direction, 2026-09-08)

Recorded as **direction, not specification.** Nothing here is implemented,
scheduled, or permitted by being written down, and no model behaviour changed
when it was added. Where a priority needs detail before it can become work, that
is said rather than guessed.

### P1 — Options-only

The economic path is **options-only**. Equity expression is not pursued as the
route to an economic result.

- **Status:** recorded; not scheduled.
- **Not yet specified:** which underlyings, which structures, which horizon, and
  how this relates to the existing options paper-exploratory work. Those are the
  operator's to define; this entry does not assume them.
- **Bearing on the critical path:** none. EXP-001B is a price-only distributional
  experiment and is unaffected.

### P2 — Proprietary forecasting

Forecasting models are **built here**, not adopted from outside.

- **Status:** recorded; not scheduled.
- **Consequence already in force:** no external models are installed. The
  external-component work concluded with adoption of the smallest justified
  artifact and nothing else, and that stands.
- **Reconciliation (2026-09-09):** the blanket wording above is narrowed, not
  reversed. **External mathematical implementations and reference code may be
  considered through review; their availability confers no forecasting or
  trading authority.** Forecasting *claims* and economic *evidence* remain
  APEX's own, produced through registered experiments. Candidate references
  are recorded in `CHALLENGER_REGISTER_V0.md` under `CANDIDATE_NOT_ADOPTED`
  with pinned revisions; none is installed or wired in by that listing.
- **Not yet specified:** which model families, and what evidence would justify
  building each. The challenger register is the place that gets decided, one
  registered experiment at a time.

### P3 — Fusion is downstream only

Combining several forecasts or models is a **downstream challenger**, never a
primary build. It is entered in the challenger register as **C14** and inherits
that register's rules: listing is not permission, activation requires a
registered experiment naming it, and its dependency rows must be tested first.

**Critical path unchanged.** None of these three is on it. The route to the first
interpretable historical result is still: review the bounded-memory repair →
fresh signed admission → EXP-001B train+validation in a new run directory →
evidence.



### P5 — Reference-assisted enhancements (recorded 2026-09-09; none scheduled)

Each row is a candidate, not a plan. Reference: HKUDS/Vibe-Trading at
`a44ed6e807e6e7d0faeeff5b8f43df8c4694e2d1` (MIT), `CANDIDATE_NOT_ADOPTED`.

| Enhancement | Intended contribution | Required evidence before adoption |
|---|---|---|
| GARCH volatility challenger | test recursively evolving variance against the existing `rv_30` scale law **and a simple EWMA baseline** | a separate frozen comparison with correct intraday clocks, units and horizon aggregation. The reference's `agent/src/quantlib/volatility.py` is a **Heston** implementation, not GARCH/EWMA; no GARCH reference code is adopted from it |
| Options analytics references | Greeks, implied-volatility inversion, pricing benchmarks | independent numerical checks and **explicit exercise-style assumptions**; European pricing alone is insufficient for American-style SPY contracts. Reference: `agent/src/quantlib/options.py` (Black-Scholes-Merton `bs_price`, `bs_greeks`, `implied_volatility` via Newton with bisection fallback, `brentq`), `agent/backtest/engines/options_portfolio.py` (European; American via an early-exercise heuristic, BS-based) |
| Live research dashboard | data freshness, active runs, forecast distributions, comparisons, refusals, evidence maturity | every displayed value tied to an actual source and timestamp; unavailable values remain unavailable. Reference UI components exist (`frontend/src/components/charts/*`) but display objects that are not APEX's |
| Selected factor references | documented candidates and simpler comparators | one named hypothesis at a time, checked for duplication, admitted through APEX's research process. Reference zoo: `agent/src/factors/zoo/{academic,alpha101,gtja191,qlib158,fundamental}` (473 files); listing confers nothing |

Boundaries that travel with these entries:

- The inspected options engine generates **theoretical** option prices. Its simulated returns cannot substitute for evidence from executable historical quotes.
- Its regime labels (`agent/backtest/regime.py`: a causal trailing-smoothed hysteresis state machine on cross-asset correlation edge density) and its Monte Carlo (`agent/backtest/validation.py::monte_carlo_test`: **trade-PnL order permutation**) are different objects from APEX's information-at-time-*t* state estimates and conditional future-path simulations, and are not comparable to them.
