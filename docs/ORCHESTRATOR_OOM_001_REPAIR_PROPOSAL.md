# ORCHESTRATOR-OOM-001 — minimal repair proposal

Proposal only. Nothing here has been applied. No service was changed,
restarted or stopped, no limit was raised, and nothing was deployed.

## What is wrong, in one paragraph

An unbounded list inflated one ledger record past a fixed 256 KiB window in the
shared hash-chain primitive. Once a record is larger than that window, the
primitive can never find the previous hash there, and it falls back to reading
the entire 438 MB ledger into memory. That needs 1267 MiB, measured. The unit
cap is 512 MiB, so the process is killed about one second after every start,
roughly every 31 seconds, and has been since 2026-09-06T04:51:05Z.

Two independent defects had to line up. Either fix alone stops the loop. Both
are worth fixing, because each is a hazard on its own.

## R1 — bound the chain primitive's prev-hash search

**File** `apex/governance/chain_ledger.py`, function `_chain_append_locked`.

**Change** Replace the whole-file fallback with a backward scan that widens
geometrically from the current 256 KiB to a hard ceiling of 8 MiB. If no
`entry_hash` is found inside the ceiling, raise a specific error naming the
ledger and the bytes searched, rather than reading the file.

**Rationale** The fallback is the amplifier. It converts a merely large record
into an allocation proportional to the whole ledger, in a primitive shared by
every writer on the host. Four other chain ledgers are between 65 MB and 688 MB
today; each is one oversized record away from the same failure, and the largest
would need roughly 2 GB. A ceiling makes the cost of an append independent of
ledger size, which is what the module's own docstring already claims when it
says the tail read is constant time.

**Why this alone unblocks the service** The orchestrator ledger's final complete
record is 262,275 bytes. A 1 MiB window contains it, so the previous hash is
found, the append succeeds, and the loop ends. No data is modified.

**Also fix, same function** the cut-guard `lines = lines[1:]` discards the first
line in the window unconditionally, including when the window happens to begin
exactly at a record boundary. Drop it only when the window did not start at a
newline.

## R2 — bound the accumulation that created the oversized record

**File** `scripts/apex_orchestrator.py`, function `tick`, the branch handling
externally supervised services.

**Change** Apply a cap to that branch as well. Keep at most
`MAX_RECOVERY_ATTEMPTS` entries and carry a count plus first and last
timestamps for the rest, so the record stays a fixed size while still recording
that the service is still missing and for how long.

**Rationale** `MAX_RECOVERY_ATTEMPTS` currently guards only the branch that
actually starts something. The supervised branch appends one entry every tick
forever, and `state["attempts"]` is cleared only on a phase change. Across a
weekend in phase IDLE that produced 1907 identical entries, and the whole list
is re-serialised into every record. The information content is a count and a
duration, not 1907 copies of the same sentence.

**Do not** fix this by clearing the state more often. The accumulation is the
defect; the retention interval is not.

## What must NOT be done

- **Do not raise the memory cap.** The measured 1267 MiB is the cost of a bug,
  not a requirement. Healthy operation peaked at 349.9 MiB under the existing
  512 MiB cap across a four-day run. With R1 the peak read is bounded by the
  8 MiB ceiling.
- **Do not truncate, rewrite or repair the ledger.** It is forensic evidence,
  and the module's own law says damaged history stays visible. R1 makes it
  readable without touching it.

## Acceptance checks

1. A unit test proves `_chain_append_locked` finds the previous hash when the
   final record exceeds 256 KiB, and does so without reading the whole file.
2. A unit test proves it raises the named error, rather than reading the file,
   when no hash exists within the ceiling.
3. A test using the real 438 MB ledger, or a fixture reproducing its shape,
   completes the prev-hash lookup inside a 512 MiB cgroup.
4. A unit test proves the supervised branch stops growing after
   `MAX_RECOVERY_ATTEMPTS` and still reports the deferral count and duration.
5. Existing chain-ledger tests pass unchanged, including torn-tail recovery and
   the two-layer locking behaviour.
6. The full bounded sharded regression passes.
7. After deployment, and only then: the restart counter stops advancing, the
   heartbeat's `last_work_utc` advances every 60 seconds, and
   `work_completed` resumes climbing.

## Resource budget

| | Now | After R1 and R2 |
|---|---|---|
| Peak on the fallback path | 1267 MiB, measured | bounded by the 8 MiB ceiling |
| Steady-state peak | 349.9 MiB, measured while healthy | unchanged |
| Unit cap | 512 MiB | 512 MiB, unchanged |
| Ledger growth | 135 bytes per tick while an incident is open | fixed size per record |

## Rollback

R1 and R2 are separate commits touching two files, with no schema, no data and
no unit-file change, so rollback is reverting either commit and redeploying. The
release mechanism is already an immutable symlink swap, so the previous release
directory remains on disk and the symlink can be pointed back. Nothing written
during the repair changes the ledger format, so a rollback reads existing
records unchanged.

## Sequencing note

R1 touches a primitive shared by every ledger writer on the host, so it deserves
its own review and its own regression, separately from R2. R1 first stops the
loop; R2 prevents it recurring.
