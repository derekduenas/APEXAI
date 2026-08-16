# APEX EXECUTION READINESS — ERD-1 (2026-08-16)

```
Market feeds            READY        (crypto fabric live; equity clock armed)
Digital World           READY
Scout                   READY
Hunter                  READY
Oracle                  PARTIAL / DATA-GATED
Assassin                READY
Captain                 READY (observational)
Capital                 READY / NO FORECAST AUTH
Options Expression      READY / DIAGNOSTIC ONLY
Robinhood connection    BLOCKED_BROKER_AUTH  <- one operator step
Equity quotes           BLOCKED_BROKER_AUTH
Option chain            BLOCKED_BROKER_AUTH
Broker review           BLOCKED_BROKER_AUTH
Flight Deck             READY
Trade Manager           READY

ORDER CONSTRUCTION      READY
BROKER PREVIEW          READY (proven with a labeled mock surface)
LIVE PLACEMENT          🔒 SEALED

KILL SWITCH             ARMED
```

## The one manual step

    /mcp   ->   select robinhood-trading   ->   authenticate

`claude mcp add robinhood-trading --transport http
https://agent.robinhood.com/mcp/trading` is DONE (the server is
registered and reports `Needs authentication`). Interactive OAuth cannot
be performed autonomously and was not faked: every adapter method
returns a typed BLOCKED_BROKER_AUTH result until the operator
authenticates, and the readiness board shows it.

## A4 — the seal (four independent barriers, 22 tests)

1. **ABSENCE** — `RobinhoodAdapter` defines no `place_*`/`submit_*`
   method. There is no flag to flip because there is no capability.
2. **ALLOW-LIST** — the transport refuses any tool outside the
   read/review list and refuses mutating tool NAMES outright, so an MCP
   that exposes placement cannot be reached through APEX's only door.
3. **UNCONSTRUCTABLE AUTHORIZATION** — `LiveExecutionAuthorization`
   raises in its constructor; a future live path must accept one, so
   that path cannot be typed today.
4. **TRIPWIRE** — `assert_no_placement_surface()` scans live objects
   (the gateway refuses to construct around a smuggler), and a
   package-wide scan proves no module defines a placement function.

`ReadinessState` has no ORDER_SENT member, and
`ExecutionReadinessResult` raises if `live_placement` is anything but
SEALED.

## A5 — the pre-handoff kill chain (17 checks)

kill switch · decision lineage · evidence eligibility · capital state
(PAPER_ELIGIBLE only) · decision freshness (≤15m) · quote available ·
quote freshness (≤30s) · data health · broker connection · tradability ·
account visibility · broker capability · risk gate · cost state (UNKNOWN
refuses) · portfolio state · instrument validity · duplicate intent.
Each failure is reason-coded; nothing stale reaches ORDER_READY.

## A6/A7 — idempotency and the kill switch

`intent_id = hash(decision_id, expression_id, intent_version)`; the
ledger (not memory) is consulted, so a restart cannot duplicate an
ORDER_READY intent — a new intent_version legitimately can. The kill
switch is a marker FILE (`touch ops/EXECUTION_KILLED`): Claude-
independent, restart-proof, throwable from a shell in one second,
ledgered on engage/release/block.

## C — options expression V2 (diagnostic only)

Underlying-first by construction: `evaluate()` refuses without an
underlying decision id — a chain can never originate a thesis. Bounded
structures only (STOCK / LONG_CALL / LONG_PUT / CALL|PUT_DEBIT_SPREAD),
built only where broker capability permits, otherwise a labeled
UNAVAILABLE candidate. Deterministic payoff grid at declared underlying
scenarios (max loss = debit, capped gains = width − debit, verified).
Greeks are never invented (`UNKNOWN_NOT_SOURCED`). **An uncalibrated
distribution cannot produce a calibrated expected option return** — the
engine returns scenario-conditioned payoffs explicitly labeled NOT an
expected value, and in ERD-1 concludes STOCK as the honest default.

## D — rehearsals (both passed)

D1 equity, unauthenticated: 11/17 checks pass, refused
BLOCKED_BROKER_AUTH with the six broker-dependent failures named.
D1 with a labeled mock read/review surface: **17/17 → ORDER_READY**,
`live_placement: SEALED`, `authorization_power: NONE_ERD1`.
D2 options: STOCK chosen, EXPRESSION_DIAGNOSTIC_ONLY, max loss $2,000,
all three candidates recorded with reasons.
All rehearsal records carry `rehearsal: True`,
`production_evidence: False`, and the `EXECUTION_REHEARSAL_FIXTURE` tag
in a SEPARATE ledger. **PAPER_ELIGIBLE appears only inside the fixture**
— production Capital still cannot emit it.

## B — the Flight Deck

`python scripts/flight_deck.py` → http://127.0.0.1:8787. Consumer only:
reads canonical ledgers, creates no state, no second source of truth,
zero external dependencies (vanilla-canvas chart over APEX's own bars —
no CDN, no TradingView licensing). Panels: live BTC chart with VWAP ·
Captain directive · Digital World with feed health · Oracle (views kept
separate) · Assassin · Capital · Execution (with SEALED + kill switch) ·
shadow positions · Equity Epoch 1 · Opportunity Board · readiness board.
Unavailable sensors render UNAVAILABLE in italic grey — a missing feed
must LOOK missing.

## What ERD-1 did NOT do

No strategy semantics changed (equity Epoch 1 and Crypto Epoch 0 remain
frozen); no production decision was created, read destructively, or
mutated; Credit 5 and the holdout remain sealed; the Captain remains
observational; production Capital still cannot reach PAPER_ELIGIBLE.

## ERD-1 finding: the architecture registry caught its own drift

Building `apex/execution/` turned three of APEX's own guards red — the
layer contract said PLANNED, the audit-claim test asserted the directory
did not exist, and the component registry required a real entry for any
BUILT layer. Nothing was silenced. The contract now reads
`BUILT_READ_REVIEW_ONLY_LIVE_SEALED`, the two components are registered
with their forbidden dependencies and activation prerequisites, and the
absence test was replaced by something with more teeth rather than less:
`scan_package_for_placement("apex")` must return clean, so the guard now
proves no module *defines* a placement function instead of merely proving
a directory is missing. `backtest`, `risk`, and `monitoring` remain in
the absence list — only `execution` earned removal.

The name-scan exemption widened from one module to three
(`broker.py`, `sealing.py`, `robinhood.py`): a deny-list and a tripwire
cannot be written without naming what they refuse.

Full suite after ERD-1: **936 passed, 1 skipped** (the skip is the
pre-existing Stage-4 vendor deferral).
