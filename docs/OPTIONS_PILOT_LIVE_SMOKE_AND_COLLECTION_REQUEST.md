# Request: read-only live smoke and prospective collection for the options pilot twin

**Status (updated 2026-09-11): operator-authorized in chat ("yup do your thing" / "yup LFG") and EXECUTED.**
- §A read-only smoke: run on the host at 02:56:58Z under containment with `APEX_PILOT_LIVE_DATA=ENABLED` and the
  authorization file `/apex-data/pilot_smoke/AUTHORIZATION.txt`. Result COMPLETED: Alpaca 91 bars accepted (0 rejected),
  NBBO with sizes, ThetaData 2,124 expirations, 332 quotes for 2026-10-02; every option quote 24,118–24,243 s old at
  receipt (market closed) so the snapshot was STALE throughout and the artifact refused `ret_1 is STALE` — the
  correct closed-market answer. Evidence: `docs/evidence/host_live_smoke_2026-09-11_closed_market.json`.
- §B prospective collection: `scripts/options_pilot_collector.py` launched at ~02:58Z as transient unit
  `apex-pilot-collector` (wmresearch.slice, MemoryMax=300M, user apex), idle outside regular hours, 10 sessions,
  SPY/QQQ/IWM, root `/apex-data/pilot_collection/`, heartbeat `HEARTBEAT.json`, stop file `STOP`.
- Robinhood MCP (agent-session channel): read-only smoke done at 02:46–02:49Z (`docs/evidence/robinhood_smoke_2026-09-11.json`);
  a one-time market-hours smoke is scheduled for 2026-09-11 09:40 ET.
The legacy options service, its maintenance block, the live options ledger and the deployed release are untouched.

## A. Read-only live smoke (one session, one symbol)

| Item | Value |
|---|---|
| Purpose | prove the provider adapters, ingestion clocks, snapshot composition and the frozen-artifact adapter on real feeds, with no decision and no ledger write |
| Command | `scripts/options_pilot_live_smoke.py --symbol SPY --minutes 90 --out-dir /apex-data/tmp/pilot_smoke --authorization-file <operator file> --execute` |
| Gates | authorization file containing `OPTIONS_PILOT_LIVE_SMOKE_AUTHORIZED <date>`; `APEX_PILOT_LIVE_DATA=ENABLED`; Alpaca key id + secret present in the existing secret backend; ThetaData terminal listening on `127.0.0.1:25503` |
| Requests | 2 Alpaca data-API GETs (bars, NBBO); 2 ThetaData GETs (expirations, one chain snapshot). No paper-endpoint call (the Alpaca paper endpoint is known to 401 with data-only keys). |
| Entitlements | Alpaca market-data (SIP feed) — data-only keys already provisioned; ThetaData options quotes — existing subscription; no new paid service |
| Writes | one JSON file under the named out-dir; **not** `/apex-data/core/options_live_ledger.jsonl`, **not** any pilot ledger |
| Resource limits | run under the standard containment (`systemd-run … MemoryMax=1400M`, research slice); expected < 60 s, < 200 MiB |
| Stop rules | any `ProviderUnavailable`, HTTP error, or parse error stops the run with the reason in the output file; no retries beyond one |
| Output | gate status (credential PRESENCE only), bar counters (accepted/duplicates/out-of-order/late/revisions/rejected), the snapshot with per-field quality, one forecast record labelled `LIVE_FEED` + `SMOKE_READ_ONLY` + `NOT_VALIDATED`, the exact request URLs (no secrets) |
| What it does not prove | edge; feed behaviour over a session; that the artifact's live features equal the historical recipe (that needs the collection below) |

The HTTP client is deliberately not wired in this build: `--execute` refuses
`HTTP_CLIENT_NOT_WIRED`. The commissioning change that wires it is a
one-function addition reviewed together with this request.

## B. Prospective collection (observation only)

| Item | Value |
|---|---|
| Purpose | collect the raw inputs the pilot twin needs, prospectively, so that (1) live-bar features can be compared against the historical recipe, (2) quote cadence, staleness and revision rates are measured before any paper decision |
| Symbols | SPY (pilot); QQQ and IWM as cross-market context only |
| Duration | 10 regular sessions, then review |
| Cadence | underlying bars: every completed minute (pull at :05 past the minute); NBBO: every 15 s; chain snapshot for the nearest ≥ 21 DTE expiration: every 60 s during regular hours |
| Paths | `/apex-data/pilot_collection/<YYYY-MM-DD>/{bars,nbbo,chain}_<symbol>.jsonl` (append-only, hash-chained via `chain_append`) |
| Retention | raw provider records retained for the review period under the vendors' licences; derived twin snapshots are proprietary records and keep source + dependency provenance |
| Resource limits | one process under containment; ≤ 300 MiB RSS; disk ≤ 2 GiB for 10 sessions (estimate: ~150 MiB/session for chain snapshots at 60 s) |
| Stop rules | disk budget reached; three consecutive provider failures; any parse error rate > 1 %; operator stop file |
| Not included | any pilot decision, any ledger record of the pilot kind, any order, any change to the deployed release or the maintenance block |
| Authorization needed | operator approval of this request; the standard containment wrapper; `APEX_PILOT_LIVE_DATA=ENABLED` for the collector process only |

## C. What is already true without either part

- The adapters parse the providers' documented shapes on fixture responses (`test_provider_parsers_…`).
- With the default environment no network access is attempted (`test_production_connectivity_is_disabled_…`,
  `test_production_route_refuses_before_any_network_access`).
- The frozen artifact's `params_hash` recomputes exactly and its forecasts reproduce the experiment's own
  model code on controlled inputs (`test_adapter_reproduces_the_experiments_reference_forecasts`).
