"""The seam between APEX's Python layer and an authenticated MCP broker.

**The problem this module exists to state honestly.**

`claude mcp add robinhood-trading ...` registers the server with the
Claude Code CLIENT, and the interactive OAuth grant belongs to that
client's session. A Python process started from a shell is not in that
session and holds no token. So a script cannot simply "call Robinhood"
once the operator authenticates -- there is no ambient credential for it
to pick up.

Before this module, both harnesses did:

    try:
        from apex.execution.mcp_transport import transport
    except ImportError:
        transport = None

...and a `None` transport rendered as BLOCKED_BROKER_AUTH. That is a
Category II defect in the instrument itself (see MUSEUM-OF-NEGATIVE-
CONTROLS.md): the board reported "the operator has not authenticated"
when the truth was "this harness cannot reach the broker even if they
have." A certification that cannot turn green is worse than no
certification, because it looks like progress is pending on someone else.

**The three honest states**, which callers must now distinguish:

    NO_TRANSPORT          nothing is wired; the Python layer has no route
                          to the MCP session. NOT a statement about auth.
    BLOCKED_BROKER_AUTH   a route exists and the broker refused it.
    READY                 a route exists and the broker answered.

**Supplying a transport.** Two supported routes, both explicit:

1. CLAIMED_MCP (Claude-mediated). The agent calls the MCP tools in its
   own session and writes the raw results to a JSON file; the harness
   reads it via `from_probe_file`. Every record is stamped
   `transport="CLAIMED_MCP"` so the archive never implies the Python
   process spoke to Robinhood itself. Read/review only -- this route
   cannot place an order because no placement tool is on the allow-list.

2. DIRECT_OAUTH. A standalone client holding its own token. NOT built:
   it is a credential-handling path, and the operator's standing rule is
   that tokens live in the Keychain and nowhere else. Building it is a
   deliberate decision, not a convenience.
"""
from __future__ import annotations

import json
from pathlib import Path

NO_TRANSPORT = "NO_TRANSPORT"
CLAIMED_MCP = "CLAIMED_MCP"
DIRECT_OAUTH = "DIRECT_OAUTH"


class TransportUnavailable(RuntimeError):
    """No route from this process to the MCP session. Distinct from the
    broker refusing an authenticated call."""


def default():
    """What a bare harness gets: nothing, said out loud.

    Returns (transport, mode). The transport is None and the mode is
    NO_TRANSPORT -- callers must render that differently from an auth
    failure.
    """
    return None, NO_TRANSPORT


def from_probe_file(path: str | Path):
    """Build a read-only transport from raw MCP results captured by the
    agent in its own authenticated session.

    The file is {tool_name: result_dict}. A tool absent from the file
    raises TransportUnavailable rather than returning an empty dict: a
    missing probe is unknown, not empty, and the difference is the whole
    lesson of LAB-04.
    """
    p = Path(path)
    if not p.exists():
        raise TransportUnavailable(f"probe file not found: {p}")
    try:
        payload = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise TransportUnavailable(f"probe file is not valid JSON: {e}")
    if not isinstance(payload, dict):
        raise TransportUnavailable("probe file must be {tool: result}")

    def call(tool: str, **kw):
        if tool not in payload:
            raise TransportUnavailable(
                f"no captured result for {tool!r}; the probe file covers "
                f"{sorted(payload)}. An uncaptured tool is UNKNOWN, never "
                f"an empty success.")
        return payload[tool]

    return call, CLAIMED_MCP
