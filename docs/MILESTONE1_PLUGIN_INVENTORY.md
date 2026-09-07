# Plugin capability inventory

Read-only. No bulk ingestion, no paid request, no subscription, and no
integration was built. This is an inventory of what is reachable, not a
research project.

## Headline

**None of the seven named plugins is callable in this Claude Code session.**
Finance, Financial Analysis, Wealth Management, Bigdata.com, Daloopa, LSEG and
S&P Global expose no tools and no skills here.

**Cause established, not guessed.** The operator has confirmed they were
installed in Claude Chat rather than in Claude Code. That accounts for the
observation exactly: the installations are real, and this session cannot reach
them. Nothing is broken and no setup is required for this milestone.

Checked three ways:

| Check | Result |
|---|---|
| Plugin listing for this session | empty |
| Skill listing, all namespaces | none of the seven appears |
| Tool search for fundamentals, filings, earnings, pricing | only the pre-existing Robinhood connector |

Installation in one Claude surface does not establish availability in another.
Until these surface as tools or skills in a Code session, nothing about their
coverage, entitlements, point-in-time semantics or licensing can be verified
from here, and none of it should be planned against.

**Context7, by contrast, IS available in this session** and was verified by a
live call. Recorded separately because the two answers are different, and the
difference matters: one capability is reachable and one is not.

Two adjacent facts from the same session state, since they bear on what is
actually reachable: three servers require an interactive authorization this
session cannot perform (`airwallex-agentos` twice, `huggingface-skills`), and
one is configured but failed to connect (`sagemaker-ai:aws-mcp`, connection
closed). The last is a connection failure, not an absence of capability.

## What IS reachable that touches the intended roles

| Surface | What it offers | Standing |
|---|---|---|
| Robinhood connector | equity/option/crypto quotes, fundamentals, financials, SEC filing index and tagged facts, earnings calendar and results, historicals, scanners | pre-existing, not one of the seven; its order-placing tools are permanently off-limits under standing law |
| `ruflo-market-data` | feed ingestion, OHLCV normalization, pattern matching | present, unevaluated |
| `ruflo-neural-trader` | backtesting, regime, risk, signals | present, unevaluated |

The Robinhood connector already covers part of the Daloopa and S&P Global role
sketch: reported revenue, gross profit, net income and margin by fiscal period,
plus SEC filing facts by GAAP concept. If those plugins later become callable,
the first question is what they add over this, not what they provide.

## Against each question asked

**What is actually callable and accessible?** For the seven named plugins,
nothing. For the roles they were meant to fill, only the Robinhood connector,
which we already have.

**Which APEX information gap could it address?** On the evidence, none can be
assessed. Worth stating plainly: the binding Phase-2 blocker is D1, historical
as-known availability. That is a question about publication and revision
semantics, not about having more fields. A vendor that answers it precisely
would matter more than any number of new data types. Bigdata.com and S&P
Global are the two whose documentation would be worth reading first for that
reason alone, if they become reachable.

**Does it duplicate data we already purchase?** Cannot be determined. The
overlap risk is real and specific: fundamentals and filings from Daloopa or
S&P Global against what the Robinhood connector already returns, and
cross-asset pricing from LSEG against the existing market-data vendor.

**Historical coverage, publication timestamps, revision history, point-in-time
semantics?** No documentation is exposed, so nothing is known. This is the
question that decides whether any of them is useful to us at all, and it is
precisely the one that cannot be answered from an install.

**Storage, licensing, additional charges?** No documentation is exposed.
Unknown, and a live constraint on any future use.

**What remains unverified?** Everything. Availability, entitlements, coverage,
semantics, licensing and cost.

## The bar any future integration must clear

Not a plan, a standard. For each proposed source, before any ingestion:

1. **Hypothesis** the specific economic claim, stated so it can be wrong.
2. **Causal availability** proof each input was knowable at the modelled
   instant, with publication and revision timestamps. Without this a source
   cannot enter a historical corpus, whatever else it offers.
3. **Simplest competing baseline** what already-held data would have to be
   beaten, quantified in advance.
4. **Falsification test** the preregistered result that kills it.
5. **Contribution after costs** the expected effect on capacity-adjusted,
   after-cost geometric growth, net of licence and storage.

More data must earn its place. A new source that cannot answer point 2 does
not enter the corpus regardless of its breadth, because it would import
exactly the defect D1 already blocks on.

Plugin output, if it ever arrives, does not override canonical Book
accounting, independent Risk authority, quantitative probability estimation, or
the research-admission gates. Sourced facts, estimates and generated
interpretation stay separately labelled.
