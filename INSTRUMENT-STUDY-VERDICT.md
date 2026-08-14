# APEX-004 Instrument Study — Verdict: NO INSTRUMENT DECLARED

Date: 2026-08-14. Study: `scripts/instrument_study_004.py`,
artifact `results/004_instrument_study.json`. In-sample only (2005-2017),
candidate set frozen at SIX before any number was computed, all six reported.

## Result

| | Construction | Gross/yr | Measured turnover | Net/yr | Names |
|---|---|---|---|---|---|
| A | top-decile EW (the §9 baseline) | −0.33% | 28%/reb | **−1.49%** | 127 |
| B | top-3-deciles EW | +0.56% | 21%/reb | −0.33% | 381 |
| C | top-decile score-weighted | −0.33% | 27%/reb | −1.48% | 127 |
| D | A + hold-to-decile-3 banding | −0.77% | 14%/reb | −1.37% | 192 |
| E | B + hold-to-decile-5 banding | +1.02% | 14%/reb | +0.45% | 468 |
| F | top-30 concentrated EW | −0.70% | 32%/reb | −2.05% | 30 |

**None clears the declared 2% net viability bar. None is declared for
holdout.** The banding hypothesis was confirmed (turnover halves, D/E), but
the underlying long-only premium is too thin to matter.

## What this establishes, honestly

1. The validated signal (IC t=3.278) RANKS the small-cap cross-section; it
   does not deliver an economically meaningful long-only premium over the
   universe in any pre-specified construction on 13 years of in-sample data.
2. The validation period's +2.06%/yr top-decile excess was the optimistic
   draw, not the norm. In-sample the same construction was ~0.
3. The concentrated deployable sleeve (F) — the shape retail capital wants —
   is the WORST candidate. Concentration harvests the noisiest part of the
   ranking. This kills the "just hold the top 30" temptation with data.
4. A long-short instrument would harvest the ranking from both sides, but is
   out of reach at current capital (borrow unmodelled, declared out of scope).

## Consequences

- **Credit 5 stays sealed.** Spending it on the 004 holdout with a baseline
  instrument that is already uneconomic would buy scientific confirmation
  and zero profit. Holding it is reversible; spending it is not.
- **The study may not be extended.** Denominator recorded = 6. Any further
  instrument search on this signal is a new study with a new recorded
  denominator, and the operator should treat a request for one as a red flag.
- **The free out-of-sample machine is the live lake.** Every night after the
  pull is armed, the world produces new data no experiment has touched.
  Running the candidates as LIVE PAPER portfolios consumes no credits and
  accumulates the only evidence that ultimately matters. That path is open
  today and blocked only on the operator arming the nightly pull.

Recorded by the study, not softened: the profit machine's first validated
alpha is real, and it is not yet money. The machine said so itself, with
receipts, before a dollar was risked. That is the asset.
