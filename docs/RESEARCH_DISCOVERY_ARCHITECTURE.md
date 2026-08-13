# Research Discovery Architecture

**Date:** 2026-08-12 · **Credits consumed:** zero · **APEX-003:** does not exist

The layer between the certified 23-feature library and the certified
screening/APEX pipeline. Its job is to let the system ask **"why should this
work?"** before it asks "does this work?" — and to make it structurally
impossible for the machine to turn an idea into an experiment, tune it, or let a
failed result choose its successor.

```
Raw PIT data ─▶ Feature Factory ─▶ Feature Registry (23 features)
                                          │
                                          ▼
                          ┌───────────────────────────────┐
                          │      RESEARCH DISCOVERY        │
                          │                               │
                          │  Digital Twin (PIT state @ T) │
                          │  Swarm (8 epistemic roles)    │
                          │  Hypothesis + Provenance      │
                          │  Novelty / Combination        │
                          │  Contamination control        │
                          └───────────────┬───────────────┘
                                          ▼
                              ResearchDossier  (a record, not an experiment)
                                          ▼
                    Novelty / governance pre-check  (DUPLICATE/REDUNDANT refused)
                                          ▼
                        Cheap Screen  (certified, reject-only, S1–S13)
                                          ▼
                              SURVIVE / REJECT   (logged, tamper-evident)
                                          ▼
                      ReviewPacket  ──▶  HUMAN GATE  (decides nothing for you)
                                          ▼
                        (human) APEX registration ─▶ credit ─▶ validation ─▶ holdout
```

The discovery layer stops at the human gate. It has **no import path** to
`apex.pipeline`, `apex.registration`, or `apex.governance.ledger` —
`gate.assert_not_auto_registerable()` proves this with the audited
`module_closure` walk, and a counterexample proves the check can fail.

## Components (all in `apex/research/`)

| Module | Responsibility | Cannot |
|---|---|---|
| `hypothesis.py` | `HypothesisDossier` wraps the certified `Dossier`; `Provenance` records the epoch | change the screenable identity by editing provenance |
| `twin.py` | `TwinState`: deterministic, versioned, PIT-guarded information set at one date | expose a feed dated after T (`assert_no_future_leak`) |
| `novelty.py` | classify NOVEL/RECOMBINATION/REDUNDANT/MODIFICATION/DUPLICATE; bounded `CombinationProposal` | emit a number; search a combination space |
| `swarm.py` | 8 roles, `ResearchDossier`, disagreement preserved | express a score; assemble without adversary + replication |
| `gate.py` | screen interface + `ReviewPacket` human gate | register an experiment; tune a hypothesis |

## One authoritative definition (Part 4)

`HypothesisDossier.screenable()` returns an `apex.governance.screening.Dossier`.
The definition of "a complete, hashable hypothesis" lives in the screening
protocol and nowhere else. The discovery layer adds provenance and novelty
metadata **outside** the screenable content, so:

- editing where an idea came from does **not** change its `dossier_hash`;
- editing the science **does** — an iterated idea cannot wear an old result's
  identity (Part 9).

## Minimum architecture (Part 11)

**Built now** — the governance-load-bearing boundaries: hypothesis object,
provenance/contamination, twin PIT guard, novelty classifier, combination
constraint, swarm disagreement, screen interface, human gate, no-registration
proof.

**Useful later** — live regime engine, portfolio constructor, actual
LLM-backed role agents. The role *contracts* exist; the automated agents behind
them do not, and are documented as future consumers, not faked.

**Not justified yet** — autonomous trading, execution, portfolio optimisation,
external data APIs, real-time agents. None is built.

## What the layer deliberately cannot do

No numeric alpha score anywhere (`RoleView`, `NoveltyAssessment`,
`CombinationProposal` have no numeric field). No ranking of candidates. No IC,
no t-stat, no forward return. No autonomous registration. No holdout access. No
credit spend. No tuning of window/threshold/weight/universe/transformation
after a screen — that is a new dossier hash.
