# APEX Research Protocol — DRAFT Experiment #004: Small-Cap Universe

Registered: ____________
Author: ____________

**DRAFT — UNSIGNED, UNREGISTERED, NO CREDIT ATTACHED.** This document
becomes a protocol only when (1) the human gate rules on
`SMALL-CAP-JUSTIFICATION.md`, (2) the structural calibration in §5a/§8a is
complete, and (3) the operator signs the header. Until then it binds nothing.

## 1. Hypothesis

[PENDING GATE RULING — one of:]
- **H-GP-SC**: High gross-profits-to-assets earns higher forward 20-day
  excess return than low, within the small-cap universe. (Signal overlaps
  APEX-003 — see justification memo §5, ruling required.)
- **H3-SC**: Among cheap small-cap stocks, profitable ones outperform
  cheap-and-unprofitable ones (dossier 123f67fa re-scoped to this universe).

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

## 4. Direction and orientation

Inherited from the chosen hypothesis's certified execution path; explicit
orientation block required as in APEX-003 §4 (the erratum lesson).

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
lag 25) t >= **[GATE CHOICE — see §8a: derived 2.85 or legacy 2.92]**;
non-overlapping robustness agrees in sign. FAILURE and INVALID defined
exactly as APEX-003 §8.

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

Moving-block bootstrap + block sign-permutation, block 20, 2000/2000, fresh
seed declared at signing. Subperiods diagnostic only.

## 9. Evaluation instrument

**Long-only top-decile sleeve** (the deployable shape): equal weight,
quarterly rebalance, evaluated post-validation by `project_long_only` against
the DECLARED long-only viability gates (net >= 2% over benchmark, quarterly
turnover <= 60%, degradation <= 60%, >= 20 names). Small-cap cost input uses
a HIGHER declared one-way cost [PENDING: declared at signing, e.g. 40–60bp]
— small caps are more expensive to trade and the gate must price that, not
inherit the 20bp large-cap constant.

## 10. Contamination

Provenance epoch: AFTER_APEX_003. **Descendant of failure: CONTESTED —
human ruling required** (see `SMALL-CAP-JUSTIFICATION.md`, especially §3
and §5). This protocol may not be signed until that ruling is recorded.

## 11. Budget

Draws one credit from the remaining 2 of the 5-credit lifetime budget. A
universe pivot does NOT mint a fresh budget (operator ruling requested; the
draft takes the conservative position).

## 12. Inheritance

All other elements inherited unchanged from APEX Research Protocol v1.0 and
amendments A-001..A-007.
