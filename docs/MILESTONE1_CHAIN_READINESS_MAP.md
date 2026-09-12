# APEX full-chain implementation and readiness map

Statuses are one of: **implemented · integrated · tested · historically
evaluated · prospectively validated · authorized for production**. They are
not interchangeable, and none below is higher than "tested". Sources are
inspected code and tests on `alpha-exp-001` at `dc321587` (chain modules are
byte-identical to the integration line except the chain primitive) and
`milestone1-r2` at `ec1bfc50`.

| Component | Implementation path | Actual callers (inspected) | Inputs → outputs | Tests | Evidence | Readiness | Missing work |
|---|---|---|---|---|---|---|---|
| **PULSE / Digital Market Twin** | `apex/pulse/{compose,twin,historical,observation,derived,anchors,anchor_freshness,freshness}.py` | `scripts/pulse*`, `apex/pulse/runtime_v1.py`, mirror runners | vendor snapshot → sealed `Field`-typed packet with per-field quality, `as_of`, `known_from` | 259 PULSE tests | PULSE-007→010 summaries; mirror: 5/5 comparable subjects consistent, coverage INCOMPLETE (NKLA) | **tested**; live collector **not commissioned** (D6) | prospective commissioning; NKLA coverage; per-field availability semantics (D1) |
| **Participant / exposure model** | none | — | — | — | — | **NOT_IMPLEMENTED** (deferred by mandate) | interface only when a registered hypothesis names what it improves |
| **World Model** | `apex/world_model/{forecast,inputs,features,targets,grader,inference,nulls,holdout,court_v1,sources,authority}.py` (WM branch) + `apex/world_model/exp001/{registration,bars,models,run}.py` | `exp001.run`, courts | admitted rows → `WorldModelForecast` (quantiles, tails, p_up, uncertainty) | lab courts (synthetic, closed `PASS_WITH_FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1`); EXP-001 13 tests | synthetic only | **tested (synthetic)**; real data **BLOCKED** at boundary | admission decision; real run |
| **Multiverse** | none as a path generator; `nulls.py` provides null worlds, `worlds.py` synthetic worlds | lab only | — | lab tests | synthetic | **NOT_IMPLEMENTED** for real-data path generation | simple defensible simulator that reproduces the forecast quantities it claims; deferred |
| **Market-implied / inverse engine** | `apex/expression/engine.py` (BS pricing, structures from a pmf + chain); `apex/option_analytics/` | expression consumers | pmf + option chain → structures | 7 test files | engineering | **implemented, not integrated into EXP-001** | 15-minute option-implied benchmark NOT_ESTIMABLE from sources on box; daily-horizon use possible with `history-a/options_history` |
| **Mispricing engine** | `exp001/run.py::_economic` + `economic_path.expressions` (forecast mean vs round-trip modelled spread) | EXP-001 | forecast → after-cost expected return per expression | in the 25 | engineering | **tested (engineering)** | no market-implied disagreement measure at 15m; model-disagreement and evidence-maturity fields present in forecast contract, not consumed |
| **Expression War** | `economic_path.expressions` (CASH/LONG/SHORT stock); `apex/expression/engine.py`, `apex/execution/expression_v2.py` (options; not wired) | EXP-001 path | forecast view → candidates with expected after-cost | in the 25 | engineering | **tested (stock only)** | option structures with defined max loss (the fundable class) — needs chain + leg-derived certification |
| **Execution simulator / fills** | `apex/predators/equities/day_trader.py::marketable_fill, size_shadow` | EXP-001 path, hunter | reference, direction → SIMULATED fill through modelled spread; sizing from executable loss at stop | day_trader tests + path tests (rejection, partial) | engineering | **tested**; fills labelled SIMULATED | latency, queue position (not fabricated), multi-leg risk, adverse selection: **unsupported, labelled** |
| **PRIME** | `economic_path.prime_select` (`PRIME_RULES_V0`) | EXP-001 path | forecast maturity, economics, uncertainty, feasibility → selection or CASH with rules fired | in the 25 | engineering | **tested** | consume evidence maturity from a real registry; no LLM authority (by construction) |
| **ARENA** | `apex/capital/arena.py::compete` | organism allocator, EXP-001 path | candidates + portfolio → FUND / PARTIAL / REFUSE with decomposed reasons | 17 test files | engineering + paper history | **tested** | shared-underlying/sector/scenario concentration present in code; not exercised with >1 candidate in EXP-001 |
| **Independent Risk** | `apex/organism/risk_certificate.py::certify` (`RISK_CERTIFICATE_V0`, `ECONOMIC_RISK_SEMANTICS_V1`) | book funding path, EXP-001 path | expression + payload → certificate: risk_class, certified max loss, authority | 2 test files + path tests | engineering | **tested**; authority preserved (stock-with-stop refused) | none for stock; option leg certification wiring for the funded path |
| **Execution boundary** | `apex/execution/{gateway,sealing,killswitch,mcp_transport,robinhood}.py` | Flight Deck (read), organism | intents → ORDER_READY, SEALED | existing | live placement SEALED | **not reachable from research path** (AST-verified) | none; keep sealed |
| **Book** | `apex/organism/book.py` (isolated ledger in research path) | organism, EXP-001 path | env + arena action + risk kernel → paper funding / refusal / outcome | 57 test files | paper history (canonical), engineering (isolated) | **tested**; isolated namespace | none |
| **Experience / attribution** | `apex/organism/{experience,calibration}.py`, `apex/capital/counterfactual.py`, `economic_path.attach` | organism, EXP-001 path | forecast + outcome → graded, calibrated, attributed | 27 + 7 + 2 files | engineering | **tested (engineering)** | attribution classes beyond single-outcome; real outcomes |
| **Discovery lab / courts** | `apex/world_model/{court_v1,court_v2,controls*,holdout}.py`, `courts/` | WM programme | seeds → verdicts | 4213 nodeids on WM line | synthetic acceptance court closed | **tested (synthetic)** | real-data null rig (Phase 3) BLOCKED |
| **Orchestrator (supervisor)** | `scripts/apex_orchestrator.py` R2–R4 | systemd | roster + phase → reconciliation, truthful launch states, bounded history | 52 tests | **commissioned in production** (quiet period); RTH observation pending | **authorized for production** under conditions | RTH-hours evidence; DRY_RUN attempt accounting |

## Registered evaluations to define (bounded; not run; not a tournament)

Each is a registered comparison with a frozen metric, a null, and an
economic readout; none may consume the sealed evaluation period more than
once.

| Evaluation | Compares | Held fixed | Primary metric | Null | Economic readout |
|---|---|---|---|---|---|
| E1 full strategy vs cash | EXP-001 path selecting per PRIME vs always-CASH | data, splits, costs | after-cost mean return, HAC SE | N0 outcome permutation | mean after-cost, z, capacity at 5% ADV |
| E2 full strategy vs simplest alternative | M1-driven path vs M0-driven path (zero-mean, so always CASH) | same | log-likelihood differential (DM-HAC) then E1 readout | N0 | difference in after-cost mean |
| E3 layer removal: PRIME | PRIME_RULES_V0 vs "select if expected_after_cost > 0" | forecast, costs | after-cost mean, turnover | N0 | cost fraction of gross |
| E4 layer removal: Risk | certified-only funding vs stop-defined funding (research observation only, never live) | same | realised max loss vs declared 1R | — | frequency of loss > declared 1R |
| E5 layer interaction: spread assumption | 2 bps vs 4 bps vs 8 bps modelled spread | forecast | after-cost mean per assumption | — | break-even spread |
| E6 capacity | target notional sweep through `assess_capacity` at SPY ADV | forecast, costs | expected gross after impact | — | capacity ceiling at declared participation |

Preconditions for any of E1–E6 on real data: the admission decision. All
six run today in engineering mode on synthetic fixtures and prove
integration only.

## Unsupported assumptions, stated

- Fills are a declared spread model; no observed bid/ask exists in the corpus.
- No queue position, latency, or adverse selection is modelled; none is fabricated.
- Option-implied benchmark at 15 minutes is not estimable from sources on box.
- The stock expression cannot be funded with certified authority; the funded class needs option structures not yet wired.
- Attribution from one outcome identifies at most one gross class; finer classes need a population of outcomes.
