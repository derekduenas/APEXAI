# DAY-1 PARTIAL-SESSION INTEGRITY — RATIFIED FINDING

**known_from: 2026-08-17T14:50:00+00:00** (operator ratification, APEX
DAY-1 FAIL-CLOSED directive)
**filed: 2026-08-17T14:57:00+00:00**

This is an append-only record. It does not alter, delete, or reinterpret
any earlier record from today — including the P0 recovery report that
first classified today `PARTIAL_FORWARD_SESSION_AFTER_P0_REPAIR`. That
classification is preserved as the operational-history description. This
document supersedes it **for strategy/decision evidence only**, with:

    DAY_1_INVALID_FOR_DECISION_EVIDENCE

## Distinguish clearly

    OPERATIONAL RECOVERY = SUCCESSFUL
    STRATEGY EVIDENCE    = INVALID

The two P0 defects (Frontier launcher typo, EODHD historical-endpoint
transport mismatch) were real production defects, correctly diagnosed,
and correctly repaired. Live trade capture, bar construction, and
FastWatch observation are genuinely healthy and continue running. None
of that is in question. What is in question is whether today's
**session-anchored ChartState** can be treated as valid input to an
official decision.

## The finding

Live equity observation began at **10:17 ET**, 47 minutes after the true
09:30 ET open. `apex/hunter/chartstate.py:164`:

```python
open_t = times.iloc[0]
```

treats the first *observed* bar as session open. There is no comparison
anywhere in `compute_chart_state()` against the true exchange session
boundary — the function cannot distinguish "market just opened" from
"our feed just started." This was true before today's repair as well
(it is a latent property of the function, not something the repair
introduced); today is simply the first day it was exercised with a feed
that started 47 minutes late.

Confirmed against live SPY numbers:

| | |
|---|---|
| First live bar | 10:17 ET |
| First live bar open price (code's `day_open`) | $775.26 |
| True Friday close | $775.98 |
| Resulting `gap_frac` | −0.093% |

That number is not an overnight gap. It is 47 minutes of unobserved
intraday drift, computed and labeled exactly as if it were the real
opening gap.

### Affected fields (all downstream of `open_t`)

`vwap`, `distance_to_vwap`, `vwap_slope`, `above_vwap`, `vwap_reclaim`,
`vwap_rejection`, `or_complete`, `or_high`, `or_low`, `position_in_or`,
`or_break_up`, `or_break_down`, `or_failure`, `gap_frac`,
`gap_direction`, `gap_fill_frac`, `rvol_tod`, `cum_volume`,
`minutes_into_session`, `day_return`.

The existing `data_quality` gate (`SPARSE_BARS`, `STALE_BARS`, etc.) does
**not** catch this: `SPARSE_BARS` compares `len(f)` against the same
`open_t`-derived `minutes_in`, so a continuously-captured late-starting
feed reads as clean. The gate is structurally blind to this exact
failure mode. This is a decision-affecting corruption, not a mere
degradation.

## Action taken (session integrity gate, not a repair)

Per explicit instruction: **ChartState math was not touched.** No frozen
Hunter predicate, threshold, Capital state, or Captain doctrine was
modified. Instead, a narrow, dated, additive refusal law was added:

- `apex/governance/session_integrity_gate.py` — a dated list
  (`INVALID_SESSIONS["2026-08-17"]`), consulted only by the two
  operational scripts already touched during today's transport repair.
  It can only refuse; it authorizes nothing and is not part of the
  Hunter birth-eligibility law.
- `scripts/hunter_forward_clock.py` — annotates `scan_record` and every
  `decision` record with `decision_evidence_validity` /
  `session_integrity`, and **withholds `enrichment_pass`** (the step
  that mints Capital's OBSERVE/WATCH/PAPER_ELIGIBLE/NO_TRADE/REFUSED
  authorization state) for the ratified date. Withheld, not run — an
  explicit `capital_review_refused` record is chained in its place.
- `scripts/frontier_loop.py` — refuses to seal a Decision Card or open a
  Shadow Paper position for any decision today, recording an explicit
  `frontier_decision_refused` record instead of silently skipping.

Because no `capital_decision` record is minted today, Shadow Paper's
**own existing, untouched** eligibility law
(`apex/frontier/shadow_paper.py: eligible()`) already returns
`(False, None, "no capital decision exists")` for anything from today —
no change to that file was needed.

## What continues, unaffected

Raw WebSocket trade capture, 1-minute bar construction, the subscription
allocator, provider/quote-channel health, quota and disk monitoring, and
FastWatch's own observation ledger (a candidate-evolution latency
measure, not a decision) all continue running exactly as before this
finding. This data remains valuable for infrastructure QA, feed coverage
analysis, provider stability, and post-close debugging — explicitly not
for Epoch-1 graduation evidence, performance statistics, calibration,
selectivity claims, or Shadow Paper economics.

## Required post-close repair (not performed tonight)

1. Repair ChartState to require explicit session-start provenance —
   `open_t` must compare against the true exchange session clock, never
   the first observed bar.
2. Each session-anchored feature must carry independent validity
   (SESSION_VWAP, OPENING_RANGE, GAP, RVOL each need their own
   sufficiency check against required history).
3. Missing history stays UNKNOWN/INVALID, never zero.
4. A canonical `SESSION_COVERAGE` contract: `required_start`,
   `observed_start`, `missing_intervals`, `coverage_fraction`,
   `opening_observed`, `session_anchor_valid`.
5. `ChartState.data_quality` must fail closed when an anchor-dependent
   feature lacks required history.
6. New tests: full session from 09:30; feed starting 09:31; feed
   starting 10:17; missing middle interval; late reconnect; DST/session-
   calendar correctness; first observed bar cannot become market open;
   a fake OR cannot become complete; partial VWAP cannot masquerade as
   SESSION_VWAP; gap cannot use an arbitrary intraday price; RVOL cannot
   silently undercount missing session volume.
7. Full suite green.
8. Remint the starting line only after (7).

Until that lands, `apex/governance/session_integrity_gate.py` is the
only thing preventing a corrupted session from producing evidence-grade
records — a dated patch, not a permanent mechanism, and it should be
retired the moment the real repair ships.
