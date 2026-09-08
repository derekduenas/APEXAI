# EXTERNAL COMPONENT ADOPTION 001

Read-only inspection of six external repositories, an adoption matrix, and
one implemented artifact. **No repository was cloned, installed, vendored or
added as a dependency. No credential, account, admission, dataset view or
broker session was created. No order was routed. No real market row was read.**

Inspection was performed from the operator's machine over the public GitHub
API at pinned commits; the host has no GitHub access and was not used for it.

## 1. Repositories, at exact HEAD, with licenses read from the actual files

| Repository | HEAD (pinned) | Commit date | License **file** | Language | Last push | Tests in tree |
|---|---|---|---|---|---|---|
| anthropics/financial-services | `69cbc81467a5dced793eee03dec4658aa24ef856` | 2026-08-25 | `LICENSE` → Apache-2.0 (verified, 11,358 B, 4× "Apache License") | Python + Markdown skills | 2026-08-25 | **0** |
| AI4Finance-Foundation/FinGPT | `1c6e2ce3b5e01eb192c57fad01ae719376868afd` | 2026-09-07 | `LICENSE` → MIT (verified, "MIT License", © 2024 AI4Finance Foundation) | Jupyter/Python | 2026-09-07 | 23 files |
| StockSharp/StockSharp | `c049b1f9ee1653b158a9303115779a1f48e5534e` | 2026-09-07 | `LICENSE` → **PROPRIETARY** (see §2) | C# | 2026-09-07 | not inspected |
| je-suis-tm/quant-trading | `611b73f2c3f577ac5b28aaa19ac8c43d3236c7a5` | **2024-04-14** | `LICENSE` → Apache-2.0 (verified) | Python | 2024-04-14 | **0** |
| wangzhe3224/awesome-systematic-trading | `424df5f4acc98dcc3880107188d20f5fa4897653` | 2026-08-30 | `LICENSE` → MIT (verified) | HTML/Markdown catalog | 2026-08-30 | n/a |
| jmfernandes/robin_stocks | `1b4ef98be36d1df127886889c843256799a1dfea` | **2026-02-11** | `LICENSE.txt` → MIT (verified, © 2018 Joshua M. Fernandes) | Python | 2026-02-11 | 4 files |

GitHub's metadata reported `NOASSERTION` for StockSharp; the file itself was
read and is decisive. Metadata was not trusted for any of the six.

## 2. StockSharp — proprietary; no adoption, and no source inspection

The `LICENSE` at `c049b1f9` states: *"All source code, binaries,
documentation, examples, media assets, configuration files, and other
materials contained in this repository are the proprietary property of
StockSharp"*, *"This repository is not licensed under a general-purpose open
source license"*, and that **viewing, downloading, copying, building,
modifying, using or distributing** any part is permitted only under the
StockSharp EULA published on their website, which they may update unilaterally.

Consequences, applied:

- **No code reuse, no dependency, no vendoring — not now, not later, without
  explicit written license approval.**
- I inspected **only** the repository metadata and the license file. I did
  **not** list or read its source tree, because the license conditions access
  itself. Its execution-simulation concepts (order state machines, latency,
  partial fills, replay) are standard market-microstructure knowledge that
  APEX can specify independently; nothing may be derived from their code.
- Recorded as **NO_ADOPTION**. The reviewer's expectation that StockSharp
  "contributes design ideas for execution simulation later" survives only in
  the weak form: it confirms that a serious execution simulator needs those
  features. The features themselves must be re-derived from public
  microstructure literature and APEX's own paper-trading evidence.

## 3. What each permissively licensed repository actually contains

**anthropics/financial-services (Apache-2.0).** 377 files, **no tests**. The
substance is ~120 `SKILL.md` files — *prose report generators for humans*.
`earnings-analysis` produces "8–12 pages, 3,000–5,000 words, Times New Roman,
8–12 charts"; `catalyst-calendar` builds a human-readable calendar. They
contain a genuinely useful **event taxonomy** (earnings, investor day,
FDA/regulatory decisions, M&A milestones, lockup expiries, conferences, FOMC
and macro releases) and a beat/miss framing. They emit **no machine-readable
record, no publication timestamp, no known-from, no source hash and no
uncertainty**. Partner plugins (LSEG, S&P Global) require vendor credentials.

→ **Interface inspiration and controlled vocabulary only.** Not code reuse.

**AI4Finance-Foundation/FinGPT (MIT).** Sentiment models are LoRA adapters on
Llama-2-13B, loaded with `trust_remote_code=True` (a real security
implication: it executes model-repo code), 8-bit on GPU. Training data is
sentence-level financial sentiment (PhraseBank/tweet style) with **no
publication timestamps** — so the leakage risk sits entirely with the
consumer, not the model. `FinGPT_Forecaster/market_sentiment.py` calls an
undocumented third-party API (`api.adanos.org`, sources: reddit/x/news/
polymarket) with a 90-day lookback — an external dependency with unknown
terms, availability and provenance.

→ **Offline challenger feature generator, gated.** Never a signal. No code
reuse required; the useful part is the task decomposition.

**je-suis-tm/quant-trading (Apache-2.0).** 177 files, **no tests**, last
pushed 2024-04-14 (~17 months stale). Frictionless single-asset backtests.

→ **Null comparators only**, at most three, rebuilt inside APEX's cost model.

**wangzhe3224/awesome-systematic-trading (MIT).** A catalog. → **Reference
only**; never a runtime dependency; every linked project needs its own
license and quality review.

**jmfernandes/robin_stocks (MIT).** Pure Python, three brokers
(robinhood/gemini/tda), 31 modules, 4 test files, last pushed 2026-02-11.
Unofficial, endpoint-fragile, session-token authentication.

→ **Broker adapter candidate, read-only surfaces only, not connected.**

## 4. The decisive finding: APEX already has most of the proposed contract

The brief asked for an Event Intelligence contract as the likely first
component. Inspecting **APEX's own code** before writing any showed that
`apex/catalyst/events.py` already implements:

- four clocks that are never conflated — `event_time`, `published_time`,
  `first_seen`, `known_from`, with the rule that `known_from` is first_seen,
  not event_time, and a check that it cannot precede first_seen;
- source authority tiers (`PRIMARY_OFFICIAL … UNVERIFIED`) with a
  `FACT_BEARING` subset, and `source_ref` required — "news says" refused;
- a 16-value `EVENT_TYPES` vocabulary; `VERIFICATION` including `CONFLICTED`;
- dedup where the **event** is the unit and headlines attach as observations,
  so a hundred headlines cannot become a hundred observations;
- surprise fields (`expected_value/actual_value/prior_value/surprise`) whose
  expectation carries `expectation_source`, `expectation_contract_sha` and
  `expectation_known_from`, with directional expectation admissible **only**
  as `LLM_DERIVED_INTERPRETATION`;
- `mechanism_hypotheses`, `uncertainty`, and `authority = SHADOW_CONTEXT_ONLY`.

Building a second event model would have duplicated all of that and allowed
two records of the same event to disagree. Under the governing standard —
*a component earns admission only if it captures something APEX currently
lacks* — a new contract fails that test.

**What APEX genuinely lacks is the gate**: a per-record decision about
whether an event may enter research, and the checks that decision needs.
That is the implemented artifact (§5), and it is strictly additive.

## 5. Implemented: `EVENT_INTELLIGENCE_ADMISSIBILITY_V0`

`apex/catalyst/event_admissibility.py` (+ 25 tests). It reads
`CatalystEvent`, **mutates nothing**, and adds only the missing checks:

| Gap in APEX today | Now refused as |
|---|---|
| no per-source **content hash** | `SOURCE_CONTENT_UNHASHED`, `SOURCE_CONTENT_MUTATED` |
| one wire story republished counted twice | `DUPLICATE_SOURCE_CONTENT` |
| retrieval time silently used as publication time | `PUBLICATION_IS_RETRIEVAL`, `PUBLICATION_TIME_UNKNOWN` |
| no future-timestamp check in any clock | `FUTURE_TIMESTAMP` |
| `known_from` earlier than publication | `KNOWN_FROM_PRECEDES_PUBLICATION` |
| absent `known_from` | `MISSING_KNOWN_FROM` |
| no extraction provenance (model, version, prompt contract, time) | `MISSING_EXTRACTION_PROVENANCE`, `EXTRACTOR_CLAIMS_AUTHORITY` |
| unresolved or ambiguous entities | `ENTITY_NOT_RESOLVED` |
| an LLM emitting a probability | `LLM_PROBABILITY_PRESENT` (recursive scan) |
| an observation carrying direction/size/order/level | `TRADE_FIELD_PRESENT` (recursive scan) |
| no admissibility status | `ADMISSIBLE_FACT` / `ADMISSIBLE_LEAD` / `ADMISSIBLE_CONFLICTED` / refusal |

It also ships `keyword_baseline_event_type()` — the deterministic comparator
any LLM extractor must beat — and it passes through the **same** gate, so the
future comparison is between two audited records rather than one audited and
one not.

Authority: `PROBABILITY_AUTHORITY: NONE`, `TRADING_AUTHORITY: NONE`,
`ORDER_AUTHORITY: NONE`, `SIZING_AUTHORITY: NONE`,
`PRIME_INPUT: NOT_ADMITTED_BY_THIS_CONTRACT`,
`DECISION_POWER: SHADOW_CONTEXT_ONLY`. An AST test asserts the module imports
nothing from `apex.execution`, `apex.organism`, `apex.capital` or
`apex.world_model`.

## 6. What is explicitly **not** claimed

No component here has alpha. Nothing has been evaluated against an economic
court. The admissibility gate improves **research validity**, not returns: it
makes a class of event research checkable, and it refuses records that would
have been silently wrong. Whether event features carry after-cost economic
value is an open question with a designed answer (§6 of the matrix) and no
evidence.
