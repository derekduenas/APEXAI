"""CANONICAL CROSS-SECTIONAL MARKET STATE -- the shared sensory layer.

WHY THIS PACKAGE EXISTS (2026-08-20 audit finding). Pattern Observatory
had real SectorRotationState/BreadthState; official Curve declared
sector_leadership and breadth dimensions -- and 8/10 Curve dimensions
sat at 0% support for an entire session because the two stacks could
not share data without violating the deliberately-maintained firewall
(the Observatory may never feed the official decision path directly).
The result was the "3 realities of VWAP" problem waiting to happen:
every stack computing its own version of the same market fact.

THE LAW OF THIS LAYER:

  * it may consume CANONICAL MARKET DATA ONLY (the persisted bar
    streams owned by the primary sensor module)
  * it may NOT import: apex.pattern_observatory, apex.hunter,
    apex.captain, apex.execution, apex.frontier, apex.frontier2
    (enforced by an AST import-closure test)
  * both Pattern Observatory and Frontier2/Curve may READ it -- they
    receive the SAME semantic object, computed once, versioned once
  * every output carries value / sufficient / quality / source /
    source_time / known_from / formula_version -- a consumer that
    ignores sufficiency is the consumer's bug, visibly, not a silent
    default

decision_power: NONE -- this is a sensor, not a decider.
"""
MARKET_STATE_POWER = "NONE_SHARED_SENSOR"

FORBIDDEN_IMPORTS = ("apex.pattern_observatory", "apex.hunter",
                     "apex.captain", "apex.execution", "apex.frontier",
                     "apex.frontier2")

# The canonical bar-stream location is OWNED by the primary sensor
# module (single source of truth). Naming that module here is a data
# dependency on the canonical sensor, not a broker relationship -- the
# vendor-name scan exempts this file BY PATH with that justification.
def _bars_root() -> str:
    from apex.intraday.alpaca_fabric import BARS_DIR
    return str(BARS_DIR)


BARS_ROOT = _bars_root()

SECTOR_ETFS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE",
               "XLU", "XLV", "XLY")
MARKET_PROXY = "SPY"
