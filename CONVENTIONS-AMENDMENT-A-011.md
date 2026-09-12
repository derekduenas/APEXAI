# CONVENTIONS — AMENDMENT A-011 (IN FORCE 2026-09-11)

**Issued on operator ruling of 2026-09-11 (Defect Repair and First Seal Block, item 3):
"Calendar is canonical, lake is diagnostic."**

## Clock semantics for prediction due dates

### 1. FINDING

The Reality Loop scores an unresolved prediction as a failure once its due date has passed
(`apex/reality/harness.py` `scoreable`: due = trade_date + 1.6 × horizon + 5 calendar days;
"silence is not neutral"). Until this amendment the runner measured "has passed" against
`lake_through`, the last date of price data the nightly pull had fetched.

The lake clock is a clock the system controls. When the pull stops, the lake stops, and under
the lake clock no prediction ever comes due. On 2026-09-11 the canonical regeneration of the
calibration report reproduced the 2026-08-24 numbers exactly, with 906 predictions of the
2026-08-03 batch (calendar due date 2026-09-09) still classed not-yet-due, because the lake
had been frozen at 2026-08-21 for 21 days. The machine had avoided every penalty by going quiet.

This is the third instance in three blocks of one failure class: a gate that reads clean because
it checks a property the system can influence (`CAMPAIGN_V1_ATTEMPT_2`, the F1 probe's
hand-typed scenario list, and this).

### 2. RULE

1. **A due date is measured by a clock the system cannot influence.** For the Reality Loop that
   clock is the calendar (UTC date at generation time).
2. `results/reality/calibration_report.json` is the **canonical scoring record** and is scored
   against the calendar. It carries `"clock": "CALENDAR_CANONICAL"` and `"data_through"` = the
   calendar date used.
3. The lake-clock scoring is retained as `results/reality/calibration_report_lake_diagnostic.json`,
   labelled in-band `"clock": "LAKE_DIAGNOSTIC"` with the sentence "NOT A SCORING RECORD". It may
   be cited to show what the producers look like on the data actually held. It may not be cited
   for standing.
4. A penalty incurred because the pipeline stopped is **correct accounting for a pipeline that
   stopped**. It is not softened, footnoted away, or deferred until the data arrives. When the
   pull is armed and the predictions resolve, the resolutions replace the penalties in the next
   canonical report, and the record shows both states.

### 3. BEFORE / AFTER (2026-09-11, same ledger, 2,762 chain entries)

| Producer | Brier, lake clock (diagnostic) | Brier, calendar (canonical) | penalised |
|---|---|---|---|
| gp_rank | 0.2390 | 0.2929 | 1 → 227 |
| h3_rank | 0.2418 | 0.2688 | 1 → 227 |
| baseline_momentum_rank | 0.2600 | 0.3028 | 1 → 227 |
| blind_twin | 0.2500 | 0.2500 | 1 → 227 |
| baseline_base_rate | 0.2209 | 0.2509 | 0 → 1 |
| baseline_momentum | 0.1600 | 0.2600 | 0 → 1 |

Every skilled producer is worse than the coin-flip twin under the canonical clock. That is the
number of record until the pull is armed.

### 4. SCOPE

Applies to every scoring rule in the repository that decides "past due", "stale", "expired" or
"exhausted". Any such rule that reads a system-controlled clock (a lake date, a heartbeat the
same process writes, a counter the scored component increments) is a defect of this class and
is to be repaired under this amendment, not re-argued.
