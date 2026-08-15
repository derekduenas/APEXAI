# SYSTEM CALIBRATION AUDIT — Can the Machine Know What It Does Not Know?

Date: 2026-08-15. Methodology and graduation criteria FROZEN FIRST in
`config/calibration.yaml` (the machine-readable scorecard) before any status
was assigned. Credit 5 SEALED; holdout untouched; no threshold tuned against
any evaluation period. Governing rule: declare → freeze → forecast → observe
→ calculate → decide → freeze. A recalibrated model is a NEW versioned model.

## 0. The four distinctions, proven concrete (tests/test_calibration_distinctions.py)

- A perfectly-discriminating model shown genuinely miscalibrated (resolution
  high AND reliability terrible — measured separately).
- A perfectly-calibrated model shown useless (base-rate parrot: both ~0).
- A PROFITABLE sample with overconfident intervals caught by PIT tails
  regardless of P&L — with the counterexample that a matched distribution
  reads uniform, so the diagnostic condemns dishonesty, not everything.
- Identity guards: ranks fed as returns are REFUSED by the estimator; no
  decision engine's signature accepts ic/rank/score/sharpe; cost sensitivity
  is monotone in the honest direction; uncertainty multiplies bars upward.

## 1. The calibration map (claim → test → status)

| Component | Claim type | Observable test | Status (frozen scorecard) |
|---|---|---|---|
| Discovery/screening | deterministic gate | n/a | REFUSED (no probabilistic claim) |
| Signal/alpha | predictive (rank) | forward IC; rank-mapping reliability | PARTIALLY (004 validated forward of registration; mapping has 1 effective date) |
| Regime classifier | predictive (state) | forward durable-transition lag; uncertain-flag value | PARTIALLY (online-ness PROVEN; lag measured only vs contaminated reference; 0 forward transitions observed) |
| Distribution estimator | probabilistic | PIT, interval coverage, log score — FORWARD | UNCALIBRATED (0 forward observations; structurally self-aware) |
| Expression engine | deterministic given pmf | inherits input status; refuses to upgrade it | REFUSED (its honesty = its refusal) |
| Risk engine | economic constants + estimate inputs | forward vol/corr realization | UNCALIBRATED (conservative by construction) |
| Capacity engine | economic model | modeled vs realized paper implementation | UNCALIBRATED (MODELED capacity, labeled as such) |
| Cost model | economic | realized turnover measured; per-trade constants declared | PARTIALLY |
| Opportunity engine | probabilistic + economic | P(positive net \| TRADE) vs frequency; rejection value | UNCALIBRATED (0 realized TRADE outcomes) |
| TRADE/NO-TRADE | decision | false-positive rate, missed-opportunity rate, "NO-TRADE prevented X" | UNCALIBRATED (needs the paper track's forward record) |
| Paper tracking | mechanical marks | realized, chained | CALIBRATED_WITH_LIMITATIONS (CONTROL +0.4% drift flagged; delisting handling crude) |

Answers to the twenty questions per component live in the scorecard's
graduation blocks (target, metric, independent observation, minimum sample,
on-insufficient behavior). Three cross-cutting answers stated once:

- **Independent observation = one formation date** (or one durable
  transition, or one resolved TRADE). Cross-sectional claims on one date are
  ONE draw — the effective-n stamp already enforces this in the reality loop
  and it governs every calibration sample size here.
- **Degradation is structural, not advisory**: uncalibrated → PAPER-GRADE
  stamps, options demoted to stock, live_intent refused, SYNTHETIC never
  trades. Downstream code CANNOT consume a distribution without its status
  (the enum travels on the object; the mapping to expression sources is
  total with no upgrading branch).
- **Versioned and hashable**: statuses live on frozen dataclasses; minting
  CALIBRATED records the evidence path; the scorecard is committed config.

## 2. Component audits — what exists vs what is still owed

**Distribution estimator** (the hinge): PIT diagnostic built; overconfidence
caught, matched generator passes. OWED: forward observations — the temporal
protocol is the reality loop plus the §5 harness below. It cannot receive
CALIBRATED from anything in this repo today, and structurally refuses to.

**Regime classifier**: online-ness proven (identical output with a violent
future appended); labels never revised; uncertain flag live (15.6%);
detection lag 4d median — **against a self-confessed contaminated reference,
which this audit demotes to diagnostic**. True calibration needs ~10 forward
durable transitions: YEARS. Until then: PARTIALLY, consumed with its
uncertainty flag, bar-raising active.

**Signal layer**: outputs are RANKS. The type-confusion guards (this turn)
make rank→probability and ic→expected-return structurally impossible. The
rank→probability mapping that DOES exist is frozen, declared, and its
reliability is being measured forward (1 effective date: PRELIMINARY).

**Expression engine**: audited against its listed behaviors — uncalibrated →
restricted implementation (demotion recorded), costs incorporated (spread
paid, theta integrated), model-vs-market certainty separated (the flat-IV
persistence is a declared ASSUMPTION in config). REFUSED status is correct:
it makes no probabilistic claim of its own.

**Risk/capacity/cost**: constants are DECLARED and conservative; capacity is
labeled MODELED (theoretical ≠ modeled ≠ observed ≠ validated is now the
scorecard's vocabulary); cost sensitivity proven monotone-honest. OWED:
realized paper fills to measure model bias (30-rebalance minimum, declared).

**Opportunity engine / TRADE-NO-TRADE**: every number it emits is currently
PAPER-GRADE by construction and stamped so. OWED: 20 realized TRADE
outcomes; the rejection-value estimate ("NO-TRADE prevented X") computes
from the paper track's record of refused candidates once the discovery
exercise generates them. The trade threshold is frozen (2%, ×1.5 under
uncertainty) and was declared before any realized outcome exists.

## 3. Leakage-risk register (chain-level)

Feature construction (PIT-audited), regime labels (never-revised store;
hindsight refused by exploration), survivorship (delisted retained),
universe membership (formation-date PIT incl. ceiling), revised
fundamentals (as-filed; macro REVISED_ONLY guard), normalization (per-date
cross-sectional only, audited), thresholds (frozen pre-observation),
cost/capacity assumptions (declared constants; sensitivity monotone-honest),
model selection (trial ledger + DSR at true denominator), candidate
selection (correlation-to-validated required). RESIDUAL RISKS, named: the
paper track's delisting handling (universe-neutral fill — crude,
conservative-ish, on the register), CONTROL drift (+0.4%/period — under
watch), and the LLM producers' weight-embedded knowledge (unfixable;
handled by rule 17: forward-only, never backtested).

## 4. The walk-forward chain-calibration harness — SPECIFICATION

The `discovery_exercise_runner` and the calibration harness are ONE design:

    for each formation date T on the locked grid (in-sample first):
      snapshot(T) = only-knowable-at-T view: panel<=T, online state(T),
                    label store <=T, vintage.asof(T), frozen thresholds
      candidates(T) = signals eligible at T (validated + exploration
                      candidates with receipts)
      for each candidate: distribution(T) -> expression(T) -> risk(T) ->
                          capacity(T) -> opportunity decision(T)  [record]
      outcome(T+h) = realized returns; append to the CALIBRATION LEDGER
                     (chained, like everything else)
    then: PIT/coverage/reliability per component from the ledger, computed
    ONCE per frozen methodology; TRADE-decision calibration from realized
    net; rejection value from refused candidates' realized outcomes.

Every stamp travels; every decision is replayable from its snapshot hash;
no step may read past T (enforced by the same window/vintage/label guards
already counterexampled). Implementation is the next tranche and consumes
no credit.

## 5. THE ANSWER

**Is the machine currently trustworthy enough to run a full historical
discovery exercise?**

**YES — for a PAPER-GRADE exercise, and precisely because it now knows what
it does not know.** Every uncalibrated cell degrades structurally: stamps
propagate, options demote, live-intent refuses, uncertainty raises bars,
and the report prints its own epistemic status on every line. The exercise's
output will be hypotheses-with-economics, explicitly not deployable
decisions — which is exactly what the North Star says the exercise is for.

**NO — for anything beyond paper grade**, and the smallest zero-credit set
to change that is: (1) implement the §4 harness (= the discovery runner);
(2) the operator's CLI login, which starts every forward clock the scorecard
is waiting on; (3) let the paper track and reality loop accrue against the
FROZEN criteria — 20 effective dates, 20 realized TRADEs, 30 rebalances.
Items 1 is build; 2 is one human minute; 3 is calendar time that cannot be
compressed and should not be faked.
