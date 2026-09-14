# Chronological evaluation readiness — 2026-09-14

Base: `0cab0b7f5b113c43c4871dbe664c8cbb6561dea8` (PR #4).
This is preparation, not a backtest result or authorization to execute a new historical experiment.

## What was inspected

The integrated candidate is checked out separately, leaving prior worktrees alone.
Filename inventory in this workspace found none of `chain_SPY.jsonl`,
`nbbo_SPY.jsonl`, `bars_SPY.jsonl`, or `prior_bars_SPY.json`.
No CSV, Parquet or HDF5 data file was found by the candidate-tree filename scan.
This does not establish that the operator's Mac or droplet lacks data.

The repository's WORLD_LAB_DATA_INVENTORY.md and
OPTIONS_HISTORICAL_DATA_SOURCE_REPORT.md describe older host-side corpora.
Their historical counts and source claims are not verified current holdings here.
The earlier FLOW-VALIDATION collection was a burned partial session; its existence
in a report does not make its bytes available to this process or make it a clean holdout.

## Existing replay command is not the next experiment

`scripts/loop_demonstration.py` is tied to FLOW-VALIDATION-001's one-run
acceptance and fit contract. It imports EXIT_POLICY_V1 and the provider fee
schedule directly. Its LifecycleRunner receives no observation_feed. The newer
RecordedQuoteSource exists, but the command does not connect it. Do not silently
change that historical contract or run it as a new walk-forward experiment.
A prospective replacement needs an explicit V2 policy plus arrival feed,
reviewed replay fee configuration, and a new dataset-use declaration.
This review did not exercise or claim a fee-gate bypass.

## Executable input inventory

Run `python scripts/flow_data_preflight.py MANIFEST OUTPUT` on the host holding
inputs. It reads only declared files, hashes bytes, names missing/changed/empty
inputs, and refuses to overwrite an output. It neither fits nor scores nor
contacts a provider. Reading files for hashing is a data read.

Manifest shape (replace paths and hashes with existing evidence; no invented pins):

```json
{
  "sessions": [{
    "market_date": "2026-09-11",
    "exposure_status": "BURNED",
    "inputs": {
      "bars": {"path": "bars_SPY.jsonl", "sha256": "<existing digest>"},
      "chain": {"path": "chain_SPY.jsonl", "sha256": "<existing digest>"},
      "nbbo": {"path": "nbbo_SPY.jsonl", "sha256": "<existing digest>"},
      "prior_bars": {"path": "prior_bars_SPY.json", "sha256": "<existing digest>"}
    }
  }]
}
```

Paths are relative to the manifest or absolute. Exposure is an unverified claim.
Matching bytes alone never marks evaluation_ready true. Coverage, causality,
permissions and holdout status require the actual subsequent review.

## Next evaluation design — draft, not a frozen statistical protocol

1. Inventory all eligible sessions without inspecting strategy outcomes. Verify
   record-level event/receipt times, option quote availability, coverage and
   existing exposure/use records. Separate diagnostic sessions from untouched ones.
2. Freeze code, fees, candidate universe, schedule, horizon, fit budget and split
   before scoring. FULL_FUNNEL, PILOT_RULE_V2 and WAIT receive the same available
   instruments and scan instants; differing universe cannot masquerade as model value.
3. Fit chronologically using only preceding available observations. Purge training
   labels overlapping evaluation; preserve an untouched final period. No search
   or repeated tuning on that final period. Insufficient sessions means diagnostic only.
4. Run through the real replay boundary and lifecycle with V2 arrivals, independent
   exit servicing, current fee gates and retained unknown obligations. The existing
   court verifier is single-scan: multi-trade independent reconstruction must be
   extended and tested, not assumed from its earlier green result.
5. Report refusals, eligible candidates, fit/fallback, layer execution, costs,
   unresolved exposure and complete-vs-partial net separately. Compare results by
   session, not by treating every correlated scan as independent.
6. Attribute defects or calibration hypotheses; register a challenger and test
   only on later data. Do not auto-promote learning or change live risk limits.

TradingView/premarket attachments are not demonstrated selection inputs.
Kelly sizing is not validated by a planted profitable fixture. SVI, fusion,
jumps, JOINT and stock expressions are not silently represented as running.
The goal is first to measure the implemented funnel honestly, then admit additions
only when their incremental effect can be tested.

No provider call, historical fit, scoring, deployment, scheduler activation,
fee authorization or order was made in this change.

## Verification

150 passed in 44.38s: input preflight, full-model-path, GARCH objective bounds,
premarket handoff, court execution reconstruction, organism court, funnel engine,
and worldmodel suites. Eight new preflight checks. These are synthetic tests;
not a full-repository regression or evidence of profitable historical trades.
