"""APEX HISTORICAL WORLD LAB -- the market experience engine.

MISSION: MAXIMIZE HONEST MARKET EXPERIENCE -- never backtest
profitability. The Lab serves all three sleeves (EQUITIES_INTRADAY,
OPTIONS, BTC_PERPS) and exists so the predator can eventually ask,
about any live state: "have I seen anything like this before, and what
happened the previous N times?" -- answered with structured evidence
(n_raw, clustering, regimes, forward MFE/MAE, tails, failure modes,
data pedigree), never with bravado. Queryable experience FIRST; ML as
one organ, maybe, later.

CONSTITUTION (operator-issued 2026-08-21):
  * every historical datum keeps: source, venue, instrument identity,
    event_time, known_from where reconstructible, acquisition time,
    resolution, timezone, adjustment methodology, quality,
    completeness, version
  * raw history is IMMUTABLE; derived datasets are VERSIONED
  * venue facts stay venue facts -- no fictional universal market
  * survivorship honesty: point-in-time membership, delisted names
  * options realism: no fill may be assumed at a mid that never traded;
    data incapable of execution realism is LABELED so

RESEARCH ERAS (per sleeve, causal time order, purge/embargo where
horizons overlap; never random train/test splits):
  DISCOVERY -> DEVELOPMENT -> VALIDATION (mostly frozen)
  -> SEALED FINAL EVALUATION (untouched) -> PROSPECTIVE (reality only)

HYPOTHESIS BIRTH LAW: every hypothesis records HYPOTHESIS_ID,
HYPOTHESIS_BIRTH, KNOWN_FROM, DATA_SEEN_BEFORE_BIRTH,
DATA_RESERVED_AFTER_BIRTH, MODEL_VERSION, FEATURE_VERSION. An LLM may
never count the period that taught it as independent validation.

MULTIPLE-TESTING LAW: the research path is persisted -- experiments
attempted, variants, families abandoned, selection rationale. The
surviving experiment is never reported as the only experiment.

WALK-FORWARD LAW: train on past, predict future, freeze output,
resolve, advance. No future-fit preprocessing of ANY kind
(normalization, winsorization, regime fitting, clustering, feature
selection, thresholds included).

DECISION_POWER = NONE_WORLD_LAB. The Lab proposes evidence; the
prospective organism judges reality. It cannot authorize Capital,
submit paper or live orders, or self-promote authority.
"""
WORLD_LAB_POWER = "NONE_WORLD_LAB"

ERAS = ("DISCOVERY", "DEVELOPMENT", "VALIDATION", "SEALED", "PROSPECTIVE")

DATA_TIERS = ("TIER_A_EXECUTION_REALISTIC", "TIER_B_RESEARCH_ONLY",
              "TIER_C_EXPLORATORY", "UNUSABLE")

SLEEVES = ("EQUITIES_INTRADAY", "OPTIONS", "BTC_PERPS")

ROOT = "results/world_lab"
