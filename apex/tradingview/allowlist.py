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
several of them read: an alert with a webhook is an outbound trigger, and this connector is observation only.

TRADINGVIEW-INTEGRATION-002 RECONCILIATION AGAINST THE LIVE CATALOG (2026-09-12). The catalog was finally observed
(docs/evidence/tradingview_integration_003/live_catalog_2026-09-12.json, 27 tools). Three facts changed this file:

  1. THE LIVE SPELLING IS DIFFERENT. Every tool is exposed as `mcp__mcp-tradingview__mcp-tv-<kebab-name>`, while
     this allowlist was written in bare snake_case. Under the old code all nine ALLOWED tools were refused in
     their live spelling -- the connector failed safe but could not call anything. Names are now CANONICALIZED
     before any check, so both spellings resolve to one reviewed identity and the allowlist governs the tools
     that actually exist.
  2. THE MARKER BELT HAD A HOLE. `stop_alerts` carries the marker `stop_`, but the live `mcp-tv-stop-alerts`
     contains no underscore and slipped the belt entirely; only default-deny caught it. Markers are now matched
     against the canonical name, so a separator can no longer defeat the structural guard.
  3. NO WATCHLIST TOOL EXISTS ON THIS SERVER. All eight watchlist denials -- `get_active_watchlist` among them --
     were written from the published documentation and are NOT in the live catalog. They stay denied, because a
     tool absent today can appear tomorrow and the denial is the point; they are labelled DOCUMENTED_NOT_LIVE so
     the file stops implying they were observed. The live catalog also contains NO order, position, portfolio,
     execution or options-quote tool of any kind."""
from __future__ import annotations

PROVIDER = "TRADINGVIEW_MCP"
SERVER_URL = "https://mcp.tradingview.com/mcp"
DOCS_URL = "https://www.tradingview.com/mcp/docs"
DOCS_RETRIEVED_UTC = "2026-09-12"
TRANSPORT = "streamable HTTP, OAuth 2.1"
ENTITLEMENT_NOTE = ("TradingView documents MCP access as included in Essential and above; trial plans are excluded. "
                    "This adapter does not verify the account's plan and does not claim one.")
DOCUMENTED_RATE_LIMIT = "~100 tool calls per minute per user (documentation, 2026-09-12). No Retry-After behaviour documented."

# ---------------------------------------------------------------- the live spelling
# Observed 2026-09-12. The server prefixes every tool twice: once with the MCP server id, once with its own
# short name. A reviewed identity must not depend on either, so names are canonicalized before any check.
LIVE_SERVER = "mcp-tradingview"
LIVE_TOOL_PREFIX = "mcp__mcp-tradingview__"
LIVE_NAME_PREFIX = "mcp-tv-"
LIVE_CATALOG_RECORD = "docs/evidence/tradingview_integration_003/live_catalog_2026-09-12.json"
LIVE_CATALOG_OBSERVED_UTC = "2026-09-12"


def _normalize(name: str) -> str:
    """Lenient canonicalization. Strips the live prefixes and folds separators so one tool has ONE identity.
    Never raises -- it is used by the marker belt, which must answer for any string at all."""
    n = str(name).strip().lower()
    if n.startswith(LIVE_TOOL_PREFIX.lower()):
        n = n[len(LIVE_TOOL_PREFIX):]
    if n.startswith(LIVE_NAME_PREFIX):
        n = n[len(LIVE_NAME_PREFIX):]
    return n.replace("-", "_")


def canonical(name: str) -> str:
    """Strict canonicalization for `permit`. A tool addressed to a DIFFERENT MCP server is refused outright:
    this allowlist reviews TradingView, and it does not get to vouch for anyone else's server."""
    raw = str(name).strip()
    if raw.lower().startswith("mcp__") and not raw.lower().startswith(LIVE_TOOL_PREFIX.lower()):
        raise ToolNotAllowed("TOOL_FOREIGN_SERVER: %r is not a %s tool; this allowlist governs one server only"
                             % (raw, LIVE_SERVER))
    return _normalize(raw)


def live_name(name: str) -> str:
    """The canonical name rendered in the spelling the transport actually accepts."""
    return LIVE_TOOL_PREFIX + LIVE_NAME_PREFIX + _normalize(name).replace("_", "-")


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

# ---------------------------------------------------------------- the catalog actually exposed, 2026-09-12
# The 27 canonical names observed on the server. This is a RECORD OF AN OBSERVATION, not a permission: nothing is
# callable because it appears here. It exists so `reconcile()` can answer the only question that matters after a
# catalog changes -- is there a live tool this file has never classified?
LIVE_CATALOG = (
    "create_alert", "delete_alert", "get_alerts", "get_alerts_log", "get_dividends_calendar", "get_document_view",
    "get_documents", "get_earnings_calendar", "get_economic_calendar", "get_economic_data", "get_economic_symbols",
    "get_financial_history", "get_financials", "get_forecasts", "get_news", "get_news_story", "get_ohlcv",
    "get_screener_columns", "get_symbol_data", "get_symbol_data_batch", "get_technicals_rating", "list_alerts",
    "restart_alerts", "run_screener", "search_symbols", "stop_alerts", "update_alert",
)

# Denied on the strength of the published documentation, and NOT present in the live catalog. The denial stands --
# a tool absent today can appear tomorrow, and default-deny plus a named reason is exactly the guard -- but the
# file no longer implies these were seen on the server.
DOCUMENTED_NOT_LIVE = frozenset({
    "create_watchlist", "delete_watchlist", "add_to_watchlist", "remove_from_watchlist", "update_watchlist",
    "get_active_watchlist", "list_watchlists", "get_watchlist",
})

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
    """Matched on the CANONICAL name. Matching the raw string let `mcp-tv-stop-alerts` slip the `stop_` marker
    because the live spelling has no underscore; canonicalizing first closes that."""
    lowered = _normalize(name)
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
    # An allowed tool must also be clean in the spelling the transport uses, so no live name can smuggle a marker.
    for name in ALLOWED_TOOLS:
        m = check_marker(live_name(name))
        if m is not None:
            raise ToolNotAllowed("ALLOWLIST_UNSOUND_LIVE: %r contains the forbidden marker %r" % (live_name(name), m))


def permit(name: str) -> None:
    """Raise unless `name` is explicitly allowed. Default is DENY, including for a tool nobody has heard of."""
    if not isinstance(name, str) or not name.strip():
        raise ToolNotAllowed("TOOL_NAME_INVALID: %r" % (name,))
    c = canonical(name)                      # raises for a foreign server before anything else is considered
    m = check_marker(c)
    if m is not None:
        raise ToolNotAllowed("TOOL_FORBIDDEN_MARKER: %r (canonical %r) contains %r; this connector never mutates "
                             "or triggers" % (name, c, m))
    if c in DENIED_TOOLS:
        raise ToolNotAllowed("TOOL_DENIED: %s -- %s" % (c, DENIED_TOOLS[c]))
    if c not in ALLOWED_TOOLS:
        raise ToolNotAllowed("TOOL_NOT_ON_ALLOWLIST: %r (canonical %r) is not one of the %d reviewed tools; a tool "
                             "is denied until a person reviews it into apex/tradingview/allowlist.py"
                             % (name, c, len(ALLOWED_TOOLS)))


def reconcile() -> dict:
    """Compare the reviewed lists against the catalog the server actually exposes.

    THE QUESTION THIS ANSWERS: is there a live tool nobody has classified? Default-deny already refuses such a
    tool, so this is not a safety control -- it is the review trigger. An unclassified live tool means the server
    grew something and no person has looked at it yet, and that should be visible rather than merely safe."""
    allowed, denied = set(ALLOWED_TOOLS), set(DENIED_TOOLS)
    live = set(LIVE_CATALOG)
    unclassified = sorted(live - allowed - denied)
    return {
        "catalog_record": LIVE_CATALOG_RECORD,
        "catalog_observed_utc": LIVE_CATALOG_OBSERVED_UTC,
        "n_live": len(live),
        "live_allowed": sorted(live & allowed),
        "live_denied": sorted(live & denied),
        "n_live_allowed": len(live & allowed),
        "n_live_denied": len(live & denied),
        "unclassified_live_tools": unclassified,
        "fully_classified": not unclassified,
        "allowed_not_in_live_catalog": sorted(allowed - live),
        "denied_not_in_live_catalog": sorted(denied - live),
        "documented_not_live": sorted(DOCUMENTED_NOT_LIVE),
        "documented_not_live_are_all_denied": DOCUMENTED_NOT_LIVE <= denied,
        "no_watchlist_tool_is_live": not any("watchlist" in t for t in live),
        "no_order_or_execution_tool_is_live": not any(
            k in t for t in live for k in ("order", "execute", "trade", "position", "portfolio", "submit", "place")),
        "every_live_mutator_is_denied": all(
            t in denied for t in live if check_marker(t) is not None or t.startswith(("create_", "update_", "delete_"))),
        "law": ("default-deny governs regardless of this report: a live tool that appears in no list is refused by "
                "permit() before it reaches the transport. This report exists to make such a tool VISIBLE."),
    }


def describe() -> dict:
    return {"provider": PROVIDER, "server_url": SERVER_URL, "docs": DOCS_URL, "docs_retrieved_utc": DOCS_RETRIEVED_UTC,
            "transport": TRANSPORT, "entitlement": ENTITLEMENT_NOTE, "documented_rate_limit": DOCUMENTED_RATE_LIMIT,
            "live_catalog_record": LIVE_CATALOG_RECORD, "live_catalog_observed_utc": LIVE_CATALOG_OBSERVED_UTC,
            "live_tool_prefix": LIVE_TOOL_PREFIX + LIVE_NAME_PREFIX, "n_live_catalog": len(LIVE_CATALOG),
            "documented_not_live": sorted(DOCUMENTED_NOT_LIVE),
            "allowed_tools": list(ALLOWED_TOOLS), "n_allowed": len(ALLOWED_TOOLS),
            "allowed_tools_live_spelling": [live_name(t) for t in ALLOWED_TOOLS],
            "denied_tools": dict(sorted(DENIED_TOOLS.items())), "n_denied": len(DENIED_TOOLS),
            "forbidden_markers": list(FORBIDDEN_MARKERS),
            "external_context_only": list(EXTERNAL_CONTEXT_TOOLS),
            "law": ("OBSERVATION_ONLY: this connector reads. It never mutates TradingView state, never registers an "
                    "outbound trigger, never places or prepares an order, and never changes a selection policy, "
                    "risk limit, fee or model promotion.")}


assert_allowlist_is_sound()
