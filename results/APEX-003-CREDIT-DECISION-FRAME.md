# APEX-003 Credit Decision Frame — H1 vs H3

**Date:** 2026-08-12 · **credits 2/5 · holdout SEALED · APEX-003 does not exist**
No validation, no holdout, no IC for a new experiment, no selection. This
document formalises two candidates and states the decision RULE. It does not
choose.

Both candidates formalise through the certified discovery system (stable dossier
hash, NOVEL, no APEX-001/002 contamination — epoch BEFORE_002):

```
H1  dossier 4104a238ef09  NOVEL  {prof_gross_profitability}
H3  dossier b4c4873c3abb  NOVEL  {val_book_to_market, prof_gross_profitability}
```

## Part 1 — the two formalised experiments

| | **H1 — gross profitability** | **H3 — quality-conditioned value** |
|---|---|---|
| Feature(s) | `prof_gross_profitability` | `val_book_to_market` + `prof_gross_profitability` |
| Ranking | ascending cross-sectional, equal-count deciles | rank composite, **equal pre-committed weight** |
| Universe | frozen §3 (unchanged) | frozen §3 (unchanged) |
| Horizon | 20 trading days | 20 trading days |
| IC definition | daily Spearman IC, Newey-West (Bartlett-25) — inherited | same |
| Success criteria | **§13 as-is**: mean IC positive, t ≥ 2.92 (validation), robustness agrees in sign | same |
| Falsification | IC not reliably positive at the hurdle | IC not positive **OR** composite fails to exceed either leg in sign |

**Confirmed for both:** no contamination (both from literature predating #001/#002); no tuning freedom (single ranked ratio / equal-weight composite, no parameter to select); reproducibility hash stable across reconstruction; §13 thresholds reused verbatim, not re-derived.

## Part 2 — side-by-side (no scores, no recommendation)

| Dimension | H1 | H3 |
|---|---|---|
| **Mechanism clarity** | Highest — one clean productivity ratio, one citation (Novy-Marx) | High but composite — two mechanisms, a joint claim |
| **Orthogonality to existing signals** | Feature audit: profitability orthogonal to the momentum block and to NSI | Both legs near-orthogonal to each other and to momentum/NSI; the composite is a genuine recombination |
| **Data coverage (as-filed ARQ)** | `gp` 96.9%, `assets` 100% | + `equity` 100%, price for B/M — all high |
| **Risk of known decay** | Documented post-2010 quality underperformance (adversary, unrebutted) | Value's long drawdown 2017–2020; quality-value more robust than either alone, but 2 decayed inputs |
| **Interpretability** | Cleanest — "productive firms are underpriced" | Strong — "cheap-and-good beats cheap-and-failing" — but composite-attribution risk (which leg?) |
| **Falsifiability** | Single criterion | Stricter: must beat both legs in sign — a harder, more informative test |
| **Monetisation profile (a priori, NOT measured)** | Low turnover (quarterly fundamentals), wide breadth → likely survives costs | Same turnover profile; composite may concentrate slightly |

## Part 3 — economic viability, DECLARED before use

Statistical validity (§13) says the signal is real. **Economic viability** — a
separate, pre-registered gate — asks whether the real signal is worth trading.
Thresholds (`apex/portfolio/viability.py`, fixed and conservative):

| Gate | Threshold |
|---|---|
| Minimum net annualised decile spread | **≥ 2%** |
| Maximum monthly turnover | **≤ 50%** |
| Maximum gross→net degradation | **≤ 60%** (net retains ≥ 40% of gross) |
| Minimum median breadth | **≥ 400 names** |

The minimal evaluator (`apex/portfolio/projection.py`) applies a FIXED policy —
long top decile / short bottom / equal weight / monthly rebalance — with
conservative fixed costs (20 bps one-way, 30% monthly turnover default). It is
an evaluator: no tuning, no policy search, no ML, no selection. **It has not
been run on either candidate** — that needs their forward returns, which is the
one paid validation look. It is exercised only on a factor already `VALIDATED_ALPHA`.

## Part 4 — the decision rule (explicit; not auto-applied)

Both are scientifically clean and NOVEL. The rule reflects a genuine trade-off,
not a score:

```
CHOOSE H1 (gross profitability) IF you prioritise:
  - the cleanest single mechanism and simplest falsification
  - one input, one citation, minimal composite-attribution risk
  - the fastest, most interpretable first VALIDATED_ALPHA to unblock monetisation
  AND you accept the documented post-2010 quality-decay risk as an
  interpretive caution, not a disqualifier.

CHOOSE H3 (quality-conditioned value) IF you prioritise:
  - exercising the multi-mechanism library the whole system was built for
  - a stricter, more informative falsification (must beat BOTH legs in sign)
  - a signal whose two legs are individually decayed but jointly more robust
  AND you accept composite-attribution ambiguity (which leg carries it) as the
  price of testing a combination.
```

**Tie-breaker toward the objective:** if the immediate goal is a *first*
validated alpha to unblock the monetisation layer (portfolio → backtest →
capacity), **H1 is the lower-variance path** — one mechanism, cleanest read,
least that can go ambiguous. If the goal is to prove the *combination thesis*
that justifies the 23-feature library, **H3 is the higher-value bet** at higher
interpretive cost.

I am not choosing. Both dossiers are ready to register the moment you do.

## Hard constraints honoured

No validation, no holdout, no new-experiment IC, no full backtester, no ML, no
regime conditioning, no optimisation, no credit spent, no candidate selected.
