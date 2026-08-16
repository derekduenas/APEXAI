# RUNBOOK — broker certification after Robinhood authentication

**State as of 2026-08-16:** `robinhood-trading` is registered (local scope,
under BOTH `/Users/derekduenas` and `/Users/derekduenas/apex-equities`) and
reports `✔ Connected`. The OAuth grant is done. Nothing further is required
of the operator except starting a session that can see the tools.

## Why a restart is needed

A Claude Code session binds its MCP toolset at startup. The session that
authenticated the server was started before the server existed, so
`mcp__robinhood-trading__*` was never in its toolset — `ListMcpResourcesTool`
did not list the server at all. Authentication and tool availability are two
different facts; this is the same NO_TRANSPORT vs BLOCKED_BROKER_AUTH
distinction the harness now draws (see `apex/execution/mcp_transport.py`).

    cd ~/apex-equities && claude

## Step 1 — capture the probe (agent, in the authenticated session)

The Python layer holds no OAuth token and cannot acquire one. The agent
calls the MCP tools in its own session and writes the RAW results to a
probe file. Read/review tools only — no placement tool is on the adapter's
allow-list, so this route cannot reach an order.

Call, for a liquid symbol (SPY or NVDA — this rehearses PLUMBING, not a
market view):

    get_account_info          get_stock_quote(SPY)
    get_buying_power          get_options_chains(SPY)
    get_positions             get_options_market_data(SPY)
                              review_equity_order(SPY, buy, 1, limit)
                              review_option_order(SPY, buy, 1)

Write them to `/tmp/rh_probe.json` as `{tool_name: raw_result}`. Do NOT
edit, normalize, or fill in values: a probe file is a capture, not a
summary. A tool that errors is OMITTED — `from_probe_file` treats an
absent tool as UNKNOWN and raises, which is correct (LAB-04: absent is
never an empty success).

## Step 2 — certification board

```bash
python scripts/robinhood_certification.py --probe-file /tmp/rh_probe.json
```

READY requires EVERY row measured — no FAIL, no BLOCKED, no NO_ROUTE — and
the three structural MUSTs:

    place_* reachable from APEX     MUST = NO
    ORDER_READY reachable           MUST = YES
    ORDER_SENT reachable            MUST = NO

Exit 0 only when all of that holds. On success the board prints:

    APEX EXECUTION INFRASTRUCTURE: READY
    Scientific authorization: NOT EARNED

Both lines matter. The second is not modesty — infrastructure readiness is
not evidence, and Epoch 1 has not produced any yet.

## Step 3 — EXECUTION_REHEARSAL_SYNTHETIC

```bash
python scripts/execution_rehearsal_synthetic.py --symbol SPY --probe-file /tmp/rh_probe.json
```

    real quote -> synthetic opportunity -> Captain -> Capital fixture ->
    Expression -> real chain -> OrderIntent -> real broker review ->
    ORDER_READY -> STOP

It refuses to proceed without a real quote: a rehearsal that invents a
price is a simulation wearing a rehearsal's clothes. Every record is
stamped `rehearsal=True`, `production_evidence=False`,
`evidence_class=REHEARSAL_NOT_EVIDENCE`, in a separate ledger.
`PAPER_ELIGIBLE` appears only inside the fixture — production Capital
still cannot emit it.

## What must NOT happen

There is no step 4. `ORDER_SENT` is not a member of `ReadinessState`, no
module in `apex` defines a placement function
(`scan_package_for_placement("apex")` must stay clean), and
`LiveExecutionAuthorization` raises in its constructor. If any of those
three changes, the certification board fails and the doctrine suite
(`tests/test_enforcement_doctrine.py`) goes red. That is the intended
behavior, not an obstacle to route around.
