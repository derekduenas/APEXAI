"""APEX HUNTER — opportunity-intelligence layer (P0: contracts only).

Sits ABOVE the sovereign APEX CORE and consumes it; may never circumvent
it. P0 ships the constitutional objects — TradeThesis, PlaybookDefinition,
lifecycle states with mechanical calibration gating, the trade state
machine with its chained decision ledger, fail-closed conditions, and the
abstract BrokerAdapter — with ZERO market intelligence, because the
repository contains zero intraday data (docs/HUNTER-GAP-ANALYSIS.md §3).

FIREWALL: this package must never import apex.registration or
apex.governance.ledger — the Hunter cannot spend, register, or unlock
anything. LLMs may propose and explain; nothing in this package exposes an
API through which one could place an order, move a stop, or change a
calibration status.
"""
