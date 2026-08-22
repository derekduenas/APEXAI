# APEX PREDATOR v2 — DEPRECATION & MIGRATION PLAN
Built 2026-08-22. **PLAN ONLY — no code has been migrated or deleted.**
Nothing here executes without explicit operator authorization, and no
frozen component is reopened without a version bump and regression
acceptance.

## Repository facts this plan rests on
```
41 packages under apex/          ~40,000 LOC
18 launchd daemons               14 packages have live callers
```

---

## A. DUPLICATE SEMANTICS (the real consolidation debt)

### A1 — THREE ASSASSINS
| implementation | loc | callers | in shadow runtime |
|---|---|---|---|
| `apex/frontier2/assassin2.py` | 217 | 3 | 9 refs — **the live one** |
| `apex/pattern_observatory/pattern_assassin.py` | 174 | — | 291 ledger rows |
| `apex/hunter/assassin.py` | 128 | — | legacy |

**Canonical:** `frontier2/assassin2`. **Migration:** pattern_assassin
becomes an internal *pattern-scoped wound provider* feeding assassin2;
hunter/assassin deprecated after its wound families are ported.
**Removal condition:** assassin2 demonstrably emits every wound family
the other two produced, proven by replay over existing ledgers.
**Evidence preserved:** all three ledgers stay append-only.

### A2 — TWO CAPTAINS
| implementation | loc | evidence |
|---|---|---|
| `apex/frontier2/captain_shadow.py` | 220 | **4,760 live records** |
| `apex/captain/` (board/cio/context/conviction/kernel) | 707 | 5 test files, no live ledger |

**Canonical:** `frontier2/captain_shadow` (it is the one with
prospective evidence). `apex/captain/` demotes to internal algorithms —
`conviction.py` and `kernel.py` contain entry-quality logic that the
missing Attack Geometry faculty should absorb rather than discard.
**Removal condition:** conviction/entry logic ported into the new
`attack_geometry` module with tests carried over.

### A3 — TWO WORLD LABS
`apex/frontier2/world_lab.py` (230 loc, 1 caller, 0 shadow-runtime refs)
vs `apex/world_lab/` (55 loc constitution + raw store with 64k Deribit
records).
**Canonical:** `apex/world_lab/` — it holds the operator-issued
constitution and the actual immutable store. frontier2/world_lab
deprecates; any analog-retrieval logic worth keeping migrates in.

### A4 — TWO OPPORTUNITY ENGINES
`apex/opportunity/engine.py` (194 loc, 0 apex callers) vs
`apex/frontier2/opportunity_graph.py` (156 loc, live).
**Canonical:** neither survives as-is — both are superseded by the
**canonical Predator Opportunity schema** (§7 of the directive), which
does not yet exist. Opportunity Graph demotes to an internal linkage
algorithm *inside* the equity predator.

---

## B. ZERO-CALLER MODULES (tests only, no apex or script importer)

| module | loc | disposition |
|---|---|---|
| `apex/exploration/` | 353 | DEPRECATE — no callers, no ledger |
| `apex/regime/` | 101 | MERGE into World Lab regime tagging |
| `apex/causal/` | 70 | MERGE into governance (forward-learning causality already lives there) |
| `apex/frontier2/edge_genome.py` | — | DEPRECATE — 0 shadow-runtime refs, no evidence it ever discriminated |
| `apex/frontier2/research_scientist.py` | — | DEMOTE to offline research tool; never in the decision path |
| `apex/frontier2/curve_metrics.py` | — | MERGE into `curve.py` (V2 superseded it) |

`apex/execution_manual/` and `apex/execution_paper/` also show zero
callers — **by design**. They are commissioned plumbing awaiting
authority and are explicitly NOT deprecation candidates.

---

## C. KEEP — CANONICAL, NO CHANGE

Truth and survival systems, per the operator's preserve list:
`governance` (chain ledger, checkpoint graph, authority ladder) ·
`intraday` (fabric, bars, sufficiency) · `market_state` ·
`btc_sleeve` · `world_lab` · `execution_paper` · `execution_manual` ·
`frontier2/curve` (V2) · `frontier2/observation_integrity` ·
`data` · `audit`.

`pattern_observatory` (5,585 loc, largest package) **KEEPS but DEMOTES**:
it remains the discovery/hunt engine for equities rather than an
independent top-level subsystem — its conjunction/pattern-id machinery
is genuinely unique, but it should feed the Hunt stage, not parallel it.

---

## D. MIGRATION SEQUENCE (nothing starts without authorization)

```
0  finish BTC-L2 acceptance                    ← Sunday gate, in flight
1  canonical Predator Opportunity schema        (new, apex/predators/core/)
2  ATTACK GEOMETRY faculty                      NOT_BUILT in all 3 sleeves
3  unblock the funnel: why SERIOUS never fires
4  A1 assassin consolidation
5  A2 captain consolidation + conviction port
6  A3/A4 world-lab + opportunity consolidation
7  B deprecations (delete only after evidence migration)
```

**Ordering rationale from evidence, not preference:** steps 1–3 target
the zero-decision bottleneck; steps 4–7 are hygiene that would otherwise
be performed twice.

## E. LAWS BINDING THIS PLAN
1. No frozen component is reopened without version bump + regression
   acceptance.
2. No ledger is ever rewritten; deprecated organs' evidence stays
   append-only and readable.
3. No module is deleted until its unique capability demonstrably exists
   elsewhere.
4. No migration adapter becomes permanent — each carries a removal
   condition in this file.
5. Architecture receives no tenure; neither does this plan.
