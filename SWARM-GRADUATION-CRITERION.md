# Swarm Agent Graduation Criterion (v4.0 §4.4)

**Recorded 2026-08-15, BEFORE any swarm agent prediction has been scored**,
so it cannot be set to fit results. Amending it after any agent has scored
predictions is a dated CONVENTIONS amendment, not an edit.

An agent graduates to **decision-support eligibility** when, over at least
**20 independent formation dates**:

1. its Brier score beats its own `stripped` twin's, AND
2. it shows non-zero resolution (Murphy decomposition), AND
3. its reliability is not materially worse than the blind baseline's.

Graduation confers eligibility for the Committee — **never** authority to
size or trade. An agent that cannot beat its own blind twin has no
demonstrated information and does not graduate, regardless of how good its
reasoning reads.

Scoring substrate: `apex/reality/` (chained, anchored, unresolved-past-due
scores as failure, PRELIMINARY below 10 effective dates). Producer identity
includes model + prompt hash; a changed prompt or model is a NEW producer
with a fresh record. The Committee and World Twin remain gated until at
least one graduated agent exists (v4.0 §0).

Current status at recording time: ZERO swarm agent predictions exist. The
LLM producer path is built but blocked on the operator's one-time headless
CLI login; the graduation clock starts at the first scored pair, not before.
