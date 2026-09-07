# Milestone 1 — deployment and commissioning package (CORRECTED)

**Supersedes the first version of this document in full.** That version is
preserved in git history at commit `9836986f`. Every executable instruction
below replaces the corresponding one there.

**Prepared for review. Nothing here has been executed.**

## 0. What was wrong in the superseded version

| Defect | Correction |
|---|---|
| Deployment commands targeted `39bd4412` | The tested candidate is `07dcbb05` |
| Inventory said four files | Five files: two production, three test |
| Commissioning used the research slice OOM counter, 11 | That slice is unrelated. Correct counters below |
| Ledger check used size growth plus a head sample | Full-prefix streaming hash at a recorded length |
| Rollback described as restoring health | It restores the OOM loop, and affects only some processes |
| Maintenance blocks called "authorization only" | Enforcement is ABSENT. It is a real prerequisite |

## 1. The deployment target

| | |
|---|---|
| **Deploy this** | `07dcbb05caf58f1ac714bb3fe87e16d46aeb98d8` |
| Branch | `milestone1-recovery-candidate` |
| Based on | `5eff1cf5e00f21b02c537f25bcd74b1c1d317546`, the running release |
| Tested by | `results/milestone1_recovery_regression.json`, 15 shards, 248 passed, 4 skipped, manifest `e69eea6ca505d8f2` unchanged |

**Historical references, not deployment targets.** `39bd4412` was an earlier
form of this candidate, superseded by the authorized portability port and never
deployed. `3b9a26f2` is the integration candidate, a different base, not a
deployment target. Neither should appear in any command.

### Five-file inventory against the running release

| File | Kind | Change |
|---|---|---|
| `apex/governance/chain_ledger.py` | production | R1, bounded chain-tail lookup |
| `scripts/apex_orchestrator.py` | production | R2, bounded incident history |
| `tests/test_chain_tail_bounded.py` | test, new | R1 evidence |
| `tests/test_orchestrator_incident_history.py` | test, new | R2 evidence |
| `tests/test_sac1_tier1.py` | test, modified | interpreter portability port |

Two files execute in production. Three are tests.

## 2. Affected callers

`chain_append` is shared. R1 changes how every writer finds a previous hash.

| Ledger | Size | Final record | Tail window |
|---|---|---|---|
| decisions.jsonl | 687.9 MB | 1,586 B | OK |
| ops/orchestrator.jsonl | 438.9 MB | 262,275 B | **fails — the defect** |
| btc/derivatives_ledger.jsonl | 416.1 MB | 6,406 B | OK |
| btc/ws_book_ledger.g2.jsonl | 135.8 MB | 762 B | OK |
| outcomes.jsonl | 65.6 MB | 1,270 B | OK |

R2 changes only the orchestrator.

## 3. Prerequisites

1. Review and explicit deployment authorization. **Not given.**
2. **The maintenance-block prerequisite in section 7 resolved.** This is not a
   formality; enforcement is absent.
3. Free disk for a release directory. 143 GB free at last check.

## 4. Deployment commands

```bash
# 1. verify the candidate is exactly what was reviewed
git -C /opt/apex-repo rev-parse 07dcbb05caf58f1ac714bb3fe87e16d46aeb98d8^{commit}
git -C /opt/apex-repo diff --stat 5eff1cf5e00f21b02c537f25bcd74b1c1d317546 \
    07dcbb05caf58f1ac714bb3fe87e16d46aeb98d8
```

```bash
# 2. record the FULL-PREFIX hash of every ledger before anything changes
for L in /apex-data/runtime/results/ops/orchestrator.jsonl \
         /apex-data/core/historical/continuous/decisions.jsonl \
         /apex-data/core/btc/derivatives_ledger.jsonl \
         /apex-data/core/btc/ws_book_ledger.g2.jsonl \
         /apex-data/core/historical/continuous/outcomes.jsonl; do
  N=$(stat -c %s "$L")
  H=$(head -c "$N" "$L" | sha256sum | cut -d' ' -f1)
  echo "$L $N $H"
done | tee /apex-data/tmp/pre_deploy_ledger_prefixes.txt
```

```bash
# 3. build the release directory from the reviewed commit
sudo -u apex git -C /opt/apex-repo worktree add --detach \
  /opt/apex/releases/07dcbb05caf58f1ac714bb3fe87e16d46aeb98d8 \
  07dcbb05caf58f1ac714bb3fe87e16d46aeb98d8
```

```bash
# 4. record the commissioning baseline BEFORE the swap
systemctl show apex-orchestrator.service -p NRestarts -p Result -p ExecMainStatus \
  | tee /apex-data/tmp/pre_deploy_unit_state.txt
sudo -n journalctl -u apex-orchestrator.service --since today --no-pager \
  | grep -c "Failed with result" | tee /apex-data/tmp/pre_deploy_oom_count.txt
python3 -c "import json;d=json.load(open('/apex-data/core/heartbeats/orchestrator.json'));print(d['last_work_utc'],d['work_completed'])" \
  | tee /apex-data/tmp/pre_deploy_heartbeat.txt
```

```bash
# 5. swap the symlink atomically
sudo ln -sfn /opt/apex/releases/07dcbb05caf58f1ac714bb3fe87e16d46aeb98d8 \
  /opt/apex/current.new && sudo mv -T /opt/apex/current.new /opt/apex/current
readlink -f /opt/apex/current
```

The orchestrator is restarting every 31 seconds, so it loads the new release on
its next restart. **Issue no restart command.**

## 5. Ledger preservation, corrected

Size growth and a head sample prove nothing about the bytes in between. The
check is a **streaming hash of the entire byte prefix at the recorded length**.

```bash
# after commissioning: the first N bytes must be byte-identical to before
while read L N H; do
  NOW=$(head -c "$N" "$L" | sha256sum | cut -d' ' -f1)
  SZ=$(stat -c %s "$L")
  if [ "$NOW" = "$H" ]; then S=PREFIX_IDENTICAL; else S=PREFIX_CHANGED; fi
  if [ "$SZ" -ge "$N" ]; then G=OK; else G=SHRANK; fi
  echo "$L $S size:$G ($N -> $SZ)"
done < /apex-data/tmp/pre_deploy_ledger_prefixes.txt
```

Every line must read `PREFIX_IDENTICAL size:OK`. Appends after byte N are
expected and permitted; a changed prefix or a shrinking file is a rollback
trigger.

**Consistency limitations, stated.** These ledgers have live writers. The
pre-deployment hash is taken over a prefix while other processes may be
appending beyond it, which is safe for an append-only file but is not an atomic
snapshot of the whole file. The check proves the first N bytes are unchanged at
the moment of verification; it does not prove no writer rewrote and restored
them, and it says nothing about bytes after N. For the orchestrator ledger
specifically the writer is the unit being deployed, so its prefix is quiescent
during the swap. For the four others the writers are untouched services that
continue appending throughout.

## 6. Commissioning measurements, corrected

The superseded version read `wmresearch.slice`. That is the **research** slice
used by the test harness and has nothing to do with this service. Correct
paths, resolved on the host:

| | |
|---|---|
| Unit slice | `apex-market.slice`, nested as `/apex.slice/apex-market.slice` |
| Parent cgroup | `/sys/fs/cgroup/apex.slice/apex-market.slice` |
| Unit cgroup | `.../apex-orchestrator.service`, **exists only while running** |
| Slice memory cap | `max` — uncapped. The binding cap is the unit's 512 MiB |

**The parent slice counter cannot attribute a kill to this service.** Five
units share it: `apex-btc-derivatives`, `apex-btc-ws`, `apex-orchestrator`,
`apex-organism`, `apex-thetaterminal`. Its `oom_kill` rises for any of them.

### Baselines captured 2026-09-07T05:50Z

| Signal | Value |
|---|---|
| Unit `NRestarts` | 2864 |
| Unit `Result` | `oom-kill`, `ExecMainStatus` 9 |
| Parent slice `oom_kill` | 3120 (shared — context only) |
| `apex.slice` `oom_kill` | 3122 (shared — context only) |
| Heartbeat `last_work_utc` | 2026-09-06T04:50:03Z |
| Heartbeat `work_completed` | 5661 |

### The authoritative per-unit signals

1. `systemctl show ... -p NRestarts` — durable, survives the cgroup vanishing.
2. `Result` and `ExecMainStatus`.
3. Journal lines `Failed with result 'oom-kill'`, timestamped and attributable.
4. The unit's own cgroup `memory.events` and `memory.peak`, readable only while
   the process lives.

### Establishing the observation baseline

The first successful start is the anchor, because everything before it belongs
to the broken release.

```bash
# the first start after the swap
systemctl show apex-orchestrator.service -p ExecMainStartTimestamp -p NRestarts
```

Record `NRestarts` at that moment as **N0** and the start time as **T0**.
Commissioning is then judged over at least 30 minutes from T0:

| Signal | Requirement |
|---|---|
| `NRestarts` | still N0 — not one further restart |
| Journal oom-kill lines after T0 | zero |
| Heartbeat `last_work_utc` | advances every ~60 s |
| Heartbeat `work_completed` | climbs by roughly one per minute |
| Unit `memory.peak` while running | well under 512 MiB; healthy history was 349.9 MiB |
| Orchestrator ledger | grows again, prefix unchanged |
| Bounded incident records | see below |

### Verifying the bounded incident record

R2's purpose is that a long incident stops inflating records. Check the newest
ledger record directly:

```bash
python3 - <<'PY'
import json
L="/apex-data/runtime/results/ops/orchestrator.jsonl"
last=None
with open(L,"rb") as fh:
    fh.seek(max(0,fh.seek(0,2)-262144)); last=fh.read().decode("utf-8","replace").splitlines()[-1]
r=json.loads(last)
print("record bytes:", len(json.dumps(r,sort_keys=True)))
for inc in r.get("incidents",[]):
    ra=inc.get("recovery_attempts",[])
    s=[e for e in ra if e.get("kind")=="deferral_summary"]
    print(" incident", inc.get("service"), "history entries:", len(ra),
          "| deferral count:", s[0]["count"] if s else "n/a")
PY
```

Requirements: record size stays a few kilobytes and does not grow with time;
history entries never exceed seven; and a long incident shows a
`deferral_summary` whose `count` rises while the entry count does not.

## 7. Maintenance blocks — an OPEN PREREQUISITE, not a formality

**Traced read-only in the exact recovery candidate. Enforcement is absent.**
Neither `scripts/apex_orchestrator.py` nor `apex/ops/orchestrator.py` at
`07dcbb05` contains any reference to `MAINTENANCE_BLOCK` or to maintenance in
any form. Two block files exist in the runtime directory:

```
/apex-data/runtime/MAINTENANCE_BLOCK_btc_resolver
/apex-data/runtime/MAINTENANCE_BLOCK_equity_fabric
```

The orchestrator does not read them. It decides what to start from the roster
and the session phase alone.

### What it can launch

It starts only services whose `supervised_by` is `orchestrator`:
**`equity-fabric`** and **`options-paper`**. For `btc-paper` and
`edgeforge-observatory` it is the verifier and escalates rather than starting.

| When | What it may start |
|---|---|
| Now, a non-trading phase | neither, if the roster expects neither in this phase |
| At the next phase transition into PREOPEN or RTH | `equity-fabric`, and `options-paper` in its phases |

**A quiet deployment window is not authorization for later launches.**
Deploying while nothing is expected to run proves only that nothing starts in
that minute. The next phase transition happens without further human action,
and at that moment a service under an explicit maintenance block could be
started by a component that cannot see the block. `equity-fabric` is exactly
such a service.

### Smallest controlled arrangement, for review

Not implemented; this is a proposal.

1. **Preferred.** A small, test-covered change teaching the tick to treat a
   `MAINTENANCE_BLOCK_<service>` file as `EXPECTED_IDLE` for that service, and
   to record the block in the tick record so the suppression is visible rather
   than silent. This is a third production change and is **outside the current
   milestone's authorization**; it should be its own reviewed brick.
2. **Interim, if recovery is wanted before that.** Deploy, and separately
   arrange that the two orchestrator-supervised services cannot be started
   without human action, by a means the deploying operator controls and can
   verify. Do not rely on the deployment window.
3. **Do not** lift or delete the maintenance blocks to make the problem
   disappear. A block is a statement that a service is deliberately down.

## 8. Rollback mechanics, corrected

```bash
sudo ln -sfn /opt/apex/releases/5eff1cf5e00f21b02c537f25bcd74b1c1d317546 \
  /opt/apex/current.new && sudo mv -T /opt/apex/current.new /opt/apex/current
```

**What actually changes, and what does not.** The symlink selects code at
process start. Swapping it back does not reach into a running process.

| Process | Effect of a rollback |
|---|---|
| `apex-orchestrator` | Restarts constantly, so it picks up the old code within ~31 s — and **returns to being OOM-killed**, because the old reader plus the oversized record on disk is exactly the defect |
| Long-lived services holding `chain_append` in memory: `apex-btc-derivatives`, `apex-btc-ws`, `apex-organism`, `apex-catalyst`, `apex-equity-shadow`, `apex-equity-field`, `apex-edgeforge-observatory` | **No effect.** They keep executing the already-imported R1 code until they are next restarted, whenever that happens |
| Timer-driven and one-shot units | Pick up the old code on their next invocation |

So a rollback is partial and staggered: it restores the defect where it hurts
and leaves the repair in place elsewhere until unrelated restarts occur. That
mixed state is itself a reason to prefer fixing forward.

**Rolling back does not restore healthy operation.** The oversized record
remains on disk and nothing here removes it.

### Rollback triggers

1. Any ledger prefix hash changes, or any ledger shrinks.
2. `ChainTailUnresolved` raised for any ledger other than the orchestrator's —
   a writer that used to append now refuses.
3. A previously healthy service begins failing after the swap.
4. The orchestrator starts a service under a maintenance block.

For trigger 2 the correct response after rollback is to measure that ledger's
final record and decide with evidence whether its writer needs a larger
ceiling. Do not raise it pre-emptively.

### Containment actions prepared, not executed

For review, in escalation order:

```bash
# A. stop the restart loop without deploying anything
sudo systemctl stop apex-orchestrator.service
```
```bash
# B. after a rollback, prevent the loop from resuming
sudo systemctl stop apex-orchestrator.service
sudo systemctl disable apex-orchestrator.service
```
```bash
# C. confirm what a rolled-back process would load
readlink -f /opt/apex/current
sha256sum /opt/apex/current/apex/governance/chain_ledger.py
```

**None of these has been run and none is authorized.** Stopping the unit is a
service action outside this milestone's authority.

## 9. Remaining deployment prerequisites

1. Milestone review and explicit deployment authorization.
2. **Maintenance-block enforcement resolved** by option 1 or 2 of section 7.
3. A decision on whether recovery precedes or follows that fix.
4. A deploying operator able to run the ledger prefix hashes before and after
   and to act on the rollback triggers.

Production recovery remains **UNVERIFIED**. Nothing in this document has been
executed.
