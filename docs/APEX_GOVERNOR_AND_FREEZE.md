# APEX GOVERNOR + ARCHITECTURE FREEZE

**Declared:** 2026-08-26 · **Authority:** `TIER1_OPERATIONAL`
**Trigger:** 2026-08-25, when Options and EdgeForge both existed,
both passed their tests, and neither ran.

---

## 1. Why a Governor

Tuesday was not a trading failure. The market was open, the code was
deployed, the tests were green — and APEX lost an entire prospective
session because nobody owned the question *"is the organism actually
showing up?"*

That question is now owned.

The Governor is an LLM executive: it reasons over logs, service
state, provenance, prior incidents, health metrics, code diffs and
research state, forms hypotheses, and acts. Ordinary code already
handles `heartbeat stale → restart`. The Governor exists for the
other thing:

> *"Options isn't scanning. Dependencies are healthy. Memory is fine.
> The release is valid. It restarted twice and exits after universe
> initialization. What changed?"*

What `apex/governor/` provides is not the reasoning — it is the
**constitution the reasoning operates inside** and the **safe action
surface** it may reach for.

## 2. Three tiers

| Tier | Scope | Authority |
|---|---|---|
| **TIER 1 — OPERATIONAL** | restart, start missing service, rotate disposable logs, rebuild derived cache, resume durable consumer, retry provider, authorized failover, isolate a resource hog, record incident | **autonomous** |
| **TIER 2 — RESEARCH** | register hypothesis, run CHRONOS campaign, spawn shadow challenger, run falsification, request additional *recording* | **autonomous** |
| **TIER 3 — PRODUCTION TRADING** | thresholds, geometry, sizing, exits, new signals, EdgeDNA promotion, capital | **LOCKED — propose only** |

### The Tier 3 lock is structural, not advisory

There is **no function in the governor package that mutates a trading
rule.** `propose()` returns a document with `applied: False` and
`status: AWAITING_OPERATOR`. A test asserts that no module in the
package exposes `apply`, `deploy`, `activate_change`,
`set_threshold`, or `promote`.

Passing `operator_approval="I_APPROVE_THIS"` is explicitly refused:
approval is the operator's act performed through their own tools, not
a parameter the executive supplies to itself.

An executive that *decided* to promote an edge would find nothing to
call. That is the only kind of guarantee worth having — "the model
was instructed not to" is not a control.

### Two further guards earned from real incidents

- **The catalog is a whitelist.** An action nobody authorized is
  unavailable merely because nobody forbade it.
- **Sealed evidence is never disposable.** With disk at 81% on
  Tuesday, a tidy-up is a plausible Tier-1 action — and it is refused
  on `results/chronos`, `results/edgeforge`, `results/day1_frozen`,
  `results/day1_corrected`, `results/governance`, `results/btc`,
  `results/decision_cards`, `results/commissioning`. A disk-pressure
  repair may not delete the research it exists to protect.
- **A diagnosis may not smuggle a trading change in as a repair.** A
  hypothesis whose `implied_repair` is Tier 3 is rejected at
  construction.
- **Every hypothesis carries its falsifier.** An executive that cannot
  say what would prove it wrong is narrating, not diagnosing.

## 3. The daily KPI

Six questions, every market day, each answered **from an artifact**:

```
DID_WE_SHOW_UP
DID_WE_OBSERVE
DID_WE_HAVE_VALID_OPPORTUNITIES
DID_WE_ATTACK_WHEN_WARRANTED
DID_WE_REFUSE_WHEN_WARRANTED
DID_WE_LEARN_FROM_THE_RESULTS
```

An unanswered question is not a pass, and an answer without an
artifact is an impression. Tuesday's scorecard, filed retroactively:
`DID_WE_SHOW_UP: NO`, `DID_WE_OBSERVE: NO`,
`DID_WE_LEARN_FROM_THE_RESULTS: NO`, three `NOT_ESTIMABLE` →
`DAY_WITH_GAPS`.

## 4. ARCHITECTURE FREEZE — in force

EdgeForge exists. CHRONOS exists. Equity, Options, BTC, the
simulator, the adversary, the scientific controls all exist. **The
organism does not need more organs. It needs experience.**

`build_request()` defaults to **DEFER**. To proceed, a capability must
name a **proven gap** — one of `IMPLEMENTATION_DEFECT`,
`DATA_DEFECT`, `SEMANTIC_DEFECT`, `OPS_DEFECT`, or
`MEASUREMENT_GAP_BLOCKING_PREREGISTERED_RESEARCH` — **with an
artifact**. Explicitly not proven gaps:

- a market loss ("we lost twice")
- a hunch or an elegance argument
- "it would be interesting" — that is curiosity, and it is routed to
  Tier 2 research where it is free

Approved builds are scoped to *"repair the named gap and nothing
adjacent."*

The Governor is expected to argue against new building, **including
against its own enthusiasm.**

## 5. The priority order, from here

```
1. APEX SHOWS UP EVERY DAY
2. APEX COLLECTS TRADES
3. EDGEFORGE STUDIES THEM
4. CHRONOS TRAINS THE SCIENTIST
5. FIX PROVEN DEFECTS
6. REPEAT
```

Not: build another cool thing, build another cool thing.

---

**The Governor keeps the organism alive, honest and observing. It may
repair operations and direct research on its own authority. It may
never change what APEX trades, how much it risks, or what it
believes — it may only propose those, with evidence, to the operator.**
