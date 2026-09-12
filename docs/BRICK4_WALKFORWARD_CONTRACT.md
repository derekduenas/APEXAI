# Brick 4 — walk-forward evaluation: contract, data inventory, authorization status (2026-09-12)

**Status: CONTRACT FROZEN; EXECUTION NOT AUTHORIZED. No scoring outcome was read.** This document was written
before any evaluation ran, and none ran, because the only datasets that could support a walk-forward of the Monday
policy are not authorized for this use and the operator has not granted the artefacts. The concrete request is
below. Self-authoring an `Authorization` object and treating it as a grant is refused.

## 1. Dataset inventory (from `apex/joint_wb/permissions.py` REGISTRY, read-only checks on the host)

| Dataset | Role | Permitted uses | Artefact needed | Coverage actually held | Fittable sessions |
|---|---|---|---|---|---|
| HIST-A-OPTIONS/2016-2019 | TRAIN | FIT, REPLAY | R4-FIT-001 | historical chains under `/apex-data/history-a/options_history` (not opened this weekend) | unknown until authorized to inventory |
| HIST-A-OPTIONS/2020-2021 | VALIDATION | REPLAY, FIT | R4-FIT-001 | same | unknown |
| HIST-A-OPTIONS/2022-2024 | EVALUATION_SEALED | none | none can authorize in this brick | sealed | — |
| HIST-A-OPTIONS/2025-2026-08-28 | RESERVE_SEALED | none | none | sealed | — |
| PILOT-COLLECTION | PROSPECTIVE_OBSERVATION | FIT, CALIBRATION_REPORT | R4-FIT-002 | **one session**: 2026-09-11, 09:30:22–12:15:39 ET, SPY/QQQ/IWM, 2,982 records (166 SPY chain snapshots at 60 s, NBBO at 15 s); the collector self-stopped at 12:15 on three consecutive nbbo HTTP 504s | **1 partial session** (2h45m of 6h30m); collection observations are not completed fittable sessions |
| PILOT-LEDGER | PROSPECTIVE_DECISION | OUTCOME_EVIDENCE | none | 0 live pilot decisions | 0 |
| SYNTHETIC-FIXTURE | SYNTHETIC | all | none | in-process | unbounded, and worthless for the claim |

Quote timestamps, availability fields and missingness for PILOT-COLLECTION: provider timestamps ET-naive localized;
receipt clocks recorded; `moneyness_status: CAUSAL`; no gaps inside the collected window; everything after 12:15 ET
missing. Known exposure: none (observation only).

**Actual count of completed fittable sessions available to an authorized fit today: 0.** Recorded as
`INSUFFICIENT_TRAINING_DATA: 0 completed sessions (1 partial prospective session held)`.

## 2. The frozen contract (what would run, unchanged, once authorized)

- **Policy under test:** the Monday policy = `PILOT_RULE_V2` on the recording boundary (deterministic rule, certified
  risk, `EXIT_AT_HORIZON_15M_V1`, `EXECUTION_POLICY_V1`), exactly the paper-mode implementations of features,
  candidate selection, pricing, risk, execution and accounting, with only the data/clock adapters replaced
  (`apex/backtest_wb/replay.py` already does this for V1; V2 is selected by `expression_rule="PILOT_RULE_V2"`).
- **Comparators on the same opportunity population:** WAIT (always), the preserved simple comparator `PILOT_RULE_V1`,
  RANDOM_DIRECTION and REVERSED_DIRECTION (already in the replay). FULL vs JOINT is **not** in scope: JOINT has no
  authorized fit and no frozen resampling budget.
- **Opportunity population:** every 15-minute scan instant 10:00–15:30 ET per session, per symbol (SPY primary).
- **Chronology:** no selector or calibration fitting exists for V2 (it is a rule), so the only chronological
  constraint is that every 15-minute outcome be fully available (bars through t+15 min and the exit-window quotes)
  before it is scored; sessions are scored in order; outer windows = sessions; all windows reported together.
- **Execution model:** actual contract identity, entry at ask with the sealed spread, exit at bid inside the window,
  fees from the schedule named in the run (`ROBINHOOD_RHF_2026` if authorized, else `UNVERIFIED` → economics
  `NOT_ESTIMABLE`), quote delay = 0.25 s simulated latency, size ≥ 1 rule, one contract, reservations and overlapping
  positions per the Book, adverse sensitivities: spread ×1.5 and exit at bid − one tick.
- **Unresolved cases:** `TRADE_UNRESOLVED` scored under the existing conservative obligation (`−100a − fees`) for
  economics and **excluded** from predictive-quality labels (never mixed).
- **Regime:** V2 does not condition on regime; nothing to predeclare. Reported diagnostics may be regime-split
  descriptively only, using causal regime labels available at each scan, never full-sample labels.
- **Event layer:** no point-in-time historical news archive with revisions exists in the repository; any replay is
  reported **EXCLUDING THE EVENT LAYER**, and the event layer is evaluated prospectively from Monday.
- **Reported:** forecast quality (CRPS, rank uniformity), net policy economics with session-block bootstrap CIs,
  drawdown, costs, exposure, candidate and WAIT counts, missing outcomes, differences versus each comparator.
- **No retuning** on the weekend report; no deployment choice made from the same test that supports the claim.

## 3. Authorization request (concrete; returned for signature, not self-granted)

```
R4-FIT-002  dataset PILOT-COLLECTION  use REPLAY (V2 policy + comparators)  session_range 2026-09-11..2026-09-11
            fit_cutoff n/a (rule policy, no fit)  evaluation_population "15-min scans 10:00-12:15 ET SPY"
            granted_by OPERATOR   notes: one partial session; result is a smoke of the pipeline, NOT an evidence claim
R4-FIT-001  dataset HIST-A-OPTIONS/2020-2021  use REPLAY  session_range <operator to name, e.g. 2021-06-01..2021-12-31>
            fit_cutoff n/a  evaluation_population "15-min scans 10:00-15:30 ET SPY"  granted_by OPERATOR
            notes: VALIDATION role; TRAIN 2016-2019 not needed for a rule policy; sealed partitions untouched
```

Until one of these is granted, Brick 4 delivers the contract and this inventory. The Monday decision does not depend
on it: observation mode needs no backtest, and paper execution is gated by fees, release and data, not by this.
