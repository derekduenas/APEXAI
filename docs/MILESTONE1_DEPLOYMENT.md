# Milestone 1 — deployment and commissioning package (v3, against the final recovery commit)

Supersedes v2 (`e34b9c62`) and v1 (`9836986f`), both preserved in history.
Every executable reference below is to the final tested recovery commit.

## 1. Target

| | |
|---|---|
| **Deploy** | `73fc712d355032e0a66b41675ba114491b04799d` |
| Branch | `milestone1-recovery-candidate` |
| Based on | `5eff1cf5e00f21b02c537f25bcd74b1c1d317546`, the running release |
| Certified by | `recovery3` provenance run on this exact commit (see evidence) |

Historical, not targets: `39bd4412`, `07dcbb05`, `658e6971` (earlier forms of
this candidate); `3b9a26f2`, `1bb32df1`, `295d80e4` (integration line).

### Seven-file inventory against the running release — two production

| File | Kind | Change |
|---|---|---|
| `apex/governance/chain_ledger.py` | production | R1 bounded chain-tail lookup |
| `scripts/apex_orchestrator.py` | production | R2 bounded incident history, R3 maintenance preflight, R4 truthful launch reporting |
| `tests/test_chain_tail_bounded.py` | test, new | R1 |
| `tests/test_orchestrator_incident_history.py` | test, new | R2 |
| `tests/test_orchestrator_maintenance_block.py` | test, new | R3 |
| `tests/test_orchestrator_launch_truth.py` | test, new | R4 |
| `tests/test_sac1_tier1.py` | test, modified | interpreter portability port |

## 2. What R3 and R4 change about launch behaviour — read before deploying

**Maintenance enforcement was never absent.** Both blocked units carry a
systemd drop-in with `ConditionPathExists=!/apex-data/core/ops/MAINTENANCE_BLOCK_<name>`,
and the orchestrator starts through `sudo -n systemctl start`, so systemd
refuses a blocked start. That was true on the running release and remains
true. The defect was **false reporting**: `systemctl start` exits 0 when the
unit is skipped for a failed condition, and the old `start()` recorded
`STARTED` on that basis — three times on 2026-09-04 for `apex-equity-fabric`.

After R3/R4 the orchestrator:
- asks systemd, immediately before each launch, whether the unit declares a
  maintenance condition whose marker exists; BLOCKED and INDETERMINATE both
  refuse the attempt and are recorded as a bounded maintenance disposition;
- runs the start command bounded (30 s), captures its result, then reads the
  unit's `ActiveState`/`ConditionResult` and records one of
  `START_COMMAND_FAILED`, `CONDITION_REFUSED`, `PROCESS_ACTIVE`,
  `START_UNCONFIRMED`. `STARTED` no longer exists;
- treats a `CONDITION_REFUSED` as a maintenance disposition, not a spent
  recovery attempt;
- confirms work only through the existing first-work artifact on a later tick.

**Race limits.** The preflight is a file-existence check, not atomic with block
creation. A block written after preflight is caught by systemd and classified
`CONDITION_REFUSED`. Systemd is the enforcing authority throughout.

### Services the recovered orchestrator can launch

| Service | Supervised by | Maintenance condition | Can it start? |
|---|---|---|---|
| `equity-fabric` | orchestrator | marker present → BLOCKED | **No.** systemd refuses; orchestrator records MAINTENANCE_BLOCKED and does not attempt |
| `options-paper` | orchestrator | no condition declared | **Yes**, in phase RTH only, up to 3 attempts, each classified truthfully |
| `btc-paper` | systemd | — | No: orchestrator verifies, never starts |
| `edgeforge-observatory` | systemd | — | No: verifies only |

`options-paper` is therefore the one service the recovered orchestrator will
actually try to start, at the next RTH phase (Tuesday 2026-09-08 from 13:30Z).
Its unit is enabled and has no maintenance condition. **If that launch is not
wanted, place a maintenance block on it before the RTH phase, using the same
drop-in convention. Do not rely on the deployment window.** This is the one
controlled-launch decision the deploying operator must make explicitly.

## 3. Prerequisites — all must hold, in this order

1. `recovery3` regression PASS on `73fc712d` with source manifest unchanged.
2. `integration3` regression PASS on `295d80e4` (the line that carries the same
   two production files) — not transferable, but required as the integration
   gate.
3. Ledger prefix hashes captured (section 5) **immediately before** the swap.
4. Baseline unit counters captured (section 6).
5. The `options-paper` decision in section 2 made and recorded.
6. Explicit go from the reviewer under the established recovery conditions.

## 4. Deployment commands

```bash
# 1. verify the exact commit
git -C /opt/apex-repo rev-parse 73fc712d355032e0a66b41675ba114491b04799d^{commit}
git -C /opt/apex-repo diff --stat 5eff1cf5e00f21b02c537f25bcd74b1c1d317546 73fc712d355032e0a66b41675ba114491b04799d
```
```bash
# 2. ledger prefixes (section 5) and baselines (section 6) -- run those blocks now
```
```bash
# 3. build the immutable release directory
sudo -u apex git -C /opt/apex-repo worktree add --detach \
  /opt/apex/releases/73fc712d355032e0a66b41675ba114491b04799d 73fc712d355032e0a66b41675ba114491b04799d
sudo chmod -R a-w /opt/apex/releases/73fc712d355032e0a66b41675ba114491b04799d
```
```bash
# 4. atomic symlink swap
sudo ln -sfn /opt/apex/releases/73fc712d355032e0a66b41675ba114491b04799d /opt/apex/current.new \
  && sudo mv -T /opt/apex/current.new /opt/apex/current && readlink -f /opt/apex/current
```

**No restart command.** The orchestrator restarts itself every ~31 s and loads
the new release on its next start.

## 5. Ledger preservation — full-prefix streaming hash

```bash
for L in /apex-data/core/ops/orchestrator.jsonl \
         /apex-data/core/historical/continuous/decisions.jsonl \
         /apex-data/core/btc/derivatives_ledger.jsonl \
         /apex-data/core/btc/ws_book_ledger.g2.jsonl \
         /apex-data/core/historical/continuous/outcomes.jsonl; do
  N=$(stat -c %s "$L"); H=$(head -c "$N" "$L" | sha256sum | cut -d' ' -f1); echo "$L $N $H"
done | tee /apex-data/tmp/pre_deploy_ledger_prefixes.txt
```
After commissioning, every line of this must read `PREFIX_IDENTICAL size:OK`:
```bash
while read L N H; do NOW=$(head -c "$N" "$L" | sha256sum | cut -d' ' -f1); SZ=$(stat -c %s "$L")
  [ "$NOW" = "$H" ] && S=PREFIX_IDENTICAL || S=PREFIX_CHANGED; [ "$SZ" -ge "$N" ] && G=OK || G=SHRANK
  echo "$L $S size:$G ($N -> $SZ)"; done < /apex-data/tmp/pre_deploy_ledger_prefixes.txt
```
Limits: live writers on four of five ledgers; the prefix hash is not an atomic
whole-file snapshot and cannot detect a rewrite-and-restore. The orchestrator
ledger's only writer is the unit being deployed, so its prefix is quiescent.

## 6. Commissioning — the unit's own signals, not a shared slice counter

| | |
|---|---|
| Unit slice | `apex-market.slice`, nested at `/sys/fs/cgroup/apex.slice/apex-market.slice` |
| Unit cgroup | `.../apex-orchestrator.service`, present only while running |
| Binding cap | the unit's own `MemoryMax=512M`; both slices are uncapped |
| Parent counter | shared by five units — context only, never attribution |

Baseline before the swap:
```bash
systemctl show apex-orchestrator.service -p NRestarts -p Result -p ExecMainStatus | tee /apex-data/tmp/pre_deploy_unit.txt
python3 -c "import json;d=json.load(open('/apex-data/core/heartbeats/orchestrator.json'));print(d['last_work_utc'],d['work_completed'])" | tee /apex-data/tmp/pre_deploy_hb.txt
```
Anchor: the first start after the swap. Record its `ExecMainStartTimestamp` as
T0 and `NRestarts` as N0. Over ≥30 min from T0:

| Signal | Required |
|---|---|
| `NRestarts` | still N0 |
| journal `Failed with result` after T0 | none |
| heartbeat `last_work_utc` | advancing ~60 s |
| heartbeat `work_completed` | climbing |
| unit `memory.peak` while alive | well under 512 MiB (healthy history 349.9 MiB) |
| orchestrator ledger | growing; prefix unchanged; newest record a few KB with ≤7 history entries per incident |
| `actions[].outcome` in new records | never `STARTED`; only the R4 states |

## 7. Rollback and the loaded-process problem

```bash
sudo ln -sfn /opt/apex/releases/5eff1cf5e00f21b02c537f25bcd74b1c1d317546 /opt/apex/current.new \
  && sudo mv -T /opt/apex/current.new /opt/apex/current
```
A symlink selects code **at process start**. It does not replace code already
loaded.

| Process | After the swap forward | After a rollback |
|---|---|---|
| `apex-orchestrator` | loads R1–R4 on its next ~31 s restart | reloads the old code on its next restart and **returns to the OOM loop** |
| Long-lived writers holding `chain_append`: `apex-btc-derivatives`, `apex-btc-ws`, `apex-organism`, `apex-catalyst`, `apex-equity-shadow`, `apex-equity-field`, `apex-edgeforge-observatory` | **unchanged** — they keep the OLD reader until they restart | unchanged — they keep whatever they loaded |
| Timer-driven and one-shot units | new code on next invocation | old code on next invocation |

So after the forward swap the host runs a **mixed state**: the orchestrator on
R1, the seven long-lived writers still on the old chain reader. That is
acceptable for recovery because those seven ledgers' tails are well inside the
old 256 KiB window, and it is the condition under which "no unrelated restarts"
holds. The service actions that WOULD bring them onto R1 are listed for review
and are **not** part of this deployment:

```bash
# NOT EXECUTED. Each is a service action requiring its own authorization.
sudo systemctl restart apex-btc-derivatives.service
sudo systemctl restart apex-btc-ws.service
sudo systemctl restart apex-organism.service
# ... etc.
```

Rollback triggers: any ledger prefix changes or shrinks; `ChainTailUnresolved`
on any ledger other than the orchestrator's; a healthy service starts failing;
the orchestrator starts a service under a maintenance block (which systemd
should make impossible — if observed, the drop-in has been altered).

Rollback does **not** restore health: the oversized record remains on disk.

## 8. Remaining prerequisites to a go

1. `recovery3` and `integration3` PASS with manifests.
2. The `options-paper` launch decision, recorded.
3. Reviewer go under the established conditions.
