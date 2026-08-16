# THE MUSEUM OF NEGATIVE CONTROLS

Every defect here was capable of **impersonating a market result**. Each
is preserved as a permanent negative control: a refactor that makes any
of them pass again is an integrity regression, not an improvement.

```
LAB-01   missing symbol      -> dead tick
LAB-02   quota starvation    -> hollow market
LAB-03   O(n^2) ledger       -> stalled experiment
LAB-04   missing context     -> blindness looked selective
LAB-05   provider quota      -> fetch-failure disguise
LAB-06   archive growth      -> production disk threat
LAB-07   reserve existed in theory, not in execution
LAB-08   class checked downstream, laundered upstream
```

The first six share a disease: **"SYSTEM FAILED TO OBSERVE MARKET"
wearing the clothes of "MARKET SAID NO."**

LAB-07 and LAB-08 belong to a second, more dangerous category.

---

## CATEGORY II — CONTROL EXISTENCE ≠ CONTROL ENFORCEMENT

> The dashboard says a protection exists while the execution path never
> consults it.

Category I corrupts *data* and can be caught by staring hard at results.
Category II corrupts *guarantees*, and it is invisible in results by
construction: the system reports compliance because the compliance report
reads the same prose the protection was written in. Nothing looks wrong.
The number is simply never enforced.

### LAB-07 — the forward reserve

`FORWARD_RESERVE_CALL_UNITS = 35_000` existed. `lab_spare_units()`
computed headroom from it. The function had **zero callers**. Compounding
that, `QuotaGovernor.used` reset in every process and the fast runner
built one governor per (worker × day) while *printing* "workers can never
collectively exceed the lab total" — a false claim, ceiling ~375k against
a stated 45k. GMT day 2026-08-16 reached 100,000/100,000. On a Monday it
would have blinded Epoch 1 and looked like a vendor outage.

**Enforcement moved to the point of consumption:** a cross-process,
GMT-day, `flock`-serialized counter consulted inside `acquire()`.

### LAB-08 — evidence-class laundering

`require_unmixed()` existed and was called — in the **scoreboard**, over
ledger records, after the fact. But `analog.retrieve()` accepted an
`evidence_class` *argument*, never inspected the rows, and stamped its
output with whatever it was told; `analog_memory_rows()` did not put a
class on the rows at all, so the engine could not have checked. The
docstring said *"ALL rows must share evidence_class (caller separates
ledgers)"* — enforcement delegated to the caller by comment.

Consequence had it been wired: offering laboratory rows while declaring
FORWARD would return a result **stamped clean-forward**. Not a mix — a
*laundering*, with valid provenance. The downstream mixing guard would
never have seen it, because it inspects ledger records, not engine
inputs. `build_dataset()` had the same shape, and its
`forward_eligibility` filter was no barrier at all: the replay lab
deliberately stamps its records `FORWARD_ELIGIBLE` as a declared
counterfactual.

Severity was LATENT — production called it correctly with the production
ledger — but latency is a property of today's wiring, not of the design.

**Enforcement moved to the point of consumption:**
`require_declared_class()` verifies every offered row against the
declaration at the top of `retrieve()` and `build_dataset()`, before a
neighbour is chosen or a field is stamped. Unstamped is refused as loudly
as mismatched, because a class that cannot be checked cannot be
certified.

---

## The standing question

For every safety claim, ask the Category II question:

> Show me the exact code path where the prohibited action is stopped at
> the moment it would occur.

Full claim-by-claim answers, with enforcement grades, live in
[ENFORCEMENT-DOCTRINE.md](ENFORCEMENT-DOCTRINE.md). Proofs live in
`tests/test_enforcement_doctrine.py`, where each test **attempts the
prohibited action through the real code path**.

Both LAB-07 and LAB-08 were found the same way: by asking `grep` who
actually calls the guard. That question is now part of the audit.

### INSTR-01 — the instrument that certified itself

**Category II, pointed at the dashboard rather than the system.**

The certification harness built to *detect* Category II defects shipped
with one. Both broker scripts did:

    try:    from apex.execution.mcp_transport import transport
    except ImportError:    transport = None

That module did not exist. `transport` was always `None`, and every
broker row rendered `BLOCKED_BROKER_AUTH` — so the board reported *"the
operator has not authenticated yet"* when the truth was *"this process
cannot reach the broker even after they do."* A certification that can
never turn green is worse than none: it looks like progress pending
someone else.

On the first run of the repair it then printed **"APEX EXECUTION
INFRASTRUCTURE: READY"** with eight rows unreachable, because the READY
condition tested only for FAIL. An unmeasured row is not a passing row.

Same audit then found the same disease in the **Flight Deck**, where it
mattered more: eleven readiness rows were hardcoded string literals.
`"Scout": "READY"` was true because someone typed it. Deleting
`apex/hunter/scanner.py` would not have changed the cockpit. This is the
surface the operator watches to decide whether the machine is alive.

**Repairs.** Three honest transport states (`NO_TRANSPORT` /
`BLOCKED_BROKER_AUTH` / `READY`); READY requires every row MEASURED, with
the exit code following; every component row now imports the module it
describes and reports `UNAVAILABLE_<error>` when it cannot. Negative
control: with the scanner made unimportable, the Scout row flips to
`UNAVAILABLE_ModuleNotFoundError` while unrelated rows stay READY.

**The principle, stated for the Flight Deck's whole future:**

> A control that reports a state it never actually measured is not a
> control. An indicator that cannot go red has no information in it
> when it is green.
