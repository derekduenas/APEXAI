# Commissioning package — Monday 2026-09-14 (prepared 2026-09-12/13, weekend commissioning)

Candidate branch `weekend-commissioning-001` (from review candidate `778a5c9`). **Package commit `ba4a8654341f3e184034e368c4f5a55619a43e87`**, tarball sha256 `b2e65343b25c7a7c38eefb94bc7d12b3aa24d418cbc410c998be23e49040851a`, decision-path tree digest `1d5aa7d2…` (`docs/evidence/release/RELEASE_MANIFEST.json`; `startup_identity_check.py` exit 0 against the build tree). Contract blob `a0228fac…` unchanged.

## 1. Identities

| Item | Identity |
|---|---|
| Code | weekend candidate commit (see manifest); reviewed base `778a5c9`; `main` `b9998d0` |
| Config | `LiveWiring(attach_market_data_http=True, fee_schedule=<operator choice>, event_snapshot_fn=<catalyst twin snapshot>, event_gate_authority="SHADOW")`; selection policy `PILOT_RULE_V2` |
| Models | none fitted on real data; `PILOT_RULE_V2` is a rule; the forecast artefact is the frozen EXP-002 L-arm (INVALID_NULL_CONTROL, recorded, not selecting) |
| Fees | `ROBINHOOD_RHF_2026` transcribed from the broker's PDF (sha `7f9c86bf…`); NOT authorized → live default stays `UNVERIFIED` |
| Event policy | `EVENT_GATE_V0` SHADOW; scheduled snapshot `SCHED-2026-09-12` (FOMC 09-16 CRITICAL) |
| Exit / execution | `EXIT_AT_HORIZON_15M_V1`, `EXECUTION_POLICY_V1` (unchanged) |
| Risk | certified authority + kernel re-check; paper limits $500/trade, $1,500 aggregate, $1,000 session drawdown halt (unchanged) |

## 2. Layers invoked on the Monday policy, and what is explicitly unavailable

forecast (recorded, non-selecting) → **event/regime state** (event context recorded; regime NOT_AVAILABLE_IN_PILOT) →
**simulation: NOT USED** (rule path) → candidates = chain rows after `DUPLICATE_POLICY_V1` → `PILOT_RULE_V2` → persisted
intent with BEFORE fields → certified risk reservation → fill (fresh quote, 15 s) → exit at +15 min → reconciled Book →
grading from sealed records. FULL/JOINT funnels are wired but not selected: JOINT has no authorized fit
(`INSUFFICIENT_TRAINING_DATA: 0 completed sessions`); FULL has no live bar history until the client is attached and
warmed.

## 3. Evidence: static review vs independently reproduced vs builder-reported

| Claim | Static review | Independently reproduced | Builder-reported |
|---|---|---|---|
| Adverse IV sign, spread into PRIME, 120 s ranking | confirmed by the external reviewer at `778a5c9` | no | 302 affected-suite passes at `778a5c9` |
| Brick 1–5 changes on this branch | none yet | no | weekend suites (numbers in §7) |
| Provenance acceptance from a clean checkout with the interpreter outside it | — | reproduced 2026-09-12 (PASS) | — |
| Full-suite node comparison | — | `docs/evidence/full_suite_node_comparison_778a5c9.json` | 15 failures, all pre-existing or checkout-layout; 6 host-relevant rows open |
| EXP-002/EXP-004 intermittent failure | — | UNREPRODUCED / CAUSE_UNKNOWN (3 attempts) | — |

## 4. Walk-forward

Contract frozen, execution NOT AUTHORIZED, 0 completed fittable sessions held (1 partial prospective session). Concrete
`R4-FIT-002` / `R4-FIT-001` requests in `docs/BRICK4_WALKFORWARD_CONTRACT.md`. Any future replay is reported
EXCLUDING THE EVENT LAYER (no point-in-time news archive exists).

## 5. Commands

Startup / health / stop / rollback: `docs/DEPLOYMENT_PACKAGE_WEEKEND.md`. Proposed read-only smoke (needs authorization):
```
APEX_PILOT_LIVE_DATA=ENABLED /opt/apex/shared/venv/bin/python scripts/options_pilot_live_smoke.py --symbols SPY --closed-market-ok
```
A weekend run can prove connectivity, authentication classification and parsing only; every age gate will (correctly)
refuse closed-market quotes, and no threshold is relaxed to make it pass.

## 6. Operational state and schedulers

Host: paper service inactive, maintenance block PRESENT, collector inactive, deployed release `73fc712…` (pruned),
`DEPLOYMENT_DIVERGENCE_001` OPEN. Mac: nightly pull ARMED and ran 2026-09-12; 20 launchd jobs loaded; automation
checkout on `main`. Full inventory in the deployment package.

## 7. Blockers and GO / NO-GO

| Requirement | State | Blocks observation? | Blocks paper execution? |
|---|---|---|---|
| Release pinned from a reviewed commit and installed; identity check at start | package builder ready; not installed; `DEPLOYMENT_DIVERGENCE_001` open | **yes** | yes |
| Live bars/NBBO client attached and smoke-tested on the host | attachable via `LiveWiring`; smoke NOT authorized/run | **yes** | yes |
| Chain/quote client smoke on the host | wired; smoke NOT authorized/run this weekend | **yes** | yes |
| Fee document authorized | transcribed; NOT authorized | no (observation records `NOT_ESTIMABLE`) | **yes** (certified authority refuses every LIVE_FEED intent) |
| Event stream cycling on the host | catalyst ledgers exist on the host; Mac cycle 2026-08-26 failed 8/8 on SSL; not verified this weekend | no (recorded `STALE`/`UNAVAILABLE`) | no (gate is SHADOW) |
| Warm-up (65 min of bars) before any forecast | policy in place | no | yes (by construction) |
| Maintenance block lifted, live switch set for the pilot process only | not done | **yes** | yes |
| Paper capital authorized | not done | no | **yes** |
| Stopping rule | proposed: 10 regular sessions or any stop rule in the commissioning package §5 | — | — |
| **Release change with an open position** | `FINDING_RELEASE_CHANGE_STRANDS_POSITION.md`: a restart under a different release strands the previous release's open position; operational rule in the finding; repair proposed, not applied | no | **yes** (no deploy/rollback while a position is open) |

**Observation mode for Monday 2026-09-14: NO-GO as of this package**, for three reasons that are each one operator
action plus one host step: the release is not installed with its identity check, the market-data smoke is not
authorized, and the block/switch are in place. If those three are done before 09:30 ET Monday, observation mode is
GO in **reduced observation** (missing layers: fees `NOT_ESTIMABLE`, event stream possibly `STALE`, no simulation
layer, no walk-forward evidence); it is not a full-funnel success and is labelled so on every record.

**Paper execution for Monday: NO-GO.** Fee document not authorized; paper capital not authorized;
`DEPLOYMENT_DIVERGENCE_001` open. A paper trade is allowed only after warm-up, forecast, event, economics and risk
requirements pass on the live records; nothing is forced at the bell.

## 8. Learning boundary

Immutable outcome joins, honest error attribution, a challenger queue. No autonomous parameter promotion, no online
self-rewriting. Local quote-based paper simulator only: **no broker-paper order routing is claimed**; no broker
acknowledgment is on any tested path.
