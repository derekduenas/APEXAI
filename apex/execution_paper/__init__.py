"""PAPER EXECUTION -- the sandbox where the predator learns to attack.

Commissioned as PLUMBING FIRST (operator authorization, 2026-08-21,
off-market): the order pipe is proven with COMMISSIONING_TEST orders
before any APEX intelligence may touch it. Strategy plugs into an
already-proven pipe, never the other way around.

STRUCTURAL SAFETY (each enforced by test):
  * there is NO live order mode -- the mode enum is COMMISSIONING_TEST /
    PAPER_EXPLORATORY / PAPER_AUTHORIZED, nothing else exists to request
  * the only permitted broker base URL is the PAPER endpoint; the live
    trading endpoint is refused by allowlist (the stored market-data
    keys were PROVEN to authenticate against the live trading API on
    2026-08-21 -- so politeness is not enough; the URL guard is load-
    bearing)
  * no import path from this package reaches apex.execution,
    apex.hunter.broker, or the robinhood modules
  * every order requires the authority ladder's consent for its mode
  * the blotter is append-only and hash-chained; restart recovery is a
    pure replay of the blotter (no hidden state)

decision_power: the ladder decides; this package only executes what the
ladder already permitted, in paper, and records everything.
"""
PAPER_EXECUTION_POWER = "PAPER_ONLY_LADDER_GATED"

ORDER_MODES = ("COMMISSIONING_TEST", "PAPER_EXPLORATORY",
               "PAPER_AUTHORIZED")

# THE URL LAW. paper-api is the only broker host this package may ever
# speak to. api.alpaca.markets (live trading) is refused by construction.
ALLOWED_BROKER_HOSTS = ("paper-api.alpaca.markets",)

FORBIDDEN_IMPORTS = ("apex.execution", "apex.hunter.broker",
                     "robinhood")
