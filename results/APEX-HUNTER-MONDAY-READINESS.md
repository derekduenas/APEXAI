# APEX HUNTER — MONDAY READINESS (assessed Saturday 2026-08-15)

## FULL ARCHITECTURE CONNECTED: YES
(Built ≠ proven. Every seat exists and is typed; dormant seats report
their gate instead of pretending readiness. 847 tests green.)

| Component | Status |
|---|---|
| FORWARD CLOCK | ACTIVE (launchd verified; fast-exit correct on Saturday) |
| INTRADAY DATA | ACTIVE (EODHD forward; historical = laboratory only) |
| DIGITAL TWIN (snapshot) | ACTIVE |
| REGIME | ACTIVE-PARTIAL (crude conservative-only intraday proxy) |
| CHARTSTATE | ACTIVE |
| RELATIVE STRENGTH | ACTIVE |
| SCANNER | ACTIVE |
| PLAYBOOKS | ACTIVE (H-001, H-002 frozen; catalyst DORMANT) |
| ANALOG ENGINE | BUILT / DATA_GATED |
| ML ENGINE | BUILT / DATA_GATED (UNTRAINED) |
| FORECAST BUNDLE | ACTIVE (typed absences) |
| DISTRIBUTION ENGINE | BUILT / DATA_GATED (REFUSED without evidence) |
| WORLD SIMULATOR | BUILT / OBSERVE_ONLY (on-demand, future-blind) |
| CALIBRATION | DATA_GATED (INSUFFICIENT_FORWARD_EVIDENCE) |
| SWARM | BUILT / AUTH_GATED (CLI login) |
| OPPORTUNITY ENGINE | ACTIVE (via Capital adapter) |
| CAPITAL | ACTIVE (monotone caution proven) |
| TRADE THESIS | BUILT |
| PAPER ENGINE | BUILT / NOT_AUTHORIZED in production |
| TRADE MANAGER | BUILT / CERTIFIED by counterexamples |
| RESEARCH MEMORY | ACTIVE (chained ledger + lineage + time firewall) |
| OPTIONS | DORMANT (interface only; V1 = STOCK) |
| LIVE EXECUTION | SEALED |

## Readiness checklist (Part 24, A–Z): ALL SATISFIED
Clock runs (A); archive intact and backward compatible (B); scanner/
playbooks run (C); baselines/N_eff run (D); scoreboard runs (E); every
eligible candidate reaches Capital (F); Analog Engine returns typed
provenance-aware results (G); ML refuses without evidence (H);
ForecastBundle exists (I); distribution accepts only legitimate sources
(J); Twin future-blind (K); simulator uncalibrated-and-labeled (L) and
cannot see future bars (M); Swarm fails gracefully (N); Opportunity
consumes the bundle contract (O); Capital deterministic and sovereign (P);
thesis/paper spine exists (Q); production PAPER_ELIGIBLE unreachable (R);
trade manager passes every safety counterexample (S); memory stores
complete lineage (T); options inactive (U); broker sealed (V); Credit 5
sealed (W); holdout sealed (X); full suite green — 847 passed (Y);
synthetic full-stack proof passes market-state→memory (Z).

## The twelve questions
CAN APEX SEE THE MARKET? **YES** (15-min state archive, verified).
FIND ABNORMALITIES? **YES** (frozen attention thresholds, funnel recorded).
RETRIEVE COMPARABLE STATES? **YES mechanically; memory is empty** — first
forward analogues exist only after the first realized sessions.
MODEL CONDITIONAL OUTCOMES? **The machinery, yes; the model, NO** —
UNTRAINED until ≥40 effective observations.
SIMULATE PLAUSIBLE FUTURES? **YES, as uncalibrated scenario frequencies**
(diagnostic only).
REPRESENT DISAGREEMENT? **YES** (first-class, never averaged away).
KNOW WHEN ITS FORECAST IS UNTRUSTWORTHY? **YES — today it knows they all
are** (REFUSED / UNTRAINED / UNCALIBRATED, enforced by type).
JUDGE CAPITAL? **YES** (OBSERVE/WATCH/NO_TRADE/REFUSED with reasons).
BUILD A TRADE THESIS? **YES (built), not authorized in production.**
MANAGE A PAPER TRADE? **YES (certified), not authorized in production.**
LEARN FROM THE RESULT? **YES** (realizations → scoreboard → memory →
analog/ML datasets grow by themselves).
SAFELY SAY NO TRADE? **YES — it is the expected Monday answer.**

## What will actually run Monday
09:30–16:00 every 15 min: state record → scan → candidates → analog
(NO_VALID_ANALOGS) → ML (UNTRAINED) → Swarm (BLOCKED_EXTERNAL_AUTH) →
ForecastBundle (REFUSED) → Capital (OBSERVE/WATCH) — plus baselines.
Post-close: realizations → scoreboard with the three relationships.
Zero paper trades. Zero capital. Clean evidence.

## What exists but stays dormant
World simulator (on-demand), paper/thesis/trade manager, options
interface, catalyst playbook family, distribution/calibration numerics.

## Blocked only by DATA
Analog support, ML training, calibration statuses, simulator calibration,
the three relationship verdicts, every graduation criterion.

## Blocked only by AUTH
Swarm (operator: run `claude` → `/login`, then create ops/swarm_auth_ok;
integration smoke required before any production use).

## Before PAPER_ELIGIBLE can become reachable
Phase 3 must be commissioned through governance: a forecast source
reaching a calibration status the frozen criteria accept (needs the
forward sample: ≥40 sessions / ≥100 effective / ≥2 regimes at checkpoint),
then an explicit versioned change to Capital's forecast-slot law (new
birth). Nothing else can open it — including time pressure.

## Before OPTIONS become relevant
A CALIBRATED underlying distribution + real chain data + expression-layer
governance. Before SHADOW/LIVE: everything above plus the frozen
graduation criteria (all ten dimensions) plus explicit operator
authorization; BrokerAdapter unsealing is not a code change APEX can make.
