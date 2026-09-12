# Freshness adjudication — what §1.1 requires for ranking versus execution

Date: 2026-09-12. Decided against the contract text, once, in writing. Two reviewers had previously instructed a
change to this behaviour from recollection; this record replaces recollection with the clause.

## The clause

`docs/R4_JOINT_MARKET_STATE_SPEC.md` §1.1 (blob `a0228fac…`, unchanged by this repair), verbatim:

> option quotes (indicative 120 s; execution 15 s at the boundary)

and §1.2, verbatim: "Every quote passes `sanitize_quote` before any use (r3 rule)."

The boundary named there is the recording boundary's fill step, `Boundary.execute_intent`, which fetches a
**fresh** quote for the intent's contract and refuses to fill when that quote is older than
`MAX_SELECTED_QUOTE_AGE_S = 15 s` at the simulated execution instant (`STALE_SELECTED_CONTRACT` → WAIT).
`state.compose` already sanitizes ranking quotes with `max_age_s = QUOTE_MAX_AGE_S = 120 s` and refuses
`FUTURE_INPUT` and `QUOTE_STALE_OR_FUTURE`.

## What the clause requires

| Stage | Quote used | Age limit | Enforced where |
|---|---|---|---|
| State assembly, IV, skew, ranking, proposal | the indicative chain quote at `t_d` | 120 s | `sanitize_quote` in `state.compose` |
| Fill | a fresh executable quote fetched after the intent is on disk | 15 s at the simulated execution instant | `Boundary.execute_intent` |

Nothing in the clause bars a 15–120 s indicative quote from producing a **proposal**. The proposal is not an
execution; the execution is the fill, and the fill re-quotes.

## What the code at the review base did

`apex/joint_wb/engine.py:293-297` (b9998d02): a candidate whose indicative quote was older than 15 s was placed
in the reported table as `INDICATIVE_ONLY` and **omitted from `ranked`**, the only set from which a proposal is
chosen. Its inline comment said the quote "may be RANKED and REPORTED". It was reported. It was not ranked.

Consequence, reproduced in `docs/evidence/decision_path_reproductions.json` (`F5`): with every valid quote 30 s
old, `n_eligible = 0` and the decision is WAIT with `NO_ELIGIBLE_CANDIDATE`. A ThetaData snapshot timestamp is the
time of the last quote change, so a stable, perfectly valid quote 20 s old could never propose. The 15 s
execution limit was being applied at proposal time, where the contract does not place it, and the boundary's own
15 s check on the fresh quote still ran afterwards.

## Ruling

**The behaviour did not comply.** It applied the execution limit one stage early and denied the indicative
window the contract grants. The repair:

- ranking and proposal accept any quote `sanitize_quote` accepts under the 120 s indicative limit; the candidate
  row records `age_s`, `executable`, and the freshness decision so the trace shows which stage the quote could
  serve;
- the census entry `EXECUTION_QUOTE_STALE` (a stage-1 exclusion) is replaced by `INDICATIVE_AGE_15_120S` (a count);
- the boundary's 15 s executable check, `FUTURE_INPUT`, `QUOTE_STALE_OR_FUTURE`, receipt-time measurement, the
  intent TTL, and every retry/recovery check are unchanged;
- the test that encoded the wrong behaviour (`test_14_9s_is_executable_and_15_1s_is_indicative_only`) is replaced
  by one that proves a 30 s indicative quote can support an intent and a stale execution quote cannot fill.

No contract text was changed. No new requirement was added. `EXECUTION_MAX_AGE_S` remains 15 s and
`QUOTE_MAX_AGE_S` remains 120 s.
