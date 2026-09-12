# FUNNEL_FIRST_RUN_RESULT — FULL_FUNNEL_V1's first execution ever (2026-09-12)

Pre-registered in `docs/FUNNEL_FIRST_RUN_PREREGISTRATION.md`, committed before the run. Mechanism test, quarantined
replay, **excluded from expectancy, calibration and alpha**. Evidence:
`docs/evidence/funnel_first_run/funnel_first_run.json`. Driver `scripts/funnel_first_run.py`.

## Setup

12 scans at the pilot's 15-minute cadence across the burned 2026-09-11 SPY session, with **5,170 prior 1-minute
bars** fetched read-only from Alpaca through the deployed release under containment, plus the session's own 169
bars. Real `TwinSources`, real `FunnelEngine` at defaults (`strikes_each_side = 4`, 2,000 paths), real certified
risk authority against a real Book, real fee schedule. Nothing tuned.

## Result

| Stage | Count |
|---|---|
| forecast produced | 12 / 12 |
| **variance fit** | **READY on all 12** — the first time this has ever happened |
| candidates constructed | 18 per scan (ATM ± 4 strikes, both rights) |
| candidates surviving the risk envelope | **0 on every scan** |
| reached PRIME | **0** |
| proposals | **0** |
| decision | WAIT × 12, `NO_ELIGIBLE_CANDIDATE: every contract rejected (18 by the risk envelope)` |

Cheapest rejected candidate on the first scan: indicative ask **11.50** against the $5.00 envelope.

## The finding

**The funnel has the defect the rule path had, and the fix never reached it.** `DEFECT_STRIKE_RULE_001` (2026-09-11)
found that `PILOT_RULE_V1` chose the nearest-to-spot strike, which the $500 cap always refuses, and recorded it as a
DEFECT under `PROFIT_TRANSITION_DIRECTIVE` hard law one. `PILOT_RULE_V2` repaired the **rule path** by selecting the
nearest cap-feasible strike. The funnel's candidate set was left at ATM ± 4 strikes, and on this session the nearest
cap-feasible strike is **8 to 15 strikes out**. The two sets cannot intersect.

So: `FULL_FUNNEL_V1` has never been able to construct a trade under the paper cap, on any data, since it was built.
Four weeks of funnel work has produced a machine that reaches its own risk envelope and stops. That is hard law one
again — zero trades because attacks are structurally impossible — and it is now **reproduced by execution**, not
inferred.

At the same instants the rule path selects normally: SPY 2026-10-02 **749 PUT** on the first scan, 15 strikes out,
ask under $5.00. **The two paths do not merely differ in selection; one selects and the other cannot.**

The repair was explicitly refused for the funnel on 2026-09-11 and that refusal still stands: widening the candidate
set from the cap would make what the machine *sees* a function of account size and contaminate candidate generation
with a financing fact. The correct repair is a candidate rule that is blind to capital and still reaches the
feasible band, for example a fixed moneyness band rather than a fixed strike count. **That is a reviewed change and
is not made here.**

## A second defect, found by running it

The funnel crashed on its first execution: `TypeError: unsupported operand type(s) for -: 'float' and 'NoneType'` in
`expression_war._pnl_paths`. Cause: `decision_wb/engine.py` called `fee_schedule.exit(1)` with no sale principal,
which now correctly returns `NOT_ESTIMABLE`, and the `None` flowed into the P&L arithmetic. Before this weekend's
fee repair the same call silently returned the fixed per-contract constant, so **every funnel candidate was priced
with an exit fee taken at the $5.00 cap regardless of its own premium**, and nobody could see it because the funnel
never ran.

Minimal repair applied: the funnel declares its exit-fee assumption explicitly (`EXIT_PRINCIPAL_EQUALS_ENTRY`, the
same assumption `TOLL_FORMULA_V1` already makes), records it on the trace under `fees`, and **refuses with
`FEES_NOT_ESTIMABLE`** if either side is unknown. A per-path exit fee from each modelled exit bid is the correct
model and is a pricing change, not this brick.

## What this does and does not establish

It establishes that the funnel's plumbing works end to end with a real fit: bars load, the variance model fits, the
regime filter runs, candidates are constructed, the envelope is applied, and the refusal is named. It establishes
that its candidate rule cannot reach a feasible contract under the current cap. It establishes nothing about
whether the funnel's selection would be good, because it has never made one.
