# APEX Research Protocol — Experiment #003: Gross Profitability

**Transcribed verbatim from the pre-registered packet
(`results/003_registration_packets.json`, dossier `97da989ad49a…`), which
survived the reject-only screen on structural grounds on 2026-08-12.**

## 1. Hypothesis

High gross-profits-to-assets earns higher forward 20-trading-day excess return
than low. The cross-sectional rank of gross profitability predicts forward
excess returns; higher profitability ranks higher.

## 2. Economic mechanism

Novy-Marx (2013): gross profitability is the cleanest accounting measure of
economic productivity, less contaminated by discretionary items than net
income. The signal sits above the line and is incorporated slowly.

## 3. Signal definition

`prof_gross_profitability = gp / assets`, both as-filed SF1 ARQ, earliest
filing per (ticker, reportperiod), admitted only where filing `date <= T`.
No winsorisation, no clipping, no z-scoring, no smoothing, no parameter of any
kind. Single ranked feature; no composite; no weights to choose.

## 4. Direction and orientation (explicit — the erratum lesson)

HIGHER is better.

    highest gross profitability -> rank 1 -> score 100 -> decile 1 (TOP)
    lowest  gross profitability -> rank n -> score ~0  -> decile 10 (BOTTOM)

Score and decile derive from ONE descending rank. Ties: `method='first'` on a
security_id-sorted view (C10). Missing: excluded at that date, never imputed.

## 5. Universe

The frozen §3 universe of APEX Research Protocol v1.0, UNCHANGED: NYSE /
NASDAQ / NYSE American common stock, market cap >= $1B, 60-day ADDV >= $10M,
close >= $5, >=252 days history, >=200 bars in prior 252, REITs and warrants
excluded, delisted securities retained. Signal computed AFTER eligibility;
signal availability never redefines the universe.

## 6. Timing

Features through filing date <= T. Formation close T+1. Forward return close
T+1 -> close T+21. Rebalance grid: every 20 trading days on the existing
locked grid.

## 7. Periods (inherited, unchanged)

    in_sample   2005-01-01 .. 2017-12-31   (unlocked, no statistical standing)
    validation  2018-01-01 .. 2021-12-31   (LOCKED — the single paid look)
    holdout     2022-01-01 .. 2026-06-30   (LOCKED — opens only on validation PASS)

## 8. Success / failure criteria (§13, unchanged, read from config)

**SUCCESS** — mean daily cross-sectional Spearman IC positive, Newey-West
(Bartlett, lag 25) t >= 2.92 (validation) / 2.88 (holdout), and the
non-overlapping robustness test agrees in sign.

**FAILURE** — measurable and complete but the threshold is not met, or
directionally negative. Experiment closed; specification NOT adjusted and
re-run.

**INVALID (0 credits)** — the hypothesis cannot be validly tested.

## 9. Robustness, declared before validation

Moving-block bootstrap of the mean daily IC and block sign-permutation null:
block size **20** (matches the 20-day forward-return overlap; declared, not
searched), 2000 resamples / 2000 permutations, seed 20260807. Subperiod
diagnostics (calendar year, calendar quarter) are DIAGNOSTIC ONLY and never
select anything.

## 10. Falsification criterion

Mean daily Spearman IC not reliably positive at the §8 hurdle over the
validation period.

## 11. Evaluation instrument (research construct, not the deployed portfolio)

Long top decile / short bottom decile, equal weight, monthly rebalance —
evaluated by the monetisation projector ONLY after validation, against the
pre-declared viability gates.

## 12. Contamination

Provenance epoch BEFORE_APEX_002. Descendant of failure: NO. Chosen from
published literature predating both closed experiments; screen survival was on
economic and data grounds with no in-sample performance computed.

## 13. Inheritance

All other protocol elements — timing firewall, cost model, evaluation
machinery, ledger, credit accounting — are inherited unchanged from APEX
Research Protocol v1.0 and its amendments (A-001 .. A-006), including A-001's
bar on the simulated null entering the decision path (the registered constants
in §8 govern).

---

**Registered:** PENDING — awaiting operator signature
**Author:** PENDING
