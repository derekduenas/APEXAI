# DATA_LIMITATIONS.md

## The SEC EDGAR + Stooq development stack — what it cannot establish

**Status:** DEVELOPMENT ONLY. NON-CONFIRMATORY.
**Written:** 2026-08-10, **before** the adapters were implemented.
**Governs:** `apex/data/edgar.py`, `apex/data/stooq.py`, `apex/dev/`

This document exists so that no result produced from this dataset can later be
mistaken for evidence about Experiment #001. Every limitation below is a reason
this stack is **disqualified as the confirmatory dataset**, and none of them is
a defect to be fixed — they are properties of free data.

Observations marked **[measured]** were verified against the live sources on
2026-08-10. Everything else is stated as the open question it is.

---

## 0. The one-line version

This stack can show that APEX **ingests and processes real-world equity data
without breaking its own rules**. It cannot show anything whatsoever about
whether the APEX Score predicts returns. A positive information coefficient
computed on this data is **meaningless** and must never be reported as a
finding.

---

## 1. Delisted-security coverage — INCOMPLETE

**Effect on the protocol:** fatal for §3's survivorship requirement.

Protocol §3 requires that "the universe must include securities that were later
delisted, acquired, or removed from indices," and states plainly that "a
universe constructed from a current list of tickers is invalid and must not be
used, even provisionally."

- SEC EDGAR **does** carry delisting events: Form 25 / 25-NSE notifications, and
  each issuer's full filing history with dates. **[measured]** `submissions`
  returns every filing with `form` and `filingDate`.
- SEC EDGAR **does** retain issuers after they stop trading — a CIK is never
  recycled or deleted.
- Stooq's coverage of delisted tickers is **undocumented and unverified**. The
  vendor publishes no delisted-security policy. Names that stopped trading may
  simply be absent from the archive.

**Consequence:** the development universe is survivorship-contaminated to an
**unknown and unmeasurable degree**. We can count the delistings we *found*;
we cannot count the ones that are missing. That asymmetry is precisely why this
dataset cannot support an inference about returns.

### 1a. Form 25 does NOT mean the issuer was delisted **[measured 2026-08-10]**

Discovered on real data while building the adapter, and worth stating loudly
because it would have silently corrupted the universe:

> A Form 25 delists a **security**, not an **issuer**.

Apple has filed a Form 25 (delisting a class of notes) and is plainly still
listed. A naive "issuer filed Form 25 → issuer delisted on that date" rule
marked **AAPL as delisted on 2019-03-14**. Centrus Energy, which reorganised and
still trades, was likewise mislabelled.

The adapter therefore requires **corroboration** — a Form 25 **and** no current
exchange **and** no current ticker — and reports its evidence per issuer. Where
a Form 25 exists but the issuer is still listed, that is recorded explicitly
rather than silently dropped.

Residual limitation: corroboration relies on *current* listing status, so an
issuer that delisted and later relisted may still be misclassified. There is no
clean fix within this stack.

### 1b. Delisting REASON is unavailable — every delisting takes the haircut

CONVENTIONS §1 and ruling B4 distinguish **performance-related** delistings
(which take the Shumway −30% terminal haircut) from **M&A / voluntary** ones
(which use the final traded price). **EDGAR does not carry the reason.** Form 25
states that a security was removed, not why.

The pre-registered fallback therefore applies to *every* delisting in the
development set: "treat any delisting not affirmatively identifiable as M&A or
voluntary as performance-related." So **100% of dev delistings receive −30%**,
including genuine acquisitions at a premium.

This is the conservative direction and it is the pre-registered rule, so the
code is correct. But it means development delisting returns are **systematically
too negative** and carry no information about real delisting economics.

**Not mitigated by:** anything. Do not attempt to patch the gap by
reconstructing prices for missing names.

---

## 2. Corporate actions — PARTIAL, AND UNVERIFIABLE

**Effect on the protocol:** §4 requires splits, dividends, spin-offs, delisting
dates and reasons.

- Stooq **omits adjusted-close fields entirely**. Only raw OHLCV is available.
  The pipeline's ratio quantities (returns, SMA ratios, volatility ratios,
  ATR/Close) assume a total-return-adjusted series; on Stooq they will be
  computed on an unadjusted or split-only-adjusted series.
- **This is a real distortion, not a cosmetic one.** An unadjusted series shows
  a 2-for-1 split as a −50% one-day return. F1 momentum, F3 volatility and F4
  relative strength will all register that as a genuine price move.
- SEC EDGAR carries corporate *events* (8-K, Form 25) but **not** split ratios
  or dividend amounts in a usable structured price-adjustment form.
- No dividend data is available in this stack at all, so no total-return series
  can be constructed.

**Consequence:** feature values on this dataset are **contaminated by
unadjusted corporate actions**. The pipeline will run; the numbers are not
economically meaningful.

**Disclosure requirement:** every development report must state whether the
price series it used was adjusted, and how.

---

## 3. Historical OHLCV gaps — UNKNOWN EXTENT

- Stooq depth varies by security; some US names go back 30+ years, others far
  less. Coverage is not uniform and is not documented per name.
- Halts, thin trading and vendor gaps are not distinguished from each other.
  The pipeline treats a missing bar as a missing bar (correctly — it never
  forward-fills), but we cannot tell a genuine non-trading day from a vendor
  omission.
- Stooq provides **volume**, but its consolidated-tape completeness is not
  documented. §3's `$10M ADDV` filter is therefore computed on volume of
  **unverified completeness**.

**Consequence:** universe membership on this dataset is approximate. Report
universe counts, but do not treat them as the counts Experiment #001 would see.

---

## 4. Sector classification — PROXY ONLY, AND NOT POINT-IN-TIME

**Effect on the protocol:** F4a is defined as the security's return minus its
sector's return, and C2/C3 govern the taxonomy.

- CONVENTIONS C3 specifies **Sharadar `TICKERS.sector`**. This stack does not
  have it.
- SEC EDGAR provides **SIC codes** **[measured]** (`sic: 3571`,
  `sicDescription: 'Electronic Computers'`). SIC is a different taxonomy with
  different granularity, and mapping SIC to a Sharadar-like sector is a
  judgement call, not a fact.
- The SIC code returned by `submissions` is the issuer's **current** code. It is
  **not point-in-time**. Reclassifications are invisible.

**Consequence:** F4a on this dataset measures something related to, but not the
same as, what the protocol specifies. Using it here is acceptable **only**
because the purpose is to exercise the code path, not to measure the factor.

---

## 5. Identity matching — REAL UNCERTAINTY, DELIBERATELY NOT RESOLVED BY GUESSING

**Effect on the protocol:** `contracts.py` structurally bans joining securities
by ticker, because tickers are recycled.

- SEC EDGAR's **CIK is a genuine permanent identifier** — stable across ticker
  changes, renames and delisting. **[measured]** `formerNames` even carries
  dated historical name changes.
- Stooq is keyed by **ticker only**. It has no permanent identifier.
- The join between them is therefore **ticker-based**, which is the exact
  operation the production architecture forbids.
- `company_tickers.json` **[measured: 10,398 entries]** is a **current** map. It
  cannot resolve a ticker that belonged to a different issuer historically.

**Consequence:** every Stooq→CIK match is a *hypothesis*. The development
adapter routes these through the existing `apex/data/identity.py` crosswalk,
which requires overlapping active windows and refuses ambiguity rather than
breaking ties. Unresolvable names are **excluded and counted**, never guessed.

The residual risk that remains even after that: a ticker whose only EDGAR match
is the *wrong*, later issuer, where windows happen to overlap. We cannot rule
this out without a historical ticker→CIK map, which this stack does not have.

---

## 6. Point-in-time capability — PARTIAL, AND BETTER THAN EXPECTED IN ONE PLACE

- **Shares outstanding ARE point-in-time.** **[measured]** The XBRL
  `companyconcept` endpoint returns each observation with a `filed` date:
  `{'end': '2009-06-27', 'val': 895816758, 'accn': '0001193125-09-153165',
  'form': '10-Q', 'filed': '2009-07-22'}`. Using `filed` (not `end`) as the
  knowledge date gives a genuinely point-in-time share count. This is the one
  place where the free stack is *architecturally* correct.
- **BUT** coverage begins with XBRL adoption — roughly 2009 for large filers,
  later for smaller ones. Before that there is **no** structured shares-
  outstanding data. Market cap is therefore **unavailable**, not approximate,
  for the early part of the protocol's 2004+ lake.
- Prices are not point-in-time in any meaningful sense: Stooq publishes a
  current view of history with no vintage information.

**Consequence:** the `$1B` market-cap filter can only be evaluated where XBRL
shares exist. Everywhere else the security-date is **excluded and reported**
via the existing `pit_market_cap` filter. It is never backfilled.

---

## 7. Licensing and access restrictions

| Source | Licence | Access |
|---|---|---|
| SEC EDGAR | **Public domain** (US Government work). No restriction. | Free API, no key. Fair-access policy requires a descriptive User-Agent with contact details, which the adapter sets. |
| Stooq | **Personal / non-commercial use only.** | **[measured 2026-08-10]** Both the bulk archive and the per-symbol CSV endpoint are behind a JavaScript proof-of-work bot challenge. |

**We do not bypass the Stooq challenge.** Solving a bot-detection mechanism
programmatically is out of bounds regardless of purpose. Stooq price data must
be downloaded **manually in a browser** by the operator and placed on disk; the
adapter reads only local files and never contacts stooq.com.

**Redistribution:** the raw Stooq artifacts are personal-use only and are **not
committed** to the repository. Only their SHA-256 hashes and row counts enter
the development manifest.

---

## 8. What this stack CAN legitimately demonstrate

Listed so the development run has an honest success criterion:

1. The adapters read real vendor files with real dtypes, encodings and nulls.
2. Security identity resolves through a permanent identifier (CIK), with real
   ambiguity excluded and counted rather than guessed.
3. Point-in-time shares outstanding are consumed using **filing dates**, and
   security-dates lacking them are excluded through the production filter.
4. Universe construction runs against real, non-uniform distributions.
5. F1–F4 and the composite compute over real price paths with real gaps.
6. Forward returns and the delisting paths fire on real events.
7. **The lookahead auditor and the cross-sectional auditor hold on real data.**
8. Reports generate end to end.
9. The system scales beyond the synthetic rig.

Item 7 is the single most valuable thing this dataset buys.

---

## 9. What this stack CANNOT demonstrate — ever

1. **Anything about the signal.** Not IC, not its sign, not decile spread, not
   monotonicity. The composite is computed on unadjusted, survivorship-
   contaminated prices.
2. That the universe matches §3.
3. That corporate actions are handled correctly *in economic terms* — only that
   the code paths execute.
4. That the sector-relative feature measures what CONVENTIONS C3 specifies.
5. That Experiment #001 will pass, fail, or be inconclusive.
6. Cost or turnover realism.

---

## 10. Enforcement

These are not honour-system rules. The development path is separated in code:

- development datasets carry a `dev-` fingerprint prefix;
- `apex/evaluate/verdict.py` **refuses** to produce a verdict for one;
- `apex/governance/ledger.py` **refuses** to record one;
- the holdout gate **refuses** to open for one;
- every development report is stamped `DEVELOPMENT / NON-CONFIRMATORY`.

A development result cannot become a confirmatory one by accident, by
misreading, or by a later operator who has not read this file.
