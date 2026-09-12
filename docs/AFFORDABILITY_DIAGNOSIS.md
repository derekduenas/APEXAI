# Affordability diagnosis — why the funnel produced zero candidates (2026-09-12)

Retained artifacts only. **No provider request, no historical read, no limit, universe, policy or fee changed.**
Evidence: `docs/evidence/affordability/affordability_diagnosis.json`, driver
`scripts/affordability_diagnosis.py`. Source data: the burned 2026-09-11 SPY collection already on disk.

## Method

For every candidate the funnel's own rule constructs (ATM ± 4 strikes, both rights, first expiry ≥ 21 DTE) at the
same 12 scan instants, I recorded contract identity, quote unit, multiplier, quantity, ask, entry fees, certified
maximum loss, applicable limit and the named rejection reason. Then I recomputed affordability **independently** —
`debit = ask × multiplier × quantity` compared against the limit directly — without consulting the risk envelope,
and compared the two answers.

## Result

| Quantity | Value |
|---|---|
| scans | 12 |
| candidates examined | **216** |
| independently affordable | **0** |
| **disagreements between the envelope and the independent recomputation** | **0 of 216** |
| cheapest candidate in the band, across all scans | ask **6.50** → debit **$650** |
| limit | `risk_kernel.MAX_RISK_PER_TRADE` = **$500**, implied max ask **$5.00**/share |
| multiplier | 100 |

First scan, spot 764.49, ATM 764, band 760–768: 18 candidates, asks **7.34 to 12.26**, debits **$734 to $1,226**.
Cheapest is the 768 call at 7.34. Entry fee $0.04 (commission 0.00, ORF+OCC 0.04, CAT sub-cent → 0.00). Certificate
class `DEFINED_MAX_LOSS`, certified max loss $500.00 (the envelope cap, as designed).

**In the same snapshot, 137 of 331 chain rows ARE affordable.** They are simply outside the band: the affordable
contracts are the far wings, and the nearest of them is 8 to 15 strikes from ATM.

## Classification

**CANDIDATE-UNIVERSE / RISK-POLICY INCOMPATIBILITY.** Not an arithmetic defect, not missing data, not unresolved.

The evidence for that classification, rather than the alternatives:

- **Not arithmetic.** An independent recomputation from the retained inputs agrees with the envelope on all 216
  candidates. Quote unit is premium per share, multiplier 100, quantity 1; `6.50 × 100 × 1 = 650` is the standard
  contract debit and it is what both computations produce.
- **Not fees.** Entry fees are $0.04 on a $650–1,226 debit; removing them entirely changes nothing.
- **Not missing data.** Every candidate in the band had a valid two-sided quote; there were no `NO_QUOTE_IN_SNAPSHOT`
  rejections in the band at any scan.
- **Not a contract-unit error.** If the multiplier were wrong the affordable set would be empty or universal; it is
  neither — 137 of 331 rows clear the same limit under the same arithmetic.

The band and the limit are each internally correct and mutually incompatible on this underlying at this price. SPY
near $765 with 21 DTE has ATM premiums around $7–12, so a $500 per-trade cap excludes the entire ATM ± 4 band by
construction and admits only the wings.

## What this does NOT establish

It does not establish that the funnel would select well if it could see an affordable contract, because it never
has. It does not establish that widening the band is correct: that remains refused, because a candidate set sized
from the account balance makes what the machine sees a function of capital. It does not establish that raising the
limit is correct either, and **no limit was changed**.

The genuine options, none taken here: a candidate rule expressed in **moneyness** rather than strike count (blind
to capital, and it would reach the affordable wings); a different underlying whose ATM premium fits the cap; a
different expiry; or an operator decision on the limit. All are reviewed changes.

## Correction to the earlier claim

The previous report said the funnel "executed for the first time ever". **That was wrong.** `FULL_FUNNEL_V1` has
executed end to end before, in `tests/test_funnel_engine.py::_full_mode_run`, reaching `fit_info["status"] ==
"READY"` and a reconciled exit on the `SyntheticHarness`. What happened on 2026-09-12 was the first run of that
policy **on real market data**: a real chain snapshot, a real underlying-bar history, and a variance fit on real
returns rather than synthetic ones. The precise claim is:

> first execution of `FULL_FUNNEL_V1` against real market data with a real (non-fixture) variance fit;
> not its first execution, and not its first end-to-end run.
