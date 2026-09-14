# MASSIVE-DATA-COMMISSIONING-001

Status: **ADAPTER BUILT · SYNTHETICALLY VERIFIED · LIVE PULL NOT RUN**  
Branch: `codex/chronological-flow-evaluation`  
Adapter version: `massive-adapter-1.0-causal`

This brick establishes the historical-data seam needed for a chronological,
layer-by-layer APEX evaluation. It does not enable a live feed, run a
backtest, fit a model, place an order, or change the paper hold.

## What is implemented

`apex/intraday/massive.py` now provides a read-only adapter with three bounded
fetches:

| feed | endpoint shape | purpose |
| --- | --- | --- |
| stock bars | `/v2/aggs/ticker/{symbol}/range/1/minute/{from}/{to}` | Tier 1 one-minute replay substrate |
| option NBBO | `/v3/quotes/{optionsTicker}` | Tier 2 on-demand candidate quote slices |
| option contracts | `/v3/reference/options/contracts` | point-in-time candidate universe |

The endpoint shapes and response fields are the operator-provided Massive
contract. The canonical option quote path is `/v3/quotes/{optionsTicker}`
with `timestamp.gte`, `timestamp.lt`, `order=asc`, `sort=timestamp`, and a
bounded `limit`. The first live smoke must verify them against an actual response;
the current session exposed no callable Massive tool, so no endpoint response
is claimed as observed.

The adapter:

* sends credentials in an Authorization header only; no key enters a URL,
  request record, exception, normalized row, or manifest;
* requires a one-minute resolution and explicit contract `as_of` for the
  options universe;
* follows only same-origin pagination, strips token query parameters, and
  enforces page and row bounds;
* records redacted request URLs, request/response times, response digests, and
  row counts without claiming those response times are historical row arrival;
* rejects malformed rows by named reason, keeps valid rows, collapses
  identical duplicate identities, and refuses conflicting duplicates;
* sorts normalized output deterministically before the replay layer sees it.

## Causality contract

For a stock bar beginning at `T`, the adapter exposes:

* `event_time_epoch = T`;
* `bar_complete_epoch = T + 60s`;
* `available_epoch = T + 60s`;
* `availability_basis = BAR_COMPLETION_DERIVED_V1`;
* `source_receipt_epoch` = the local response receipt, retained separately;
* `attribution_status = UNVERIFIED_ARCHIVE_RECEIPT`.

`visible_rows(rows, decision_epoch)` uses `available_epoch <= decision_epoch`.
The retrieval clock cannot silently become the historical receipt clock.

For an option quote, `sip_timestamp` is retained in nanoseconds and exposed as
the provider-stated event/visibility instant. The adapter does not claim that a
bulk-download response receipt is the quote's historical arrival. A stronger
availability assumption or archive receipt is still a replay-input decision.

## Evidence

`tests/test_massive_adapter.py` exercises synthetic payloads only: URL and
header construction, secret redaction, one-minute completion boundaries,
malformed/crossed rows, deterministic duplicate policy, same-origin bounded
pagination, option quote and contract normalization, empty-result distinction,
clock rewind, and fail-closed unsupported endpoints.

No Massive API key is stored in this repository. The key pasted in chat was
not used or copied; it should be rotated before any future live smoke.

## Gate to the next brick

An interactive session that actually exposes the Massive connector must run a
bounded read-only smoke and preserve the verbatim responses plus a manifest.
Only after that smoke is independently reviewed should the resulting files be
fed to `flow_data_preflight.py`, then into the sequential layer audit. The
first historical evaluation should use stock bars across multiple symbols;
option contracts and NBBO should be fetched only for candidates admitted by
the point-in-time universe stage.
