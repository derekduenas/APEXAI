# FULL funnel execution reconstruction

Base: `533dfbd83d5769a3eb9ad17a5a149c755fdcd2b4`.

The original court verifier accepted a modified outcome with gross P&L 100
and net P&L 99.91, returning no problems and `pnl_agrees: true`. It subtracted
fees from the recorded gross figure, and did not actually verify the ledger
hash chain. Existing independent round-trip tests exercised the rule route only.

The verifier now checks the complete chain before accounting, backward
references from forecast/funnel to intent to fill to outcome, the funnel's
proposal against the intent and its canonical proposal digest, fee identity
and component totals, quoted entry ASK and exit BID, and position/P&L fields
of the closing Book. Gross P&L is derived from prices, quantity and the recorded
certificate multiplier. Net is derived from that gross and recorded fee
components; entry and exit cashflows must agree independently.

The retained synthetic FULL flight verifies: debit 250.00, credit 270.00,
entry fee 0.04, exit fee 0.05, gross 20.00, net 19.91, zero open positions.
The fresh FULL fixture now unconditionally requires TRADE and independently
reconstructs the round trip. These fixture amounts are not profitability evidence.

Run the verifier in a separate process:

```sh
python -m apex.court.verify docs/evidence/organism_court_001/runs/fc-FULL-500
```

It reads artifacts only, writes JSON to stdout, and exits 1 on a detected
problem. It imports no producer, execution, fee or Book implementation.

## Validation and limits

Focused command:

```sh
python -m pytest -q tests/test_court_execution_reconstruction.py tests/test_organism_court_001.py
```

Negative fixtures cover broken hashes, consistently rehashed incorrect amounts,
a false gross/net pair, wrong contract/quantity, altered fee identity, changed
proposal, duplicate discharge, contradictory closing Book, malformed JSON and
CLI failure status. Original fixture artifacts are copied before mutation.

Scope is a single-scan long-option court run. Multiple scans/fills are explicitly
unsupported, not partially summarized as verified. This does not verify broker
tariffs, risk-limit correctness, model calculations, calibration, receipt
authenticity, source availability or the unwired complete decision-context ID.
Recorded fee amounts and multiplier are cross-checked, not externally attested.
A wholly consistent rewritten history cannot be authenticated without an
external anchor. Receipt references remain reference evidence, not consumption.

No premarket, production trading, fee computation, limits, provider configuration
or deployment code changes. No live provider or operational host access. This
patch does not commission a later layer or replace the pending premarket R5.
# Final focused validation

52 tests passed across `test_court_execution_reconstruction.py` and
`test_organism_court_001.py`, using an external virtual environment. This includes
a newly executed synthetic FULL_FUNNEL flight, retained-fixture reconstruction,
and corrupted-record refusal tests. No full-tree regression was run.
