# TRADINGVIEW-INTEGRATION-002 — carry-forward, catalog reconciliation, and the snapshot join seam (2026-09-12)

Branch `tradingview-integration-002` at `4682e4f7a29d09f74699dbc8815cdcdb465e529d`, based on
`be626bbc42a5a9ae359994191baaf3165617be41`. TradingView modules carried from `tradingview-connector-001` at
`39fbd21`. *(Base and carry verified against the repository on 2026-09-13: `be626bb` is `4682e4f`'s parent, and
`39fbd21` is the tip of `tradingview-connector-001`.)*

> **§1 AND §2 ARE SUPERSEDED (2026-09-13) by `docs/TRADINGVIEW_INTEGRATION_003.md`.** The central finding below
> — *"this session is exposed no TradingView tools at all"* — was true of the session that wrote it and is
> **false of the successor session**, which was exposed all 27 tools. The reconciliation in §2 was
> documentation-based; it has since been redone against the live catalog, and that reconciliation found two real
> defects §2 could not have found. Everything else in this file stands.

**Observation-only boundary preserved. Nothing is connected to execution, risk, exits or order submission.**

## Status in one line

**The adapter, normalization, smoke script, tests and documentation are carried onto the current code line and
green; the snapshot join seam is built and tested; the bounded live smoke STILL COULD NOT RUN, because this
session is exposed no TradingView tools at all.**

---

## 1. Tool enumeration — what was actually attempted

**`/mcp` could not be run.** It is a terminal-dialog slash command that opens an interactive panel, and this
session is the desktop app's Code tab, where those commands are unavailable. That is a limitation of where this
session runs, not a refusal and not an authorization problem. What was run instead, and the verbatim results:

| probe | result |
|---|---|
| `claude mcp list` | `mcp-tradingview: https://mcp.tradingview.com/mcp (HTTP) - ✔ Connected` |
| `claude mcp get mcp-tradingview` | `Scope: Local config (private to you in this project)` · `Status: ✔ Connected` |
| `ToolSearch "+tradingview"` | **no matching tools** |
| `ToolSearch "select:search_symbols,get_ohlcv,get_technicals_rating,get_news,get_screener_columns"` | **no matching tools** |
| `ToolSearch "ohlcv candles technicals rating economic calendar dividends earnings"` | returned only Robinhood and Apollo tools — **nothing from this provider** |

**The discovered TradingView tool catalog for this session is empty.** *(Superseded: see
`docs/TRADINGVIEW_INTEGRATION_003.md` §1 — the successor session discovered 27 tools.)* The server is reachable and the account
authorization stands; the session's tool registry contains zero `mcp__mcp-tradingview__*` entries. This is the
same state the connector brick recorded on 2026-09-12, and it is unchanged by starting from
`/Users/derekduenas` — the working directory where the server is registered — because the registry is built at
session start and this session began before the probe.

**No tool catalog was therefore observed, and none is reported as observed.**

---

## 2. Catalog reconciliation — documentation-based, and labelled as such

Because no live catalog was exposed, the reconciliation below compares
`apex/tradingview/allowlist.py` against `docs/TRADINGVIEW_CONNECTOR_001.md` and the documented tool set. **It is
not a live reconciliation and must not be read as one.** Section 7 states what remains.

### 2.1 Allowed — 9 tools, and they match the authorized smoke list exactly

`search_symbols` · `get_screener_columns` · `get_ohlcv` · `get_technicals_rating` · `get_news` ·
`get_news_story` · `get_earnings_calendar` · `get_economic_calendar` · `get_dividends_calendar`

This is the same set of nine named in the smoke authorization, with no additions and no omissions. Verified by
comparing `ALLOWED_TOOLS` element-by-element against the authorized list.

### 2.2 Denied — and the denial survives a mistaken edit

`DENIED_TOOLS` carries **26** named entries with reasons *(corrected 2026-09-13: the figure "24" stated here was
wrong — `len(DENIED_TOOLS)` is 26, being 8 watchlist + 8 alert + 10 out-of-scope)*, in four groups: watchlist mutation, alerts (including
anything that can register a webhook), account-state reads that are outside this connector's purpose, and
read-only tools not reviewed in this brick (`run_screener`, `get_symbol_data`, `get_forecasts`, `get_financials`,
the document tools, and others).

Two structural properties make the denial hold rather than depend on the list being complete:

- **Default is DENY.** `permit()` raises `TOOL_NOT_ON_ALLOWLIST` for any name not in the nine. A tool that appears
  on the server and in nobody's list is refused without anyone noticing it first.
- **`FORBIDDEN_MARKERS` is a structural belt**: `create`, `delete`, `update`, `add_`, `remove`, `set_`, `stop_`,
  `restart`, `activate`, `order`, `buy`, `sell`, `submit`, `place`, `execute`, `trade`, `webhook`, `subscribe`,
  `upgrade`, `purchase`, `active_watchlist`. A name containing any of these is denied **even if someone adds it to
  `ALLOWED_TOOLS` by mistake**, and `assert_allowlist_is_sound()` runs at import so such an edit fails the build
  rather than reaching the server.

**Mutating, alert, webhook, watchlist-changing, order and execution tools are all denied, and so is every unknown
tool.** That requirement is met by construction, independent of catalog knowledge.

### 2.3 The one documentation inconsistency, re-affirmed

`get_active_watchlist` stays **denied**. TradingView's documentation carries it under a read-only label *and*
describes activation/creation side effects for it. **Documented behaviour governs; the label does not.** It is
denied twice over — by name in `DENIED_TOOLS`, and by the `active_watchlist` forbidden marker.

### 2.4 Reconciliation findings

| finding | status |
|---|---|
| allowlist matches the authorized smoke list | **exact, 9 for 9** |
| allowlist contains no forbidden marker | **verified** at import and by test |
| allowlist and denylist do not overlap | **verified** by `assert_allowlist_is_sound` |
| unknown tools denied | **verified** — default DENY |
| documentation label vs documented behaviour conflict | **resolved against the label**, `get_active_watchlist` denied |
| live catalog vs allowlist | **NOT PERFORMED** — no catalog was exposed (§7) |

---

## 3. Carry-forward onto the current code line

`git checkout -b tradingview-integration-002 be626bb`, then the TradingView files only:

```
apex/tradingview/{__init__,adapter,allowlist,normalize}.py
scripts/tradingview_smoke.py
tests/test_tradingview_connector_001.py
docs/TRADINGVIEW_CONNECTOR_001.md
```

**No newer exit-scheduling or pilot file was touched.** The carry adds seven files and modifies none, so nothing
from EXIT-SCHEDULING-002/003, the bounded correction, or the recorded-feed wiring could be overwritten.

**Dependency drift checked, not assumed.** The TradingView modules import only `apex.pulse.twin` from outside
their own package. `git diff 1b86541 be626bb -- apex/pulse/twin.py` is **empty** — the file is byte-identical
between the connector's original base and the current line, so the carry is clean rather than merely passing.

---

## 4. The snapshot join seam — built and tested, NOT wired

`apex/tradingview/seam.py`. The chain the review requires:

```
snapshot_id → market_state_digest → model_identities → candidate_set → decision_record
```

**Why it was needed.** Verified absent: the options-path Twin snapshot has no id. `snapshot_id` exists only in
`apex/catalyst/twin_snapshot.py` and `apex/vision/render.py`; `TwinSources.snapshot()` returns a composed dict with
no identity. A decision therefore cannot currently name the market state it was made on, and an observation cannot
be bound to it. The seam supplies that id as a **content-addressed digest** over symbol, canonical instant and the
snapshot's own values, so it is falsifiable: a reviewer holding the snapshot recomputes it.

**Two rules the seam enforces in code, not in prose:**

1. **Nothing informs a decision it was not knowable for.** An observation whose `known_from` postdates the
   snapshot's `as_of` is recorded `REFUSED_LATE_ARRIVING` and attached to nothing, reusing
   `normalize.valid_for_as_of`. Retrieving something later never makes it available earlier.
2. **An observation that fed nothing says so.** Attaching requires declaring what it feeds; one with no declared
   consumer is `RETRIEVED_UNUSED`. "What did the eyes contribute to this decision" is answered from the record.

**Premarket observations are `PRIOR_CONTEXT`**, attached to the packet reference rather than the decision
snapshot, and never counted as decision-time evidence. **Intraday observations are `DECISION_TIME_CONTEXT`** and
attach to the current `snapshot_id`.

**Labels are enforced on attach.** `_assert_context_only` refuses a record whose `calibrated`, `authority` or
`source_class` has been altered, and refuses a record from another provider. A joined observation is never a
calibrated probability, never a trading signal by itself, never a model promotion and never an order
authorization — asserted by test against `AUTHORITY_LAW`.

**The seam touches no execution path.** Its entire import set is `hashlib`, `json` and `.normalize`, asserted by a
test that parses the module's import graph (a text search would fail on the docstring, which names those paths
precisely because it promises not to touch them).

Every record it emits carries `wiring_status: SEAM_NOT_WIRED`, stating in the artifact itself that production Twin
wiring is not complete.

---

## 5. Test results — clean checkout of this branch

| suite | result |
|---|---|
| `tests/test_tradingview_connector_001.py` | **51 passed** |
| `tests/test_tradingview_seam_002.py` | **21 passed** |
| TradingView total | **72 passed** |
| with the affected APEX suites (15 files together) | **602 passed, 1 skipped, 0 failed** |

One of my own new tests was wrong on first run and was corrected rather than worked around: it grepped the
module's source text for "execution" and matched the docstring's own promise not to touch execution. It now
parses the import graph.

---

## 6. The bounded live smoke — NOT RUN, with the precise blocker

**Zero calls were made to TradingView by any process. No recording exists, and none was invented.**

**Blocker:** this session's tool registry contains **no `mcp__mcp-tradingview__*` tool**, so there is nothing to
call. The server is Connected and the account is authorized; the tools are simply not exposed here (§1).

**What was NOT done, deliberately:** no `calls.json` was fabricated. `scripts/tradingview_smoke.py` takes recorded
request instants, receipt instants and verbatim payloads, and `known_from` is taken from the receipt — a
fabricated receipt would manufacture exactly the hindsight the normalization contract exists to prevent. A
synthetic file run through the script would produce an artifact that looks like smoke evidence and is not one.

**What is verified instead:** the script itself is carried forward intact and its refusals are exercised by the
connector suite on this code line — more than ten calls, a receipt in the future of the wall clock, a receipt
preceding its request, out-of-order receipts, and off-allowlist tools are each refused by name.

**To complete it** (unchanged from the authorization, still ≤10 calls, still the nine allowlisted tools): an
interactive session that exposes the tools calls each one, records `request_start`, `response_receipt`, `args` and
the verbatim `payload` into `calls.json`, then runs
`python scripts/tradingview_smoke.py calls.json out.json`. Evidence is preserved outside the source tree.

---

## 7. Remaining gaps

1. **The live tool catalog has never been observed.** The reconciliation in §2 is documentation-based. Anything
   the server exposes that is not among the nine is denied by default, so the gap is bounded — but a tool the
   documentation omits, or one whose behaviour differs from its documentation, is unknown to us.
2. **The bounded smoke is unspent.** No live payload has ever passed through the adapter.
3. **Production Twin wiring is NOT complete, and is not claimed to be.** The seam exists and is tested; nothing
   calls it. Specifically: `TwinSources.snapshot()` does not emit a `snapshot_id`, no decision record carries
   `external_inputs_used`, and no premarket packet carries `external_context[]`. Wiring those three is the
   remaining work, and each is a change to the pilot path that should be reviewed on its own.
4. **Unattended APEX access remains `NOT_CONNECTED`.** No service authentication route exists. TradingView
   documents OAuth 2.1 with no token lifetime; `adapter.runtime_status()` records
   `refresh_lifecycle: UNDOCUMENTED`. Claude's OAuth credentials are not borrowed, exported or read, and an
   interactive connection is not reported as a service connection.
5. **Chart rendering and options data remain unavailable** from this connector, by its own documentation.
6. **Entitlement is `UNKNOWN`** on every observation until a live response proves real-time versus delayed.

---

## 8. What this branch does not do

- It does not connect TradingView to execution, risk, exits or order submission — the seam imports none of them.
- It does not allow any mutating, alert, webhook, watchlist-changing, order or unknown tool.
- It does not make a provider call, change a credential, deploy anything, or change a limit, fee, selection
  policy, exit policy or model promotion.
- It does not claim the observation is a signal, a probability, a promotion or an authorization.
