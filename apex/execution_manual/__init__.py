"""MANUAL KRAKEN EXECUTION -- APEX brain, human hands.

Operator decision 2026-08-22: KRAKEN PRO / KRAKEN DERIVATIVES US is the
intended MANUAL execution interface for BTC perpetuals (Bitnomial-
listed underneath -- the same market our sensors watch). No Kraken API,
no FIX onboarding, no broker write credentials, none of it needed:
APEX detects, underwrites, sizes, and defines the trade; the HUMAN
pushes the buttons; APEX measures what actually happened -- including
the human.

LAWS:
  * A card is an INSTRUCTION, never an order. No FILLED state without
    explicit operator confirmation. EXIT_REQUESTED != EXITED.
  * Manual latency is part of execution reality -- every hop is
    timestamped and the decision-time price is never pretended
    achievable.
  * NOT_EXECUTED is a legitimate, research-grade outcome.
  * Emergency law: no card without invalidation + protective stop.
  * Maintenance law: VENUE_UNAVAILABLE_SCHEDULED blocks new cards.
  * At OBSERVE authority, only COMMISSIONING_TEST cards exist.

decision_power: NONE -- this package renders instructions and does
bookkeeping; it cannot touch Kraken and holds no credentials.
"""
MANUAL_EXECUTION_POWER = "NONE_MANUAL_EXECUTION"
