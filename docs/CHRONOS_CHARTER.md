# CHRONOS — Causal Walk-Forward Intelligence Evolution Laboratory

**Born:** 2026-08-25 · **Authority:** `NONE_RESEARCH`, permanently
**Evidence label:** `HISTORICAL_REPLAY` — never upgrades to prospective
**Tests:** 33 contracts · suite 2,881 passing · V1 untouched

## 0. The honest goal

Overfitting cannot be made mathematically impossible. CHRONOS is built
so that overfitting becomes **extremely difficult to hide**: every
observation carries `known_from`, every hypothesis a birth and a frozen
hash, every discovery a search-family denominator, every fold a purge
and an embargo — and the pipeline is continuously fed poison and
nonsense to measure its own propensity to hallucinate alpha.

CHRONOS is **accelerated education**, not evidence. Real sessions
remain the final judge.

## 1. The laws (each enforced by test)

| Law | Enforcement |
|---|---|
| The clock only moves forward | `CausalClock.advance` refuses rewind |
| One door for data | `KnowledgeHorizon.get` is the only read path |
| NOT_YET_KNOWABLE ≠ POISON_CONSUMED | withheld field vs **hard fail naming the consumer, run invalidated** |
| No poison planted = untested firewall | audit reports `firewall_tested: false` |
| Hypotheses freeze over 6 degrees of freedom | variables, direction, threshold family, mechanism, horizon, payoff — missing one refuses to freeze |
| Killed in validation stays dead | "improving" it = **descendant**, new birth, zero inherited evidence |
| Purge + embargo at every boundary | train samples whose outcome window crosses a zone are `PURGED` |
| Partial folds dropped, never stretched | fitting the design to the data that happens to exist |
| Lockbox **2025-01-01 → 2026-06-01**, sealed by hash | any touch refuses without a one-time explicit operator act |
| Lifelines cannot cite the future | an event's `evidence_known_from` may not postdate the event |
| The future grades sealed decisions, never feeds them | `grade_retirement_timing`; `RETIRED_A_LIVING_EDGE` is a named cost |
| Common history in the tournament | a policy skipping moments is refused, roster closed, NO_TRADE mandatory |
| Beating momentum but not RANDOM_ELIGIBLE | "discovered eligibility, not skill" |
| Two scores, no composite | `blend()` raises — a composite is a dial someone will optimize |
| Unmeasured ≠ low | zero control runs → `NO_CONTROLS_RUN`, never a pass |

## 2. First demonstration — the machine caught itself immediately

One full cycle on real SPY daily history (2018–2024, last fold:
train 500d / validate 180d / test 180d, lockbox untouched, poison
planted):

**The economic result looked good and the machine says not to
believe it.** That sentence is the whole deliverable.

- **Poison pill:** `TRAP_FIRED_AS_DESIGNED` — a deliberate consumption
  of `future_return_1d` hard-failed, naming the consumer.
- **Zone A discovery, WITH shadows injected:**

  | feature | separation (pct) | discovered | nonsense? |
  |---|---|---|---|
  | moon_phase_mod_7 | **−0.455** | yes | **yes** |
  | prior_day_ret_pct | +0.288 | yes | no |
  | gap_pct | +0.236 | yes | no |
  | random_gaussian_14 | −0.211 | yes | **yes** |
  | vol20 | −0.192 | yes | no |
  | hash_of_timestamp | −0.149 | yes | **yes** |

  The strongest "discovery" in the entire search was **the moon
  phase**. Real-feature separations sit *inside* the nonsense range.
  Shuffled-label controls hit 4/6. **Hallucination temperature: 1.0 —
  `PIPELINE_TOO_PERMISSIVE`.** The 0.12pp separation bar was set far
  below the measured noise floor of 343 correlated daily observations.

- **And yet the pipeline "succeeded" downstream:** the frozen candidate
  (`prior_day_ret_pct` top-quintile, LONG) `SURVIVED_VALIDATION`
  (n=8 acts) and `CHALLENGER_DOMINATED` the sealed-test tournament
  (+3.11R over 8 acts, 87.5% favorable, beat momentum, random-eligible
  and NO_TRADE). Without the controls this would read as a discovery.
  With them, it reads as what it almost certainly is: **noise that got
  lucky twice**, produced by an engine with a measured 100% hit rate
  on known nonsense. `false_discovery_restraint: FAILED` is recorded
  in the scientific score beside the pretty economics, and neither can
  erase the other because they are never blended.

## 2b. Experiment 000 — official classification (appended 2026-08-25)

```text
ECONOMIC_TEST_RESULT:  POSITIVE            (+3.11R / 8 acts, sealed)
SCIENTIFIC_VALIDITY:   FAILED_FALSE_DISCOVERY_CONTROL
EDGE_AUTHORITY:        NONE
```

The key fact is not +3.11R. It is that **the discovery engine could
not distinguish real structure from deliberate nonsense.** The
economic outcome is preserved as a real sealed fact and earns zero
edge authority — economic success cannot rescue scientific
invalidity. Experiment 000 is never rerun with a corrected threshold;
the corrected machinery is a new lineage (Campaign #001, EXP 001+).

## 3. Campaign rule earned by this result

For the real CHRONOS campaign, the discovery bar is **set
prospectively from the measured nonsense floor** — above the maximum
separation the shadows and shuffles achieve in the same fold — and is
never adjusted retroactively to clean up a report. Tonight's report
stands as-is, permissive threshold and all, because a corrected
scoreboard with the original miss erased is how instruments learn to
lie.

## 4. What V0 is not

- Not the multi-year online-learning replay — that is a **campaign**
  (a long-running accumulation, like live sessions), not a build.
- Not wired into EdgeForge's full faculties yet — the demo used a
  deliberately crude single-feature searcher to test the **cage**.
- Not a source of prospective evidence, ever.

## 5. Campaign #001, first pass (58 monthly epochs, 2020-03 → 2024-12)

Success criterion (not profitability): drive false-discovery behavior
materially below Experiment 000 while still occasionally finding
candidates that survive unseen time.

**Half met, half not — and the honest half-miss taught more.**

- **Restraint: 0/58 epochs failed** the per-epoch null calibration
  (vs Experiment 000's temperature 1.0). The p99 null bar, frozen in
  the discovery zone each epoch, did its job: real scores hovered at
  0.18–0.21 against bars of 0.15–0.22, and births happened only on
  strict exceedance. The self-attack fired all nine poison traps in
  every epoch. Criterion half one: **met**.
- **Survival: the family did not survive unseen time.** 51 edges born,
  42 retired, 2,003 sealed decisions netting **−7.05R**. Fifteen
  retirees were positive (+53.6R) — but they are clones: births in 51
  of 58 epochs are the *same marginal hypothesis reborn monthly under
  a new id*, and its siblings lost −60.4R. Selecting the winners would
  be survivorship. Criterion half two: **not met**.
- **My own metric defect, corrected with lineage:**
  `survived_unseen_time` was computed as `bool(retired)` — retirement
  counted as survival — inflating the first-pass classification to
  `RESEARCH_CANDIDATE`. Corrected (correction appended to the
  registry, original preserved):

  ```text
  ECONOMIC_TEST_RESULT:  NEGATIVE   (−7.05R / 2,003 sealed decisions)
  SCIENTIFIC_VALIDITY:   PASSED_FALSE_DISCOVERY_CONTROL
  EDGE_AUTHORITY:        NONE
  ```

- **The identified multiplicity gap (registered for Campaign #002):**
  per-epoch null calibration controls nonsense *within* an epoch; it
  cannot see the same hypothesis reborn *across* epochs on overlapping
  data. Rebirth must obey the descendant law — a candidate whose
  frozen spec matches an active or recently retired edge is the same
  hypothesis, not a new discovery.

The organism is no longer fooled by the moon phase. It has not yet
found anything real. Both facts are on the record, separately.

## 6. Campaign #002 — the rebirth channel closed (same battlefield)

Same four features, same family, same 58 epochs, same lockbox. Only
the scientific process changed: three-level identity (SPEC / FAMILY /
MECHANISM), clone blocking, the descendant law, and predeclared
alpha-spending sequential control (attempt k spends 0.05·2⁻ᵏ, judged
by rank among an attempt-determined null budget).

| | Campaign #001 | Campaign #002 |
|---|---|---|
| "discoveries" / edges born | 51 | **3** |
| unique hypothesis families | (untracked; ≈1) | **1** |
| clone births blocked | 0 | **33** |
| sequential / tail refusals | 0 | **22** |
| sealed decisions | 2,003 | 166 |
| sealed total | −7.05R | +9.10R |
| CROSS_EPOCH_MULTIPLICITY_CONTROL | FAIL | **PASS** |
| OVERALL_SCIENTIFIC_AUTHORITY | NONE | **QUALIFIED** |

**"I found 51 edges" became "I tested one idea 25 times."** The
family's full lifeline: attempt 1 died (−1.87R, on record as a
sealed-test failure); attempt 2 refused; attempt 3 admitted at
α₃=0.00625 and ran 112 acts to **+11.35R** before decay retired it;
attempt 4 died (−0.38R); attempts 5–25 hit `NULL_TAIL_UNRESOLVED`
twenty-one straight times — the lifetime alpha budget is spent, and
the family can never be asked about again at the fixed null budget.
The organism kept asking; the framework refused every time.

**Plain answers (as corrected on the chain):**
- Did the cross-epoch rebirth channel close? **YES.**
- Did any candidate survive unseen time *without* repeated research
  attempts? **NO.** The one net-positive survivor was its family's
  third attempt — admitted legitimately under the charged-repeat
  framework, which is that framework's purpose, but never to be
  conflated with first-shot survival. (My script initially answered
  YES from family-level net survival; corrected with lineage.)

The +9.10R is HISTORICAL_REPLAY, one family, one realized path,
dominated by a single 112-act run through 2020-09→2022-10. It confers
`RESEARCH_CANDIDATE` under the predeclared rules and nothing more.
Prospective sessions remain the judge, and the lockbox remains
sealed.

## 7. Campaign #003 — roster control held; the survivor was beta

**Scientific dimension** (predeclared hierarchical alpha-spending,
MECHANISM → FAMILY → ATTEMPT, `ALPHA_GLOBAL = 0.10`, halving at every
level): 6 persistent nonsense research lanes with complexity-matched
search ran through the identical process for 58 epochs — **21
nonsense families, 20 nonsense mechanisms, 348 attempts, ZERO
admitted at any level.** `ROSTER_MULTIPLICITY_CONTROLLED`. Honesty
about the mechanism: 342 of 348 attempts were refused as
`TEST_NOT_ESTIMABLE` before scoring — the schedule makes late
mechanisms unresolvable at the capped null budget, so protection came
primarily from *refusal by budget*, and only ~6 nonsense attempts
were ever scored. Small denominators, stated. Research opportunity is
consumed, not printed.

**Economic dimension** — the archaeology of C2EDGE_002, under verdict
rules predeclared in the script:

| | value |
|---|---|
| candidate total | +11.35R over 112 acts |
| random 112-day subsets of the SAME period | median +2.01R, p90 +12.98R |
| selection permutation p̂ | **0.141** (> 0.05) |
| market beta / up capture / down capture | 0.26 / 0.28 / 0.23 |
| RANDOM_ELIGIBLE over the same window | **+21.1R** |
| verdict | **`BASELINE_REPACKAGING`** |

Picking those 112 days added nothing distinguishable from picking 112
days at random in a window so generous that a coin-flip policy made
almost twice as much. The within-UP_HIVOL cell shows p̂ = 0.022, but
that cell was selected post hoc among four and the overall gate
failed first — recorded as a residual observation, never a finding.

**Plain answers:** roster control — **YES** (with the refusal-by-
budget caveat). Survivor beyond beta — **NO.**

**Status:** `SCIENTIFIC_PROCESS_AUTHORITY: QUALIFIED_REPLAY_ONLY` ·
`ECONOMIC_EDGE_STATUS: UNPROVEN` · `TRADING_AUTHORITY: NONE`. The
scientist's ledger now reads: one idea, tested 25 times, its best run
explained by the market it sat in. That is not a failure of the
scientist — it is the scientist finally being able to say so.

**CHRONOS educates. Reality examines. The lockbox waits.**
