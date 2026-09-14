# Hunter causal handoff repair

Base: d01332eb0b3420d15c4d476778d232209ba8b5a7.

Both decision_pass and the scheduled Hunter clock omitted bars_by_symbol when
calling enrichment_pass. Both now pass the frame mapping. Simulation returns
and spot now derive from the same sorted, completed regular-session bars on the
decision's market date. Supplied available_epoch also gates visibility.
Duplicate timestamps and invalid visible prices refuse; gaps are not converted
into one-minute returns.

Without supplied availability, bar completion remains an explicit assumption,
not proof of historical receipt. Provenance records this limitation.

The existing intelligence test fixture ended before the regular session. It now
ends at 18:00 UTC with a cutoff at 18:01 UTC, and expects return event time at
bar completion. Thresholds and forecast authorization remain unchanged.

Validation: tests authored; no local Python runtime or host terminal is available
in the authoring session. No passing-test claim is made. PR CI and host entrypoint
verification are required before activation.

Outstanding commissioning work:
- integrate this repair with the intended release, including newer premarket and
  options-path repairs; this branch is deliberately based on the reviewed Hunter head;
- inspect actual live sensor freshness and scheduled entrypoint output;
- implement/review the commissioned forecast-to-paper authorization route; Hunter
  still supplies ForecastSlot() and cannot authorize paper trades;
- prove durable order/fill/exit/fee/realized and unrealized P&L reconciliation using
  the existing Book and ledger, including restart with open positions;
- demonstrate the entire scheduled path on controlled data, then one live-data
  observation cycle; publish exact release identity and per-layer receipts.

No deployment, live trade, paper activation or account-limit change was performed.
