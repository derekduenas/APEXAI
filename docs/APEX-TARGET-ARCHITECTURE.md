# APEX Target Architecture — the canonical end state

The complete governed research operating system. This is the destination; the
gap to it is in `results/APEX-TARGET-ARCHITECTURE-AUDIT.md`. Every layer's
boundary is declared as data in `apex.governance.firewalls` and enforced by
`tests/test_architecture_firewalls.py` — **the boundary exists before the
engine, and arms the instant the engine's package appears.**

## The system, as one graph with allowed dependencies

```
                          ┌──────────────────────────────────────────────┐
   GOVERNANCE SUBSTRATE   │ credits · immutable ledger · screening ·      │
   (all layers run inside)│ registration · criteria · provenance ·       │
                          │ auditors · firewalls · holdout firewall      │
                          └──────────────────────────────────────────────┘

  DATA/PIT ─▶ UNIVERSE ─▶ FEATURE REGISTRY ─▶ FEATURE FACTORY ─▶ REDUNDANCY
                                                       │
                                                       ▼
                                                 DIGITAL TWIN  (PIT state @ T)
                                                       │
                                                       ▼
        DISCOVERY ── SWARM · NOVELTY · CAUSAL-CRITIQUE · HYPOTHESIS · NOTEBOOK
                                                       │
                                                       ▼
                                                  HUMAN GATE
                                                       │
                                                       ▼
                                           REJECT-ONLY SCREEN (in-sample)
                                                       │
                                                       ▼
                                          REGISTERED EXPERIMENT (credit debit)
                                                       │
                          ┌────────────────────────────┴───────────────┐
                          ▼   IN-SAMPLE RESEARCH (inside one experiment)│
                STATISTICS · CAUSAL · ML · REGIME · COMBINATION         │
                          └────────────────────────────┬───────────────┘
                                                       ▼
                                            LOCKED VALIDATION (one look)
                                                       │
                                     ┌─────────────────┴─────────────────┐
                                     │  VERDICT — the only credit gate     │
                                     └─────────────────┬─────────────────┘
                                                       ▼  (VALIDATED_ALPHA only)
        MONETISATION ── PORTFOLIO · RISK · COSTS · CAPACITY · BACKTEST · STRESS
                                                       │
                                                       ▼
                          PAPER ─▶ SHADOW ─▶ EXECUTION ─▶ LIVE MONITORING
                                                       │
                          ATTRIBUTION · DRIFT · DECAY · KILL/REVIEW
                                                       │
                                                       ▼
                        RESEARCH FEEDBACK ── a NEW dossier, provenance-stamped
```

**The firewall in one line:** information flows DOWN freely; it flows UP only as
a new, provenance-stamped hypothesis. Every upward edge that is not a
human-authored dossier is forbidden and mechanically blocked.

## Six-state classification of every component

**BUILT + CERTIFIED** — exists, tested, audited:
Data/PIT · Universe · Feature Registry · Feature Factory · Redundancy · Digital
Twin (v1) · Discovery · Novelty · Swarm · Hypothesis · Screening · Human Gate ·
Registration · Experiment · Credits · Immutable Ledger · Statistics (IC/NW/
decile/HAC-null) · Attribution (research) · Costs (decile turnover) · Auditors ·
**Firewalls (this turn)** · Provenance (fingerprints/hashes).

**UNDER CONSTRUCTION** — partially built:
Statistics (bootstrap/permutation null and reusable subperiod module remain) ·
Reproducibility (artifacts + git, no notebook system).

**PLANNED** — designed here, not implemented, boundary armed:
Causal · ML · Regime · Combination-as-experiment · Portfolio · Risk · Capacity ·
Backtest · Stress · Paper · Shadow · Execution · Monitoring · Drift.

**DATA GAP** — cannot be built with current vendor data:
Event/announcement features (filing dates only) · Sentiment/attention ·
Positioning/short-interest/13F · Analyst expectations · Full causal
identification (no instrument/shock).

**FORBIDDEN** — must never exist:
Any upward edge from a lower layer that selects research · a broker influencing
strategy choice · an optimiser over validation/holdout · a model that fits
before its governance · a second governance framework.

**ABSENT (correctly, premature)** — no slot yet:
Model registry (nothing to register) · live broker adapter.

## Where each dangerous mechanism attaches (the critical principle, structural)

ML, causal claims, regime conditioning, and factor combinations are **research
mechanisms, not automatic downstream steps.** In `apex.governance.firewalls`,
each is a `LayerContract` with `is_new_hypothesis=True` and
`consumes_credit=True`. `test_every_contract_that_is_a_new_hypothesis_consumes_a_credit`
enforces that a layer producing a research claim must debit a credit — so a
validated factor **cannot** automatically become an ML model's training target,
a regime selector, or a portfolio optimiser's objective. That requires a new
governed hypothesis, by construction.

## The five per-layer governance documents

- `APEX-RESEARCH-ML-GOVERNANCE.md` — before the first `.fit()`
- `APEX-CAUSAL-GOVERNANCE.md` — association is not causation
- `APEX-PORTFOLIO-GOVERNANCE.md` — signal is not policy
- `APEX-BACKTEST-GOVERNANCE.md` — an evaluator, never an optimiser
- `APEX-LIVE-GOVERNANCE.md` — research → paper → shadow → live

Each specifies, for its layer: purpose · inputs · outputs · allowed deps ·
forbidden deps · governance boundary · provenance · what is a new hypothesis ·
what consumes a credit · what can never access the holdout · what can never
optimize · tests required before activation.
