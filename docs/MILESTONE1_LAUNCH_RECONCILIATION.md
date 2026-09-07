# Milestone 1 — launch-authorization reconciliation for the next trading session

**Deadline: 2026-09-08T13:30:00Z (RTH open).** Written 2026-09-07T17:47Z.

## 1. The gap, stated plainly

The recovery deployment authorization excludes *unrestricted launches of
inactive services* and requires *controlled service-launch behaviour*. My
package described the `options-paper` launch as "pre-existing intended
behaviour". That is a description of the code, not a permission, and I
withdraw it as a justification.

`apex-options-paper.service` is **inactive** (unit disabled, `SubState=dead`,
last active 2026-09-04 13:30:30→20:03:34Z, `PAPER_EXPLORATORY`, 86.6 MiB
peak, 133 work units, no capital). It carries **no maintenance condition** —
its only drop-in is `slice.conf`. Under the current authorization it must
not be started by the orchestrator merely because the roster deems it
eligible.

## 2. What the deployed orchestrator will do at 13:30Z — demonstrated, not argued

The deployed release `73fc712d` was driven through one tick with the phase
forced to RTH, process creation intercepted at the `systemctl start` call,
and everything else real (roster, drop-ins, markers, systemd state).

```
--- dry_run=True
   action: options-paper DRY_RUN | --dry-run
   equity-fabric  recovery=0 maintenance=BLOCKED /apex-data/core/ops/MAINTENANCE_BLOCK_equity_fabric
   options-paper  recovery=1 maintenance=None
--- dry_run=False
   action: options-paper START_COMMAND_FAILED | AssertionError('REAL LAUNCH INTERCEPTED')
   real systemctl start invocations intercepted:
     ['/usr/bin/sudo', '-n', '/usr/bin/systemctl', 'start', 'apex-options-paper.service']
```

So: `equity-fabric` is refused by its block with no attempt (R3 working);
`options-paper` passes preflight as `NOT_BLOCKED` and the orchestrator
**issues a real start command** — up to three attempts, each classified
truthfully by R4. Absent a change, the restriction does not hold at 13:30Z.

A first version of this probe returned `INDETERMINATE` for both services.
That was my interceptor referencing a name that lives in the ops module, not
the script; the preflight caught the resulting exception and failed closed
with no launch — the correct behaviour for the code, a wrong measurement from
me. Recorded, not hidden.

## 3. The arrangements

| | Arrangement | Holds the restriction? | Requires |
|---|---|---|---|
| **A** | **Maintenance block on `options-paper`** using the established convention: a marker `/apex-data/core/ops/MAINTENANCE_BLOCK_options_paper` plus a root drop-in declaring `ConditionPathExists=!<marker>`, then `daemon-reload` | **Yes, by systemd.** The deployed R3 preflight then records `MAINTENANCE_BLOCKED` and attempts nothing; if a race slipped past, systemd refuses and R4 records `CONDITION_REFUSED`. Reversible with `rm <marker>`. | One authorization: a systemd configuration change (root drop-in + `daemon-reload`). Not covered by the recovery authorization. |
| B | Explicitly authorize the launch as a `PAPER_EXPLORATORY` session with truthful reporting | Not a hold — a permission. | A reviewer decision. Nothing changes. |
| C | Stop the orchestrator before 13:30Z | Yes, crudely. | A service action, not authorized, and it blinds the session — the outcome recovery existed to prevent. Not recommended. |

**Recommendation: A**, prepared as a gated, fail-stop script
(`scripts/milestone1_block_options_paper_gated.sh`) whose dry-run prints the
exact marker and drop-in it would write. It is **not executed**. It converts
"the restriction holds if nobody is surprised" into "the restriction holds
because systemd enforces it", using the mechanism that already governs two
other services, and it is reversible in one command without a reload.

If B is chosen instead, the record should say so explicitly and the
Tuesday observation plan below still applies.

## 4. Verification if A is applied

1. `systemd-analyze condition "ConditionPathExists=!<marker>"` → `Conditions failed`.
2. `systemctl show apex-options-paper.service -p DropInPaths` lists the new drop-in.
3. The deployed R3 preflight, run read-only, returns `BLOCKED` for
   `options-paper` (the script performs this check itself).
4. At 13:30Z the orchestrator ledger records `maintenance.options-paper.state
   = BLOCKED` with a count, and **no action** for it.

## 5. The 13.5 MiB figure — a quiet-period measurement only

Thirty samples in phase IDLE on a non-trading day, with no launch attempted
and no incident escalated. It is not comparable to the previous multi-day
peak of 349.9 MiB, and it proves nothing about trading-hours behaviour, where
the orchestrator reconciles a fuller roster, verifies first work, and may
record incidents with bounded history. The plan is to re-run the
commissioning observer across the Tuesday open (13:15Z–14:15Z) and record
the unit's peak, the maintenance dispositions, and the newest record sizes
under RTH. Until then the trading-hours claim is **unmeasured**.

## 6. Research

No change. EXP-001's registration is preserved at hash
`1a3f55a5…`; the next research decision is the admission review, and
nothing runs on real data until it is made.
