# Ladder ruling — Stage 0 corrected gate (dated amendment, 2026-09-12)

The original Stage 0 exit condition, "non-zero PRIME census at default", was a drafting error acknowledged by the
reviewer: PRIME is not a stage on the rule path, so the condition could only be satisfied by the funnel, and it was
applied to the path actually being commissioned. The original prompt text is not edited; this record supersedes its
gate.

**Corrected Stage 0a exit condition:** `CONSTRUCTS_A_CERTIFIABLE_CANDIDATE` on the Monday policy (`PILOT_RULE_V2`),
at default settings, on collected data. Met: 166 / 166 snapshots in both directions
(`docs/evidence/stage0_census_2026-09-11.json`). Certification was 0 / 166 for one named reason (fee schedule
`UNVERIFIED`), an operator authorization gate that hard law one does not classify as a defect; the operator
authorized the fee document the same day and the census was re-run (see the Stage 1 entry record).

**Funnel path:** UNDETERMINED on `INSUFFICIENT_HISTORY: 0 < 400 bars`, correctly not DEFECT, and does NOT gate
Stage 1. Lowering the history floor to produce a count would have been the failure the gate exists to catch, and it
was refused.

**Stage 0b:** pull provenance established (main `b9998d0` at pull time). **Stage 0c:** divergence classified (2,549
added / 28 modified / 0 deployed-only); the eight guards and validators absent from the deployed tree are named in
the Stage 0 closeout report; deploy proceeds from the merged reviewed tree, book flat, under A-012.

Ruling recorded by the reviewer: "Stage 0a PASSES for the rule path. Proceed."
