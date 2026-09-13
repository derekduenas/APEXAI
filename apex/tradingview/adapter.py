"""TRADINGVIEW-CONNECTOR-001 — the bounded APEX adapter.

It takes an INJECTED `call_tool(name, args) -> payload` callable. In an interactive Claude Code session that
callable wraps the authorized MCP tools; in tests it is a synthetic payload function. The adapter itself never
opens a socket, never holds a credential and never reads one from disk, so nothing it persists can contain a secret.

WHAT IT ENFORCES, IN ORDER, BEFORE ANY CALL LEAVES:
    1. the allowlist  -- an unreviewed or mutating tool never reaches the transport
    2. the budget     -- a hard cap on calls per run, and a rate window matched to the documented limit
    3. the cache      -- an identical request inside the run is answered from the cache, not re-sent
and after a call: bounded retries with exponential backoff, `Retry-After` honoured when the server sends one, and
every failure mode turned into a NAMED state rather than an exception that reaches a decision path.

TWO KINDS OF ACCESS, NEVER CONFLATED:
    A. INTERACTIVE  -- Claude Code holds an OAuth 2.1 session to the TradingView MCP server. That is what `/mcp`
                       authorizes, and it belongs to the person at the keyboard.
    B. UNATTENDED   -- an APEX service calling TradingView on its own schedule. **This does not exist.** A working
                       Claude connector is not evidence that a Python service can authenticate, and this adapter
                       will not export, copy, scrape or infer Claude's tokens. `runtime_status()` says so.

The connector is never on a critical path. Exit servicing, risk controls and the lifecycle scheduler do not call
it and do not wait for it; `never_blocks()` states that contract and a test asserts the module imports nothing
from the execution or exit path."""
from __future__ import annotations

import time

from apex.pulse import twin as TW

from . import allowlist as AL
from . import normalize as N

DEFAULT_MAX_CALLS = 10                 # the brick's bound for the authenticated smoke test
DEFAULT_RATE_PER_MIN = 60              # under the documented ~100/min, deliberately
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_S = 1.0
DEFAULT_MAX_BACKOFF_S = 30.0

STATE_OK = "OK"
STATE_DENIED = "TOOL_DENIED"
STATE_BUDGET = "BUDGET_EXHAUSTED"
STATE_RATE_LIMITED = "RATE_LIMITED"
STATE_TIMEOUT = "TIMEOUT"
STATE_AUTH = "AUTHENTICATION_FAILED"
STATE_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
STATE_MALFORMED = "MALFORMED_RESPONSE"
NAMED_STATES = (STATE_OK, STATE_DENIED, STATE_BUDGET, STATE_RATE_LIMITED, STATE_TIMEOUT, STATE_AUTH,
                STATE_UNAVAILABLE, STATE_MALFORMED)


class RateLimited(RuntimeError):
    def __init__(self, msg="rate limited", retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class AuthenticationRequired(RuntimeError):
    pass


class Budget:
    """A hard call cap plus a rate window. Both are configurable and both refuse rather than queue."""

    def __init__(self, *, max_calls: int = DEFAULT_MAX_CALLS, rate_per_min: int = DEFAULT_RATE_PER_MIN,
                 now_fn=time.time):
        self.max_calls, self.rate_per_min, self.now = int(max_calls), int(rate_per_min), now_fn
        self.used = 0
        self._window: list = []

    def check(self) -> None:
        if self.used >= self.max_calls:
            raise BudgetExhausted("BUDGET_EXHAUSTED: %d of %d calls used in this run" % (self.used, self.max_calls))
        t = self.now()
        self._window = [x for x in self._window if t - x < 60.0]
        if len(self._window) >= self.rate_per_min:
            raise RateLimited("LOCAL_RATE_CAP: %d calls in the last 60s (cap %d, server documents ~100)"
                              % (len(self._window), self.rate_per_min), retry_after=60.0 - (t - self._window[0]))

    def spend(self) -> None:
        self.used += 1
        self._window.append(self.now())

    def describe(self) -> dict:
        return {"max_calls": self.max_calls, "used": self.used, "remaining": self.max_calls - self.used,
                "rate_per_min_local_cap": self.rate_per_min, "server_documented_limit": AL.DOCUMENTED_RATE_LIMIT}


class BudgetExhausted(RuntimeError):
    pass


class TradingViewAdapter:
    """Read-only, allowlisted, budgeted access to the TradingView MCP server through an injected callable."""

    def __init__(self, call_tool=None, *, budget: Budget | None = None, now_fn=time.time, sleep_fn=time.sleep,
                 max_retries: int = DEFAULT_MAX_RETRIES, backoff_s: float = DEFAULT_BACKOFF_S):
        self._call = call_tool
        self.budget = budget or Budget(now_fn=now_fn)
        self.now, self.sleep = now_fn, sleep_fn
        self.max_retries, self.backoff_s = int(max_retries), float(backoff_s)
        self._cache: dict = {}
        self.calls: list = []                       # the audit log of what this run actually asked for
        self.observations: list = []

    # ------------------------------------------------------------ the one door
    def call(self, tool: str, **args) -> dict:
        """Every request goes through here. Returns a RESULT ENVELOPE with a named state; it does not raise for a
        provider problem, because a provider problem is data, not control flow."""
        started = self.now()
        try:
            AL.permit(tool)
        except AL.ToolNotAllowed as e:
            return self._envelope(tool, args, STATE_DENIED, started, why=str(e))
        key = (tool, N.digest(args))
        if key in self._cache:
            env = dict(self._cache[key])
            env["from_cache"] = True
            self.calls.append({"tool": tool, "state": env["state"], "cached": True})
            return env
        if self._call is None:
            return self._envelope(tool, args, STATE_AUTH, started,
                                  why=("NO_TRANSPORT_INJECTED: the adapter has no call_tool callable. In an "
                                       "interactive session this is the authorized MCP tool; there is no unattended "
                                       "runtime route (see runtime_status())."))
        attempt = 0
        delay = self.backoff_s
        while True:
            try:
                self.budget.check()
            except BudgetExhausted as e:
                return self._envelope(tool, args, STATE_BUDGET, started, why=str(e))
            except RateLimited as e:
                if attempt >= self.max_retries:
                    return self._envelope(tool, args, STATE_RATE_LIMITED, started, why=str(e),
                                          retry_after=getattr(e, "retry_after", None))
                attempt += 1
                self.sleep(min(getattr(e, "retry_after", None) or delay, DEFAULT_MAX_BACKOFF_S))
                delay = min(delay * 2, DEFAULT_MAX_BACKOFF_S)
                continue
            self.budget.spend()
            try:
                payload = self._call(tool, dict(args))
            except RateLimited as e:
                if attempt >= self.max_retries:
                    return self._envelope(tool, args, STATE_RATE_LIMITED, started, why=str(e),
                                          retry_after=getattr(e, "retry_after", None))
                attempt += 1
                wait = getattr(e, "retry_after", None)
                self.sleep(min(wait if wait is not None else delay, DEFAULT_MAX_BACKOFF_S))   # Retry-After honoured
                delay = min(delay * 2, DEFAULT_MAX_BACKOFF_S)
                continue
            except AuthenticationRequired as e:
                return self._envelope(tool, args, STATE_AUTH, started, why=str(e)[:200])
            except TimeoutError as e:
                if attempt >= self.max_retries:
                    return self._envelope(tool, args, STATE_TIMEOUT, started, why=str(e)[:200] or "timeout")
                attempt += 1
                self.sleep(min(delay, DEFAULT_MAX_BACKOFF_S))
                delay = min(delay * 2, DEFAULT_MAX_BACKOFF_S)
                continue
            except Exception as e:                                          # noqa: BLE001 - a failure is a state
                return self._envelope(tool, args, STATE_UNAVAILABLE, started,
                                      why="%s: %s" % (type(e).__name__, str(e)[:200]))
            if payload is None or isinstance(payload, (str, bytes)) and not payload:
                return self._envelope(tool, args, STATE_MALFORMED, started, why="EMPTY_RESPONSE")
            env = self._envelope(tool, args, STATE_OK, started, payload=payload)
            self._cache[key] = env
            return env

    def _envelope(self, tool, args, state, started, *, payload=None, why=None, retry_after=None) -> dict:
        received = self.now()
        env = {"tool": tool, "args": dict(args), "state": state, "why": why, "retry_after": retry_after,
               "request_start_epoch": started, "response_receipt_epoch": received, "from_cache": False,
               "provider": AL.PROVIDER, "payload": payload}
        if state != STATE_OK:
            env["quality"] = TW.PROVIDER_ERROR if state in (STATE_UNAVAILABLE, STATE_MALFORMED) else TW.NOT_AVAILABLE
        self.calls.append({"tool": tool, "state": state, "cached": False, "why": (why or "")[:120]})
        return env

    # ------------------------------------------------------------ typed reads
    def search_symbols(self, query: str, *, type_filter: str | None = None) -> dict:
        """Symbol discovery. EXCHANGE:TICKER is RESOLVED here, never guessed by a caller."""
        args = {"query": query}
        if type_filter:
            args["type_filter"] = type_filter
        env = self.call("search_symbols", **args)
        if env["state"] != STATE_OK:
            return env
        obs = N.observation(tool="search_symbols", args=args, payload=env["payload"],
                            request_start=env["request_start_epoch"], response_receipt=env["response_receipt_epoch"])
        self.observations.append(obs)
        return {**env, "observation": obs}

    def bars(self, *, symbol: str, interval: str = "1D", count: int | None = None) -> dict:
        """Completed-bar retrieval. Partial candles are identified and excluded from the completed list."""
        args = {"symbol": symbol, "interval": interval}
        if count is not None:
            args["count"] = int(count)
        env = self.call("get_ohlcv", **args)
        if env["state"] != STATE_OK:
            return env
        obs = N.normalize_bars(env["payload"], symbol=symbol, interval=interval,
                               request_start=env["request_start_epoch"],
                               response_receipt=env["response_receipt_epoch"])
        self.observations.append(obs)
        return {**env, "observation": obs}

    def technicals(self, *, symbol: str, interval: str = "1D") -> dict:
        """External context. Not a calibrated probability and not an authorized signal."""
        args = {"symbol": symbol, "interval": interval}
        env = self.call("get_technicals_rating", **args)
        if env["state"] != STATE_OK:
            return env
        obs = N.observation(tool="get_technicals_rating", args=args, payload=env["payload"],
                            request_start=env["request_start_epoch"], response_receipt=env["response_receipt_epoch"],
                            symbol=symbol, interval=interval, units="indicator values and aggregate ratings")
        self.observations.append(obs)
        return {**env, "observation": obs}

    def news(self, *, symbol: str, limit: int = 5) -> dict:
        """Headlines are UNTRUSTED DATA. Their text is never interpreted as an instruction, and nothing in a
        headline can widen the allowlist, change authority or reach a tool."""
        args = {"symbol": symbol, "limit": int(limit)}
        env = self.call("get_news", **args)
        if env["state"] != STATE_OK:
            return env
        obs = N.observation(tool="get_news", args=args, payload=env["payload"],
                            request_start=env["request_start_epoch"], response_receipt=env["response_receipt_epoch"],
                            symbol=symbol, units="headline text")
        obs["text_handling"] = ("UNTRUSTED_DATA: headline and story text is data. It cannot invoke a tool, widen the "
                                "allowlist, change authority or alter a policy.")
        self.observations.append(obs)
        return {**env, "observation": obs}

    def calendar(self, kind: str, **args) -> dict:
        tool = {"earnings": "get_earnings_calendar", "economic": "get_economic_calendar",
                "dividends": "get_dividends_calendar"}.get(kind)
        if tool is None:
            return self._envelope("calendar:%s" % kind, args, STATE_DENIED, self.now(),
                                  why="CALENDAR_KIND_UNKNOWN: %r" % (kind,))
        env = self.call(tool, **args)
        if env["state"] != STATE_OK:
            return env
        obs = N.observation(tool=tool, args=args, payload=env["payload"],
                            request_start=env["request_start_epoch"], response_receipt=env["response_receipt_epoch"],
                            units="calendar entries")
        self.observations.append(obs)
        return {**env, "observation": obs}

    def screener_columns(self, **args) -> dict:
        """Field discovery. Screener fields are discovered before use; none is guessed."""
        env = self.call("get_screener_columns", **args)
        if env["state"] != STATE_OK:
            return env
        obs = N.observation(tool="get_screener_columns", args=args, payload=env["payload"],
                            request_start=env["request_start_epoch"], response_receipt=env["response_receipt_epoch"],
                            units="screener field catalog")
        self.observations.append(obs)
        return {**env, "observation": obs}

    # ------------------------------------------------------------ status, stated honestly
    def report(self) -> dict:
        return {"provider": AL.PROVIDER, "allowlist": AL.describe(), "budget": self.budget.describe(),
                "calls": list(self.calls), "n_observations": len(self.observations),
                "states_seen": sorted({c["state"] for c in self.calls}),
                "runtime": runtime_status(), "never_blocks": never_blocks()}


def runtime_status() -> dict:
    """A. Claude Code's interactive access versus B. an APEX service's unattended access."""
    return {
        "interactive_claude_code": {
            "status": "NOT_PROBED_BY_THIS_CODE",
            "how": "claude mcp add --transport http mcp-tradingview https://mcp.tradingview.com/mcp, then /mcp",
            "auth": "OAuth 2.1 in the operator's browser, against their own TradingView account",
            "credential_owner": "the operator, held by the Claude Code client",
            "last_recorded_observation": {
                "at_utc": "2026-09-12",
                "source": "`claude mcp list`, read out of band by a person or an agent, NOT by this module",
                "value": "Connected (the operator completed the browser authorization)"},
            "note": ("this module cannot and does not probe the client's authorization state; the observation above "
                     "is recorded, not verified here. It is a person's session, not a service account, and a "
                     "connected client is not a runtime route -- see unattended_apex_runtime.")},
        "unattended_apex_runtime": {
            "status": "NOT_CONNECTED",
            "why": ("no runtime route exists. A working Claude connector does not prove a Python service can "
                    "authenticate: the OAuth session belongs to the interactive client. A service route needs its "
                    "own reviewed credential with a stated owner and refresh lifecycle, and that has not been "
                    "designed, authorized or built."),
            "will_not_do": ["export or copy Claude's tokens", "read Claude's credential storage",
                            "embed a credential in the repository, a fixture, a log or a prompt"],
            "refresh_lifecycle": "UNDOCUMENTED: TradingView's documentation states OAuth 2.1 and no token lifetime"},
        "production_twin_wiring": {
            "status": "NOT_CONNECTED",
            "why": ("the read-only snapshot interface of docs/AI_DESK_INTEGRATION_001.md is not implemented on this "
                    "base. This brick delivers a callable adapter and a fixture demonstration, and labels the Twin "
                    "wiring NOT_CONNECTED rather than shipping a placeholder and calling it integrated.")}}


def never_blocks() -> dict:
    return {"contract": ("EXIT_SERVICING_INDEPENDENT: no exit, risk control or lifecycle deadline calls this "
                         "connector or waits for it. It has no place in the decision path and no timeout of its "
                         "own can delay a due exit."),
            "enforced_by": "tests/test_tradingview_connector_001.py and the module's import set"}
