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
