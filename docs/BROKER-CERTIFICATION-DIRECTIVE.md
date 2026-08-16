# APEX BROKER CERTIFICATION — EXECUTE ONLY, NO NEW FEATURES

*Operator directive for a FRESH session started from ~/apex-equities.
Robinhood is already authenticated; MCP toolsets bind at session startup,
which is why the previous sessions could not reach it.*

**Correction note (2026-08-16):** an earlier commit message claimed this
file was staged; a failed `cp` short-circuited the `cat` that wrote it and
the claim went unverified — the same disease as INSTR-01, in the audit
trail itself. This is the real file.

## PRE-FLIGHT

Do not modify strategy logic, Epoch 1, Crypto Epoch 0, Captain, Capital,
Hunter, Assassin, or execution semantics. Do not build DIRECT_OAUTH. Do
not add credentials. Do not expose or invoke any live placement,
cancellation, or account-mutating tool. No feature work unless a P0/P1
certification defect is discovered.

Companion runbook: `docs/RUNBOOK-BROKER-CERTIFICATION.md`.

## STEP 1 — BIND + CERTIFY

Prove `robinhood-trading` is BOUND into THIS session before anything
else: `ListMcpResourcesTool` must list it and an exact tool lookup must
resolve. Reachability is a measurement, not an assumption — three prior
sessions were authenticated with zero tools bound.

**If it still does not bind in a genuinely fresh session started from
~/apex-equities, stop calling it session binding.** Three sessions is
enough evidence; investigate the registration itself:
`claude mcp get robinhood-trading`, both project scopes in
`~/.claude.json`, transport health.

Once bound, call the read/review tools against real data and capture RAW
outputs to `/tmp/rh_probe.json` (`{tool_name: result}`; erroring tools
OMITTED so `from_probe_file` fails honestly). Then:

```
python scripts/robinhood_certification.py --probe-file /tmp/rh_probe.json
python scripts/execution_rehearsal_synthetic.py --symbol SPY --probe-file /tmp/rh_probe.json
```

Required end state — every row MEASURED (no FAIL/BLOCKED/NO_ROUTE/
UNKNOWN-as-PASS); unsupported surfaces report SUPPORTED=NO, not FAIL:

```
Account / portfolio / buying power     PASS
Equity quotes / tradability            PASS
Equity price book (L2)                 PASS or SUPPORTED=NO
Option chains / quotes                 PASS
Equity review / option review          PASS

ORDER_READY                            YES
ORDER_SENT                             DOES NOT EXIST
place_* reachable from APEX            NO
```

Report `APEX EXECUTION INFRASTRUCTURE: READY` only if all of that holds,
always followed by `Scientific authorization: NOT EARNED`.

## STEP 2 — OPERATE THE CANDIDATE MICROSCOPE

The selector and record law are BUILT and tested
(`apex/hunter/microscope.py`). The agent session is the ONLY thing that
can call Robinhood tools — the launchd clock structurally cannot (no MCP
route in a Python process). Loop during market hours:

1. Read the official forward ledger (scans + decisions).
2. `select_targets()` — deterministic, LLM-free: hunter candidates first,
   then watchlist by signal count/RVOL, then board rank. ≤20 quote
   targets, first ≤4 get L2.
3. Call quote for all targets; price book for `wants_l2` targets only.
4. Persist `record_request` / `record_result` (transport=CLAIMED_MCP)
   into `results/hunter/microscope_ledger.jsonl` via the standard
   `_chain_append`. Absence rules are enforced in the record law:
   missing book = UNKNOWN, never zero imbalance.

## STEP 3 — ARM FASTWATCH IF LAB QUOTA IS GREEN

```
python scripts/fastwatch.py
```

EODHD-based, `purpose="LAB"` so it structurally cannot touch the 35k
forward reserve; bounded to 8 symbols read from the official ledger; own
chained ledger with kinds no official reader consumes; conditions
recorded as `FASTWATCH_CONDITION_OBSERVED`, never as matches. It
measures the latency tax of the 15-minute official cadence. It does not
trade, match, or decide.

## STANDING CONTEXT

- Epoch 1 opens Mon 2026-08-17 09:30 ET and depends on NONE of this.
- Everything here is decision_power = NONE_OBSERVATIONAL_EPOCH1, and
  tests assert the frozen modules consume none of it.
- Category II doctrine applies to this certification itself: a row that
  cannot go red carries no information when it is green
  (`docs/AUDIT/ENFORCEMENT-DOCTRINE.md`).
- Session report at day's end:
  `python scripts/epoch1_session_report.py --date 2026-08-17`
