# APEX Master Architecture

The canonical blueprint for the whole machine: data → discovery → validation →
monetisation → deployment. This is the TARGET. What is built today, and what is
merely planned, is reconciled in `results/APEX-MASTER-ARCHITECTURE-AUDIT.md`.

## What the finished system is for

Not "find factors." The complete loop:

```
OBSERVE ─ the PIT data and feature state at each date
  → UNDERSTAND ─ what each feature means economically
  → HYPOTHESISE ─ a mechanism, stated before any test
  → SCREEN ─ reject cheap non-starters, in-sample, reject-only
  → REGISTER ─ a signed, credit-consuming commitment
  → TEST ─ one honest validation look
  → REPLICATE ─ non-overlapping / subperiod robustness
  → UNDERSTAND CAUSALLY ─ placebo / neutralised re-test
  → MODEL NONLINEARITY ─ ML, as a governed experiment
  → CONDITION ON REGIME ─ regime-conditioned hypotheses
  → CONSTRUCT PORTFOLIO ─ sizing, neutralisation, limits
  → BACKTEST REALISTICALLY ─ costs, borrow, capacity, turnover
  → PAPER TRADE
  → DEPLOY
  → MONITOR ─ live vs backtest, drift
  → ATTRIBUTE ─ realised return decomposition
  → DETECT DECAY
  → GENERATE THE NEXT RESEARCH QUESTION ─ as a new dossier, with provenance
```

The goal is progressive skill at **finding real, reproducible, economically
defensible alpha and rejecting seductive false positives** — then, only for what
survives, turning it into a realistic portfolio. No architecture guarantees
profit; this one guarantees that a false positive is expensive to manufacture.

## The five layers and their firewall

```
┌─ LAYER 0  GOVERNANCE SUBSTRATE ─────────────────────────────────┐
│  credits · immutable ledger · screening · registration ·        │
│  success criteria · contamination controls · auditors           │
│  (everything below runs INSIDE these rules)                     │
└─────────────────────────────────────────────────────────────────┘
LAYER 1  RESEARCH SUBSTRATE
   data(PIT) → universe → feature registry/factory → redundancy/PIT
   → Digital Twin → discovery{ swarm · novelty · causal-critique · dossier }
   → HUMAN GATE
LAYER 2  ALPHA DISCOVERY  (each item consumes a credit)
   reject-only screen → registered experiment → LOCKED validation
   → statistics{ IC · NW-t · null(HAC+bootstrap) · decile · attribution
                 · subperiod · concentration }
   → causal robustness → [ML as governed experiment] → [regime-conditioned]
LAYER 3  PORTFOLIO MONETISATION  (only for VALIDATED alpha)
   sizing → neutralisation(sector/beta) → cost/borrow/turnover
   → capacity → risk/drawdown/tail → realistic backtest
LAYER 4  DEPLOYMENT
   paper → execution → live monitoring → realised attribution → decay
   → (feedback) a NEW research question
```

**The firewall, stated once:** information flows DOWN through the layers freely,
and UP only as a new, provenance-stamped dossier. A lower layer's convenience
(a broker's available symbols, a backtest's favourite parameter, a live model's
drift) may never reach up to *select* research. That single rule is what keeps a
trading system from quietly becoming a curve-fit.

## Non-negotiable invariants (true at every layer)

1. **PIT or nothing.** No stage may use information unknowable at its formation
   date. Enforced by `known_from`, the lookahead auditor, and the twin's
   refuse-don't-drop rule.
2. **A credit prices a comparison.** Every confirmatory test — factor, ML model,
   regime split, causal claim — consumes a credit and is pre-registered. The
   number of things tried is always counted (file-drawer rule).
3. **Discovery cannot register; execution cannot research.** The top boundary
   (`assert_not_auto_registerable`) and the bottom boundary (execution consumes
   weights, emits fills) are mechanical, not cultural.
4. **A screening or diagnostic result is never evidence** for the hypothesis it
   describes (S13). Robustness diagnostics inform interpretation, never
   selection.
5. **A failed result cannot choose its successor.** Provenance epochs;
   descendants of a failure require independent re-justification at the human
   gate.
6. **The lifecycle is honest.** FEATURE → DISCOVERY_CANDIDATE →
   SCREENED_CANDIDATE → REGISTERED_EXPERIMENT → VALIDATED_ALPHA / FAILED /
   DEPRECATED. A feature is not an alpha because it exists; a validated factor is
   not money until Layer 3 says it is monetisable.

## Where the dangerous layers attach

- **ML** attaches at Layer 2 as a *hypothesis*, not at a mystical "model layer"
  after validation. A model is a credit-governed experiment with stricter
  leakage controls; its governance must be written before its first `.fit()`.
- **Regime conditioning** attaches at Layer 2 as a *new hypothesis class*, not
  as a free refinement of a validated factor.
- **Causal analysis** attaches twice: as a discovery critique (Layer 1) and as a
  post-validation robustness question (Layer 2). Our data supports placebo and
  neutralised re-tests only — not full identification.
- **Portfolio / backtest / risk** attach at Layer 3, gated on a validated alpha.
- **Execution / monitoring** attach at Layer 4, gated on a monetisable backtest.

## Status at a glance

Layer 0: **built + certified.** Layer 1: **~90% built** (causal critique and a
reproducibility harness remain). Layer 2: **statistics built; ML/regime/causal/
bootstrap planned.** Layers 3–4: **absent, correctly deferred.** Full detail,
per component, in the audit document.
