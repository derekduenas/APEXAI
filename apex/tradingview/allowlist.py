"""TRADINGVIEW-CONNECTOR-001 — the enforced tool allowlist.

FAIL CLOSED. A tool the adapter has not explicitly reviewed cannot be called, whatever its documented label says.
The allowlist is a literal tuple, not a filter over a pattern: a new tool appearing on the server is DENIED by
default and must be reviewed into this file by a person.

AN INCONSISTENCY INSIDE THE DOCUMENTATION, NOT A DISPUTE WITH IT. The official documentation (retrieved 2026-09-12,
https://www.tradingview.com/mcp/docs) carries `get_active_watchlist` under a READ-ONLY label AND describes
activation/creation side effects for it. The label and the description contradict each other; the description is
the operative fact, so the tool is excluded. A read-only label is a summary, and a summary does not override the
behaviour the same document sets out.

`monitor` on `create_alert` and the `webhook` parameter are the reason every alert tool is denied even though
several of them read: an alert with a webhook is an outbound trigger, and this connector is observation only."""
from __future__ import annotations

PROVIDER = "TRADINGVIEW_MCP"
SERVER_URL = "https://mcp.tradingview.com/mcp"
DOCS_URL = "https://www.tradingview.com/mcp/docs"
DOCS_RETRIEVED_UTC = "2026-09-12"
TRANSPORT = "streamable HTTP, OAuth 2.1"
ENTITLEMENT_NOTE = ("TradingView documents MCP access as included in Essential and above; trial plans are excluded. "
                    "This adapter does not verify the account's plan and does not claim one.")
DOCUMENTED_RATE_LIMIT = "~100 tool calls per minute per user (documentation, 2026-09-12). No Retry-After behaviour documented."

# ---------------------------------------------------------------- what this connector may call
# Exactly what symbol discovery, bars, technical context, news and calendars need. Nothing else.
ALLOWED_TOOLS = (
    "search_symbols",            # symbol discovery: resolve EXCHANGE:TICKER rather than guessing it
    "get_screener_columns",      # field discovery: screener fields are discovered before any use
    "get_ohlcv",                 # bars
    "get_technicals_rating",     # technical context (EXTERNAL CONTEXT, not a calibrated signal)
    "get_news",                  # news headlines
    "get_news_story",            # a headline's full text, by id from get_news
    "get_earnings_calendar",
    "get_economic_calendar",
    "get_dividends_calendar",
)

# ---------------------------------------------------------------- what it may not, and why
DENIED_TOOLS = {
    # mutating: watchlists
    "create_watchlist": "MUTATES_ACCOUNT_STATE: creates a watchlist",
    "delete_watchlist": "MUTATES_ACCOUNT_STATE: destroys user data",
    "add_to_watchlist": "MUTATES_ACCOUNT_STATE: changes a watchlist",
    "remove_from_watchlist": "MUTATES_ACCOUNT_STATE: changes a watchlist",
    "update_watchlist": "MUTATES_ACCOUNT_STATE: renames a watchlist",
    "get_active_watchlist": ("DOCUMENTED_SIDE_EFFECTS: the official documentation describes activation/creation "
                             "side effects for this tool while also carrying a read-only label. The described "
                             "behaviour governs; the label does not make it safe to call."),
    "list_watchlists": "NOT_NEEDED: account state, outside symbol discovery / bars / context / news / calendars",
    "get_watchlist": "NOT_NEEDED: account state, outside this connector's purpose",
    # mutating or outbound: alerts
    "create_alert": "MUTATES_ACCOUNT_STATE_AND_OUTBOUND: creates an alert and can register a webhook URL",
    "update_alert": "MUTATES_ACCOUNT_STATE: changes an alert, including its webhook",
    "delete_alert": "MUTATES_ACCOUNT_STATE: destroys user data",
    "stop_alerts": "MUTATES_ACCOUNT_STATE: changes alert delivery",
    "restart_alerts": "MUTATES_ACCOUNT_STATE: changes alert delivery",
    "list_alerts": "NOT_NEEDED: account state; reading alerts is outside this connector's purpose",
    "get_alerts": "NOT_NEEDED: account state",
    "get_alerts_log": "NOT_NEEDED: account state",
    # read-only but out of scope for this brick
    "run_screener": "NOT_REVIEWED_IN_THIS_BRICK: screening is not symbol discovery; needs its own review",
    "get_symbol_data": "NOT_REVIEWED_IN_THIS_BRICK",
    "get_symbol_data_batch": "NOT_REVIEWED_IN_THIS_BRICK",
    "get_economic_data": "NOT_REVIEWED_IN_THIS_BRICK",
    "get_economic_symbols": "NOT_REVIEWED_IN_THIS_BRICK",
    "get_forecasts": "NOT_REVIEWED_IN_THIS_BRICK: analyst targets are not this connector's context set",
    "get_financials": "NOT_REVIEWED_IN_THIS_BRICK",
    "get_financial_history": "NOT_REVIEWED_IN_THIS_BRICK",
    "get_documents": "NOT_REVIEWED_IN_THIS_BRICK",
    "get_document_view": "NOT_REVIEWED_IN_THIS_BRICK",
}

# Any tool name containing one of these is denied even if someone adds it to ALLOWED_TOOLS by mistake. This is the
# structural belt to the allowlist's braces, in the spirit of apex/execution FORBIDDEN_TOOL_MARKERS.
FORBIDDEN_MARKERS = ("create", "delete", "update", "add_", "remove", "set_", "stop_", "restart", "activate",
                     "order", "buy", "sell", "submit", "place", "execute", "trade", "webhook", "subscribe",
                     "upgrade", "purchase", "active_watchlist")

# Tools whose OUTPUT is external opinion, never a calibrated probability or an authorized signal.
EXTERNAL_CONTEXT_TOOLS = ("get_technicals_rating", "get_news", "get_news_story")


class ToolNotAllowed(PermissionError):
    """A call the adapter refuses to make. Named, never silent."""


def check_marker(name: str) -> str | None:
    lowered = str(name).lower()
    for m in FORBIDDEN_MARKERS:
        if m in lowered:
            return m
    return None


def assert_allowlist_is_sound() -> None:
    """The allowlist must not contain a forbidden marker. Called at import and asserted by a test, so a later edit
    that allows a mutating tool fails the build rather than reaching the server."""
    for name in ALLOWED_TOOLS:
        m = check_marker(name)
        if m is not None:
            raise ToolNotAllowed("ALLOWLIST_UNSOUND: %r contains the forbidden marker %r" % (name, m))
    overlap = set(ALLOWED_TOOLS) & set(DENIED_TOOLS)
    if overlap:
        raise ToolNotAllowed("ALLOWLIST_CONTRADICTORY: %s appear in both lists" % sorted(overlap))


def permit(name: str) -> None:
    """Raise unless `name` is explicitly allowed. Default is DENY, including for a tool nobody has heard of."""
    if not isinstance(name, str) or not name:
        raise ToolNotAllowed("TOOL_NAME_INVALID: %r" % (name,))
    m = check_marker(name)
    if m is not None:
        raise ToolNotAllowed("TOOL_FORBIDDEN_MARKER: %r contains %r; this connector never mutates or triggers"
                             % (name, m))
    if name in DENIED_TOOLS:
        raise ToolNotAllowed("TOOL_DENIED: %s -- %s" % (name, DENIED_TOOLS[name]))
    if name not in ALLOWED_TOOLS:
        raise ToolNotAllowed("TOOL_NOT_ON_ALLOWLIST: %r is not one of the %d reviewed tools; a tool is denied until "
                             "a person reviews it into apex/tradingview/allowlist.py" % (name, len(ALLOWED_TOOLS)))


def describe() -> dict:
    return {"provider": PROVIDER, "server_url": SERVER_URL, "docs": DOCS_URL, "docs_retrieved_utc": DOCS_RETRIEVED_UTC,
            "transport": TRANSPORT, "entitlement": ENTITLEMENT_NOTE, "documented_rate_limit": DOCUMENTED_RATE_LIMIT,
            "allowed_tools": list(ALLOWED_TOOLS), "n_allowed": len(ALLOWED_TOOLS),
            "denied_tools": dict(sorted(DENIED_TOOLS.items())), "n_denied": len(DENIED_TOOLS),
            "forbidden_markers": list(FORBIDDEN_MARKERS),
            "external_context_only": list(EXTERNAL_CONTEXT_TOOLS),
            "law": ("OBSERVATION_ONLY: this connector reads. It never mutates TradingView state, never registers an "
                    "outbound trigger, never places or prepares an order, and never changes a selection policy, "
                    "risk limit, fee or model promotion.")}


assert_allowlist_is_sound()
