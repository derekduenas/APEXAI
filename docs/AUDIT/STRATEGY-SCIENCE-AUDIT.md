# STRATEGY SCIENCE AUDIT (2026-08-15, frozen — findings only, no retuning)

## Hunter-001 (RS momentum continuation, LONG)

Hypothesis: participation + relative strength + structural breakout in a
non-hostile tape = continued price discovery. Assumed advantage:
institutional order flow leaves footprints (RVOL, sustained excess) that
persist minutes-to-hours. Other side: momentum faders, index-flow
mechanical sellers, market makers. Decay: crowding, regime shift,
latency of a 15-minute observation cadence. Costs: spread+impact on
liquid megacaps small vs 60m moves, but the 15-min cadence itself is a
material handicap (entry up to 15m after formation is possible — the
DECISION timestamp law handles measurement honestly, but economic
capture is untested). Predicate-level review:

- Dimensional coherence: OK (fractions vs fractions; RVOL vs time-of-day
  median; risk band vs price fraction).
- Redundancy: excess_market_15m>0 AND 30m>0 AND 60m≥75bp partially
  overlap; conjunction is strict by design — recorded, not simplified.
- Market floor (SPY ≥ −0.5%) overlaps the capital-side uncertainty proxy
  (|SPY| ≥ 1.5% → WATCH) — two layers, different bars, both conservative;
  coherent but worth remembering they stack.
- Stop=VWAP geometry matches the mechanism (VWAP loss = thesis death). A
  known tension: formation requires above-VWAP + OR-break + risk ∈
  [0.15%,1.5%], so late-day candidates with VWAP far below rarely fit —
  effectively a morning/midday playbook. Expected, not a defect.
- Verdict: **PLAUSIBLE / UNTESTED** — apparent edge could still be
  momentum beta + time-of-day seasonality; the frozen baselines
  (RAW-MOMENTUM, RAW-RELSTRENGTH on identical subjects) are exactly the
  controls that will separate that.

## Hunter-002 (failed-extension reversion, symmetric)

Hypothesis: a ≥2.5z leg whose structure fails was reflexive flow
completing; reversion toward VWAP follows. Other side: informed traders
whose news is real (the known failure mode; catalyst data is the missing
discriminator and stays DORMANT). Costs: stop at the extreme is wide
(≤4%); 1.5R target demands ~58% target-first at breakeven-ish after
costs — demanding, recorded. Predicates dimensionally coherent; leg
z-scale uses PRIOR-day ATR only; two-sided simultaneous match impossible
(opposite VWAP sides + opposite excess signs). Verdict: **PLAUSIBLE /
UNTESTED**; opposition to H-001 is the point.

## Confound checklist (both playbooks)

beta (controlled: BASELINE-MARKET), momentum (BASELINE-MOMENTUM), sector
exposure (excess-vs-sector predicate + peer baselines), liquidity premium
(top-liquidity-tier universe makes it unlikely), microcap effect
(excluded by universe), lookahead (poison-proven clean), survivorship
(forward-only evidence), event concentration (N_effective session×playbook
cells), time-of-day seasonality (UNCONTROLLED in v1 — no time-of-day
baseline exists; flagged as a scientific gap for post-Week-1 measurement,
not a Monday blocker), volatility exposure (partially controlled by the
ATR-scaled predicates; residual risk recorded).

## Intelligence sources

Analog: hypothesis = state similarity predicts outcome similarity —
UNTESTED, currently caution-only. ML: relationship extraction — UNTRAINED.
Simulator: donor-day resampling represents plausible path variation —
diagnostic. Swarm: context the numbers miss — blocked. All correctly
carry non-evidence statuses.
