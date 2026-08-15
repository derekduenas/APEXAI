# MVPM Reconciliation — Current Machine → Minimum Viable Profit Machine

Date: 2026-08-15. Governing objective: `docs/NORTH-STAR.md`. Credit 5:
SEALED (confirmed; nothing in this reconciliation or Track 5 touched any
locked period). Registry: `apex/governance/component_registry.py` is the
OWNER of this inventory; this document narrates it, the registry enforces it.

## 1. The thirty-item state of the machine

| Piece | State | Where |
|---|---|---|
| Data ingestion / PIT | ACTIVE | snapshot + nightly lake (dev-namespaced) |
| Universe construction | CERTIFIED | apex/universe (opt. mcap ceiling) |
| Feature factory/registry | CERTIFIED | 23 features, PIT knowability |
| Digital Twin (research) | CERTIFIED | apex/research/twin |
| Discovery / novelty / provenance | CERTIFIED | apex/research |
| Research memory | **PLANNED** | dossiers+ledger exist; no recall index |
| Hypothesis generation | CERTIFIED (human), BUILT (swarm scaffold) | |
| Reject-only screening | CERTIFIED | S1–S13, separate chain |
| Registration / validation / robustness | CERTIFIED, 4 experiments run | |
| Causal layer | CERTIFIED (claims), UNDER_CONSTRUCTION (executors) | |
| Regime / world state | **ACTIVE** | Track 4: online, 4d median lag |
| Macro vintages | BUILT, feed PENDING (FRED key) | REVISED_ONLY guard live |
| ML / exploration | **BUILT this turn** | Track 5, fails closed |
| Swarm producers | BUILT, clock BLOCKED (CLI login) | graduation criterion recorded |
| Probability / distribution layer | **ABSENT — named gap #1** | |
| Expression engine | BUILT | only CALIBRATED may recommend |
| Portfolio construction | BUILT | attribution ladder 0–5 |
| Risk engine | **PLANNED** | limits/heat/correlation aggregation |
| Backtest (evaluator) | **PLANNED** | rung runs exist; no unified evaluator |
| Transaction costs | BUILT | realized-turnover based |
| Capacity | **PLANNED** | breadth proxies only |
| Paper trading | ACTIVE | 6 portfolios, nightly, chained |
| Shadow trading | PLANNED | |
| Execution | PLANNED (deliberately) | |
| Live monitoring / drift / kill | **PLANNED** | reality loop covers producers only |
| Attribution | BUILT (research-level) | lifecycle attribution PLANNED |
| Opportunity ranking | **ABSENT — named gap #2** | |
| NO-TRADE decisioning | **ABSENT** (part of gap #2) | |
| Reproducibility / evidence | CERTIFIED | chains, pins, evidence_class |
| Experiment lineage | CERTIFIED (ledger), memory index PLANNED | |

## 2. The two pieces we had never named (now registry-owned, ABSENT)

**`distribution_estimator`** — THE missing link between alpha and money.
Nothing turns "GP rank 0.93 + state CALM_UP/uncertain" into the calibrated
pmf over forward returns that the expression engine's input contract
requires. Its calibration evidence can only come from the reality loop
(Group B, forward-only) — which is another reason the CLI login matters.

**`opportunity_engine`** — nothing ranks candidate opportunities net of
cost, risk, and capacity, and nothing can output the governed
TRADE/NO-TRADE report. Depends on the distribution estimator, risk engine,
capacity engine, and expression engine.

Also newly noted (smaller): corporate-action handling in the live paper
track (delistings currently resolve as universe-neutral — disclosed, crude);
per-position attribution in paper marks; the research-memory recall index
("have we tested this?" is currently a human grep).

## 3. The regime question, audited honestly (directive §5)

- State detection: YES — online, never-revised, median lag 4 days.
- State uncertainty: YES — boundary flag (15.6% of history), live today.
- Transition detection: YES — measured, durable-transition diagnostic.
- Regime-conditioned ALPHA: **NO — and correctly not.** It is a new
  hypothesis. The machinery to test it exists as of this turn: exploration
  accepts state features ONLY with LabelStore provenance (hindsight regimes
  refused by test), and a surviving candidate goes to registration.
- Regime-conditioned EXPRESSION and PORTFOLIO POLICY: NO — same status,
  new hypotheses, same path.

## 4. The profit-machine question, brutally (directive §6)

**Today the machine discovers statistically interesting factors and prices
their implementation. It cannot yet discover and rank opportunities.** The
exact missing links, in dependency order:

    signal + state ──X──> calibrated distribution        (distribution_estimator, ABSENT)
    distribution ─────ok─> expression                     (built, waiting on calibration)
    expression ───X──> portfolio-aware sizing             (risk_engine, PLANNED)
    candidate ────X──> capacity + net-of-everything       (capacity_engine, PLANNED)
    all of it ────X──> ranked TRADE/NO-TRADE report       (opportunity_engine, ABSENT)

Can the machine answer "what is the highest expected-value opportunity
available right now, in what expression, at what cost, risk, and capacity,
and should we trade at all?" — **No.** It can answer every sub-question
except the four X's above. Those four ARE the remaining build, and none of
them requires a credit.

## 5. What remains before the first full-system historical discovery run

1. `distribution_estimator` v1 — even a deliberately crude, DECLARED
   mapping (rank + state → pmf) tagged UNCALIBRATED_MODEL, so the pipe runs
   end-to-end while the reality loop accrues the calibration that upgrades it.
2. `risk_engine` v1 — declared limits, portfolio heat, correlation to
   existing sleeves.
3. `capacity_engine` v1 — ADV participation → capacity curve per candidate.
4. `opportunity_engine` v1 — assemble, evaluate net of everything, rank,
   and emit the report with NO-TRADE as a first-class outcome.
5. Auditor extensions run against the new surfaces (macro vintages when the
   feed exists; ML label windows — the purge demonstration covers the
   mechanism, the auditor should own it).
6. Then: the END-TO-END HISTORICAL DISCOVERY EXERCISE, in-sample, fully
   tagged, producing the operator's opportunity-report format — judged a
   failure if it returns "47 significant factors," a success if it returns
   ranked economics or an honest NO-TRADE.

Credit 5 comes after that exercise. The A-010 anchor remains separate,
already purchased, and at the operator's hand.
