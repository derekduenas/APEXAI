# RESEARCH SWARM CHARTER (operator design ruling, recorded 2026-08-15)

The governing question is never "where can we put Claude?" but "where
does an LLM have the highest marginal advantage over the quantitative
system?" The answer, frozen as design intent: the Swarm is APEX's
contextual research + adversarial trade-intelligence desk — not its
chart calculator, not its TP/SL engine, not its final stock picker.

## The three moments (one desk, three context walls)

1. **DISCOVERY (before/around market)** — events, filings, guidance,
   analyst changes, sector narratives → structured CatalystIntelligence
   (event, event_time, materiality, novelty, expected mechanism,
   ambiguity, peers). GATED on a timestamped news/event feed; dormant
   until then.
2. **TRADE (live candidate interrogation)** — the primary subscription
   budget. The deterministic funnel does 5,000 → 3; the Swarm deeply
   interrogates the 3. Never "which stocks should we buy" — always
   "here is everything APEX knows at T; attack the thesis."
3. **REVIEW (post-trade forensics)** — after outcomes are known and
   SEGREGATED from the prospective record: why was APEX wrong?
   Classification: THESIS_WRONG / TIMING_WRONG / WORLD_CHANGED /
   EXECUTION_FAILURE / TAIL_EVENT / DATA_FAILURE / UNEXPLAINED → Research
   Memory. The forensic agent must never contaminate prospective
   records (hard context wall; separate producer birth when built).

## The five target seats (not nine firing constantly)

1. **THESIS ANALYST** — the strongest coherent mechanism, not
   "bullish/bearish".
2. **ADVERSARIAL TRADER** — the #1 seat and the point of attack. Sole
   job: why should APEX NOT take this trade? Target output shape:
   structured flags (e.g. CHASE_RISK / SECTOR_CONFIRMATION /
   MARKET_SUPPORT / EXTENSION_RISK with levels), a PRIMARY OBJECTION,
   and a VERDICT (NO_MATERIAL_OBJECTION / MATERIAL_OBJECTION). The
   quant stack is excellent at finding reasons to trade; what it needs
   most is an intelligent opponent trying to prove it wrong.
3. **MARKET CONTEXT ANALYST** — interprets the Twin's facts in
   interaction (Twin = representation; Claude = interpretation).
4. **CATALYST / INFORMATION ANALYST** — the second-biggest advantage
   once timestamped events exist: "earnings beat" vs "beat + raised
   guide + margin expansion + durable-sounding management" are not the
   same event, and OHLCV cannot tell them apart.
5. **CONTRADICTION / SYNTHESIS ANALYST** — not a voter; names the
   unresolved contradictions across playbook/analog/ML/Twin/simulation/
   Swarm ("directional thesis stronger than entry thesis" → WATCH,
   don't chase).

## The forbidden list (equally binding)

- ❌ Primary chart calculation (ChartState owns structure; Claude may
  interpret levels, never establish canonical ones)
- ❌ TP/SL numbers (invalidation geometry + MAE/MFE + analogs +
  simulation + Capital own that; Claude may phrase an invalidation
  CONDITION which deterministic code translates into measurable state)
- ❌ Position sizing (zero vote)
- ❌ Final authorization (Claude's ceiling is NO_MATERIAL_OBJECTION;
  Capital alone decides)
- ❌ Screening thousands of tickers (computation is better and cheaper)

## Every seat must earn its keep

The ablation is the employment contract: APEX+SWARM vs identical
candidates without, per seat where separable. After enough outcomes,
findings like "the Adversary consistently misses opening-chase failures"
or "catalyst analysis adds no measurable value" lead to firing agents.
No assumption that AI = edge; the smoke test proved the transport, not
the trader.

## V1 state vs this charter (recorded gaps, not tonight's work)

Active today: MARKET_STATE_ANALYST + ADVERSARIAL_TRADER, shared prompt
template with per-role tasks. Charter deltas for swarm producer v2 (a
new birth, post-freeze): per-role prompts (the current template shows
both role tasks to both agents — a prompt-hygiene gap), the Adversary's
structured flag/verdict output shape, the Synthesis seat, and the
DISCOVERY/REVIEW moments behind their data and context-wall gates. The
ideal interaction on record: quant + analogs + catalyst align, the
Adversary objects to entry geometry, Synthesis says "good stock, good
thesis, bad price," Capital says WATCH — and APEX re-evaluates when
geometry improves. The Swarm earns its keep by discovering what the
machine doesn't know and preventing it from fooling itself.

## Amendment: tiered scheduling + the three clocks (2026-08-15, implemented)

The Swarm is a scarce, expensive reasoning resource deployed in
proportion to APEX's interest — never one large step every candidate
waits on:

- **TIER 1 — the assassin (~fast)**: ADVERSARIAL_TRADER +
  MARKET_CONTEXT_ANALYST. Job: the fastest credible reason this trade is
  deceptive. A MATERIAL_OBJECTION ends the desk (kill cheaply; the
  objection already carries maximum caution). Budget 120s.
- **TIER 2 — the committee (minutes)**: survivors only. THESIS +
  SYNTHESIS join (CATALYST when event data exists). Total budget 300s.
- **TIER 3 — forensics (after outcome, context-walled)**: error
  classification into Research Memory; never touches prospective records.

The three clocks: machine clock (seconds — feed/Twin/chart/scan/risk, no
LLM), decision clock (tens of seconds — analogues/ML/sim/fast Swarm/
Capital), research clock (minutes-hours — deep Swarm, events, forensics).
Each intelligence works at the speed where it has an advantage.

Latency is a first-class trading metric: tick records carry
t0/t1(state)/t2(quant) stamps, capital records carry enrichment time and
capital wall time, so edge decay during reasoning is computable from the
bars at resolution. Future elite rule: match intelligence spend to the
opportunity's alpha half-life. Future concept (recorded, not built):
per-playbook declared intelligence requirements (REQUIRED / PREFERRED /
OPTIONAL / NOT_REQUIRED seats), so mechanism dictates intelligence and
architecture never becomes bureaucracy. Trade management stays
deterministic and fast — Claude may enrich a thesis asynchronously; it
never holds the steering wheel.
