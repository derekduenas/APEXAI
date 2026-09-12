# Deployment package — weekend commissioning candidate (prepared, NOT activated)

Everything here is preparation. No merge, no rollout, no maintenance-block removal, no switch. Activation is an
operator action against the exact package identified below.

## Reconciliation of the three trees

| Tree | Where | Commit | Relationship |
|---|---|---|---|
| Reviewed repository | `main` on GitHub / Mac `~/apex-equities` | `b9998d0` (+ candidate `778a5c9` on `decision-path-repair-001`, + weekend branch) | the reviewed tree |
| Canonical host checkout | `/opt/apex-repo` on the droplet | `eca00a9e5`, branch `milestone1-r2` | an ancestor lineage now merged into `main`; contains no file `main` lacks (verified 2026-09-11) |
| Deployed release | `/opt/apex/current → /opt/apex/releases/73fc712d…` | tip of `milestone1-recovery-candidate` | a pruned tree (232 files fewer); its two substantive patches are in `main`; unique code: none |

Nothing is deleted. Six release directories exist under `/opt/apex/releases`; all stay. Reconciliation = install the
candidate release beside them and re-point the link, when authorized.

## The package

Built by `scripts/build_release_package.py --commit <weekend candidate> --out out/release/`:
`apex-<sha>.tar.gz` (content-addressed), `RELEASE_MANIFEST.json` (commit, tarball digest, decision-path module digests,
dependency expectations, service command pin), `ROLLBACK.json` (current link target + the exact re-point command),
`startup_identity_check.py` (compares `runtime_identity()` against the manifest at process start and exits non-zero on
any mismatch). The runtime also stamps `runtime_identity` on the report and on `pilot_session_open`.

**Service command pin** (to be written into the unit only when the operator activates):
`/opt/apex/shared/venv/bin/python -u /opt/apex/releases/<sha>/scripts/options_paper_session.py --pilot-boundary --pilot-selection-policy PILOT_RULE_V2 …`

Startup: `systemctl start apex-options-paper.service` (after the block is lifted). Health: `startup_identity_check.py
RELEASE_MANIFEST.json` exit 0; heartbeat under `/apex-data/core/heartbeats`; the report's `policy_identity.consistent`
and `runtime_identity.git_commit == manifest.commit`. Stop: `systemctl stop apex-options-paper.service` (positions
remain obligations on the ledger and are recovered on the next start of the SAME release). Rollback: the command in
`ROLLBACK.json`.

## Scheduler writers (inventory; none reconfigured)

| Where | Job | Writes | Status |
|---|---|---|---|
| Mac launchd | `com.apex.nightly-pull` (02:30 local; ran 2026-09-12 14:07Z after a catch-up) | `data/live/sharadar`, `data/live/paper_root`, `results/paper/*`, `results/reality/*`, `logs/nightly_pull.log` in `~/apex-equities` | ARMED; runs `main` from the automation checkout; its outputs are left uncommitted and untouched |
| Mac launchd | `com.apex.event-capture` (15 min) | `apex/events` EDGAR archive | loaded |
| Mac launchd | host-sentinel, btc-derivatives, edgeforge-observatory, btc-ws, crypto-daemon, orchestrator (running) and 14 others (loaded) | their own `results/`/`logs/` paths under `~/apex-equities` | untouched |
| Host systemd | `apex-health.timer` (10 min), `apex-edge-sensor`, `apex-event-optshadow-entry/exit`, `apex-event-shadow`, `apex-edge-resolve` (Mon 2026-09-14) | `/apex-data/...` under release `5f561448…` | untouched |
| Host | `apex-options-paper.service` | `/apex-data/core/options_live_ledger.jsonl` (legacy path) | inactive, maintenance block present |
| Host | `apex-pilot-collector` | `/apex-data/pilot_collection/<day>/` | inactive |

Weekend outputs are isolated in `~/apex-weekend-wt/out/` and the branch `weekend-commissioning-001`; the automation
checkout `~/apex-equities` was returned to `main` before any weekend work.

## What activation requires, in order

1. Operator authorizes the fee document (`ROBINHOOD_RHF_2026`, transcribed from the broker PDF sha `7f9c86bf…`), which selects it in `LiveWiring(fee_schedule=…)`.
2. Operator authorizes the read-only market-data smoke on the host (proposed command in `COMMISSIONING_PACKAGE_2026-09-14.md`).
3. Install the package, verify `startup_identity_check.py`, write the service pin, keep the maintenance block.
4. Operator lifts the block and sets `APEX_PILOT_LIVE_DATA=ENABLED` for the pilot process only, in observation mode (no paper capital).
5. Separately: paper capital authorization for paper execution.
