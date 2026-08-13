# APEX Research Engine — the reusable substrate

The deterministic, governed machinery that lets the three remaining credits be
spent intelligently. Every engine below EVALUATES a declared question and is
structurally incapable of searching, selecting, or optimising.

## Dependency graph (what is BUILT this turn, in bold)

```
                    ┌──────────── GOVERNANCE SUBSTRATE (firewalls, ledger, screen) ┐
                    │                                                              │
 DATA/PIT ─▶ FEATURES ─▶ DIGITAL TWIN ─▶ DISCOVERY ─▶ HUMAN GATE ─▶ SCREEN ─▶ REGISTER
                                                                                  │
                                                                                  ▼
                                                                     REGISTERED EXPERIMENT
                                                                                  │
   ┌──────────────────────────── in-sample research (inside one experiment) ─────┤
   │  **STATISTICS: IC/NW  +  block bootstrap  +  block permutation  +           │
   │               subperiod  +  multiple-comparison denominator**  (apex.stats) │
   │  **CAUSAL claim object** (apex.causal) — refuses 'confirmed' w/o rung+placebo│
   │  **ML search accounting** (apex.ml)   — the file-drawer denominator, NO fit  │
   │  **REGIME assignment** (apex.regime)  — declared def, PIT-safe, no discovery │
   └──────────────────────────────────────────────────────────────────────────┬─┘
                                                                                ▼
                                                                     LOCKED VALIDATION
                                                                                │
   **RESEARCH MANIFEST** (apex.research.manifest) stamps every run with a       │
   content-addressed science_id: science ≠ provenance ≠ presentation.           │
                                                                                ▼
   [PLANNED, gated on a validated alpha] PORTFOLIO ▶ RISK ▶ BACKTEST ▶ PAPER ▶ SHADOW ▶ LIVE
```

## The five engines built this turn

| Engine | Module | Evaluates | Cannot |
|---|---|---|---|
| Statistical robustness | `apex.stats.robustness` | a declared series + block size + scheme | return a 'best' block size / subperiod / method |
| Research manifest | `apex.research.manifest` | one run's scientific identity | let a presentation edit change `science_id` |
| ML search accounting | `apex.ml.search_ledger` | how many model specs were tried | name a winner (`select_best` refuses); fit a model |
| Causal claim | `apex.causal.claim` | a claim's rung + assumptions + placebo | emit 'confirmed' from significance; fake IV/RDD/DiD |
| Regime assignment | `apex.regime.engine` | a declared regime definition over PIT state | discover the best-performing regime |

## The one property they share

None has a `select_best`, `argmax`, `optimise`, `search`, or `tune`. A test
asserts the absence for each. The engines produce EVIDENCE; turning evidence
into a choice (best model, best regime, best subperiod) is a new hypothesis that
consumes a credit and passes the firewall — enforced by
`apex.governance.firewalls` and `tests/test_architecture_firewalls.py`.

## Autocorrelation is respected

The stats engine never treats 987 overlapping daily ICs as 987 independent
draws. The moving-block bootstrap resamples blocks; the permutation flips signs
on whole blocks. Both preserve the MA(19)-ish dependence that overlapping 20-day
forward windows create — the same structure the existing HAC null accounts for.
