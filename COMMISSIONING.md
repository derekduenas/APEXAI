# APEX COMMISSIONING BOARD
**Mode entered 2026-08-21 post-Friday (operator directive).**

## THE LAW
> LAYER N DOES NOT EXIST UNTIL LAYER N-1 PASSES NATURAL ACCEPTANCE.

Tests are necessary, never sufficient: a layer passes only against real
live inputs over a defined period, with acceptance metrics that
reconcile against reality (born of coverage=1.0 during 26% tape loss).
Nothing is deleted; downstream layers stay built but are NOT judged and
carry no operational status until their turn.

## LAYER STATUS

| # | Layer | Status | Evidence |
|---|-------|--------|----------|
| 0 | HOST | **COMMISSIONING** — FAILED Fri (clamshell sleep, 26% tape loss); sentinel live since Fri 15:44 ET; caffeinate -i on fabric; **awaiting first clean unattended session (Mon)** | results/host/*, ops/host_sentinel.sh |
| 1 | ROBINHOOD READ-ONLY | **PASS (Fri 15:30 ET)** — CONNECTIVITY=COMMISSIONED (6/6 reads, byte-identical, auth persisted, READ_ONLY, orders SEALED). **LIVE_CAPITAL_ACCOUNT=NOT_YET_COMMISSIONED** (acct ••••2160 UNFUNDED; any future funding/routing change requires separately proving the intended capital account is the one APEX sees, before any execution layer) | results/commissioning/layer1_robinhood_acceptance.json |
| 2 | ALPACA TRANSPORT | **COMMISSIONING** — HEARTBEAT_TIMEOUT labeled (client provably healthy at every event); pong telemetry added (which side of heartbeat dies — answers Mon); tape_continuity axis added (coverage can no longer lie); **awaiting Mon natural acceptance** | reconnect ledger telemetry, health tape_continuity |
| 3 | RAW→CANONICAL BARS | **PROVISIONAL PASS (Fri)** — reconciled vs Alpaca official REST aggregates: transport-delivered minutes are EXACT (1575/1575 trades, volume byte-identical); deficit fully attributed to L0/L2 damage; found+fixed COMPLETE_HEALTHY mislabeling of mid-minute losses (MAX_INTRA_GAP_S=20); confirm on clean-host session | results/commissioning/layer3_bar_reconciliation.json |
| 4 | DATA QUALITY | **PROVISIONAL PASS (Fri)** — component logic passed (injection bench 4/4 + 4,437 natural refusals); system-level PASS awaits clean L0/L2 upstream | results/commissioning/layer4_quality_acceptance.json |
| 5 | CANONICAL MARKET STATE | **PROVISIONAL PASS (Fri)** — component logic passed (independent recompute 1e-9 match); system-level PASS awaits clean L0/L2 upstream | results/commissioning/layer5_market_state_acceptance.json |
| 6 | CURVE V2 | **PROVISIONAL PASS (Fri)** — 3,078 states 100% V2; non-degenerate (elevated 9% of supported); UNKNOWN honest on gaps; finalize on clean-host session | results/commissioning/layer6_curve_acceptance.json |
| 7 | LEADING EDGE + **ENTRY GEOMETRY ENGINE (unbuilt — commissioned here)** | FROZEN / GAP DECLARED | — |
| 8 | ASSASSIN (one wound at a time) | FROZEN AS BUILT | — |
| 9 | CAPTAIN | FROZEN AS BUILT | — |
| 10 | PATTERN / HUNTER INTELLIGENCE | FROZEN AS BUILT (shadow runtimes CONTINUE for evidence accumulation; not judged) | — |
| 11 | OUTCOME + MEMORY | FROZEN AS BUILT (near-ready; explicit recommission later) | — |
| 12 | FORECAST (asymmetry-hunting spec) | FROZEN AS BUILT | — |
| 13 | CAPITAL (NO_TRADE/NORMAL/STRONG/RARE_ASYMMETRIC attack doctrine) | FROZEN AS BUILT | — |
| 14 | EXPRESSION (weapon auction) | FROZEN AS BUILT | — |
| 15 | PAPER EXECUTION (blotter) | **PLUMBING COMMISSIONED (Fri evening, off-market)** — full lifecycle/idempotency/duplicate-prevention/restart-recovery/no-live-route proven with COMMISSIONING_TEST orders; ALPACA_PAPER adapter refusing until operator generates dedicated paper keys; **APEX intelligence NOT connected** | results/commissioning/layer15_paper_plumbing.json |
| 16 | PAPER / TINY LIVE | NOT BUILT — **blocked also by unfunded account** | — |

## FOUNDATION: NOT COMMISSIONED
Upstream truth must be commissioned before downstream truth becomes
final. L3–L6 PROVISIONAL evidence is retained; they promote TOGETHER
when Monday's clean L0+L2 session reconfirms them on clean natural data.

## THE PROMOTION RULE (Monday)
```
IF L0 PASS AND L2 PASS
THEN independently reconfirm L3 bars / L4 quality / L5 state / L6 Curve
IF ALL PASS ON CLEAN NATURAL DATA:
    FREEZE L0–L6 · FOUNDATION COMMISSIONED · AUTHORIZE L7
```

## THE FREEZE LAW
Once frozen, L0–L6 may not be casually edited because of any future
Captain/Pattern/Forecast problem. Modifying a frozen layer requires
EXPLICITLY REOPENING commissioning: version bump + regression
acceptance. Frozen layers are floors, not moving targets.

## L2 HEARTBEAT — MECHANISM UNDERSTOOD (Fri evening, pong telemetry)
Server/path stops answering protocol pongs under stream load while
market data keeps flowing (msg_age <3s at every timeout; one 58s
connection got ZERO pongs while streaming). The library's watchdog then
kills healthy connections. Proposed remedy (AWAITS OPERATOR
AUTHORIZATION, an L2 behavior change): application-level liveness —
data-frame arrival IS the heartbeat; reconnect only on genuine message
staleness. NOT a bigger timeout.
Evidence: results/commissioning/layer2_heartbeat_mechanism.json

## L0 MONDAY REQUIREMENTS (prevention, not detection)
AC POWER + SLEEP PREVENTED + LID/CLAMSHELL PLAN (operator attestation)
+ SENTINEL + PROCESS SUPERVISION + DATA-PROGRESSION WATCHDOG.
Gate: `scripts/l0_preflight.py` — refuses (exit 1) unless all
checkable requirements hold. Dry-run Fri 17:23 ET: NOT_READY
(ac_power=false — the laptop was still on battery).

## THE AUTHORITY LADDER (operator doctrine: "Paper early. Real money late.")
```
OBSERVE  ->  PAPER_EXPLORATORY  ->  PAPER_AUTHORIZED  ->  TINY_LIVE  ->  LIVE_SCALE
```
Current level: **OBSERVE** (apex/governance/authority_ladder.py).
Every transition = an explicit operator-authorized ledger record;
one step at a time; code can never self-promote. PAPER_EXPLORATORY
trades are real sealed decisions tracked like real trades but NEVER
proof of edge and NEVER live-promotion evidence; PAPER_AUTHORIZED
(forecast gates + Capital approval + auction + sizing) is the cohort
that can argue for TINY_LIVE. COMMISSIONING_TEST orders are
infrastructure, allowed at any level, never in strategy performance.

## THE PATH
```
NOW        paper plumbing commissioned (done Fri evening)
MONDAY     L0-L6 FOUNDATION PASS -> FREEZE
NEXT       L7 Entry Geometry -> commission
THEN       Captain/Hunter natural acceptance
           -> operator enables PAPER_EXPLORATORY
           -> actual APEX paper trades begin (labeled, non-promotable)
           -> forecast evidence accumulates -> PAPER_AUTHORIZED
           -> prove economic edge -> TINY_LIVE
```
KNOWN RISK (recorded): the stored Alpaca DATA keys authenticate against
the LIVE trading API (acct 8453***, $0). The paper package refuses that
host structurally; nothing in APEX may ever use those keys for orders.

## STANDING DECISIONS
- Shadow runtimes (Observatory, Frontier2) keep running to accumulate
  prospective evidence; they are READ-ONLY consumers and cannot perturb
  Layers 0–2 measurements. They carry **no operational status** until
  their layer's turn. (Operator may override to full shutdown.)
- Layer 2 open question for Monday: at each HEARTBEAT_TIMEOUT, was a
  pong EVER received on that connection, and how stale was the last one?
  Do not raise timeouts until the mechanism is understood.
- Layer 0 residual risk that userland cannot fix: clamshell sleep.
  Operator options: lid open + AC · `sudo pmset disablesleep 1` ·
  move APEX off a laptop.

## MONDAY — DELIBERATELY BORING
```
08:00–09:30  l0_preflight (must be READY) + L2 startup validation
09:30–16:00  LEAVE IT ALONE (observe host/network/ws/pong/tape/bars/
             quality/state/Curve)
after close  reconcile vs independent Alpaca REST aggregates
             -> ONE verdict via the promotion rule
```
Do NOT commission Layer 7 Monday morning. Perturbations (like Friday's
15:56 restart) are recorded as such, never as free validation.
