# APEX HUNTER — FORWARD CLOCK PROTOCOL (FROZEN 2026-08-15)

Operator ruling: option (c), staged. Hash of this file is recorded in every
forward-ledger entry; editing it after the clock starts voids nothing
retroactively but requires a dated amendment. Credit 5 SEALED. BrokerAdapter
SEALED. No options. No live execution.

## 1. Data evidence classes — LAW (enforced in apex/hunter/evidence.py)

- **EODHD_FORWARD_OBSERVATION**: true forward records frozen before their
  outcomes exist. Scientifically clean; not automatically confirmatory
  under experiment governance.
- **EODHD_HISTORICAL_EXPLORATORY**: engineering/exploration only. Every
  artifact carries HISTORICAL_PROVIDER_SURVIVORSHIP_LIMITATION=TRUE.
  FORBIDDEN for: graduation, profitability certification, survivorship-free
  claims, calibration certification, Credit-5 decisions, live eligibility.
  NEVER mixed into a forward calibration statistic (separate ledgers,
  enforced by refusal).
- **INSTITUTIONAL_HISTORICAL_INTRADAY**: future; requires a provider passing
  the existing frozen certification framework. None pre-approved.

**EODHD historical results cannot graduate Hunter. Stated per deliverable 12.**

## 2. Forward-ledger schema (deliverable 8)

Chained, anchored, append-only: results/hunter/forward_ledger.jsonl.
STATE records (v1, running now): timestamp_utc, session, market state
(index/sector ETF returns, day VWAP position, realized vol, dispersion,
crude breadth proxy — labeled crude), regime (daily online classifier +
intraday vol state), uncertainty, data_health, code commit, config hash,
protocol hash, evidence_class=EODHD_FORWARD_OBSERVATION.
DECISION records (P1B): the directive's full field list (decision_id …
config hash). REALIZATION records appended after horizon; originals never
mutated. Every record chains; the anchor detects truncation.

## 3. Recording cadence

Launchd job every 15 minutes; the recorder exits immediately outside
REGULAR session. End-of-day deterministic backfills of intra-session state
are labeled MECHANICAL_DETERMINISTIC and are NOT decision-grade — only
prospectively recorded snapshots are.

## 4. Scanner specification (frozen design targets, NOT quotas)

PIT universe (Sharadar-defined; EODHD coverage recorded as limitation) →
liquidity/data-quality (price ≥ $5, median $ vol ≥ $50M, spread gate when
quotes exist, fresh data required) → abnormality scan (RVOL ≥ 1.5×
time-of-day, |return z| ≥ 1.5, range expansion) → watchlist ≤ ~20 →
playbook match → regime/context (caution channels only) → distribution →
capital gates → TRADE/WATCH/NO-TRADE. Zero candidates is legal and
common. Full denominator recorded at every stage.

## 5. Playbook mechanism families (frozen at contract level; exact
predictive rules must be predeclared per-playbook BEFORE forward scoring)

A. OPENING/SESSION MOMENTUM — discovery + abnormal participation +
relative strength + structural displacement. B. CATALYST CONTINUATION —
information arrival with incomplete repricing; DORMANT until timestamped
catalyst data exists (none today; never inferred from price). C. STRUCTURAL
PULLBACK/REVERSION — overextension toward equilibrium in compatible
structure. Horizons: 15/30/60/90m, separate declared targets. No family is
claimed to work because it is coded.

## 6. Baselines (frozen prospectively)

RANDOM(p=0.5) / MARKET-DIRECTION / RAW-MOMENTUM(60m sign) /
RAW-RELATIVE-STRENGTH / ALWAYS-TAKE-SCANNER-CANDIDATE / NO-TRADE.
Scored on identical subjects and horizons. No post-hoc baseline selection.

## 7. Calibration policy (primary scoreboard)

Per horizon×playbook: Brier, log score, reliability, PIT/coverage for
distributions, MAE/MFE, time-to-target/stop, residuals. Strata (playbook,
horizon, regime, uncertainty, liquidity) are DIAGNOSTIC — never silent
retuning. Statuses per the existing lifecycle; an LLM cannot change them.

## 8. Effective-sample policy

N_raw AND N_effective always together. Clustering keys: formation
timestamp, day, security, sector, market event, playbook, overlapping
windows. Conservative rule (frozen): N_effective = number of distinct
(session-day × playbook) cells with at least one scored decision, further
capped by distinct sessions; correlated same-event candidates count once.

## 9. Provider-upgrade trigger (frozen; upgrade on data quality, never
excitement) — any of: (1) forward discrimination demonstrated vs frozen
baselines but historical confirmation blocked by EODHD coverage; (2) a
playbook on PAPER_GRADE trajectory needs earlier-regime stress tests; (3)
execution/microstructure becomes the dominant uncertainty; (4) options
expression justified and needs real chains; (5) EODHD feed quality
materially limits fidelity.

## 10. First forward graduation checkpoint (frozen; reconciled with the
reality loop's 20-date and calibration scorecard's norms): review requires
BOTH ≥ 40 completed sessions AND ≥ 100 effective scored opportunities
across ≥ 2 regime states. Sufficient only to answer "does forward signal
justify deeper infrastructure" — NEVER live capital. Promising =
signal-quality dimensions (discrimination vs baselines, proper-score
improvement, reasonable reliability, no single name/day/regime driving,
selected-vs-rejected economic separation, magnitudes not wildly overstated)
— no CAGR requirement exists.

## Failure is acceptable and will be recorded, not repaired.
