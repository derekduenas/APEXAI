"""THE THREE PREDATORS -- domain-expert sleeves competing for capital.

    apex/predators/core/       shared contracts every sleeve speaks
    apex/predators/equities/   EQUITIES_INTRADAY
    apex/predators/options/    OPTIONS          (interface only, v2p1)
    apex/predators/btc/        BTC_PERPS        (interface only, L3-gated)

Each Predator owes seven faculties: DOMAIN_STATE, MECHANISM_INTELLIGENCE,
HISTORICAL_MEMORY, ATTACK_GEOMETRY, ASSASSIN, FORWARD_DISTRIBUTION,
MONETIZATION_INTELLIGENCE. The implementations are domain-specific; only
the contracts are shared. There is no generic APEX_SCORE.

decision_power: NONE_PREDATOR -- a Predator proposes an Opportunity.
Capital decides. Nothing here can submit an order.
"""
PREDATOR_POWER = "NONE_PREDATOR"

SLEEVES = ("EQUITIES_INTRADAY", "OPTIONS", "BTC_PERPS")

FACULTIES = ("DOMAIN_STATE", "MECHANISM_INTELLIGENCE",
             "HISTORICAL_MEMORY", "ATTACK_GEOMETRY", "ASSASSIN",
             "FORWARD_DISTRIBUTION", "MONETIZATION_INTELLIGENCE")
