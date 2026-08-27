"""CATALYST INTELLIGENCE — what is happening in the world.

The quantitative stack reads the MARKET: price, volume, structure,
breadth, volatility, liquidity, options. It is very good at that and
completely blind to why any of it is moving.

This package reads the WORLD, and then does the thing that actually
matters:

    CATALYST  +  MARKET REACTION  ->  the disagreement between them

A headline is not information. A headline whose reaction does not fit
it is information. Good news that cannot lift a stock, bad news that
cannot break one -- that is where an event-driven analyst earns their
seat, and it is unreachable from price data alone.

THE DIVISION OF LABOUR IS STRICT:

    DETERMINISTIC CODE OWNS      scheduling, retrieval, timestamps,
                                 known_from, dedup, source identity,
                                 persistence, reaction math, surprise
                                 arithmetic, authority

    THE LLM OWNS                 semantic interpretation, event class,
                                 relevance, mechanism hypotheses,
                                 affected entities, contradiction
                                 detection

The LLM may never invent a factual event, compute a surprise, or set an
authority. Those are arithmetic and governance, and an interpreter that
is allowed to do arithmetic will eventually do it wrong in a way that
reads like insight.

AUTHORITY: SHADOW_CONTEXT_ONLY. Catalyst data may be observed, stored,
researched by EdgeForge and CHRONOS. It may not change a thesis, a
geometry, an entry quality, an expression, a size, or authorize or
block a single trade.

    CATALYST != SIGNAL.
    POSITIVE HEADLINE != LONG.
    NEGATIVE HEADLINE != SHORT.
"""

CATALYST_VERSION = "1.0.0"

AUTHORITY = "SHADOW_CONTEXT_ONLY"

CHARTER = (
    "Catalyst Intelligence observes the world and measures how the "
    "market answered it. It interprets; it never trades, never gates, "
    "and never overrides the incumbent Predator.")
