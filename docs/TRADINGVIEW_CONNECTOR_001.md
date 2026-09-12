# TRADINGVIEW-CONNECTOR-001 — read-only TradingView observations for the Digital Market Twin (2026-09-12)

Branch `tradingview-connector-001`, based on `trace-replay-001` at `1b86541`. **Deliberately not based on
`operating-loop-001`**, so the two bricks stay separate and neither depends on the other's review. No running
regression was disturbed. No existing market-data feed was replaced, no risk limit, selection policy, fee or model
promotion was changed, nothing was deployed and no order exists.

## Status in one line

**Authorized and connected at the account level; the offline adapter and its 45 acceptance tests pass. The bounded
smoke test has NOT run, because the session that built this could not see the tools.**

### Authorization: done. Tool access from this session: not available.

The operator completed the browser authorization on 2026-09-12. `claude mcp list` now reports:

```
mcp-tradingview: https://mcp.tradingview.com/mcp (HTTP) - ✔ Connected
```

**No `mcp__mcp-tradingview__*` tool is exposed to the session that wrote this file.** A Claude Code session builds
its tool registry at start; this one started while the server still needed authorization, and it does not pick up a
newly authorized server mid-session. Two searches of the deferred-tool registry returned nothing from this
provider, so the smoke test could not be attempted and no partial result is being reported as one.

**A fresh session picks the tools up.** The smoke test is nine allowed tools and a ten-call budget away, and the
adapter is ready to receive them as its injected transport.

## 1. The integration

Documentation read: <https://www.tradingview.com/mcp/docs>, retrieved **2026-09-12**.

The documented command was run verbatim:

```bash
claude mcp add --transport http mcp-tradingview https://mcp.tradingview.com/mcp
```

It added one server to the local config for `/Users/derekduenas` and **changed nothing else**. Every pre-existing
connector is intact: Context7, Higgsfield, Google Drive, Google Calendar, Gmail, Apollo GraphOS, ruflo and
robinhood-trading all still report as before. No unofficial bridge was installed.

At the time it was added the server reported `! Needs authentication`; after the operator's browser sign-in the
same command reports `✔ Connected`.

### Authorization

OAuth 2.1 in the operator's browser, against their own TradingView account. **Completed by the operator on
2026-09-12.** No password was requested and no OAuth token was copied into the repository, a log, a fixture or a
prompt. What remains is not authorization but tool visibility in a running session, described above.

TradingView documents MCP access as **included in Essential and above, with trial plans excluded**. This adapter
does not check your plan and makes no claim about it.

## 2. Discovered capabilities

**The capability list below is DOCUMENTED, not DISCOVERED.** Live enumeration needs the tools loaded in a session,
and the session that wrote this file does not have them. **The first thing to do in a fresh session is enumerate the
real tool list and reconcile it with this file** — a documented list is not a discovered one, and the discrepancy in
the next paragraph is exactly why that matters.

**Documented: 35 tools.** Watchlists (8), market data (3), symbol search (1), screener (5), news (2), fundamentals
and forecasts (3), documents (2), calendars (3), alerts (8).

**Enforced allowlist: 9.** Everything else is denied by name with a reason, in `apex/tradingview/allowlist.py`.

| purpose | allowed |
|---|---|
| symbol discovery | `search_symbols` |
| field discovery | `get_screener_columns` |
| bars | `get_ohlcv` |
| technical context | `get_technicals_rating` |
| news | `get_news`, `get_news_story` |
| calendars | `get_earnings_calendar`, `get_economic_calendar`, `get_dividends_calendar` |

**26 tools are denied**, each with a named reason: 10 mutate account state (watchlist and alert writes), 6 are
read-only account state outside this connector's purpose, 9 are read-only but unreviewed in this brick, and one is
the disputed case below. A tool that is on neither list is **denied by default** — a new tool appearing on the
server cannot be called until a person reviews it into the file.

### A documentation discrepancy, recorded rather than resolved silently

**The documentation labels `get_active_watchlist` READ-ONLY. Your brief states it has documented
activation/creation side effects.** The two disagree. The adapter excludes it, and the reason string in the code
says why: a disputed mutation is not called. If the documentation is right, the cost is one unavailable read; if
your brief is right, silently trusting the label would have mutated your account. Worth resolving with TradingView
support at some point, but not by testing it against your live account.

A second structural guard sits behind the allowlist: `FORBIDDEN_MARKERS` denies any tool name containing `create`,
`delete`, `update`, `add_`, `remove`, `set_`, `stop_`, `restart`, `activate`, `order`, `buy`, `sell`, `submit`,
`place`, `execute`, `trade`, `webhook`, `subscribe`, `upgrade`, `purchase` or `active_watchlist` — even if someone
later adds such a name to the allowlist by mistake. `assert_allowlist_is_sound()` runs at import and is asserted by
a test, so that mistake fails the build rather than reaching the server.

Symbols are **resolved** through `search_symbols`, never guessed; screener fields are **discovered** through
`get_screener_columns` before any use.

## 3. The APEX boundary

`apex/tradingview/` — three modules, no new market-state system. It reuses the Twin's existing vocabulary:
`apex.pulse.twin` supplies the quality states (`VALID`, `STALE`, `UNKNOWN`, `NOT_AVAILABLE`, `NOT_ESTIMABLE`,
`PROVIDER_ERROR`, `SESSION_INAPPLICABLE`) and the `Field` invariant that already refuses a `known_from` preceding
its `as_of`.

Every observation carries: provider; **the actual tool name**; request arguments and their digest; the response
digest; the source event and publication times as supplied, verbatim; request start, response receipt and ingestion
instants; `known_from`; symbol, interval, units, revision; entitlement and delay status; quality, completeness and
any named refusal.

### The rule the module exists for

**`known_from` is always the response receipt on this connection.** Never the candle's own time, never a
publication date. `historical_availability` reads `NOT_ESTABLISHED` on every observation, and
`valid_for_as_of(obs, t)` refuses any decision instant earlier than `known_from` with the named reason
`LATE_ARRIVING_INFORMATION`. A candle stamped yesterday and fetched today became knowable to APEX today. This is the
single most common way a data connector manufactures hindsight, and it is closed by construction here.

### The rest of the normalization contract

- **Partial candles are identified and excluded.** A bar is `COMPLETE` only when its window closed at or before the
  response receipt and every price field is a real number. Unclosed windows are `PARTIAL`, missing fields make a bar
  `INCOMPLETE`, and both are kept in a separate list so nothing vanishes. `completed_bars()` is the only accessor a
  completed-bar consumer may use, and a partial bar is not reachable through it.
- **Missing is unknown, not zero.** A missing volume or price is `None` with the field named in `unknown_fields`.
- **Bars from the future are refused**, not ingested.
- **TradingView never overwrites another source.** `provider = TRADINGVIEW_MCP`, `source_class = EXTERNAL_CONTEXT`,
  its own schema version, and nothing it produces is written to the pilot ledger. `compare_price()` records a
  disagreement with both values, both sources and both timings, and resolves nothing.
- **Indicators and ratings are external context.** `authority = EXTERNAL_CONTEXT_ONLY`, `calibrated = False`. A
  `STRONG_BUY` from TradingView is an opinion in a record, not a probability and not a signal.
- **Entitlement defaults to `UNKNOWN`** and the delay status says the server does not state one. An invented
  entitlement value is refused.

### Budgets, retries and rate limits

A hard cap of 10 calls per run (configurable), a local rate cap of 60/minute against the documented ~100/minute,
an in-run cache so an identical request is never re-sent, bounded retries with exponential backoff capped at 30 s,
and **`Retry-After` honoured when the server supplies one** rather than replaced by the local backoff. Every failure
becomes a named state — `TOOL_DENIED`, `BUDGET_EXHAUSTED`, `RATE_LIMITED`, `TIMEOUT`, `AUTHENTICATION_FAILED`,
`PROVIDER_UNAVAILABLE`, `MALFORMED_RESPONSE` — rather than an exception reaching a decision path.

## 4. The captain, and the two kinds of access

The read-only snapshot interface of `docs/AI_DESK_INTEGRATION_001.md` **is not implemented on this base**, so this
brick delivers a callable adapter and a fixture demonstration and labels the production Twin wiring
**NOT_CONNECTED**. No placeholder is described as an integration. `docs/AI_DESK_001A_GAP_MAP.md`, on the
`ai-desk-001a-gapmap` branch, is the map of what building that interface would take.

The distinction the brief asks for is enforced in `runtime_status()`:

| | status |
|---|---|
| **A. Claude Code interactive access** | `CONFIGURED_PENDING_AUTHORIZATION`. OAuth 2.1, in your browser, against your account. The credential belongs to you and is held by the Claude Code client. |
| **B. APEX unattended runtime access** | **`NOT_CONNECTED`.** No route exists. |

**A working Claude connector is not evidence that the Python service can authenticate.** The OAuth session belongs
to the interactive client. A service route needs its own reviewed credential with a named owner and a refresh
lifecycle, and none has been designed or authorized. The adapter will not export Claude's tokens, will not read its
credential storage, and holds no transport of its own — a test parses every module's imports and fails the build if
`requests`, `urllib`, `httpx`, `socket`, `aiohttp`, `http`, `ssl` or `subprocess` appears. TradingView's
documentation states OAuth 2.1 and **no token lifetime or refresh behaviour**, so the refresh lifecycle is recorded
as `UNDOCUMENTED`.

There is **no path from a TradingView recommendation to an order**, and this brick creates none.

## 5. The bounded smoke test — NOT RUN

Ten non-mutating calls are budgeted and specified: resolve SPY's qualified symbol through `search_symbols`, then
small samples of `get_technicals_rating`, `get_news` and `get_earnings_calendar` / `get_economic_calendar`. **No
historical OHLCV retrieval** is in this brick; the bars adapter is tested on synthetic payloads only.

**It has not run.** The server is authorized, but the session that built this connector cannot see its tools: the
tool registry is fixed at session start and this session started before the authorization. Nothing was persisted,
no call was made, and no partial result is being presented as one. A fresh session can run it immediately.

Not done and not attempted: backtesting, fitting, any paid upgrade or subscription purchase, collector activation,
recurring polling.

## 6. Acceptance test results

`tests/test_tradingview_connector_001.py` — **45 tests, all passing**, synthetic payloads only, no network call.

| requirement | proven by |
|---|---|
| disallowed and side-effecting tools cannot be called | 6 tests; the transport records zero calls for all 10 mutating tools, the disputed one, and unknown names |
| malformed, future-dated or incomplete inputs refuse | 5 tests |
| late-arriving information cannot enter earlier snapshots | 4 tests, including a yesterday-candle-fetched-today case |
| duplicates idempotent, revisions distinct | 4 tests |
| partial bars do not masquerade as complete | 4 tests |
| unknown delay/entitlement does not become real-time verified | 3 tests |
| timeouts, rate limits, auth failure become named states | 6 tests, including `Retry-After` being honoured exactly |
| hostile headline text stays data | 3 tests, with an injection headline that names tools, a webhook and an authority change |
| existing feeds, risk controls and exit handling independent | 4 tests, including an import audit of the session and exit-policy modules |
| no credentials in persisted evidence | 4 tests, checking code imports and credential-shaped values rather than the words |

Two of these tests failed on their first run against my own prose — the docstrings contain the words "socket" and
"tokens" — and were rewritten to check the code's import set and the report's field names and value shapes instead
of doing a substring scan. That is recorded because the first version would have passed for the wrong reason later.

## 7. What remains

- **The smoke test.** Blocked only by session tool visibility, not by authorization. Run it from a new session.
- **Tool enumeration.** The capability list here is documented, not discovered. Enumerate the live tool list in the
  new session and reconcile it with this file before trusting the allowlist's coverage.
- **The `get_active_watchlist` discrepancy** is unresolved and the tool stays excluded.
- **Unattended APEX runtime access: NOT_CONNECTED**, and it needs its own reviewed credential design.
- **Production Twin wiring: NOT_CONNECTED**, pending the read-only snapshot interface.
- **Chart display gap.** TradingView's MCP server documents **no chart image or screenshot tool**. Embedding an
  interactive TradingView chart in APEX is a separate integration with its own licensing and attribution questions,
  and this connector does not advance it.
- **Execution feed gap.** The server documents **no options data of any kind** — no chains, no option quotes, no
  greeks — and no order or execution capability. TradingView cannot serve the options pilot's market data and
  cannot execute anything. It is a context source.
- **Rate-limit behaviour** is documented as ~100 calls/minute with no `Retry-After` semantics stated. The adapter
  honours a `Retry-After` if one arrives and otherwise backs off; what the server actually sends is unverified.
- **Data terms.** The documentation makes no statement about redistribution, persistence or delay entitlement, so
  the adapter persists nothing by default and marks entitlement `UNKNOWN`. Confirm the terms before storing any
  retrieved content as evidence.
