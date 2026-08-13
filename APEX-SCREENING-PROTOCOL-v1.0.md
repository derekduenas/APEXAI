# APEX Screening Protocol v1.0 — the Phase 2 cheap screen

**Status:** governance layer, ratified 2026-08-12
**Scope:** hypothesis screening between idea generation and pre-registration
**Credits consumed:** zero, always

---

## Why this exists

The research budget is five lifetime experiments; two are spent. Without a
filter, the remaining three go to whichever ideas happened to arrive first.
With an *unconstrained* filter, they go to whichever idea the filter was tuned
to like — and the budget stops meaning anything, because the multiple
comparisons have moved upstream where nothing counts them.

The screen exists to reject cheaply. It is deliberately incapable of improving
anything.

> **The cheap screen can reject an idea, but it cannot be used to optimise an
> idea until that idea becomes a registered experiment.**

## The twelve rules

**S1 — Frozen dossier first.** A hypothesis must exist as a complete, frozen
dossier before it may be screened. There is no screening of an idea held in a
conversation, a notebook, or someone's head.

**S2 — Content hash.** Every dossier is identified by the SHA-256 of its
canonical content. The hash is the identity; the filename is not.

**S3 — Permanent log.** Every screen execution is appended to a hash-chained,
tamper-evident log keyed by dossier hash. Screens that reject are logged with
exactly the same permanence as screens that survive.

**S4 — Two outcomes.** A screen returns `REJECT` or `SURVIVE`. There is no
score, no rank, no "promising", no "borderline", no percentage.

**S5 — Rejection is terminal.** A `REJECT` ends that dossier permanently. The
exact frozen dossier may never be screened again and may never be registered.

**S6 — Survival is not authorisation.** A `SURVIVE` makes the exact frozen
dossier *eligible for registration*. It does not create an experiment, does not
reserve a credit, does not unlock a period, and does not permit execution.
Registration remains a separate, signed act.

**S7 — No optimisation information.** A screen may not emit, and its return
type may not express: parameter sweeps, rankings of variants, tuning
recommendations, best-period or best-universe selection, or any instruction for
iterative modification. A screen that tells you how to make an idea pass has
destroyed the reason for having a screen.

**S8 — Change means new identity.** Any material change to a hypothesis
produces a different dossier hash and is a new screening event, logged
separately. Iteration is permitted and is *visible*; it cannot be laundered.

**S9 — Determinism.** Re-screening the same frozen dossier produces the same
verdict. A screen whose answer depends on when it was run is not evidence.

**S10 — Zero credits.** Screening never touches the research ledger, never
calls `spend`, and never changes `credits_spent`.

**S11 — Holdout is untouchable.** A screen may not read, request, or receive
holdout data. The screening window is bounded by the in-sample period.

**S12 — No mutation of the experimental record.** A screen may not alter the
registered experiment, the protocol, the ledger, the validation period, or any
success criterion.

## The file-drawer rule (S3, restated because it is the one that erodes)

If a screen kills eleven ideas and only the survivors are written down, the
survivors look stronger than they are. The denominator is part of the evidence.
Every screen execution is logged, including — especially — the rejections. The
log is the record of how many questions were asked, and no later reader should
have to take that number on trust.

## Architecture

Screening is implemented in `apex/governance/screening.py` and touches nothing
else. The existing governance modules are unmodified.

**The screen log is a separate chain, not an extension of the research
ledger.** `LedgerEntry.payload()` covers every field, so adding one field to
carry a dossier hash changes the computed hash of *every entry already
written*, and `verify_chain` — which recomputes `entry.compute_hash()` per
entry — would then fail on the live six-entry ledger. Demonstrated in
`tests/test_screening.py`. Reusing the class would also have meant screening
events sharing a file with credit-consuming events, which S10 and S12 forbid in
spirit even where no `spend` is called.

```
results/research_ledger.jsonl   experiments, credits          UNCHANGED
results/screen_log.jsonl        screening events, no credits  NEW
```

Both are append-only, hash-chained, and anchored by an external head file that
records the expected length, so truncation is detectable.

## What a screen may examine

Signal economics, stability, breadth, sector neutrality, market-cap dependence,
alternative holding periods, portfolio-construction feasibility, published
literature, economic rationale, and obvious data artifacts — all within the
in-sample window, which §7 grants no statistical standing.

Examining these to decide *whether the question is worth a credit* is the
purpose. Examining them to decide *which version of the question to ask* is S7,
and is forbidden.

## What this protocol does not do

It does not select a hypothesis, rank candidates, or express a preference among
them. It does not lower, raise, or reinterpret any success criterion. It has no
opinion on APEX-003.
