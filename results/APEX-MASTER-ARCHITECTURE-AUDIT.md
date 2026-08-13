# APEX Master Architecture Audit

**Date:** 2026-08-12 · commit `5ed29c8` · **credits 2/5 · holdout SEALED**
**Nothing modified.** No experiment, credit, screen, IC, backtest, or holdout
access. This is a reconciliation, not a build.

The brutally honest one-line summary: **APEX is a certified factor-VALIDATION
engine with a certified research-DISCOVERY front end. It is not yet an alpha
MONETISATION system, and four of the layers the eventual machine needs —
causal, ML, portfolio/backtest, execution/monitoring — are ABSENT, not merely
uncertified.**

---

## 1. Current-state inventory

Grounded in `find apex -name '*.py'` (57 modules, 11,280 lines) and per-module
inspection. Every claim below was checked against the source, not memory.

### Data / PIT infrastructure — BUILT + CERTIFIED
`data/snapshot_loader.py`, `production_source.py`, `sharadar_api.py`,
`nsi.py` (as-filed `known_from`), `universe.py`, `calendar.py`.
PIT via filing dates; dataset fingerprint on every result; survivorship-safe
(delisted retained); corporate actions classified; `MANIFEST.json` per snapshot.
Dev adapters (`edgar.py`, `stooq.py`) quarantined by `dev/namespace.py`.

### Feature architecture — BUILT + CERTIFIED
`features/registry.py` (23 canonical FeatureSpecs, lifecycle states),
`factory.py` (14 PIT-safe builders), `redundancy.py` (structural + empirical),
`pit_validation.py`, `composite.py` (#001), `nsi_scores.py` (#002).
The f1/f4 rank-identity was found by this machinery.

### Research discovery — BUILT + CERTIFIED
`research/hypothesis.py` (dossier wraps the certified screening `Dossier`),
`novelty.py`, `twin.py` (Digital Twin), `swarm.py` (8 roles), `gate.py`
(human gate). Contamination epochs, provenance, disagreement preserved.

### Screening — BUILT + CERTIFIED
`governance/screening.py`, S1–S13, reject-only, tamper-evident log, structurally
barred from the evaluation path.

### Governance / ledger — BUILT + CERTIFIED
`governance/ledger.py` (hash-chained, external anchor, annulment),
`registration.py` (signing, protocol pin, unlock tokens), `evaluate/criteria.py`
(per-experiment success criteria). 39 audited guards.

### Statistical research — BUILT + CERTIFIED (with named gaps)
`evaluate/ic.py` (Spearman IC, Newey-West HAC), `deciles.py` (equal-count,
orientation-aware), `reference.py` (simulated HAC null, dispersion null),
`report/attribution.py` (§9 sector attribution), `evaluate/turnover.py`
(drift-aware turnover + per-side cost).
**Present:** IC, rank IC, Newey-West t, decile spread, HAC null simulation,
subperiod/concentration (done ad hoc in the #002 post-mortem), sector attribution.
**ABSENT as certified stages:** bootstrap and permutation nulls (only the HAC
*dispersion* reference exists); subperiod/breadth/concentration as a REUSABLE
certified module (the post-mortem computed them in a one-off script).

### Audit infrastructure — BUILT + CERTIFIED
`audit/lookahead.py` (black-box future-perturbation), `cross_sectional.py`
(row-destruction), `execution_path.py` (import-closure isolation).

### Causal research — **ABSENT**
`grep -rli 'causal|dag|confound|mediation|treatment' apex/` → **0 files.**
No event study, placebo, or quasi-experimental capability.

### Machine learning — **ABSENT**
`grep -rli 'sklearn|xgboost|lightgbm|torch|random.forest|walk.forward|nested'`
→ **0 files.** No models, no CV, no feature selection, no model registry.

### Regime / market state — **ARCHITECTURALLY PLANNED, reporting-only**
`config/experiment.yaml §regimes` defines trend-SMA / VIX / vol-tercile for B5
*reporting*. There is no regime ENGINE, no detection, no regime-conditioned
alpha. The seven `grep regime` hits are config consumers and the swarm's
regime ROLE — not an implementation.

### Portfolio construction — **ABSENT**
No optimiser, sizing, neutralisation, or exposure control. `turnover.py` costs a
decile long-short SPREAD; it does not construct a portfolio.

### Backtesting — **PARTIAL / ABSENT**
`turnover.py` gives net decile-spread after per-side costs — a costed research
statistic, not a portfolio simulation. No walk-forward, no capacity, no
borrow-cost model (borrow is documented as a known omission).

### Risk — **ABSENT**
No factor risk, beta, drawdown, tail, stress, or exposure limits.

### Execution — **ABSENT** (correctly — must be downstream)
No broker, OMS, MCP, paper or live trading.

### Monitoring / attribution — **PARTIAL**
`report/attribution.py` is *research* attribution (which sector drove a decile
spread). No realised/live attribution, no drift detection, no live-vs-backtest.

### Research infrastructure — **PARTIAL**
`results/*.md` artifacts, git provenance, dataset fingerprints, config hashing.
No notebook system, no experiment-tracking UI, no model artifact registry.

---

## 2. Complete architecture map (the corrected dependency graph)

The prompt's linear chain is *almost* right but collapses two distinctions the
governance design depends on. The real graph forks after validation:

```
RAW DATA
  → PIT DATA LAYER  ── dataset fingerprint, known_from
  → UNIVERSE / ELIGIBILITY  ── §3 filters, survivorship
  → FEATURE REGISTRY + FACTORY
  → FEATURE VALIDATION / REDUNDANCY / PIT VALIDATION
  → DIGITAL TWIN  (deterministic PIT state at T)
  → RESEARCH DISCOVERY  { swarm · novelty · [CAUSAL: absent] · dossier · [notebook: partial] }
  → HUMAN GATE
  → REJECT-ONLY SCREEN            ── in-sample only; reject-only; logged
  → REGISTERED EXPERIMENT         ── signed; credit debited
  → LOCKED VALIDATION
  → STATISTICAL VALIDATION  { IC · NW-t · null · decile · attribution · [bootstrap/subperiod: partial] }
       │
       ├─────────────► (VERDICT: pass/fail)  ── the ONLY output that gates a credit
       │
       ▼  [everything below is ABSENT and is POST-validation, never a gate on it]
  [ML / NONLINEAR DISCOVERY]      ── absent; must be credit-governed like any experiment
  [REGIME ANALYSIS]               ── planned; reporting-only today
  [PORTFOLIO CONSTRUCTION]        ── absent
  [BACKTEST · RISK · CAPACITY · COSTS]  ── partial (decile costing only)
  [PAPER TRADING]                 ── absent
  [EXECUTION]                     ── absent
  [LIVE MONITORING · REALISED ATTRIBUTION · DECAY]  ── absent
  → RESEARCH FEEDBACK  ── the only edge that may re-enter discovery, and ONLY
                          as a NEW dossier with declared provenance (Part 7
                          contamination control), never as a silent tuning loop
```

**The load-bearing correction:** the prompt draws validation → ML → regime →
portfolio as a straight pipeline. Architecturally, ML and regime-conditioning
are NOT downstream refinements of a validated factor — they are *new
hypotheses* that each consume a credit and pass the same governance. Drawing
them as a free post-validation pipeline is exactly how a validation engine
turns into a hyperparameter search. See §6.

---

## 3. Built / planned / absent classification

| Component | State |
|---|---|
| PIT data, universe, survivorship, corporate actions | **A — built + certified** |
| Feature registry / factory / redundancy / PIT validation | **A** |
| Digital Twin | **A** |
| Swarm, novelty, contamination, hypothesis dossier, human gate | **A** |
| Reject-only screening, credits, immutable ledger | **A** |
| IC, Newey-West, decile, HAC null, sector attribution | **A** |
| Lookahead / cross-sectional / execution-path auditors | **A** |
| Turnover + per-side transaction cost | **A** (decile-spread scope only) |
| Bootstrap / permutation null | **C — planned; only HAC dispersion null exists** |
| Subperiod / breadth / concentration as reusable stage | **B → C — done ad hoc, not a certified module** |
| Regime engine / regime-conditioned alpha | **C — reporting config only** |
| Research notebook / reproducibility harness | **B/C — artifacts + git, no system** |
| Causal inference | **C — absent, belongs in the plan** |
| Machine learning | **C — absent, belongs in the plan** |
| Portfolio construction | **C — absent** |
| Backtest (portfolio simulation) / capacity / borrow | **C — absent** |
| Risk model | **C — absent** |
| Execution / broker / paper trading | **C — absent (correctly downstream)** |
| Live monitoring / realised attribution / drift | **C — absent** |
| Model registry / artifact hashing for models | **D — no models exist to register yet** |

No component is class **D-by-omission** except the model registry, which is
genuinely premature (nothing to register). Everything else discussed is either
built or explicitly planned below.

---

## 4. Dependency graph — what may cross each boundary

| Boundary | May cross | Prohibited | Enforced today? |
|---|---|---|---|
| PIT → feature | data with `known_from ≤ T` | any post-T value | **yes** (lookahead auditor, twin) |
| feature → discovery | feature definitions, redundancy | forward returns | **yes** (discovery imports no returns) |
| discovery → screen | a frozen dossier | a score, a ranking | **yes** (S4/S7 types) |
| screen → registration | SURVIVE eligibility | the screen verdict as evidence | **yes** (S13 import isolation) |
| registration → validation | signed protocol + credit | an unregistered id | **yes** (registration gates) |
| validation → verdict | IC/t vs registered criteria | a screening or discovery signal | **yes** (criteria layer) |
| **validation → ML/regime/portfolio** | **a validated factor's DEFINITION** | **its validation statistics as a tuning target** | **NO — layers absent; boundary undefined** |
| portfolio → execution | approved target weights | broker availability influencing selection | **N/A — both absent** |
| monitoring → discovery | decay as a NEW dossier | silent re-fit of a live model | **N/A — absent** |

**The one unguarded boundary that matters now:** validation → (future ML /
regime / portfolio). It is undefined because those layers do not exist. Before
any of them is built, this boundary needs the same mechanical enforcement the
screen→registration boundary has, or the credit system is bypassable.

---

## 5. Governance boundaries (what already holds)

- **credits count experiments, not runs** (CONVENTIONS A-003); annulment is
  append-only.
- **screening cannot become evidence** (S13, import-isolation tested).
- **discovery cannot register or spend** (`assert_not_auto_registerable`).
- **a failed result cannot select its successor** (provenance epochs).
- **success criteria are per-experiment and registered**, never hardcoded
  (INCIDENT-001 D3 fix).
- **the holdout opens only on a recorded validation PASS**, one look, ever.

These five are the substrate the whole plan rests on. Nothing below may weaken
them.

## 6. ML architecture (design, not implementation)

ML is the single most dangerous addition, because an unconstrained model IS a
hyperparameter search, and the entire credit system exists to price search.
The design principle:

> **A machine-learned signal is a hypothesis. It consumes a credit. It obeys
> every rule a single-factor hypothesis obeys, plus stricter leakage controls.**

**Where it sits:** ML is NOT a post-validation refinement layer. An ML model
over the feature library is a *discovery-layer hypothesis* that produces a
dossier (features used, model class, why the nonlinearity is economically
plausible), passes novelty + human gate + reject-only screen, and is registered
as a credit-consuming experiment before it ever sees validation data.

**Governance ML must obey:**
- **temporal boundary:** train only on in-sample; validation and holdout are
  as locked for a model as for a factor.
- **nested walk-forward within in-sample:** all hyperparameter and model
  selection happens inside the in-sample fold, never touching validation.
- **model selection IS multiple testing:** every model family tried is a
  comparison; the number tried is logged like screen rejections (file-drawer).
- **a fixed, pre-registered model spec per credit:** the registered dossier
  names the model class, features, and CV scheme; changing any of them after
  seeing validation is a new dossier (Part 9 iteration rule).
- **leakage detection is mandatory, not optional:** cross-sectional leakage
  (a feature that peeks across names on the same date) and temporal leakage
  (a feature knowable only later) both get auditors, reusing `lookahead.py`
  and `cross_sectional.py`.
- **interpretability is a gate, not a nicety:** an uninterpretable model that
  passes validation is a *result*, but the human gate must record why the
  nonlinearity is economically defensible, or it is contamination waiting to
  happen.

**Foundational interface needed now (small):** none. ML requires no code today.
It requires this governance to be written into the protocol BEFORE the first
model, so ML enters as a governed experiment and not as a `.fit()` someone runs
on a Tuesday.

## 7. Digital Twin architecture (placement)

The twin already exists and is correctly placed: a deterministic, versioned,
PIT-guarded state at date T. Its **minimum canonical state** today is
{eligible set, feature values, knowability dates, dataset fingerprint}. The
architecture reserves, but does NOT yet build, additional twin facets:

- **market state** (index level, breadth) — needed by regime analysis
- **regime state** — needed by regime-conditioned alpha
- **portfolio state** — needed by backtest replay
- **model state** — needed by ML reproducibility

Each is a new versioned field on a future `TwinState`, gated by the same
`assert_no_future_leak`. The rule that never changes: **a twin at T contains
nothing unknowable at T, and refuses rather than silently drops.**

## 8. Swarm architecture (placement)

The swarm sits BEFORE the human gate and produces records, never experiments.
Its correct role — and the one guardrail that matters — is that it contributes
*reasoning*, not *selection*: economic mechanism, adversarial challenge,
replication, and (once built) causal and regime critique. It must never become
"generate N strategies, keep the best" — enforced today by the absence of any
numeric field on `RoleView` and the requirement that assembly include the
adversary and replication roles. The gap: the swarm's causal and ML critique
roles have contracts but no methods behind them (see §9, §6).

## 9. Causal architecture (design)

Causal analysis belongs in **two** places, for different questions:

1. **Upstream of registration (discovery):** a causal CRITIQUE — does the
   proposed mechanism have a plausible DAG, or is the feature a collider /
   confounded proxy? This is the swarm's causal role, today a contract without
   a method.
2. **Downstream of predictive evidence (post-validation):** an event study or
   placebo test that asks whether a validated predictive relationship is
   plausibly *causal* rather than a stable correlation. This is a NEW
   credit-governed question, not a free refinement.

**What our data actually supports:** the honest answer is *limited*. We have no
clean exogenous shocks, no announcement dates (SF1 gives filing dates), and no
instrument. Justifiable methods: **placebo tests** (does the signal "predict"
pre-formation returns it shouldn't?), **subperiod stability** as a weak
robustness proxy, and **sector/size-neutral re-tests** to rule out mechanical
confounds. Full causal identification (IV, diff-in-diff, RDD) is **not**
supported by this vendor's data and must not be pretended.

## 10. Portfolio / backtest architecture (design)

The question this layer answers — *"even if it predicts, can we monetise it?"* —
is downstream of a VALIDATED factor and must not influence validation. Correct
dependency: `validated alpha → portfolio construction → realistic backtest →
capacity/risk`. Today only decile-spread costing exists. The layer needs, in
order: position sizing → neutralisation (sector/beta) → turnover/cost/borrow →
capacity → drawdown/tail. **None may be built before there is a validated alpha
to monetise** — building it now is optimising a portfolio of nothing.

## 11. Execution architecture (design)

Strictly downstream, strictly a consumer. `research → validation → portfolio →
paper → execution`, never `broker availability → strategy selection`. Execution
consumes approved target weights and emits fills; it generates no hypotheses and
touches no research artifact. Not to be built until there is a paper-traded,
validated, monetisable portfolio — which is at least four layers away.

## 12. Monitoring / attribution architecture (design)

Two kinds exist conceptually and must not be conflated: **research attribution**
(built — which sector drove a decile spread) and **realised attribution**
(absent — did the live signal earn what the backtest promised). Live monitoring,
drift detection (feature/regime/performance), and live-vs-backtest divergence
are all deployment-era and absent. Their only feedback edge into research is as
a NEW dossier with declared provenance — never a silent re-fit.

## 13. Missing components (the honest gaps)

```
MISSING: Bootstrap / permutation null tests
WHY IT MATTERS: the HAC dispersion null covers estimator over-dispersion but not
  the finite-sample distribution of the IC itself; a second, assumption-light
  null strengthens every future verdict.
WHERE IT BELONGS: statistical validation, beside reference.py.
DEPENDENCIES: none — operates on the existing IC series.
GOVERNANCE: must be pre-registered per experiment; cannot be added after seeing
  a result to rescue it.
PRIORITY: Phase 2, high — cheap, and it hardens the credit-consuming stage.

MISSING: Reusable subperiod / breadth / concentration module
WHY IT MATTERS: the #002 post-mortem computed these in a throwaway script; the
  next experiment should get them from a certified module, not re-derive them.
WHERE IT BELONGS: statistical validation (post-verdict diagnostics).
DEPENDENCIES: none.
GOVERNANCE: diagnostic-only; must never feed back as hypothesis selection
  (the #002 breadth-contamination lesson).
PRIORITY: Phase 2, medium.

MISSING: Regime engine
WHY IT MATTERS: regime-conditioned alpha is a distinct, defensible mechanism
  class; today only B5 reporting exists.
WHERE IT BELONGS: a discovery-layer capability feeding regime-conditioned
  hypotheses, each a credit-governed experiment.
DEPENDENCIES: market-state twin facet (§7).
GOVERNANCE: a regime-conditioned signal is a NEW hypothesis, not a free
  refinement of a validated factor.
PRIORITY: Phase 2, medium — after the first fundamental factor is validated.

MISSING: Causal critique method (placebo / neutralised re-test)
WHY IT MATTERS: distinguishes a stable correlation from a plausibly causal one;
  cheap defence against seductive false positives.
WHERE IT BELONGS: §9 — discovery critique + post-validation robustness.
DEPENDENCIES: none for placebo; sector/size data (present) for neutralised tests.
GOVERNANCE: post-validation causal tests are new credit-governed questions.
PRIORITY: Phase 2, medium.

MISSING: ML governance (protocol text, not code)
WHY IT MATTERS: the moment a model is fit, the credit system is bypassable
  unless the rules in §6 are already law.
WHERE IT BELONGS: CONVENTIONS + a new ML protocol document.
DEPENDENCIES: none — it is governance, written before any model.
GOVERNANCE: it IS the governance.
PRIORITY: Phase 2, high — BEFORE the first model, not with it.

MISSING: Portfolio construction, risk, realistic backtest, capacity, borrow
WHY IT MATTERS: without them a validated factor is a research finding, not money.
WHERE IT BELONGS: Phase 3, downstream of a validated alpha.
DEPENDENCIES: at least one VALIDATED factor.
GOVERNANCE: must not influence validation.
PRIORITY: Phase 3 — do not start until a factor validates.

MISSING: Execution, paper trading, live monitoring, realised attribution, drift
WHY IT MATTERS: turning a monetisable portfolio into deployed capital, safely.
WHERE IT BELONGS: Phase 4.
DEPENDENCIES: a backtested, capacity-checked portfolio.
GOVERNANCE: strictly downstream; never influences research.
PRIORITY: Phase 4 — far downstream.

MISSING: Research notebook / reproducibility harness / experiment-tracking UI
WHY IT MATTERS: as experiment count grows, provenance-by-git-log stops scaling.
WHERE IT BELONGS: research infrastructure, cross-cutting.
DEPENDENCIES: none.
GOVERNANCE: read-only over the ledger; must not become a second source of truth.
PRIORITY: Phase 1/2, low-medium — useful, not blocking.
```

## 14. Recommended build order

**Phase 0 — Governance substrate — COMPLETE.** Ledger, credits, screening,
registration, auditors, criteria layer, contamination controls.

**Phase 1 — Research substrate — ~90% COMPLETE.** Feature library ✓, redundancy
✓, PIT ✓, Digital Twin ✓, discovery/swarm ✓. *Remaining:* causal critique
method (placebo), a reproducibility harness (low priority).

**Phase 2 — Alpha discovery — the current frontier.** In dependency order:
(a) bootstrap/permutation null [high, cheap, no deps];
(b) ML GOVERNANCE text [high, before any model];
(c) reusable subperiod/concentration diagnostics [medium];
(d) causal placebo/neutralised re-test [medium];
(e) regime engine [medium, needs market-state twin facet];
(f) ML implementation [only after (b), and as a credit-governed experiment].

**Phase 3 — Portfolio monetisation.** Only after ≥1 validated factor: sizing →
neutralisation → cost/borrow/capacity → risk/drawdown → realistic backtest.

**Phase 4 — Deployment.** Paper trading → execution → live monitoring →
realised attribution → drift detection → decay-driven new research questions.

## 15. Explicit list — do NOT build yet

- **ML models** (XGBoost/NN/ensembles) — governance text first, model second.
- **Portfolio optimiser / risk model** — no validated alpha to monetise.
- **Backtester / capacity / borrow model** — same.
- **Execution / broker / MCP / paper trading** — four layers downstream.
- **Live monitoring / drift / realised attribution** — deployment-era.
- **Model registry** — nothing to register.
- **Full causal identification (IV / diff-in-diff / RDD)** — data does not
  support it; would be pretending.

Building any of these now optimises a stage whose input does not yet exist.

## 16. Risks of architectural omission

1. **ML-as-search (highest).** If ML arrives before its governance, the credit
   system is silently bypassed and every prior control is moot. Mitigation:
   §6 governance is Phase-2 item (b), before any model.
2. **The validation→downstream boundary is undefined.** Today it is safe only
   because the downstream layers are absent. The moment ML/regime/portfolio
   exist, a validated factor's *statistics* could become a tuning target.
   Mitigation: define and mechanically enforce that boundary in the same commit
   that introduces the first downstream layer.
3. **Monetisation mistaken for validation.** A factor with a real IC can still
   be unmonetisable (capacity, borrow, turnover). Reporting a validated IC as
   "alpha" before Phase 3 would overstate the system. Mitigation: the lifecycle
   states (FEATURE → … → VALIDATED_ALPHA) already distinguish these; keep them.
4. **Post-mortem contamination creeping into Phase 2.** Regime and breadth work
   are exactly where "#002 found breadth → build breadth" would re-enter.
   Mitigation: provenance epochs already flag it; the human gate must honour it.
5. **Diagnostic feedback becoming selection.** Subperiod/concentration
   diagnostics must inform interpretation, never hypothesis choice — the same
   line the screen enforces. Mitigation: keep them post-verdict and
   descriptive.

---

**Bottom line for the three remaining credits.** The machine is scientifically
valid *for what it currently does*: it can discover an economically-grounded
hypothesis, refuse to let a failed result choose it, screen it reject-only,
register it against pre-committed criteria, and validate it once with honest
statistics. It is NOT yet able to tell you whether a validated factor is
*monetisable*, and it has no ML, causal, regime, portfolio, or execution
capability. None of that blocks spending a credit on a clean single-factor
hypothesis (H1/H3 from the candidate set). All of it blocks calling the result
"a trading system" — which is precisely the omission this audit exists to name.
