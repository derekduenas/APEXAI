# Research Swarm Protocol

`apex/research/swarm.py`. Eight roles with **different epistemic jobs** — not
ten agents running the same correlation.

## The roles (Part 2)

| Role | Question it asks |
|---|---|
| `economic_theorist` | what mechanism would make this true? |
| `fundamental_analyst` | what do these accounting features actually mean? |
| `microstructure_analyst` | is a theoretically valid signal tradable? |
| `quantitative_researcher` | is the transformation mathematically coherent? |
| `adversarial_researcher` | how do I KILL this — look-ahead, survivorship, artefact, redundancy, tuning? |
| `portfolio_constructor` | could this become a usable exposure? |
| `regime_researcher` | should the mechanism depend on market state? |
| `replication_researcher` | is this actually distinct from existing features and known factors? |

## What no role may do

Register an experiment · spend a credit · access the holdout · alter APEX
criteria or the protocol · silently modify a hypothesis. These are structural:
no `apex.research` module can import the ledger or pipeline
(`gate.assert_not_auto_registerable`).

## Output: a record, never an experiment (Part 8)

The swarm produces a `ResearchDossier`: hypothesis, novelty assessment, every
role's view, and any combination proposals. It carries:

- **no numeric alpha score.** `RoleView` has `supports: bool` and prose — no
  `score`, `ic`, or `confidence` field exists.
- **preserved disagreement.** `assemble` does not average views into a
  consensus. `unrebutted()` flags adversary objections no other role answered;
  `dissent()` lists every non-supporting role verbatim.
- **required disconfirmers.** `assemble` refuses to build a dossier without the
  adversary AND the replication researcher — the roles whose job is to kill the
  idea. A dossier of enthusiasts cannot be assembled.

## The roles are contracts, not agents

The `RoleView` contract exists; automated LLM agents that fill the roles do
not, and are `USEFUL LATER`. A human or a future agent supplies the reasoning;
the protocol enforces that the reasoning is preserved, disagreement is kept,
and no number substitutes for judgement.
