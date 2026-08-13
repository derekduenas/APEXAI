# Research Discovery Readiness

**Date:** 2026-08-12 · Built on commit `22f2e11` (feature factory)

| Item | Status |
|---|---|
| **CURRENT FEATURES** | 23 canonical (9 pre-existing + 14 factory-built) |
| **EFFECTIVE FEATURE DIMENSIONS** | was ~4 (1 momentum block + 2 volatility + NSI); the 14 new features add valuation, profitability, quality, growth, accruals, capital-allocation, liquidity and balance-sheet families — materially more than 4, but a formal cross-family redundancy pass on the full 23 is future work, not claimed here |
| **DISCOVERY COMPONENTS BUILT** | hypothesis object, provenance/contamination, digital twin, novelty classifier, combination constraint, swarm roles, screen interface, human gate |
| **DIGITAL TWIN STATUS** | BUILT — deterministic, versioned, PIT-guarded `TwinState`; refuses future feeds |
| **SWARM STATUS** | PROTOCOL BUILT — 8 role contracts, disagreement preserved, no numeric score; automated agents are future consumers, not built |
| **HYPOTHESIS MODEL STATUS** | BUILT — `HypothesisDossier` wraps the certified `Dossier`; one authoritative screenable definition |
| **SCREENING INTEGRATION** | BUILT — `gate.screen_dossier` calls the certified reject-only screen unchanged; DUPLICATE/REDUNDANT refused before the screen |
| **CONTAMINATION CONTROLS** | BUILT — provenance epoch (BEFORE/DURING/POSTMORTEM 002); post-mortem or explicit descendant → `requires_independent_rejustification`; surfaced to the human gate, never auto-actioned |
| **GOVERNANCE GUARDS** | 39 load-bearing with demonstrated counterexamples, 7 ordinary by ruling; audit PASS |
| **TEST COUNT** | 518 collected; full suite green (515 passed, 1 skipped, + repo-integrity after tracking) |
| **CREDITS CONSUMED** | 0 this task; 2/5 lifetime (APEX-001, APEX-002) |
| **APEX-003 STATUS** | DOES NOT EXIST — not created, not proposed, not screened |
| **HOLDOUT STATUS** | SEALED — not accessed |

## What was built (Part 11 discipline)

**MUST BUILD NOW — done.** Every governance-load-bearing boundary between the
feature library and the human gate:

- `HypothesisDossier` reusing the certified `Dossier` (one source of truth)
- `Provenance` with contamination epochs and descendant-of-failure flagging
- `TwinState` with a measured no-future-leak PIT guard
- `classify_novelty` → NOVEL/RECOMBINATION/REDUNDANT/MODIFICATION/DUPLICATE
- `CombinationProposal` requiring an economic reason, incapable of holding a score
- swarm roles preserving disagreement, refusing assembly without disconfirmers
- `ReviewPacket` human gate that presents 8 questions and answers none
- `assert_not_auto_registerable` proving no research module reaches the ledger

**USEFUL LATER — documented, not built:** live regime engine, portfolio
constructor, automated LLM role agents.

**NOT JUSTIFIED YET — absent:** autonomous trading, execution, optimisation,
external APIs, real-time agents.

## What this layer cannot do

No numeric alpha score, no candidate ranking, no IC/t-stat/forward-return, no
autonomous registration, no holdout access, no credit spend, no post-screen
tuning (an edited idea gets a new hash). Each is enforced by a type or a
refusal with a demonstrated counterexample, not by a comment.

## The machine now asks "why should this work?" before "does this work?"

A hypothesis must state an economic mechanism, name its features, declare its
provenance epoch, survive novelty classification, carry preserved swarm
disagreement, and clear a human gate — all before a credit can be spent, and
the credit spend remains a separate human act the discovery layer cannot reach.
