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

---

# Corrections, added 2026-09-06 after review of R1

Additive. Nothing above is deleted; where a statement above is wrong, the
correction is here and the original stays visible.

## 1. R2 alone cannot recover the running service

The proposal above says "either fix alone stops the loop." That is wrong for
R2 and right only for R1.

R2 bounds FUTURE deferral entries. It cannot help the service that is failing
now, because the oversized record is already on disk: a 262,275-byte final
record sits at the end of a 438 MB ledger, and every start reads the whole
file before R2's code is ever reached. Bounding what a future tick would write
does not shrink a record that was written yesterday.

Only R1 recovers the current service, and it does so without touching data,
because the existing final record fits inside the widened window. R2 remains
necessary to stop the condition recurring, but it is a preventative, not a
recovery.

## 2. The read ceiling is not a memory budget

The proposal above says the peak after repair is "bounded by the 8 MiB
ceiling." That conflates bytes read with process memory. Decoding those bytes
to text and parsing candidate lines as JSON allocate on top of the read, so the
process figure is several times the window.

Measured, rather than estimated, inside the same 512 MiB cap:

| Case | Bytes read | Process peak |
|---|---|---|
| Production shape, 438.8 MB fixture | one widening to 512 KiB | 16.7 MiB maxrss, 7.6 MiB cgroup |
| Worst case, widening to the ceiling | 8 MiB | 39.2 MiB maxrss, 30.0 MiB cgroup |
| Refusal beyond the ceiling | 8 MiB | 40.4 MiB maxrss |

Keep the two apart. What the repair GUARANTEES is the read: no single read
exceeds MAX_TAIL_SEARCH_BYTES, the total across the widening is under twice
that, and neither figure depends on ledger size. What the table reports is
MEASURED process memory on three specific fixtures, of which 40.4 MiB is the
highest observed value, not a proven universal bound. Process memory also
depends on record sizes, line counts and interpreter behaviour, none of which
these three fixtures exhaust.

On the evidence available the measured peaks sit near 8 percent of the
existing cap, which is why no cap change is proposed. That is a judgement from
measurement, not a guarantee, and a ledger with a very different record shape
should be measured rather than assumed.

## 3. Production recovery is unverified

Everything measured here was measured on disposable fixtures on a development
branch. The service has not been repaired, restarted, or deployed, and the
production loop is still running.

R1 is expected to end it, because the production ledger's final record is
262,275 bytes and the widened window contains it. Expected is not verified.
Verification requires a separate authorized commissioning step that deploys the
release and then observes the restart counter stop advancing, the heartbeat's
last-work timestamp advance every 60 seconds, and the completed-work count
resume climbing. Until that has been done and its evidence returned, the
correct status of production recovery is UNVERIFIED.

## 4. Sequencing, restated

1. R1, this brick: implemented and evidenced, not deployed.
2. Deployment and production verification: a separate authorized step.
3. R2: still unimplemented, and still required so the condition cannot recur.

## 5. Genesis, stated precisely

An earlier summary said the repair "never falls back to genesis". That is true
of the case it was describing and wrong as a general statement. The two paths
are different and both are deliberate.

**Ceiling exhaustion never substitutes genesis.** When the search reaches
MAX_TAIL_SEARCH_BYTES without finding a hash, and bytes remain unexamined
before that point, the append raises ChainTailUnresolved and writes nothing.
It does not link to genesis, because it does not know what lies further back.

**A whole file of garbage still yields genesis, unchanged from before.** When
the search reaches the start of the file -- every byte examined -- and no
parseable entry_hash exists anywhere in it, the previous hash is genesis and
the torn flag is set. That is the pre-existing behaviour and it is preserved
deliberately: there the absence of a prior record is a measurement over the
complete file, not an assumption made because reading was inconvenient.

The distinguishing condition is whether the search reached byte zero. It did:
genesis. It stopped at the ceiling: refuse.

## 6. Regression provenance, from retained evidence only

The R1 regression artifact records the HEAD commit 810b72c8 and its tree
ed35f988, and those agree, so HEAD was the repair commit and did not move
during the run.

No working-tree hash, dirty flag or status was captured per shard, and the
shards executed against the working directory rather than the commit.
Retained evidence therefore establishes WHICH COMMIT was checked out, and does
not establish that the working tree equalled it at that moment. That gap is
recorded rather than closed by inference.

Two things that are known: a clean status was observed at the moment 810b72c8
was committed, and the primitive at HEAD today is byte-identical to 810b72c8's
version, this continuation being test-only. Neither retroactively proves the
working tree during the run.

Future regressions should record a source hash per run so this question is
answerable from the artifact.
