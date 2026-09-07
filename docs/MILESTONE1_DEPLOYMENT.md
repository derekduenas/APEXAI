# Milestone 1 — deployment and commissioning package

**Prepared for review. Nothing here has been executed.** No service was
deployed, restarted, stopped or reconfigured, and no limit was changed.

## 1. The candidate

| | |
|---|---|
| Recovery candidate | `39bd44127b2ff6cb8a0a25a5590133669fb2382a` |
| Branch | `milestone1-recovery-candidate` |
| Based on | `5eff1cf5e00f21b02c537f25bcd74b1c1d317546`, the currently deployed release |
| Files changed vs deployed | 2 production, 2 new test modules |

```
apex/governance/chain_ledger.py                R1  bounded chain-tail lookup
scripts/apex_orchestrator.py                   R2  bounded incident history
tests/test_chain_tail_bounded.py               new
tests/test_orchestrator_incident_history.py    new
```

Nothing else differs from what is running. None of the PULSE or World Model
work is carried. The four files are byte-identical to those in the integration
candidate, which is recorded, but the two candidates sit on different bases and
neither one's regression result transfers to the other.

## 2. Affected callers

`chain_append` is a shared primitive. Every writer that uses it is affected by
R1, not only the orchestrator.

| Ledger | Size | Final record | Tail window today |
|---|---|---|---|
| historical/continuous/decisions.jsonl | 687.9 MB | 1,586 B | OK |
| ops/orchestrator.jsonl | 438.9 MB | 262,275 B | **fails — the defect** |
| btc/derivatives_ledger.jsonl | 416.1 MB | 6,406 B | OK |
| btc/ws_book_ledger.g2.jsonl | 135.8 MB | 762 B | OK |
| historical/continuous/outcomes.jsonl | 65.6 MB | 1,270 B | OK |

Services holding these writers open: `apex-btc-derivatives`, `apex-btc-ws`,
`apex-organism`, `apex-equity-shadow`, `apex-equity-field`, `apex-catalyst`,
`apex-edgeforge-observatory`. R1 changes how each finds a previous hash. Their
serialisation, hashing and locking are untouched, and 246 existing tests across
the 15 modules that exercise the primitive pass on the candidate.

R2 changes only the orchestrator.

## 3. Prerequisites

1. This package reviewed and deployment explicitly authorized. **Not authorized
   today.**
2. A deployment window outside a trading session. The next non-trading days
   after the review are the immediate ones; the next trading session is
   **Tuesday 2026-09-08**, which is the deadline for the orchestrator to be
   working again.
3. The two maintenance blocks currently in place stay respected:
   `MAINTENANCE_BLOCK_btc_resolver` and `MAINTENANCE_BLOCK_equity_fabric` in
   `/apex-data/runtime`. Deploying does not clear them and must not.
4. Free disk for a new release directory. 143 GB free at last check.

## 4. Deployment commands

Run as the deploying operator, in order, stopping on any nonzero status.

```bash
# 1. verify the candidate is what was reviewed
git -C /opt/apex-repo rev-parse 39bd44127b2ff6cb8a0a25a5590133669fb2382a^{commit}
git -C /opt/apex-repo diff --stat 5eff1cf5e00f21b02c537f25bcd74b1c1d317546 \
    39bd44127b2ff6cb8a0a25a5590133669fb2382a
```

```bash
# 2. record the ledger bytes BEFORE anything changes
for L in /apex-data/runtime/results/ops/orchestrator.jsonl \
         /apex-data/core/historical/continuous/decisions.jsonl \
         /apex-data/core/btc/derivatives_ledger.jsonl \
         /apex-data/core/btc/ws_book_ledger.g2.jsonl \
         /apex-data/core/historical/continuous/outcomes.jsonl; do
  stat -c "%n size=%s mtime=%y" "$L"; done | tee /apex-data/tmp/pre_deploy_ledgers.txt
```

```bash
# 3. build the release directory from the reviewed commit
sudo -u apex git -C /opt/apex-repo worktree add --detach \
  /opt/apex/releases/39bd44127b2ff6cb8a0a25a5590133669fb2382a \
  39bd44127b2ff6cb8a0a25a5590133669fb2382a
```

```bash
# 4. swap the symlink atomically
sudo ln -sfn /opt/apex/releases/39bd44127b2ff6cb8a0a25a5590133669fb2382a \
  /opt/apex/current.new && sudo mv -T /opt/apex/current.new /opt/apex/current
readlink -f /opt/apex/current
```

The orchestrator is already restarting every 31 seconds, so it picks up the new
release on its next restart without an explicit restart command. **Do not
issue a restart for it.** Other services keep running their loaded code until
they are next restarted, which is not part of this deployment.

## 5. Ledger-preservation checks

Run before and after. Every one must hold.

```bash
# byte counts and hashes of the first 1 MiB and last 1 MiB of each ledger
for L in /apex-data/runtime/results/ops/orchestrator.jsonl \
         /apex-data/core/historical/continuous/decisions.jsonl; do
  echo "$L $(stat -c %s "$L") \
$(head -c 1048576 "$L" | sha256sum | cut -c1-16) \
$(tail -c 1048576 "$L" | sha256sum | cut -c1-16)"; done
```

- The orchestrator ledger must be **438,867,453 bytes** before deployment, and
  must GROW after it, never shrink or be rewritten.
- The head hash of every ledger must be unchanged after deployment. R1 only
  reads; nothing in this candidate rewrites or truncates history.
- Damaged history stays forensic. No repair, truncation or compaction is part
  of this deployment.

## 6. Commissioning criteria

Judge on completed work, not on process state. `systemctl is-active` reports
`activating` in this failure mode, and a check that substring-matches the word
"active" is fooled by it.

Observe for at least 30 minutes after the symlink swap:

| Signal | Now | Required |
|---|---|---|
| `NRestarts` | climbing ~116/hour | **stops advancing** |
| `Result` | `oom-kill` | not `oom-kill` |
| Heartbeat `last_work_utc` | frozen at 2026-09-06T04:50:03Z | **advances every ~60 s** |
| Heartbeat `work_completed` | 5661, static | **climbing** |
| Slice `oom_kill` counter | 11 | unchanged |
| Unit `MemoryPeak` | hits the 512 MiB cap | well under it; healthy history was 349.9 MiB |
| Orchestrator ledger | frozen at 04:50:03Z | growing again, records bounded |

```bash
systemctl show apex-orchestrator.service -p NRestarts -p Result -p ActiveState -p MemoryPeak
python3 -c "import json;d=json.load(open('/apex-data/core/heartbeats/orchestrator.json'));print(d['last_work_utc'],d['work_completed'])"
```

Commissioning PASSES only if the restart counter is static, work is completing,
and no ledger changed except by growth. Until that evidence exists, production
recovery stays **UNVERIFIED**.

## 7. Side effects: the orchestrator starts other services

This is the part of the deployment that carries real operational risk, and it
has nothing to do with memory.

A working orchestrator does what a broken one cannot: it reconciles the
expected roster against what is running and **starts what it owns**. It has
been unable to do that for over sixteen hours. Restoring it restores that
authority.

- It starts only services whose `supervised_by` is `orchestrator`. Today those
  are `equity-fabric` and `options-paper`. It does **not** start `btc-paper` or
  `edgeforge-observatory`, which are systemd-supervised; for those it is the
  verifier and escalates.
- Its `decision_power` is `NONE_OPERATIONAL`. It places no orders and changes
  no trading rule.
- **Before deploying, confirm that starting `equity-fabric` and
  `options-paper` is currently intended.** There is a
  `MAINTENANCE_BLOCK_equity_fabric` file in the runtime directory, and a
  maintenance block is a statement that the service is deliberately down. The
  deploying operator must verify that the orchestrator honours those blocks, or
  deploy in a phase where neither service is expected to run, or lift the
  blocks deliberately. Do not discover this by watching it start something.
- Deploying during a non-trading phase means the roster expects neither of
  those two services to be running, which is the low-risk window.

## 8. Rollback

```bash
sudo ln -sfn /opt/apex/releases/5eff1cf5e00f21b02c537f25bcd74b1c1d317546 \
  /opt/apex/current.new && sudo mv -T /opt/apex/current.new /opt/apex/current
```

**Rolling back restores the OOM loop.** The old reader is the defect: it reads
the whole 438 MB ledger on every append and is killed by the 512 MiB cap. The
oversized record is still on disk and nothing in this deployment removes it, so
reverting returns the orchestrator to being killed every 31 seconds. Rollback
is a way to stop a NEW problem the deployment introduced; it is not a way to
restore healthy operation, and it must not be described as one.

Roll back if, and only if, one of these is observed:

1. Any ledger shrinks, is rewritten, or its head hash changes.
2. A `ChainTailUnresolved` error appears for a ledger other than the
   orchestrator's, meaning a writer that used to append now refuses. That
   would be R1 declining a ledger whose tail sits beyond the 8 MiB ceiling.
3. Any currently healthy service begins failing after the swap.
4. The orchestrator starts a service that was deliberately blocked.

For 2, the correct response after rollback is to measure that ledger's final
record and decide whether the ceiling should be raised for that writer, with
evidence. Do not raise it pre-emptively.
