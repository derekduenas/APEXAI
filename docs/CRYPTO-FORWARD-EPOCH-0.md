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
