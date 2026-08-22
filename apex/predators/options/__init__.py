"""OPTIONS PREDATOR -- INTERFACE ONLY (v2 Phase 1 records gaps; it does
not attempt to solve the sleeve).

KNOWN PRIMARY GAPS (from the PhD matrix, evidence-based):
  * realized-vs-implied volatility        NOT_BUILT (0 modules)
  * historical NBBO / point-in-time chains DATA_GAP
  * option-vs-equity economic comparator   NOT_BUILT
  * Attack Geometry                        NOT_BUILT

CORE LAW when it is built: GOOD UNDERLYING THESIS != GOOD OPTION TRADE.
The sleeve must be able to answer OPTION_ATTACK / EQUITY_BETTER /
NO_TRADE -- an options predator that cannot say "just buy the stock" is
not an options predator.
"""
OPTIONS_PREDATOR_POWER = "NONE_OPTIONS_PREDATOR"
OPTIONS_PREDATOR_STATUS = "INTERFACE_ONLY_GAPS_RECORDED"
