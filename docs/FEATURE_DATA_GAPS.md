# APEX Feature Data-Gap Report

**Date:** 2026-08-12 · grounded in actual field coverage, not assumption

Field coverage below is measured on the real as-filed SF1 ARQ records
(488,635 rows, 13,126 tickers, reportperiods 2002-12-28 → 2026-05-31). "Built"
means a factory builder exists and produced a PIT-100% feature on the in-sample
eligible universe.

---

## 1. Features we can build NOW (built, or fields present)

### Built this cycle — 14, all PIT 100.000000% compliant

| feature | fields (as-filed ARQ) | coverage | direction |
|---|---|---|---|
| prof_gross_profitability | gp, assets | 99.7% | higher |
| prof_operating_profitability | opinc, assets | 99.7% | higher |
| prof_return_on_equity | netinc, equity | 99.7% | higher |
| prof_return_on_assets | netinc, assets | 99.7% | higher |
| prof_gross_margin | gp, revenue | 99.4% | higher |
| prof_net_margin | netinc, revenue | 99.4% | higher |
| accr_total_accruals | netinc, ncfo, assets | 99.6% | lower |
| grow_asset_growth | assets (YoY) | 98.6% | lower |
| grow_sales_growth | revenue (YoY) | 97.8% | unsigned |
| val_book_to_market | equity / market cap | 100.0% | higher |
| val_earnings_yield | netinc / market cap | 99.7% | higher |
| val_sales_to_price | revenue / market cap | 99.7% | higher |
| bs_leverage | debt, assets | 100.0% | unsigned |
| cap_net_buyback_yield | ncfcommon / market cap | 99.6% | higher |

The brief's specific questions, answered against real fields:

| requested | verdict |
|---|---|
| ROE / ROA | **BUILT from raw** — vendor `roe`/`roa` are **0% populated in ARQ** (trailing dimensions only), so built from netinc/equity and netinc/assets |
| gross profitability | BUILT (gp/assets) |
| operating profitability | BUILT (opinc/assets) |
| margins | BUILT (gross, net) |
| leverage | BUILT (debt/assets) |
| asset growth | BUILT (YoY) |
| sales growth | BUILT (YoY) |
| earnings growth | **DEFERRED** — netinc is frequently negative, so a ratio is unstable; needs a sign-robust construction |
| cash-flow quality | DATA AVAILABLE — ncfo 95%, netinc 96.8%; builder pending (sign issues) |
| accruals | BUILT (netinc − ncfo)/assets |
| investment | DATA AVAILABLE — capex 95%, asset growth built as a proxy |
| payout / buyback intensity | BUILT (net buyback via ncfcommon); dividend payout DATA AVAILABLE (ncfdiv 91.8%, dps 100%) |
| valuation ratios | BUILT (book/market, earnings yield, sales/price) |

### Fields present, builder not yet written (DATA AVAILABLE)

- **Liquidity:** Amihud illiquidity, share turnover — SEP `volume`, `closeadj`,
  `closeunadj` all present. *Not built, and deliberately not motivated by
  APEX-002's post-mortem breadth observation.*
- **Cash-flow quality:** ncfo/netinc — sign handling to design.
- **Dividend payout:** ncfdiv, dps.
- **Current ratio / working capital:** assetsc, liabilitiesc, workingcapital —
  ~80% coverage (lower; many firms report unclassified balance sheets).
- **R&D intensity:** rnd (96.9% populated but only 36.2% non-zero — sector-
  concentrated, needs care).

## 2. Features requiring additional vendor fields

- **Analyst estimates / revisions** — not in this subscription. The estimate-
  revision and earnings-surprise families need an estimates feed.
- **True earnings announcement date** — SF1 gives the FILING date. A 10-Q
  follows the earnings press release, so any surprise/drift feature built on
  the filing date measures the wrong event, late. See §4.

## 3. Features requiring genuinely new datasets

- **Short interest** (positioning) — no feed present.
- **Institutional holdings / 13F** (positioning, crowding).
- **Options** (implied vol, skew, put/call).
- **News / search volume** (attention).

The entire **sentiment / attention / positioning** family (registry family 12)
is **not constructible** from this vendor. Marked DATA_GAP, lineage recorded as
absent, and no placeholder pretends otherwise.

## 4. Impossible with the current historical data

- **PEAD / earnings-announcement drift.** The event date does not exist in the
  snapshot. Registered as `evt_pead`, status **DATA_GAP**, lineage "none —
  announcement date absent". This is the honest verdict, not a deferral: the
  data cannot support the feature, so it must not be built here regardless of
  how well-documented the anomaly is.

## Contamination note

APEX-002's post-mortem found IC concentrated in high-breadth dates. That
observation appears in this document only as a warning. It did **not** motivate
any feature. The liquidity family is justified from the data architecture and
the published illiquidity-premium literature, and remains DATA_AVAILABLE and
**unbuilt** — so that if a liquidity or breadth experiment is ever registered,
its justification is independent of #002's failed result rather than selected
by it.
