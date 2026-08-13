# APEX Architecture Gaps — prioritised P0–P4

Each gap: why it matters · zero-credit buildable? · prerequisites · governance
risk · does building it now create an optimization channel?

## P0 — required before another credit is spent

**None.** The machine can already discover an economically-grounded hypothesis,
screen it reject-only, register it against pre-committed criteria, and validate
it once with autocorrelation-aware statistics (bootstrap + permutation + HAC +
subperiod). Spending a credit on a clean single-factor hypothesis is
scientifically supported today. The one caution is a *choice*, not a gap: the
bootstrap/permutation block size must be pre-registered in the protocol, not
chosen after seeing a result.

## P1 — required before validated alpha becomes a portfolio

- **Research memory** — cumulative record of every hypothesis/rejection/lineage.
  Zero credits. No prerequisites. Governance risk: LOW (read-only over existing
  ledger + screen_log). No optimization channel. *Prevents rediscovering dead
  ends and makes the file-drawer denominator queryable.*
- **Portfolio construction (signal≠policy objects)** — turns a validated signal
  into a versioned policy. Zero credits to build the OBJECTS; needs a
  VALIDATED_ALPHA to exercise. Governance risk: MEDIUM — policy params must be
  versioned, never fitted to validation. Optimization channel: ONLY if a policy
  is chosen by backtest performance (forbidden; a policy search is a new credit).
- **Risk engine** — exposure/drawdown/tail limits. Zero credits. Prereq:
  portfolio. Risk LOW if kept independent of alpha (a limit relaxed to improve a
  backtest is the failure mode; the firewall forbids risk importing evaluate).

## P2 — required before paper trading

- **Realistic backtest engine** — evaluator of signal+policy+costs. Zero credits
  to build; needs portfolio + a validated alpha to run. Governance risk: HIGH —
  a backtest that selects parameters IS the overfit machine. Must be an
  evaluator with versioned, frozen inputs; the firewall forbids it importing
  registration/discovery.
- **Capacity engine** — ADV/participation/impact/borrow → net alpha, capacity
  curves. Zero credits. Prereq: backtest. Risk LOW. *Answers the real question:
  does the alpha survive realistic scale?*
- **Full cost model** — extend the decile-turnover cost with borrow/slippage/
  impact. Zero credits. Risk LOW.

## P3 — required before live trading

- **Paper / shadow promotion state machine** — RESEARCH→…→LIVE with
  human-authorised transitions. Zero credits. Prereq: capacity. Risk MEDIUM —
  no automatic promotion is the invariant.
- **Execution layer** — broker abstraction, pre-trade risk, reconciliation. Do
  NOT connect a broker. Zero credits to design the contract. Prereq:
  paper/shadow + risk. Risk HIGH operationally; the firewall gives it the widest
  forbidden set (no upstream import at all).
- **Live monitoring / drift** — REVIEW/PAUSE/KILL, never retune. Zero credits to
  design. Prereq: execution. Risk MEDIUM — a monitor that retunes is a hidden
  optimizer.

## P4 — future enhancements

- Digital Twin multi-facet (market/portfolio/model state).
- Model registry + versioning (needs the ML estimator first).
- Lifecycle attribution expansion (regime/interaction/execution/cost).
- ML estimator itself — UNDER_CONSTRUCTION; its governance and accounting exist,
  the first `.fit()` is gated. Whether it precedes or follows a first validated
  factor is a sequencing decision, not a gap.
- Causal executors + regime state builders — the objects exist; the runners do
  not. Zero credits; each becomes a new hypothesis when used to make a claim.

## The rule across all gaps

Every P1–P4 component can be BUILT for zero credits (they are machinery). What
consumes a credit is USING one to make a new predictive claim — an ML model, a
regime-conditioned strategy, a combination, a causal claim. The machinery is
free; the comparisons are priced. That separation is the whole design.
