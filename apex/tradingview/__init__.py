"""TRADINGVIEW-CONNECTOR-001 — read-only, allowlisted TradingView MCP observations for the Digital Market Twin.

Observation only. This package never mutates TradingView state, never registers an outbound trigger, never places
or prepares an order, and never changes a selection policy, risk limit, fee or model promotion. It holds no
credential: the transport is an injected callable."""
from .allowlist import ALLOWED_TOOLS, DENIED_TOOLS, PROVIDER, ToolNotAllowed, describe, permit  # noqa: F401
