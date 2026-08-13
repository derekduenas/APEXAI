# APEX-003 Registration Summary — H1 vs H3 (pre-registered, not registered)

**Date:** 2026-08-12 · **credits 2/5 · holdout SEALED · APEX-003 not registered**
No validation, no holdout, no validation IC, no credit spent, no winner chosen.

Both candidates were taken through the **certified reject-only screen** on the
in-sample window (2005-01-01 .. 2017-12-31) and both **SURVIVED**. Full packets
in `results/003_registration_packets.json`; screen log in
`results/screen_log.jsonl` (tamper-evident, chain verified).

```
screen log: 2 screens · 0 rejected · 2 survived · 2 distinct dossiers
  SURVIVE  APEX-003-H1 gross profitability        97da989ad49a
  SURVIVE  APEX-003-H3 quality-conditioned value  123f67fa844d
```

**Survival ground (both):** PIT-safe fundamental feature(s), coverage confirmed,
economic rationale present, not redundant with a closed experiment. **Survival
was on economic and data grounds — no in-sample performance was computed or
used** (that would contaminate the paid validation look).

## Registration packets, side by side

| | **H1 — gross profitability** | **H3 — quality-conditioned value** |
|---|---|---|
| Features | `prof_gross_profitability` (gp ÷ assets) | `val_book_to_market` + `prof_gross_profitability` |
| Source fields | gp, assets (as-filed ARQ) | equity, price, gp, assets |
| Directionality | higher better | value higher better + quality higher better |
| Signal construction | single ascending rank, equal-count deciles | **equal pre-committed weight** rank composite |
| Portfolio policy | long top decile / short bottom / equal weight / monthly | identical |
| §13 success criteria | mean IC > 0, t ≥ 2.92, robustness agrees in sign | **identical (unchanged)** |
| Bootstrap / permutation | moving-block bootstrap + block sign-permutation | identical |
| Block size | **20** (matches 20-day forward overlap; declared, not searched) | 20 |
| Subperiod diagnostics | calendar_year, calendar_quarter (diagnostic only) | identical |
| Falsification | IC not reliably positive at the hurdle | IC not positive **OR** fails to beat either leg in sign |
| Contamination | epoch BEFORE_002; descendant-of-failure: **False** | same |

## The comparison the decision turns on

| Dimension | H1 | H3 |
|---|---|---|
| **Mechanism clarity** | Highest — one ratio, one citation | High — two mechanisms, a joint claim |
| **Degrees of freedom** | Minimal — one feature, no weight | One extra: the composite (fixed equal weight removes tuning, but two inputs) |
| **Falsification strength** | Single criterion | **Stronger** — must clear the hurdle AND beat both legs in sign |
| **Risk of ambiguous outcome** | Low — one number decides | Higher — a pass could be carried by one leg (composite-attribution ambiguity) |
| **Single vs multiple features** | Single | Multiple (the recombination the library exists to test) |

## Reading the trade-off

- **H1** minimises degrees of freedom and ambiguity: the cleanest, lowest-variance
  path to a first `VALIDATED_ALPHA`, which is the input every PLANNED monetisation
  component waits on.
- **H3** has the *stronger falsification* — its "must beat both legs" clause makes
  a pass more informative — but a higher risk of an ambiguous read (which leg
  carried it), and it tests the combination thesis the 23-feature library was
  built for.

Both are audit-ready. Registering either is the single explicit decision that
spends Credit 3 — a signed human act the machine does not take. I have not
chosen.

## What was NOT done

No validation run · no holdout access · no validation IC · no full backtest ·
no ML · no regime conditioning · no optimisation · no credit spent · no winner
selected. The research ledger is unchanged at 6 entries; `config/experiment.yaml`
still names no APEX-003.
