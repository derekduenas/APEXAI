# APEX FULL-SYSTEM REPLAY CAMPAIGN v1 (PREDECLARED 2026-08-15 ~23:20Z,
frozen BEFORE any campaign result exists)

Frozen production commit: **0efad01 / model v1.5.7** (the lab harness
executes this exact machine; laws in scripts/hunter_replay.py).
Evidence: **EODHD_HISTORICAL_EXPLORATORY ONLY** — can never graduate,
calibrate, spend Credit 5, or authorize anything. Swarm: **DISABLED
(Rule 17, tripwire-enforced)**. No strategy modifications during the
campaign; findings become *versioned hypotheses* (e.g. Hunter-001-v2)
that enter governance later — the laboratory is never an optimizer.

## Date selection (predeclared, selection-bias-immune)

**ALL NYSE trading sessions from 2026-04-06 through 2026-08-14
(~92 sessions), no exclusions, no hand-picking.** A continuous window
cannot cherry-pick famous days. Regime coverage is MEASURED afterwards
(SPY-derived online labels + per-session world descriptors), not
selected for. If any stratum is thin, that is reported as a coverage
limitation, never patched by adding chosen dates.

## Universe

Production parity: the frozen liquidity-top-150 rule from the CURRENT
snapshot (non-PIT for these dates — survivorship limitation stamped on
every record; one more reason this is a laboratory).

## Preregistered analyses (scripts/hunter_replay_analysis.py)

1. **THE FUNNEL** (the architecture test): N / 60m EV / hit / MFE / MAE
   at Scout-baseline → Hunter-matched → Assassin clean vs wounded →
   Capital states. Hypothesis: economic quality rises down the funnel.
2. **ASSASSIN, brutally**: wounded-vs-clean cohorts across 15/30/60/90m
   EV, median, hit, MFE, MAE, downside tail. Question: does it identify
   trades we are genuinely better off avoiding?
3. **Baselines**: RANDOM / MARKET / MOMENTUM / RELSTRENGTH on identical
   subjects (recorded inside the replay by the frozen machine itself).
4. **Regime breakdown**: session-level UP/DOWN, CALM/VOL (online SPY
   classifier, never revised), plus long/short and per-playbook splits.
   Sample sizes reported ruthlessly; cells below n_eff 10 are labeled
   INSUFFICIENT, never interpreted.
5. **Edge persistence (exploratory)**: EV by horizon per playbook —
   what kind of predator is each mechanism?
6. **Deterministic post-hoc ablations** on the recorded candidate set:
   NO-ASSASSIN-CAUTION (capital re-evaluated with wounds zeroed),
   NO-ROUTER (deep always allowed — no LLM in lab so scheduling-only),
   capital-caution on/off. PRE-SELECTION ablations (no-RS scanner,
   no-Twin) require instrumented re-runs and are declared Phase 2 of
   the laboratory, not computed post-hoc from insufficient records.
7. **Time-of-day and concentration diagnostics** (symbol/sector/day
   dominance).

## Discipline

Analysis script written BEFORE the campaign completes; its report shape
is this document. Nothing in Epoch 1 changes because of anything found
here. Sample-size floors: no cohort below 10 effective sessions is
interpreted. The Swarm's value is evaluated ONLY prospectively from
Monday (its unique advantage: evidence we cannot manufacture
historically).

## Amendment (2026-08-16 ~01:15Z): ATTEMPT_1 aborted; accelerated harness certified

ATTEMPT_1 (legacy harness) went HOLLOW after 7 sessions — LAB-02: the
QuotaGovernor's per-process 2000-request budget (pilot-era) starved all
later fetches silently. Caught by states-health before any economics
were read; ledger preserved for diagnostics; ZERO observations
contribute. Fixes: lab-scale budget (90k) + fail-loud per-day health
abort in both harnesses + hollow-day check in the integrity gate.

ACCELERATOR CERTIFIED: two-pass harness (parallel per-day perception ->
chronological enrichment) produced BYTE-IDENTICAL canonical records in
IDENTICAL ORDER vs the legacy harness on a fixed 2-session sample
(1,347/1,347). Same experiment, less compute. The official campaign_v1
denominator restarts from zero under the accelerated harness; dates,
universe, laws, and preregistered analyses unchanged.

Lab speed tiers (standing): SMOKE 2 / MICRO 10 / RESEARCH 25 /
CAMPAIGN 90+ sessions; FORWARD = the only evidence that matters.

## Amendment (2026-08-16): the three-level clean + the museum

Operator hierarchy, now enforced in compute_integrity():
1. RECORD integrity — did we write the data correctly? (chain, classes,
   production isolation)
2. OBSERVATION integrity — could APEX actually see? (context health
   median/p10/min per session, hollow days, context-starved days).
   Zero abnormalities is LEGAL; zero observability is not. Prove APEX
   could see before asking what APEX saw.
3. EXPERIMENT integrity — were the declared laws obeyed? (Rule 17,
   denominator, counterfactual declarations)

ATTEMPT_2 passed 1 and 3 while failing 2 — a perfectly valid ledger of
perfectly wrong observations. The gate now locks economics on all three.

THE MUSEUM (tests/test_integrity_museum.py): aborted attempts are
permanent negative controls — ATTEMPT_1 (LAB-02 hollow) and ATTEMPT_2
(LAB-04 blindfold) must be REFUSED forever, each for its own disease;
if a refactor ever makes a museum piece pass, the integrity system has
regressed. ATTEMPT_0's ledger was not preserved (tombstone + unit
guards only) — preservation is now the standing rule.

LAB DEBT (recorded, not blocking ATTEMPT_3): a shared provider-
concurrency semaphore so CPU workers and outbound API pressure become
separate knobs (WORKERS=12 / PROVIDER_CONCURRENCY=3 style); per-fetch
failure/retry counters instrumented into the lab ledger so provider
health is reportable, not inferred.

TWIN DOCTRINE reinforced by LAB-04: every future world-state facet
carries VALUE + SOURCE + EVENT_TIME + KNOWN_FROM + FRESHNESS + QUALITY
+ COVERAGE + STATUS — "RVOL unavailable" is fundamentally different
from "RVOL normal"; "breadth weak" is fundamentally different from
"only 22% of the universe was measurable." APEX must always know
'the market is quiet' from 'my sensors are broken.'
