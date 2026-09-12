# SIGNAL_STATUS_001 — there is no validated directional signal on the options path

Recorded 2026-09-12. Standing until superseded by a signal that has cleared its own evidence bar.

## The plain statement

`apex/pulse_options/sources.py:29`:

```
DIRECTION_RULE = "HEURISTIC_DIRECTION_V1: LONG if ret_15 > 0, SHORT if ret_15 < 0, None otherwise; not a forecast"
```

That is the entire live direction logic on the options path: **the sign of the last 15-minute return.** It selects
the right of every contract the pilot buys. It is labelled "not a forecast" in its own constant, and that label is
accurate.

1. **There is no validated directional signal on the options path.** None has ever been proposed, fitted, or
   evaluated for this instrument at this horizon.
2. **`HEURISTIC_DIRECTION_V1` is a placeholder.** It exists so the recording boundary has a deterministic input and
   the pipeline can be exercised end to end. It was never a hypothesis.
3. **No P&L produced under it is evidence about anything except the pipeline.** Not about edge, not about the
   instrument, not about the exit rule, not about the toll model beyond the toll's own arithmetic.
4. **A negative result under it is the EXPECTED result, not a finding about the system.** A 15-minute hold on a long
   single leg crosses the spread twice and pays theta; see `docs/SIGNAL_HURDLE_001.md` for the arithmetic. Momentum
   at the sign of a 15-minute return has no established relationship to the next 15 minutes on SPY. Losing money
   under it confirms the toll, not a defect.
5. **The forecast record is also not a signal.** `EXP002_L` is sealed on every forecast with
   `validation_status: NOT_VALIDATED … INVALID_NULL_CONTROL … no edge claim`, and `drives_expression_selection:
   false`. It is recorded, not consulted.

## Why this document exists

A placeholder becomes a strategy by accumulation: sessions run, records pile up, someone reads the pile as a track
record. The defence is that every record points here. A reference to this document is sealed on every pilot record
so that no future reader can mistake accumulated observations under a placeholder for evidence about a signal.

## What would change this

A signal earns the name when it (a) is written down before it is measured, (b) clears the hurdle in
`docs/SIGNAL_HURDLE_001.md` on data it was not fitted on, and (c) is evaluated under the same execution, fee and
exit machinery the pilot runs. Until all three, `HEURISTIC_DIRECTION_V1` stays, and it stays labelled.
