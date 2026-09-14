# PREMARKET-SEQUENTIAL-AUDIT-001 — Checkpoint 1 (2026-09-13)

Base `d5d3a71aa421ffeb271e516cce714544a0e185b6` (verified). Separate clean worktree. Hold intact. No fits, no
backtest, no deployment, no orders. **Stops at the handoff.**

## PREMARKET-FLIGHT-001

Selected by the frozen rule *latest complete packet by sealed time* — **not** by any later market outcome.

| | |
|---|---|
| packet | `results/frontier/premarket/2026-08-25.json` |
| `packet_sha256` | `cb8144b2899a36dcd1cec4e30e023b0596ccbe4a30b7d5fb88368375b9ad176b` |
| sealed | `SEALED_BEFORE_OPEN`, `as_of 13:25:00Z`, open `13:30Z` |
| authority | `decision_power: NONE_FRONTIER_SHADOW` |

**Real prospective packets exist** — 7 of them, 2026-08-18 → 2026-08-25, each sealed 06:25 PT before a 06:30 open.
No synthetic flight was needed. **The premarket job has not produced a packet since 2026-08-25** (19 days):
`com.apex.premarket` is loaded but has not run — **CONFIGURED_BUT_INACTIVE**.

## Architecture, by exercise

| component | state |
|---|---|
| `scripts/premarket_run.py` + `apex/frontier/premarket.py` `seal()` | IMPLEMENTED_AND_REACHABLE |
| `com.apex.premarket` launchd (Mon–Fri 05:14 PT) | CONFIGURED_BUT_INACTIVE since 2026-08-25 |
| `EODHD_PREMARKET`, `SEC_EDGAR` | CONNECTED |
| `ROBINHOOD_EARNINGS` | CHILD_SESSION_WHEN_AVAILABLE |
| `COMPANY_NEWS`, `ANALYST_NEWS`, `MACRO_CALENDAR`, `CROSS_ASSET` | **NOT_CONNECTED — declared blind spots** |
| TradingView in the premarket path | **UNWIRED** — no premarket module references it |
| Captain brief agent (bounded child session) | IMPLEMENTED_AND_REACHABLE |

## What the packet actually delivered

4 index symbols with prior close and premarket last (QQQ: none). `gap_map` **empty**. All three `watch_map`
lists **empty**. Four categories declared blind. That is the entire premarket contribution.

## Verification

- **Seal verifies** under the production method. *Retraction recorded:* my first recomputation used compact
  separators and disagreed — **my canonicalization error, not a seal defect.** Caught before reporting.
- **The sealer refuses to seal after the bell** (`PremarketViolation … hindsight`) — exercised.
- **Every AI numeric claim checked is SUPPORTED** by the sealed packet (SPY/IWM/DIA prior closes, premarket lasts,
  gaps to within rounding).
- **Missing stayed missing.** QQQ had no premarket print; the brief says `NO_PREMARKET_PRINTS_YET — no overnight
  read exists at all` and makes QQQ the **#1 attention item precisely because it is absent**. No fabrication.
- **Trading-vocabulary firewall holds**: none of the seven forbidden terms appears in the brief.
- **Injection**: the firewall function rejects hostile text. It **cannot** be an end-to-end injection test on this
  flight — `COMPANY_NEWS`/`ANALYST_NEWS` are NOT_CONNECTED, so no headline reaches the agent at all.

## Temporal note, not yet classified as a defect

`premarket_run.py:158` sets `as_of_time = now()` **at seal time**, after absorption. On this flight `created_at`
is `13:20:01` and `as_of_time` is `13:25:00` — the packet is stamped **299s later than its content was gathered**,
and `as_of_time` is what the manifest registers as `known_from`. Direction is *unsafe* (data looks fresher than it
is). Whether the absorption genuinely continued to 13:25 is not determinable from the packet alone; it needs the
absorption log, which is Checkpoint 1's one unresolved question.

## THE STOPPING POINT — the handoff does not exist

```
REFERENCED_IN_RECORD : NO   no pilot record carries the packet sha or any packet field
CONSUMED             : NO   no trade-path reader exists to instrument
BEHAVIORAL_EFFECT    : NOT TESTABLE  there is no reader to perturb
                    -> NO_DOWNSTREAM_READER in the decision path
```

The only real reader is `scripts/daily_forensics_v2.py` via `morning_prior_manifest.locate()`, which runs **after
the close**. The packet is an **evening-forensics input, not a morning decision input**. The pilot supplies
`event_snapshot_fn` from `apex.catalyst` — a *different* source at SHADOW authority.

**Bounded repair proposal (not applied):** give `TwinSources` an optional `premarket_packet_fn`, bind the packet's
`packet_sha256` into the decision context identity built in R1, and attach it as `PRIOR_CONTEXT` under the
TradingView seam's existing disposition vocabulary — so it is recorded as attached context and cannot become a
signal. That is one bounded seam, and Checkpoint 1 should be rerun after it.

## Verdicts

| | |
|---|---|
| Source-data correctness | **PASS** on what was collected |
| Source-data completeness | **FAIL** — 4 of the requested categories NOT_CONNECTED; gap and watch maps empty |
| Temporal integrity | **PASS with one open question** (`as_of_time` stamped 299s after absorption) |
| AI factual accuracy | **PASS** — all checked claims supported, nothing invented, missing stayed missing |
| Interpretation quality | **PASS** — cites packet fields, names its own blind spots, elevates the gap it cannot see |
| Packet integrity | **PASS** — seal verifies, post-bell sealing refused |
| Downstream integration | **FAIL — NO_DOWNSTREAM_READER** |
| Readiness to advance to live feeds and PULSE | **NO** |

A successful packet establishes no predictive value and no profitability.
