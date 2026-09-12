# Stage 1 entry record — 2026-09-12 (PIPELINE_COMMISSIONING, rule path only)

Pre-registration: `docs/STAGE1_PREREGISTRATION.md` (committed before any seal; id `STAGE1-PREREG-2026-09-12`).

## Deployed
| Item | Value |
|---|---|
| main | `a6e123d36a89ac70ca512243336eb1561a9b9cd3` |
| `/opt/apex/current` on the host | `/opt/apex/releases/a6e123d36a89ac70ca512243336eb1561a9b9cd3` (**deployed hash == main hash**) |
| tarball sha256 | `c8e71fca310f92dc109ced45901d196a8ee63adebd19fc917232e18ddf5166ee` |
| decision-path tree digest (manifest = loaded) | `e57c98f41866007623ad04bac3b40eef70f6287362e640f75720b48110ff19e1`, `startup_identity_check.py` exit 0 on the host interpreter (3.12.3, numpy 2.4.6, scipy 1.17.1, pandas 3.0.5) |
| previous release (rollback target) | `/opt/apex/releases/73fc712d355032e0a66b41675ba114491b04799d`; an intermediate `fcad5df…` was installed and superseded the same hour, book flat both times (A-012 honoured) |
| maintenance block / legacy service | PRESENT / inactive (untouched) |

## Smoke (closed market, deployed release, containment)
Unit `apex-pilot-smoke-2026-09-12c`, `--pilot-live-wiring`, `PILOT_RULE_V2`, `--dry-run`. LiveGate enabled from the
secret backend (presence only). Endpoint health: Alpaca `stocks/SPY/bars` OK, `stocks/SPY/quotes/latest` OK
(`HTTP_POLICY_V1`). Decision: REFUSE `FEATURE_UNAVAILABLE: ret_1 is UNKNOWN` — correct on a weekend (no completed bar
in the window); no age threshold relaxed. Chain and quote endpoints were not reached (forecast refused first); they
were exercised by the collector on 2026-09-11 and will be on Monday. Fee schedule on the report: `ROBINHOOD_RHF_2026`,
`PROVIDER_VERIFIED`. Smoke ledger `/apex-data/core/options_pilot_smoke_2026-09-12c.jsonl` (separate from Monday's).

## Armed for Monday
User-level transient timer on the host (`loginctl enable-linger apex` set so it survives logout):
`apex-pilot-stage1-2026-09-14.timer` → 2026-09-14 13:24:00 UTC (09:24 ET), runs from `/opt/apex/current`:
```
/opt/apex/shared/venv/bin/python /opt/apex/current/scripts/options_paper_session.py --pilot-boundary --pilot-live-wiring \
  --pilot-selection-policy PILOT_RULE_V2 --symbols SPY --minutes 390 --interval-min 15 \
  --ledger /apex-data/core/options_pilot_ledger.jsonl --out /apex-data/history-a/pilot_2026-09-14.json \
  --pilot-session-id PILOT-2026-09-14 --pilot-release a6e123d36a89ac70ca512243336eb1561a9b9cd3
```
`MemoryMax=1400M`, `APEX_PILOT_LIVE_DATA=ENABLED` for that process only. Simulated fills (`"simulated": true`); no
placement surface exists. Expected first scans: forecast refusals until the 65-minute warm-up completes (~10:35 ET),
then rule-path intents with certified approval under the authorized fees; every record carries the FOMC snapshot.

Inspect / stop:
```
systemctl --user list-timers apex-pilot-stage1-2026-09-14.timer
systemctl --user stop apex-pilot-stage1-2026-09-14.timer          # disarm before Monday
systemctl --user stop apex-pilot-stage1-2026-09-14.service        # stop a running session (positions stay obligations on the ledger)
journalctl --user -u apex-pilot-stage1-2026-09-14.service -f
```

## Known reduced layers on Monday (labelled on every record)
- Event stream: the release directory has no `results/catalyst` ledgers → unscheduled stream `UNAVAILABLE` (recorded);
  scheduled stream from the committed snapshot (FOMC 2026-09-16 CRITICAL). Gate SHADOW.
- Funnel/joint paths not selected. Bar client attached: the funnel's 400-bar history is requested from Alpaca as
  7 days of 1-minute bars on the first fit, so **days-to-satisfaction = 0 additional days once a funnel session runs**
  (2 sessions if only the collector's own bars were used). Not gating Stage 1.
- Certified fees: `ROBINHOOD_RHF_2026`; SEC fee computed at the $5.00 cap and rounded up (overstates cheaper sells by ≤ $0.01).

## Stage 1 deliverable
The first date producing a complete scored observation chain, reported per session with candidates constructed /
certified / selected, modelled entry cost, modelled exit, realised simulated P&L. Exit: 10 consecutive sessions,
zero unresolved-past-due (calendar clock), `n_effective_dates > 1`.
