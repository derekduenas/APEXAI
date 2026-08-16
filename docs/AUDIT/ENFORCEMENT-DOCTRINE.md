# CONTROL EXISTENCE ≠ CONTROL ENFORCEMENT

**Operator doctrine, adopted 2026-08-16 after LAB-07.**

For every major safety claim APEX makes, the audit question is:

> Show me the exact code path where the prohibited action is stopped **at
> the moment it would occur.**

Not:

> Show me the function that calculates whether it should occur.

LAB-07 is why. `FORWARD_RESERVE_CALL_UNITS = 35_000` existed;
`lab_spare_units()` computed headroom from it; the function had **zero
callers**. The dashboard said a protection existed while the execution
path never consulted it. A campaign then spent the entire reserve.

Three enforcement grades, strongest first:

1. **NON-REACHABILITY** — the action cannot be expressed. No method, no
   enum member, no import. Nothing to check because nothing to call.
2. **POINT-OF-ACTION REFUSAL** — the action is attempted and the code
   that would perform it refuses, in the same call.
3. **DOWNSTREAM DETECTION** — a validator elsewhere notices afterwards.
   *This grade is not a control.* It is a smoke alarm, and LAB-07/LAB-08
   are what it looks like when it is mistaken for a fire door.

Each claim below names its enforcement point and its proof in
`tests/test_enforcement_doctrine.py`.

---

### CLAIM 1 — "the Captain cannot authorize"

**Grade 1, non-reachability.** `apex/hunter/capital.py` contains no
reference to the Captain at all — no import, no parameter, no field. The
Captain physically cannot reach the moment of authorization. The kernel
separately contains no authorization verbs.
*Gap closed by this audit:* the property was true but unguarded; a future
import would have silently broken it. Now asserted.

### CLAIM 2 — "Capital caps size"

**Grade 2.** The clamp is applied where the weight is produced
(`capital.py:215`, `min(PAPER_RISK_BUDGET_FRAC * scale / risk_frac,
MAX_POSITION_WEIGHT * scale)`), then re-checked by `assess_risk` at 227.
An absurd `risk_frac` cannot inflate the result.

### CLAIM 3 — "a stop never widens"

**Grade 2.** `tighten_stop()` raises on the widening call itself, and
`paper.py:173-178` repeats the refusal at the position level. Two
independent points, both at the moment of the change.

### CLAIM 4 — "live placement is sealed"

**Grade 1 + 2, four barriers.** No `place_*` method exists; the transport
refuses non-allow-listed and mutating tool *names*;
`LiveExecutionAuthorization` raises in `__init__`; a package-wide scan
proves no module defines a placement function. `ReadinessState` cannot
express `ORDER_SENT`.

### CLAIM 5 — "paper is unreachable in Epoch 1"

**Grade 2.** `PAPER_ELIGIBLE` requires a commissioned forecast; the slot
is `NOT_YET_AVAILABLE` and a present-but-uncommissioned estimate is
REFUSED rather than synthesized. `LIVE_ELIGIBLE` is not in the enum at
all (grade 1).

### CLAIM 6 — "evidence classes cannot mix"

**WAS GRADE 3 — FIXED BY THIS AUDIT (LAB-08).** `require_unmixed()` ran
only in the scoreboard, over ledger records, *after* the fact. The analog
engine accepted an `evidence_class` argument, never inspected the rows,
and stamped its output with whatever it was told; `analog_memory_rows()`
did not even put a class on the rows, so the engine could not have
checked. `build_dataset()` filtered on `forward_eligibility` — which the
replay lab deliberately sets to `FORWARD_ELIGIBLE` as a declared
counterfactual, so it was never a class barrier.
**Now grade 2:** `require_declared_class()` verifies every offered row
against the declaration at the top of `retrieve()` and `build_dataset()`,
before anything is selected or stamped. Unstamped is refused as loudly as
mismatched.

### CLAIM 7 — "the forward reserve is protected"

**WAS GRADE 3 (in fact grade 0 — no caller). FIXED: LAB-07.** Now a
cross-process, GMT-day, `flock`-serialized counter consulted inside
`QuotaGovernor.acquire()`, the single gate immediately preceding every
provider request.

### CLAIM 8 — "stale data cannot trade"

**Grade 2.** Quote freshness (≤30s) and decision freshness (≤15m) are
checks inside the execution kill chain, evaluated where the intent
becomes `ORDER_READY`. Hard `data_quality` flags block the capital
decision at `capital.py:107/182`.

---

## Standing rule

A new safety claim is not "implemented" when the check exists. It is
implemented when a test in `test_enforcement_doctrine.py` **attempts the
prohibited action through the real code path** and is stopped. A test
asserting that a validator returns False is evidence about the validator,
not about the system.
