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

---

# PHASE 1 ADDENDUM (2026-08-22) — rulings now backed by forensic evidence

## LEGACY CAPTAIN RULING: **DEMOTE_TO_INTERNAL_CONVICTION**
The forensic settles the two-Captain question empirically.
`frontier2/captain_shadow` holds all 4,760 prospective reviews and its
predicate structure is sound — SERIOUS is unreachable because of
*starved inputs*, not bad logic. It is therefore KEEP_AS_UNDERWRITER.
`apex/captain/` (707 loc, no prospective ledger) contains conviction
and entry-adjacent logic in `conviction.py` / `kernel.py` that belongs
inside the new ATTACK_GEOMETRY faculty.
**Migration:** port conviction primitives into
`apex/predators/*/attack_geometry.py`, carry their tests, then retire
the package. **Removal condition:** every conviction test passes
against the geometry implementation.

## ASSASSIN CONSOLIDATION DESIGN (design only — no code merged)
Canonical interface `PredatorAssassin` with sleeve-specific wounds:

| implementation | ruling | rationale |
|---|---|---|
| `frontier2/assassin2` | **KEEP** — becomes `PredatorAssassin` | the live one (9 runtime refs, 4,726 records) |
| `pattern_observatory/pattern_assassin` | **MIGRATE** to a pattern-scoped wound provider | unique conjunction wounds worth keeping |
| `hunter/assassin` | **DEPRECATE** after wound-family port | superseded; no unique wound identified |

Long-term there is exactly one decision semantic; wounds differ by
sleeve, the verdict grammar does not.

## THE TWO STRUCTURAL BLOCKERS (both must be fixed; neither alone suffices)
```
1. entry_quality UNKNOWN        4,760 / 4,760  (100%)   -> Attack Geometry ABSENT
2. transition_quality STRONG        0 / 4,760  ( 0%)    -> Curve INPUT STARVATION
```
Curve dimension support measured over 3,324 records carrying the field:
```
price                643   (19%)      correlation      0   NEVER
relative_strength    353   (11%)      cross_asset      0   NEVER
breadth               48  (1.4%)      event_reaction   0   NEVER
sector_leadership     48  (1.4%)      flow             0   NEVER
                                      liquidity        0   NEVER
                                      volatility       0   NEVER
```
HIGH likelihood requires >=3 elevated dimensions across >=2 dependency
groups. Only PRICE_DERIVED and CROSS_SECTIONAL groups have ever had a
supported dimension; VOLATILITY, LIQUIDITY_FLOW and EXTERNAL have
**never once** been supported. Max observed independent elevated groups
= 1. **SERIOUS was structurally unreachable, exactly like the earlier
self-inclusive-sigma defect** — and, as then, the correct fix is to feed
the organ, never to lower the bar.

**PHASE 2 CANDIDATE (not authorized):** curve dimension feeding —
volatility and liquidity dimensions are computable from bars already
persisted; correlation and cross_asset need the market_state layer
wired; event_reaction needs apex/events joined.
