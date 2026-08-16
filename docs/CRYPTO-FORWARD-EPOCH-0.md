# CRYPTO FORWARD EPOCH 0 — THE 24/7 SHADOW ARENA (FROZEN 2026-08-16,
before the first scored observation)

Purpose: a live proving ground for the MACHINERY — perceive → reason →
reject → forecast → manage → learn on genuinely unseen 24/7 data —
while equities wait for their session. It is NEVER evidence that the
equity Hunter works, and crypto results can never graduate, calibrate,
or authorize anything in the equity track (separate evidence class
COINBASE_FORWARD_OBSERVATION; the unmixed law enforces separation).

## Zero capital, by construction

The feed module can read candles/ticker/book and nothing else; no order
endpoint exists in the package; verdicts are SHADOW_TRADE / SHADOW_WATCH
only. The evidence ladder is unchanged: shadow → (much later, if earned)
paper → (far later) tiny capital. Crypto grants no permission to skip
rungs.

## Instrument and world

BTC-USD is the sole instrument. The Digital World watches the ecosystem:
BTC/ETH/SOL 60m returns, BTC-ETH relative strength, 3-name breadth,
BTC vol state, uncertainty (|BTC 60m| >= 2% or data quality → SHADOW
verdicts cap at WATCH — conservative-only, same law as equities).

## Crypto-native perception (schema crypto_feature_schema_v1)

Rolling 24h VWAP (no session open), position in 24h range, trailing-4h
breakout structure (extreme excludes the current bar), hour-of-UTC
volume seasonality (14-day median baseline), realized 1h vol +
vol-implied 30m scale, volume acceleration, live spread bps + top-10
book imbalance. Completed candles only; future-poison law applies.

## Frozen playbooks (thresholds set BEFORE observation one)

CRYPTO-001 v1 — rolling momentum continuation (symmetric): 4h breakout
+ rvol_hour >= 1.5 + vol_accel >= 1.3 + VWAP side + BTC-ETH RS agreeing
(>= 10bp); stop = rolling VWAP, 2R target, 90m time stop, risk
[0.1%, 1.5%].
CRYPTO-002 v1 — failed-extension reversion (symmetric): leg (4h extreme
vs rolling VWAP) >= 2.5x the vol-implied 30m scale; extreme last touched
[5, 45]m ago; retrace [50%, 100%]; wrong side of VWAP; rvol >= 1.2;
stop = the extreme, 1.5R, 60m time stop, risk [0.15%, 3%].
No catalyst playbook (no event feed wired). Coding a playbook confers no
predictive standing.

## Shadow-execution honesty

Entries are hypothetical at the RECORDED ask (long) / bid (short) at
decision time — the spread is paid on paper from observation one, and
bid/ask/spread-bps are stored on every decision. Outcomes resolve
continuously (24/7): 15/30/60/90m returns from shadow entry to candle
closes, MAE/MFE over the window, target-before-stop within the time
stop.

## Assassin, live from day one

Tier-1 only (Adversarial Trader + Market Context), budget 12 OK-calls
per UTC day, ordering law (decision persists before enrichment), and
MATERIAL_OBJECTION or an uncertain world caps the verdict at
SHADOW_WATCH. This is the genuine prospective Swarm test: after enough
observations, MATERIAL_OBJECTION vs NO_MATERIAL_OBJECTION cohorts are
directly comparable on live outcomes.

## The test

The Profit Machine staircase on live data: all states → playbook
matches → assassin survivors → shadow verdicts — does economic quality
rise with selectivity, prospectively, spread-paid? Interpretation floors
apply (nothing under 10 distinct UTC days per cohort is interpreted).
Failure is recorded, not repaired; predicates never retuned inside v1.

## Amendment (2026-08-16): the Market Fabric (transport + fidelity only)

Strategy semantics UNCHANGED (CRYPTO-001/002 predicates, thresholds,
Assassin, Capital). Upgraded from 5-minute REST polling to a continuous
WebSocket Market Fabric:

- Coinbase public WS: heartbeats + ticker + market_trades + level2, all
  three products, auto-reconnect + resubscribe, no auth, no order path.
- OUR OWN BARS from the trade stream (the exchange's candle channel
  buckets at 5m; our battlefield needs finer perception), completed
  minutes only, with per-bar trade counts and buy volume.
- LIVE BOOK: best bid/ask, spread bps, depth1/depth10, imbalance, and
  BOOK WALKING for realistic fills at $1k/$10k/$50k notional (slippage
  measured on the real ladder, not assumed).
- HEALTH IS AUTHORITY: sequence gaps and staleness set
  BOOK_HEALTH=DEGRADED and REVOKE microstructure authority; a gap heals
  ONLY on a true snapshot resync, never on the next incremental update.
  Degraded state falls back to REST quotes and is recorded on every
  decision (`microstructure_authorized`, `feed_mode`, `book_health`).
- LATENCY TELEMETRY on every decision: last_market_timestamp,
  decision_timestamp, data_age_seconds — so edge decay before APEX even
  sees a candidate becomes measurable.
- LIVE TRADE MANAGEMENT (daemon, 30s): open shadow positions face
  deterministic stop/target/time-stop transitions against current book
  state; exits cross the spread again (both sides paid).

LAB-06 (caught in the first 15 minutes of live streaming): the raw L2
firehose wrote ~2.9GB/day and would have filled the disk and taken down
MONDAY'S CLOCK. Fix: archive only value-dense channels (trades+ticker,
~50MB/day) plus periodic bounded book snapshots; L2 remains live state;
hourly rotation, 72h retention, hard 400MB cap. A research archive must
never be able to starve production of disk.

## Amendment (2026-08-16): execution-readiness hardening (3 items)

1. DISK SOVEREIGNTY (apex/crypto/diskgov.py) — free space is governed
   like API quota, same doctrine: FORWARD EQUITY > CRYPTO LABORATORY.
   Declared reserves (production 2GB + critical services 1.5GB) are
   subtracted before the arena sees any budget; graduated response
   HEALTHY -> TRIM (raw archival stops) -> MINIMAL (snapshots slow to
   5min) -> SUSPEND (the daemon self-terminates). Crypto voluntarily
   dies before it can threaten Monday.
2. DECISION-TIME BOOK EVIDENCE — every decision that used microstructure
   carries a bounded DecisionBookSnapshot: top-30 bids/asks with sizes,
   depth1/5/10 per side, sync state. Retaining a book-walk RESULT while
   discarding the ladder that produced it would be exactly the evidence
   gap APEX refuses elsewhere; the walk is now reproducible forever from
   the decision record alone.
3. BAR-GAP PROVENANCE — stream-built bars carry coverage_status
   (COMPLETE_HEALTHY / COMPLETE_WITH_GAP / INCOMPLETE) plus
   gap_duration_ms, computed from recorded feed outages and intra-bar
   trade-time coverage. ONLY COMPLETE_HEALTHY bars feed perception;
   gapped/thin bars are dropped and counted in the decision's
   bar_health. Valid calculation over incomplete observation is still a
   lie — the book's law now applies to candles too.

FUTURE (recorded, not built): the measured fill curve is the seed of
capacity-aware Capital — "how much can THIS opportunity absorb before
impact destroys the asymmetry" — which is how account scaling
eventually becomes a measured question instead of a guess.

---

## Observability/orchestration repair — 2026-08-16 (NOT an Epoch break)

After 176 world records and **zero decisions**, two infrastructure defects
were found. Neither is a strategy change; Crypto Epoch 0 predicates,
thresholds, RS/VWAP definitions, risk bands, and Assassin/Captain/Capital
semantics are untouched and remain frozen.

### 1. Zero decisions was indistinguishable from zero scanning

Only the human-readable daemon log carried `decisions: 0`. The scientific
archive recorded world state and nothing about the funnel, so the record
could not answer *"did APEX evaluate and decline, or never evaluate?"* —
LAB-04's lesson, never applied to crypto.

Repair: a `crypto_scan_tick` record per cycle carrying symbols
expected/observed/healthy/evaluated, bar and book health, per-stage
counters for both playbooks, stage counts through Hunter/Assassin/Captain,
shadow watch/trade, and an explicit
`COMPLETE_HEALTHY | PARTIAL | REFUSED_DATA_HEALTH | FAILED` status.

The counters are collected by an optional `trace` dict threaded into the
matchers, incremented at the predicates' EXISTING early-exits. No
predicate was duplicated (this repo's most-repeated bug is two sources of
truth), and nothing reads the trace: the matchers' returns are proved
byte-identical with and without it.

    decision_power = NONE_OBSERVATIONAL_EPOCH0

First live tick under the repair — the shape that was previously
unprovable:

    scan_status            COMPLETE_HEALTHY
    symbols_healthy        3 / 3
    C001_evaluated         1     C001_structure_pass  0
    C002_evaluated         1     C002_blocked_volume  1
    hunter_candidates      0

Scanned, healthy, evaluated, declined. **Zero matches remains completely
legal** — selectivity is the design.

### 2. Intentional suspension fought KeepAlive

The disk governor correctly suspended at 16:56 and 17:13 (crypto budget
exhausted, production reserves untouched). The daemon exited; launchd read
the exit as a crash and resurrected it into the same starved condition.
Two correct controls, oscillating ~17 minutes apart, each restart
re-warming the fabric and breaking book continuity.

Repair: suspension is now a first-class state. The daemon **stays alive
and idle** rather than exiting, so KeepAlive has nothing to resurrect, and
it waits on `may_resume()` — a materially healthier disk — rather than the
mere absence of `must_suspend()`. Hysteresis: suspend at zero crypto
budget, resume only above the full TRIM band (800MB).

**The law:** the condition required to restart must be materially healthier
than the condition that caused suspension.

### 3. A stale log could not be distinguished from a dead daemon

Observed: process alive, ledger written at 18:19, daemon log last written
at 17:13. The operator surface was lying by omission.

Repair: `results/crypto/crypto_health.json`, atomically overwritten each
cycle — pid, start time, last heartbeat, last market message, last scan,
last ledger write, fabric/book health, disk state, suspension state,
restart count. A missing artifact reads `NO_HEALTH_ARTIFACT` and a torn one
reads `HEALTH_ARTIFACT_UNREADABLE`; neither is ever reported as healthy,
and unknown staleness returns None, never 0.

### Honest board

    COINBASE MARKET FABRIC        LIVE
    WORLD STATE                   LIVE
    BAR CONSTRUCTION              LIVE
    L2 / MICROSTRUCTURE           LIVE
    DATA HEALTH                   LIVE
    SCAN TELEMETRY                LIVE  (new)

    SCOUT/HUNTER CODE             DEPLOYED
    REAL SCOUT/HUNTER SIGNAL      NOT YET OBSERVED
    ASSASSIN CODE                 DEPLOYED
    REAL CRYPTO ASSASSIN REVIEW   NOT YET OBSERVED
    CAPTAIN CODE                  DEPLOYED
    REAL CRYPTO CAPTAIN REVIEW    NOT YET OBSERVED
    SHADOW EXECUTION              READY
    REAL SHADOW POSITION          NONE YET
    TRADE MANAGER                 READY
    REAL MANAGED SHADOW TRADE     NOT YET OBSERVED

    REAL DECISIONS                0
    REAL SHADOW TRADES            0
    CRYPTO EPOCH 0                FROZEN
    ECONOMIC EVIDENCE             INSUFFICIENT

The decision layer is **deployed, not tested live**. It earns that word when
one genuine forward candidate traverses it.
