# Commissioning package — SPY options paper pilot (first live-data run)

**Status: PACKAGE PREPARED. Nothing in it is activated.** This document is the single
concise commissioning decision request the mandate asks for. It distinguishes what
is implemented, what is synthetically verified, what is independently accepted
(nothing yet), and what is operationally authorized (nothing).

## 1. Scope

| Item | Value |
|---|---|
| Underlying | SPY only (QQQ, IWM as cross-market context, not traded) |
| Expression rule | frozen `PILOT_RULE_V1`: heuristic direction → BUY one CALL (LONG) / PUT (SHORT); nearest expiry ≥ 21 DTE; nearest-ATM strike; quantity 1 |
| Forecast source | frozen EXP-002 L-arm artifact (`params_hash ca04fc6e713e1a5c`, provenance INVALID_NULL_CONTROL, no edge claim) through `apex.pulse_options.inference`; recorded, not selecting |
| Exit policy | frozen `EXIT_AT_HORIZON_15M_V1` (due +900 s, 120 s window, ≤5 attempts, exhaustion keeps the obligation) |
| Execution policy | `EXECUTION_POLICY_V1` (0.25 s simulated latency, 3 fill attempts, quantity ∈ {0,1}, size rule, SIMULATED label) |
| Risk | certified authority: real `risk_certificate.certify()` + `risk_kernel.check()` (paper limits: $500/trade, $1,500 aggregate, $600 same underlying, $1,000 family, $1,000 session drawdown halt); envelope `RISK_ENVELOPE_V1`; atomic reservations |
| Start condition | operator authorization recorded; fee schedule PROVIDER_VERIFIED; live smoke (§A of the request doc) passed; `APEX_PILOT_LIVE_DATA=ENABLED` for the pilot process only |
| End condition | 10 regular sessions, or any stop rule below |
| Evidence class of output | PROSPECTIVE_PAPER, `data_provenance: LIVE_FEED`, `execution_mode: PROSPECTIVE_ORCHESTRATION`; not alpha evidence by definition |

## 2. Blocking prerequisites (each is an operator decision or an external fact)

1. **Fee schedule verification.** `UNVERIFIED_FEES` refuses every LIVE_FEED intent. A `FeeSchedule` with
   `provenance=PROVIDER_VERIFIED` and a `verified_against={provider, document, date}` record must be committed
   in a reviewed change. An unknown cost is not zero.
2. **Kernel cap vs SPY option prices.** `max_risk_per_trade` $500 ⇒ max entry price $5.00 per contract. SPY ATM
   21-DTE options typically price above that, so the pilot rule will refuse most SPY ATM intents as
   `RISK_ENVELOPE_INFEASIBLE`. Decision needed: (a) accept a mostly-WAIT pilot, (b) change the strike rule (a new
   reviewed rule), (c) an operator-approved, dated limit change. Not tuned here.
3. **Live smoke** (`docs/OPTIONS_PILOT_LIVE_SMOKE_AND_COLLECTION_REQUEST.md` §A) executed and reviewed,
   with the HTTP client wired in the same reviewed change.
4. **Prospective collection** (§B) of at least a few sessions so that live-bar features can be compared to the
   historical recipe before a forecast is trusted even for recording. (Prefix invariance and recipe parity are
   proven on synthetic bars only.)
5. **Independent acceptance** of M0–M6 candidates (all currently `SYNTHETIC_VERIFIED`, none `ACCEPTED`).
6. **Deployment mechanics**: a release pin, a systemd unit with the standard containment, the maintenance
   block lifted by the operator — none done here.

## 3. Expected records per session (from the representative-scale synthetic run)

Ten synthetic sessions × three symbols × three cycles through the real entry point
(`scripts/options_pilot_scale_check.py`, output `docs/evidence/scale_check_10_sessions_OUTPUT.json`):

| Quantity | Observed |
|---|---|
| records total / ledger bytes | 470 / 1.9 MB |
| forecasts = intents = fills = decisions | 90 each (every scan ends in exactly one decision) |
| outcomes | 63 (every FILLED position discharged) |
| expired intents (stale-quote sessions, WAIT then TTL) | 18 |
| intents cancelled at close | 9 |
| binding problems (forecast↔intent↔fill↔outcome, risk provenance, kernel re-check) | 0 |
| chain verification / cash identity / integrity problems | verified / holds / none |
| open positions at the end | 0 |
| elapsed / peak RSS | 54 s / 129 MB (Mac, no containment) |

For SPY alone at 15-minute cycles over a 6.5-hour session, expect ≈ 26 scans ⇒ ≈ 26 forecasts, ≤ 26
intents, ≤ 26 fills, ≤ 26 outcomes, ≈ 26 decisions plus refusals, one open and one close record: ≈ 150–200
records/session, ≈ 0.6 MB/session. The synthetic P&L in the scale run (+1,135.89 over 10 sessions) is an
artefact of constant fixture quotes and is **not evidence of anything**.

## 4. Data and order authorities

| Authority | State |
|---|---|
| Market data (Alpaca SIP bars/NBBO; ThetaData chain) | gated by `LiveGate`: switch + credentials; **disabled** |
| Orders | none exist on the pilot path; fills are SIMULATED and labelled; no broker adapter |
| Risk | certified authority approves against the Book; production route refuses until fees are verified |
| Ledger | a NEW pilot ledger path; the legacy live ledger (94 records) is never written |

## 5. Failure stop conditions (the loop stops and reports; the operator decides)

- provider failures: three consecutive `ProviderUnavailable`/parse failures on any input;
- ledger persistence failure (`PERSISTENCE_FAILED`/`PERSISTENCE_UNPROVEN`) — the loop halts, nothing proceeds;
- any Book integrity problem or cash-identity failure at a close;
- session drawdown halt (kernel refuses new intents; existing positions still exit under the policy);
- exit-window exhaustion on any position (`EXIT_WINDOW_EXHAUSTED`: the obligation remains; operator decision);
- chain verification failure at start-up.

## 6. Recovery procedure

Re-run the same command with the same `--pilot-session-id`:
- an open session resumes (`resume`: expired intents get terminal records, WAIT intents are re-quoted within
  TTL, pending intents execute once), recovers unresolved positions and drives them through the exit policy;
- a closed session runs RECOVERY_ONLY (no new scans), attempting labelled recovery exits for outstanding
  positions and writing a new numbered close record;
- another session's obligations are reported as foreign and untouched.

## 7. Operator commands (generated from the implementation; all refuse without the gates)

```bash
# dry plan of the read-only smoke (contacts nothing)
python scripts/options_pilot_live_smoke.py --symbol SPY --minutes 90 --dry-plan
```

```bash
# the pilot session (production route). Without APEX_PILOT_LIVE_DATA=ENABLED + credentials every scan refuses LIVE_DATA_DISABLED
python scripts/options_paper_session.py --pilot-boundary --ledger /apex-data/pilot/pilot_ledger.jsonl --out /apex-data/pilot/report_<date>.json --symbols SPY --minutes 390 --interval-min 15 --pilot-session-id PILOT-<date> --pilot-release <commit>
```

```bash
# representative-scale synthetic verification of the same path (no network)
python scripts/options_pilot_scale_check.py --out-dir /apex-data/tmp/pilot_scale --sessions 10 --cycles 3
```

```bash
# recovery of a closed session (same id) after a failure
python scripts/options_paper_session.py --pilot-boundary --ledger /apex-data/pilot/pilot_ledger.jsonl --out /apex-data/pilot/recovery_<date>.json --symbols SPY --dry-run --pilot-session-id PILOT-<date> --pilot-release <commit>
```

## 8. What a ten-session pilot can and cannot establish

It can establish observability, recovery, record completeness and after-cost accounting mechanics. It
cannot establish forecast skill or edge: the forecast source is an INVALID_NULL_CONTROL artifact recorded for
engineering continuity, and ten sessions are not a sample plan. Statistical evaluation needs its own
registered study contract (`apex.worldmodel_wb.study_contract`). Operational success, forecast skill,
after-cost economics and release readiness are reconciled separately.

## 9. State summary

| Component | Implemented | Synthetically verified | Independently accepted | Operationally authorized |
|---|---|---|---|---|
| Recording boundary (M0) | yes | yes (r4, contained run at `360536cb`) | pending | no |
| Accounting / paper loop (M1) | yes | yes | pending | no |
| Twin / adapters (M2) | yes | yes (fixtures) | pending | no (live gated off) |
| Workbench (M3) | yes | yes | pending | n/a (research) |
| Multiverse / pricing (M4) | yes | yes | pending | n/a |
| Fusion / supervision / experience (M5) | yes | yes | pending | no (authority NONE) |
| Operator view + this package (M6) | yes | yes | pending | no |
