# CONVENTIONS — AMENDMENT A-009 (DRAFT, UNSIGNED, NOT IN FORCE)

**Filed verbatim from the operator's 2026-08-14 draft. Nothing herein is
implemented. See the signature block: unsigned. One open question flagged in
review remains unresolved and is recorded at the bottom.**

## Segmented Holdout Capacity, Priced by Measured Independence

**Status: AWAITING SIGNATURE. Not in force.**
Claude Code must not implement, wire, or partially apply anything in this
document prior to signature and a dated amendment-log entry.

**Drafted:** 2026-08-14
**Extends:** A-003 (2026-08-09). Amends nothing.
**Numbering:** Issued as A-009 following the log audit that found A-004
through A-008 already assigned. An earlier draft circulated as "A-004"; that
identifier is void and must not appear in the log.
**Independently signable** of A-010.

### 1. THE PROBLEM

A-003 grants five experiments, each with one validation pass and one holdout
evaluation against 2022-01-01 → 2026-06-30. Four are spent. One remains.
Idea supply is effectively unbounded; confirmation capacity is one. The
remedy is not holdout reuse (forbidden, blocked) but recognition that other
segments, geographies, and asset classes are genuinely fresh out-of-sample
draws — which are NOT equally independent, and must be priced accordingly.

### 2. DEFINITIONS

**2.1 Holdout**: a (universe, period) pair never subject to a confirmatory
evaluation. Identified by both together; neither alterable after an
experiment naming it is registered.

**2.2 Independence classes** (assigned at definition; pricing floors bind):

| Class | Definition | ρ̄ floor | Status |
|---|---|---|---|
| I — Primary | The original holdout | n/a | US large-cap 2022-01→2026-06 |
| II — Segment | Same period/geo, disjoint segment | **0.50** | mid-cap $2-10B; micro <$100M |
| III — Geography | Different geography | **0.20** | needs new vendor + PIT audit |
| IV — Asset class | Different asset class | **0.20** | needs new vendor + PIT audit |
| V — Period | Disjoint prior period, provably untouched | **0.30** | **currently empty** (lake starts 2004, consumed as warm-up) |

Class V requires an explicit prior audit proving the period untouched;
absent proof, presumed contaminated.

**2.3 Disjointness**: mandatory by construction; boundary migration fixed
as-of formation date, PIT, reported; no security in two segments within one
formation window; a security-date in two holdouts invalidates both.

### 3. PRICING

**3.1** `N_eff(k, ρ̄) = k / (1 + (k−1)·ρ̄)`;
`charge_k = N_eff(k, ρ̄) − N_eff(k−1, ρ̄)`, floored at **0.25**. No
evaluation is ever free.

**3.2** Governing ρ̄ = max(measured, class floor). Measured = mean pairwise
correlation of the strategy's own in-sample return series across the
universes, locked before registration, recorded in the ledger. Unmeasurable
→ ρ̄ = 0.7 default. A guess that flatters the programme is not permitted.

**3.3** Path dependence ruling: **the sum of recorded charges governs the
budget; N_eff over the current set governs multiplicity.** Both always
reported together.

**3.4** Leak suppression: the ρ̄ measurement routine emits the correlation
coefficient ONLY. Level, mean, sign, dispersion, and any performance
statistic of the candidate segment's series are suppressed, never printed,
logged, or recorded. A test must prove no segment performance statistic is
obtainable through the pricing path.

**3.5** Budget rises **5 → 8** (4 spent under A-003 accounting), justified
solely by the pricing mechanism. **If pricing is removed, suspended,
bypassed, or inoperative, the budget reverts to 5 automatically — in code,
not policy.**

### 4. MULTIPLICITY AND REPORTING

**4.1** Family-wise threshold computed against N_eff; ledger reports N_eff
and raw count together, always. Bartlett mis-sizing inflation (A-001)
unchanged. Clarification: t ≥ 2.5 is Experiment #001's bar; live registered
bars are 2.92 validation / 2.88 holdout.

**4.2** Verdicts carry their weight inline — e.g.
`SUCCESS (Class II, ρ̄=0.60, +0.25 N_eff)` — and may not be serialized into
any report stripped of class and contribution. Enforced by test.

**4.3** Mandatory ledger fields per holdout evaluation: holdout identifier,
universe definition hash, period, class, measured ρ̄, governing ρ̄,
estimation window, N_eff before/after, charge, cumulative charges, remaining
budget. All existing guards remain in force.

### 5. IRREVOCABILITY AND BURN

**5.1** Holdout naming (universe, period, class) is fixed at
pre-registration, never renegotiated. Failure against the named holdout is
failure; a modified hypothesis is a new experiment and a new charge.

**5.2** Burn is programme-wide and permanent.

### 6. WHAT THIS DOES NOT DO

No holdout reuse in any form. A-001, A-002, Rule 17 unaltered. No threshold
weakened. No capital, no live execution, no paper-track change.

### 7. IMPLEMENTATION SEQUENCE (POST-SIGNATURE ONLY)

1. Ledger schema extension (§4.3), chain preserved, anchor re-verified.
2. N_eff/charge with 0.25 floor, class floors, 0.7 default — hand-tested
   incl. boundary cases.
3. §3.4 leak suppression, proven by test.
4. §3.5 automatic reversion, in code.
5. Irrevocable naming + programme-wide burn, each proven by counterexample.
6. §4.2 verdict weight rendering, enforced by test.
7. Mid-cap breadth census + null recalibration BEFORE any Class II holdout
   is defined.
8. Charge-sum and N_eff reported together everywhere; no code path emits
   one alone.

STOP and report if any step would modify the frozen pre-registration or
bypass an existing gate.

---

### SIGNATURE

    Amendment:    A-009
    Title:        Segmented holdout capacity, priced by measured independence
    Drafted:      2026-08-14
    Operator:     ______________________
    Date:         ______________________

**Unsigned. Not in force. Do not implement.**

---

### OPEN REVIEW QUESTION (flagged 2026-08-15, unresolved)

**Composition with A-003**: A-003 prices EXPERIMENTS (1 credit = validation
+ one holdout); §3 prices HOLDOUT EVALUATIONS. Unstated: whether the 5th
A-003 experiment's first holdout sits inside its 1.0 credit with §3 pricing
applying only to ADDITIONAL segment holdouts of an already-validated
strategy — and whether k is counted per-strategy (implied by per-strategy
ρ̄) or programme-wide. Reviewer's proposed reading: experiment costs its
A-003 credit including its named holdout; §3 governs additional holdout
evaluations of the same validated strategy; k per-strategy. ONE SENTENCE in
§3.1 settles this; it should be settled before signature.
