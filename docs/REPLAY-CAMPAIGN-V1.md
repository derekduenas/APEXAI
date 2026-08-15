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
