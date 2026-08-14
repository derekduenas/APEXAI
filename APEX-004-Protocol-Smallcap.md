# APEX Research Protocol — Experiment #004: Small-Cap Gross Profitability

Registered: 2026-08-13
Author: Derek Duenas

**Signed on operator authorization ("sign and run it", 2026-08-13), after all
three preconditions were met on the record: the human gate ruling on
`SMALL-CAP-JUSTIFICATION.md` (H-GP-SC at the stricter 2.92 bar), the §5a
breadth census, and the §8a null recalibration. Dry-run certification PASSED
twice bit-for-bit (digest 3daebc37…) BEFORE this signature.**

## 1. Hypothesis

**H-GP-SC** (GATE-RULED 2026-08-13, see `SMALL-CAP-JUSTIFICATION.md`): High
gross-profits-to-assets earns higher forward 20-trading-day excess return
than low, within the small-cap universe. Single ranked feature
`prof_gross_profitability`; no composite; no parameters. The signal overlaps
APEX-003's; the ruling accepted that with the CONTESTED disclosure standing
in the record and the stricter legacy bar retained (§6).

## 2. Economic mechanism

Anomaly premia concentrate where arbitrage capital is scarce and information
diffuses slowly: limits-to-arbitrage (transaction costs, analyst neglect,
institutional mandates) are strongest below ~$2B market cap. Mechanism
citations predate this program (Fama–French 2008; Asness et al. 2018).

## 3. Universe — THE experimental change (everything else inherited)

NYSE / NASDAQ / NYSE American common stock, **market cap >= $100M and
< $2B**, 60-day ADDV >= **$1M**, close >= **$2**, >=252 days history, >=200
bars in prior 252, REITs and warrants excluded, delisted securities RETAINED
(this universe is where survivorship bias does its real damage; the as-filed
snapshot already retains delistings). Signal computed AFTER eligibility.

Floors marked bold are PROVISIONAL until the §5a breadth census; they are
calibrated on STRUCTURAL grounds only (breadth, tradability) — never on any
signal's performance.

## 4. Direction and orientation (explicit — the erratum lesson)

HIGHER is better.

    highest gross profitability -> rank 1 -> score 100 -> decile 1 (TOP)
    lowest  gross profitability -> rank n -> score ~0  -> decile 10 (BOTTOM)

Score and decile derive from ONE descending rank (`apex.experiments.apex003`,
the certified shared path). Ties: `method='first'` on a security_id-sorted
view (C10). Missing: excluded at that date, never imputed.

## 5. Periods (inherited)

    in_sample   2005-01-01 .. 2017-12-31
    validation  2018-01-01 .. 2021-12-31   (LOCKED — the single paid look)
    holdout     2022-01-01 .. 2026-06-30   (LOCKED — opens only on PASS)

### 5a. Pre-registration structural calibration (REQUIRED, zero credit)

Before signing: a breadth census of the §3 universe on the in-sample period
(names per day, coverage of `gp`/`assets`, ADDV distribution). Census reads
eligibility and data coverage only — NO signal values, NO returns joined.
Output committed as `results/004_universe_census.json` and referenced here.

**DONE 2026-08-13** (`scripts/census_004_universe.py`): median **1,250
eligible names/day** (p10 1,140 / p90 1,605), GP availability **99.7%** of
eligible names. 2005 medians are zero — the 252-day history warm-up of a
panel loaded from 2005-01-01, not a data gap; 2006–2017 range 1,164–1,609.
Breadth supports ~120+ names per decile: the floors in §3 are structurally
adequate and are hereby FIRMED (no longer provisional). Remaining §5a-class
work before signing: ADDV distribution detail if the gate requests it.

## 6. Success / failure criteria

Mean daily cross-sectional Spearman IC positive; Newey-West (Bartlett,
lag 25) t >= **2.92** (GATE-RULED 2026-08-13: the stricter legacy bar, true
size 0.872% under the derived null — chosen over the exact-1% 2.85 so no
reading of this experiment can allege a lowered bar); non-overlapping
robustness agrees in sign. FAILURE and INVALID defined exactly as
APEX-003 §8.

### 8a. Null recalibration (REQUIRED, zero credit, before signing)

**DONE 2026-08-13** (`scripts/recalibrate_004_null.py`,
`results/004_null_recalibration.json`). The null t-distribution depends only
on (n_obs, overlap, lag, kernel) — the t-statistic is scale invariant, so
breadth drops out. Derived at n=987 (the shared validation calendar), 100,000
replications, declared seed 20260813, stable across four independent check
seeds (p99 range 2.848–2.876):

    exact-1% bar (derived):   t >= 2.85   (true size 0.997%)
    legacy 002/003 bar:       t >= 2.92   (true size 0.872% — conservative)

The derived bar is LOWER than the registered 2.92 — and this derivation
arrives immediately after a near-miss FAILURE, which is precisely when
bar-lowering must be suspect. The method and seed were declared before the
number was seen, but the CHOICE between the exact-1% 2.85 and the stricter
legacy 2.92 is reserved to the human gate and frozen into config at signing.
Neither choice touches any closed experiment (APEX-003's 2.525 is below
both). The holdout-length bar is derived by the same script at signing.

## 7. Robustness (declared)

Moving-block bootstrap + block sign-permutation, block 20, 2000/2000, seed
**20260814** (declared 2026-08-13, before any small-cap statistic exists).
Subperiods diagnostic only.

## 9. Evaluation instrument

**Long-only top-decile sleeve** (the deployable shape): equal weight,
quarterly rebalance, evaluated post-validation by `project_long_only` against
the DECLARED long-only viability gates (net >= 2% over benchmark, quarterly
turnover <= 60%, degradation <= 60%, >= 20 names). Small-cap cost input uses
a HIGHER declared one-way cost of **50bp** (declared 2026-08-13, before any
small-cap result exists) — small caps are more expensive to trade and the
gate must price that, not inherit the 20bp large-cap constant.

## 10. Contamination

Provenance epoch: AFTER_APEX_003. **Descendant of failure: CONTESTED —
RULED ADMISSIBLE by the operator 2026-08-13** (`SMALL-CAP-JUSTIFICATION.md`,
ruling block). The CONTESTED disclosure is retained, not erased: any reader
of this protocol sees that the signal choice postdates a near-miss on the
same signal, and that the experiment answers with the stricter bar and the
independent grounds of the memo's §2.

## 11. Budget

Draws one credit from the remaining 2 of the 5-credit lifetime budget. A
universe pivot does NOT mint a fresh budget (operator ruling requested; the
draft takes the conservative position).

## 12. Inheritance

All other elements inherited unchanged from APEX Research Protocol v1.0 and
amendments A-001..A-007.
