"""APEX OPTION ANALYTICS V1 — APEX's own IV/Greeks computation layer,
built because trusting a vendor's Greek field blindly is worse than
computing (and validating) our own. This is NOT "elite" because it
implements Black-Scholes -- everyone can. It earns that only through
its validation and uncertainty architecture: every Greek carries a
model_range (BSM vs American) and a model_disagreement classification,
never a single fake-precise number; every IV comes as a BID/MID/ASK
triple, never one number; no-arbitrage gates reject bad prices before
they ever reach a solver; and OPT-002/OPT-003 (the mechanisms that
depend on real surface pricing) are refused at the expression-engine
level until this package's own adversarial validation suite has been
run and has passed -- checked mechanically via a certification ledger,
never self-declared.

OPTION_ANALYTICS_POWER = "NONE_OPTION_ANALYTICS": this package computes
numbers. It places no order, holds no Capital or broker authority, and
is not itself part of apex.options_research -- options_research reads
its OUTPUT (a computed OptionAnalyticsState), the same directional
relationship options_research has with Frontier-2's persisted ledgers.
"""

OPTION_ANALYTICS_POWER = "NONE_OPTION_ANALYTICS"
