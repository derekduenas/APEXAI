# Premarket packet to Twin and decision: integrated candidate

Base: R5 report commit `8c1cf96fa8e97799c2ad7eb2e6ecd35b70d7e0ac`.
Includes PR #1 (independent execution reconstruction) and PR #2 (early-trigger
repair), preserving both commits as parents of this integration candidate.

## What now flows

The production staged CLI builds a sealed packet. A configured `TwinSources`
reads the same market date's local packet while building its snapshot. It checks
the content seal, declared shadow authority, schema, date, before-open seal and
availability. It attaches prior context to the snapshot, copies it into forecast
inputs, and the real session reads that persisted forecast to write the decision.

The full parsed packet and digest remain in the ledger. A later file edit cannot
rewrite that capture. Snapshot identity continues to cover its existing underlying
state only; the context explicitly names that snapshot and its own packet digest.
Intent/fill references lead back to the forecast; no execution quote is folded
back into the premarket packet.

Missing, unwired, invalid and attached are distinct statuses. Invalid or late
packets attach no content. V1 freshness remains unreconstructible; V2 timing is
producer-reported. Cutoff age is not represented as individual source freshness.
The seal checks content consistency, not publisher or market-source authenticity.

## Authority and configuration

`model_consumed=False` and `selection_effect=NONE` are explicit. This adds a real
reader for carrying context into the record. It does not add a model feature,
change ranking, grant an LLM trading authority, or assert improved expectancy.
The four source blind spots remain visible in the persisted original packet.

The existing production wiring accepts the local root explicitly:

```python
from apex.options_pilot.entrypoint import LiveWiring, ProductionSources

provider = ProductionSources(wiring=LiveWiring(
    premarket_root="results/frontier/premarket",
))
```

This construction does not contact a provider, enable market data or authorize
execution. Default configuration remains `NOT_WIRED`. The field is exposed in
the production wiring report; no host configuration has been installed.

## Tests and scope

The new integration test runs all five production premarket invocations as
separate processes over frozen synthetic transports. It then runs a 09:35 ET
FULL_FUNNEL flight with synthetic training history and intraday tape. The packet
identity and content agree on forecast and decision; the flight trades, exits,
and passes independent single-trade execution reconstruction. The no-context
control has identical model outputs, selected contract, quantity and net P&L.

Two fixture mistakes were corrected while building the flight: extending the
upward walk to 1,400 bars moved spot outside the fixed option quotes' valid range;
and the legacy harness's single September call became eligible on the August
test date. The test declares separate training/current bars and a two-sided
October chain. Pricing and selection gates were not changed to get a trade.

The focused command covers the new handoff, court reconstruction, organism court,
early retry, Twin, entrypoint and TradingView pilot seam suites:

```sh
python -m pytest -q tests/test_premarket_twin_handoff.py \
  tests/test_court_execution_reconstruction.py tests/test_organism_court_001.py \
  tests/test_premarket_early_retry.py tests/test_pulse_options_twin.py \
  tests/test_options_pilot_entrypoint.py tests/test_tradingview_pilot_seam_003.py
```

155 passed on the final candidate using an external Python environment. No
full-tree regression or Mac scheduler commissioning is claimed. All market data
and Captain output in the new flight are synthetic/recorded fixtures; this is
not a profitability test, live inference test, or source-entitlement test.

## Next gates

Review and validate the exact combined candidate, then commission the local
producer and packet path on the operator host under its existing holds. The next
model-stage work must identify which premarket measurements have a declared
consumer and test that consumer's behavior; copying this packet into a model
input map would not itself prove meaningful consumption. A strategy's edge still
needs an authorized chronological evaluation with frozen choices and costs.
