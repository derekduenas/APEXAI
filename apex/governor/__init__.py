"""APEX GOVERNOR — the executive brain, with a hard ceiling.

Tuesday 2026-08-25 proved the gap this fills: Options and EdgeForge
both existed, both passed their tests, and neither ran. Nobody owned
the question "is the organism actually showing up?" The Governor owns
it.

It is an LLM executive: it reasons over logs, service state,
provenance, prior incidents, health metrics, code diffs and research
state, forms hypotheses, and acts. What this package provides is not
the reasoning -- it is the CONSTITUTION the reasoning must operate
inside, and the safe action surface it may reach for.

    TIER 1  OPERATIONAL          autonomous. restart, start, rotate a
                                 disposable log, recover a feeder,
                                 resume a consumer, retry a provider,
                                 fail over to an AUTHORIZED backup.
    TIER 2  RESEARCH             autonomous. register a hypothesis,
                                 run a CHRONOS campaign, spawn a
                                 shadow challenger, falsify. Never
                                 touches V1.
    TIER 3  PRODUCTION TRADING   LOCKED. thresholds, geometry, sizing,
                                 exits, new signals, EdgeDNA
                                 promotion, capital. The Governor may
                                 PROPOSE and assemble evidence. It may
                                 not deploy.

THE TIER 3 LOCK IS STRUCTURAL, NOT ADVISORY. There is no function in
this package that mutates a trading rule. `propose()` returns a
document. An LLM that decided to promote an edge would find nothing
to call -- which is the only kind of guarantee worth having, because
"the model was instructed not to" is not a control.

THE GOVERNOR'S OWN BIAS IS TOWARD DOING LESS. Its default answer to
"should we build X" is DEFER, and it must name the proven economic or
informational gap before anything is built. APEX's problem on Tuesday
was not a shortage of trading intelligence.

decision_power: TIER1_OPERATIONAL. Never trading, never capital.
"""

GOVERNOR_VERSION = "1.0.0"

TIERS = ("TIER1_OPERATIONAL", "TIER2_RESEARCH",
         "TIER3_PRODUCTION_TRADING")

AUTONOMOUS_TIERS = ("TIER1_OPERATIONAL", "TIER2_RESEARCH")

CHARTER = (
    "The Governor keeps the organism alive, honest and observing. It "
    "may repair operations and direct research on its own authority. "
    "It may never change what APEX trades, how much it risks, or what "
    "it believes -- it may only propose those, with evidence, to the "
    "operator.")
