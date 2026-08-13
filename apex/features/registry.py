"""The canonical feature registry. ONE FEATURE = ONE AUTHORITATIVE DEFINITION.

This is infrastructure, not an experiment. It expands the information set so
future experiments can test different economic mechanisms instead of restating
momentum. It computes no forward return, no IC, no predictive statistic, and
ranks nothing by performance.

WHY DESCRIPTORS, NOT FREE-FORM CODE
-----------------------------------
Each feature carries a machine-readable `formula` descriptor, not a hand-written
function. Two consequences:

  * the definition is the descriptor, so a feature cannot have two spellings;
  * redundancy is detectable STRUCTURALLY -- `apex.features.redundancy` compares
    descriptors, so an algebraic duplicate (num/den swap, a growth measure
    written two ways) is caught before it is ever computed. The
    f1_mom_63 / f4_vs_market identity slipped through precisely because names
    were the only check.

Descriptor kinds, all PIT-safe by construction:

  ratio        num / den from the SAME as-filed record; knowable at its filing
  log_ratio    ln(field_t / field_{t-k}); knowable at max(filed_t, filed_{t-k})
  growth       field_t / field_{t-k} - 1; same knowability as log_ratio
  valuation    fundamental(as-filed, filed<=T) / market_cap(T); knowable at the
               filing date, because market cap at T is a price, known at T
  scaled_flow  flow(as-filed) / market_cap(T); same knowability as valuation

STATUS is not a claim about alpha. A feature is FEATURE until an experiment is
registered against it; it never becomes "alpha" merely by existing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Feature lifecycle states. A feature is NOT an alpha because it exists.
FEATURE = "FEATURE"                       # a defined, computable input
DISCOVERY_CANDIDATE = "DISCOVERY_CANDIDATE"
SCREENED_CANDIDATE = "SCREENED_CANDIDATE"
REGISTERED_EXPERIMENT = "REGISTERED_EXPERIMENT"
VALIDATED_ALPHA = "VALIDATED_ALPHA"
FAILED = "FAILED"
DEPRECATED = "DEPRECATED"

# Build status -- whether the factory can produce this feature TODAY.
BUILT = "BUILT"                           # factory computes it from frozen data
DATA_AVAILABLE = "DATA_AVAILABLE"         # fields present, builder not written
DATA_GAP = "DATA_GAP"                     # requires a field/dataset we lack

HIGHER_BETTER = "higher_better"
LOWER_BETTER = "lower_better"
UNSIGNED = "unsigned"                     # no pre-registered direction


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    feature_family: str
    economic_mechanism: str
    source_fields: tuple[str, ...]
    transformation: str
    formula: dict                          # the machine-readable definition
    pit_rule: str
    frequency: str
    universe: str
    directionality: str
    limitations: str
    lineage: str
    version: str
    status: str                            # BUILT / DATA_AVAILABLE / DATA_GAP
    lifecycle: str = FEATURE

    def __post_init__(self) -> None:
        if self.status not in (BUILT, DATA_AVAILABLE, DATA_GAP):
            raise ValueError(f"{self.feature_id}: bad status {self.status!r}")
        if self.directionality not in (HIGHER_BETTER, LOWER_BETTER, UNSIGNED):
            raise ValueError(f"{self.feature_id}: bad directionality")
        kind = self.formula.get("kind")
        if kind not in ("ratio", "log_ratio", "growth", "valuation",
                        "scaled_flow", "price"):
            raise ValueError(f"{self.feature_id}: unknown formula kind {kind!r}")


_ART_ONLY = (
    "vendor computes this only in trailing dimensions (ART/MRT); it is 0% "
    "populated in the ARQ as-filed records this factory reads, so it is built "
    "from raw components rather than consumed directly"
)


def _spec(**kw) -> FeatureSpec:
    return FeatureSpec(**kw)


# ---------------------------------------------------------------------------
# THE REGISTRY. Grouped by family. `formula` is the authoritative definition.
# ---------------------------------------------------------------------------

_SPECS: tuple[FeatureSpec, ...] = (
    # --- PROFITABILITY / QUALITY -------------------------------------------
    _spec(
        feature_id="prof_gross_profitability",
        feature_family="profitability",
        economic_mechanism=(
            "Novy-Marx (2013): gross profits scaled by assets is the 'other "
            "side of value' -- profitable firms earn higher average returns, "
            "and gross profit is the cleanest profitability line, least "
            "polluted by discretionary items below it."
        ),
        source_fields=("gp", "assets"),
        transformation="gp / assets",
        formula={"kind": "ratio", "num": "gp", "den": "assets"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations="gp 96.9% populated; financials have weak gross-profit meaning",
        lineage="SF1.ARQ.gp, SF1.ARQ.assets",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="prof_operating_profitability",
        feature_family="profitability",
        economic_mechanism=(
            "Fama-French (2015) RMW: operating profitability scaled by assets. "
            "Operating income strips financing and one-offs above net income."
        ),
        source_fields=("opinc", "assets"),
        transformation="opinc / assets",
        formula={"kind": "ratio", "num": "opinc", "den": "assets"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations="opinc 96.9% populated",
        lineage="SF1.ARQ.opinc, SF1.ARQ.assets",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="prof_return_on_equity",
        feature_family="profitability",
        economic_mechanism=(
            "Return on equity: profitability relative to book capital. A "
            "quality proxy; persistent high ROE indicates a durable franchise."
        ),
        source_fields=("netinc", "equity"),
        transformation="netinc / equity",
        formula={"kind": "ratio", "num": "netinc", "den": "equity"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations=(
            f"vendor 'roe' field is unusable ({_ART_ONLY}); built from "
            "netinc/equity. Negative or near-zero equity makes the ratio "
            "explode -- a documented tail, not a bug"
        ),
        lineage="SF1.ARQ.netinc, SF1.ARQ.equity (NOT vendor roe)",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="prof_return_on_assets",
        feature_family="profitability",
        economic_mechanism="Return on assets: profitability per unit of assets.",
        source_fields=("netinc", "assets"),
        transformation="netinc / assets",
        formula={"kind": "ratio", "num": "netinc", "den": "assets"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations=f"vendor 'roa' field unusable ({_ART_ONLY}); built from raw",
        lineage="SF1.ARQ.netinc, SF1.ARQ.assets (NOT vendor roa)",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="prof_gross_margin",
        feature_family="profitability",
        economic_mechanism="Gross margin: pricing power and cost structure.",
        source_fields=("gp", "revenue"),
        transformation="gp / revenue",
        formula={"kind": "ratio", "num": "gp", "den": "revenue"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations="undefined for zero-revenue firms; excluded where revenue<=0",
        lineage="SF1.ARQ.gp, SF1.ARQ.revenue",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="prof_net_margin",
        feature_family="profitability",
        economic_mechanism="Net margin: bottom-line profitability per sales dollar.",
        source_fields=("netinc", "revenue"),
        transformation="netinc / revenue",
        formula={"kind": "ratio", "num": "netinc", "den": "revenue"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations="undefined for zero-revenue firms",
        lineage="SF1.ARQ.netinc, SF1.ARQ.revenue",
        version="1.0.0",
        status=BUILT,
    ),

    # --- ACCRUALS / EARNINGS QUALITY ---------------------------------------
    _spec(
        feature_id="accr_total_accruals",
        feature_family="accruals",
        economic_mechanism=(
            "Sloan (1996): the accrual anomaly. Earnings not backed by cash "
            "flow are less persistent, and the market overweights them, so "
            "high-accrual firms subsequently underperform."
        ),
        source_fields=("netinc", "ncfo", "assets"),
        transformation="(netinc - ncfo) / assets",
        formula={"kind": "ratio", "num": "netinc", "num2": "ncfo",
                 "num_op": "subtract", "den": "assets"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=LOWER_BETTER,
        limitations="ncfo 95% populated; both from the same as-filed record",
        lineage="SF1.ARQ.netinc, SF1.ARQ.ncfo, SF1.ARQ.assets",
        version="1.0.0",
        status=BUILT,
    ),

    # --- GROWTH / INVESTMENT -----------------------------------------------
    _spec(
        feature_id="grow_asset_growth",
        feature_family="growth",
        economic_mechanism=(
            "Cooper-Gulen-Schill (2008): the asset growth effect. Firms that "
            "expand their asset base aggressively subsequently underperform, "
            "consistent with over-investment and empire-building."
        ),
        source_fields=("assets",),
        transformation="assets_t / assets_{t-4q} - 1",
        formula={"kind": "growth", "field": "assets", "quarters": 4},
        pit_rule="both endpoints filed by T; knowable at max(filed_t, filed_{t-4q})",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=LOWER_BETTER,
        limitations="needs >=5 quarters of as-filed history; thin in early years",
        lineage="SF1.ARQ.assets (two observations ~12 months apart)",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="grow_sales_growth",
        feature_family="growth",
        economic_mechanism=(
            "Sales growth as a fundamental-momentum proxy, and its extremes as "
            "an over-extrapolation proxy. Sign is genuinely ambiguous a priori."
        ),
        source_fields=("revenue",),
        transformation="revenue_t / revenue_{t-4q} - 1",
        formula={"kind": "growth", "field": "revenue", "quarters": 4},
        pit_rule="both endpoints filed by T; knowable at max(filed_t, filed_{t-4q})",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=UNSIGNED,
        limitations="undefined where base revenue<=0",
        lineage="SF1.ARQ.revenue (two observations ~12 months apart)",
        version="1.0.0",
        status=BUILT,
    ),

    # --- VALUATION ---------------------------------------------------------
    _spec(
        feature_id="val_book_to_market",
        feature_family="valuation",
        economic_mechanism=(
            "The value effect (Fama-French HML). Book equity relative to market "
            "capitalisation; high book-to-market ('cheap') firms have earned a "
            "premium. Built as as-filed book equity over point-in-time market "
            "cap, so no restated book value enters."
        ),
        source_fields=("equity", "marketcap"),
        transformation="equity(as-filed) / marketcap(T)",
        formula={"kind": "valuation", "num": "equity"},
        pit_rule=(
            "book equity from earliest filing with date<=T; market cap is the "
            "value AT T (a price, knowable at T); knowable at the filing date"
        ),
        frequency="daily (fundamental refreshes on filing)",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations="negative book equity yields a negative ratio; a real tail",
        lineage="SF1.ARQ.equity (as-filed) / panel market cap (point-in-time)",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="val_earnings_yield",
        feature_family="valuation",
        economic_mechanism=(
            "Earnings yield: as-filed quarterly net income over point-in-time "
            "market cap. The earnings analogue of book-to-market."
        ),
        source_fields=("netinc", "marketcap"),
        transformation="netinc(as-filed) / marketcap(T)",
        formula={"kind": "valuation", "num": "netinc"},
        pit_rule="net income from earliest filing with date<=T; market cap at T",
        frequency="daily (fundamental refreshes on filing)",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations=(
            "single-quarter earnings are seasonal and noisy; a trailing-four "
            "sum would be steadier but needs four filed quarters -- deferred"
        ),
        lineage="SF1.ARQ.netinc (as-filed) / panel market cap",
        version="1.0.0",
        status=BUILT,
    ),
    _spec(
        feature_id="val_sales_to_price",
        feature_family="valuation",
        economic_mechanism=(
            "Sales-to-price: robust to the accounting choices that distort "
            "earnings- and book-based value measures (Barbee et al.)."
        ),
        source_fields=("revenue", "marketcap"),
        transformation="revenue(as-filed) / marketcap(T)",
        formula={"kind": "valuation", "num": "revenue"},
        pit_rule="revenue from earliest filing with date<=T; market cap at T",
        frequency="daily (fundamental refreshes on filing)",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations="single-quarter revenue is seasonal",
        lineage="SF1.ARQ.revenue (as-filed) / panel market cap",
        version="1.0.0",
        status=BUILT,
    ),

    # --- LEVERAGE / BALANCE SHEET ------------------------------------------
    _spec(
        feature_id="bs_leverage",
        feature_family="balance_sheet",
        economic_mechanism=(
            "Book leverage: total debt relative to assets. A risk and "
            "financial-distress characteristic; its return relation is regime "
            "dependent, hence unsigned here."
        ),
        source_fields=("debt", "assets"),
        transformation="debt / assets",
        formula={"kind": "ratio", "num": "debt", "den": "assets"},
        pit_rule="earliest filing per (ticker, reportperiod); admit where date<=T",
        frequency="quarterly, broadcast to daily by filing date",
        universe="frozen section 3 eligible",
        directionality=UNSIGNED,
        limitations="debt 100% populated but 84.8% non-zero",
        lineage="SF1.ARQ.debt, SF1.ARQ.assets",
        version="1.0.0",
        status=BUILT,
    ),

    # --- CAPITAL ALLOCATION (beyond NSI) -----------------------------------
    _spec(
        feature_id="cap_net_buyback_yield",
        feature_family="capital_allocation",
        economic_mechanism=(
            "Net equity payout via the financing cash flow: negative "
            "ncfcommon is net repurchase. A cash-flow-based complement to "
            "NSI's share-count measure -- ADJACENT to APEX-002, see limitation."
        ),
        source_fields=("ncfcommon", "marketcap"),
        transformation="-ncfcommon(as-filed) / marketcap(T)",
        formula={"kind": "scaled_flow", "num": "ncfcommon", "sign": -1},
        pit_rule="ncfcommon from earliest filing with date<=T; market cap at T",
        frequency="daily (fundamental refreshes on filing)",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations=(
            "ncfcommon nets issuance and repurchase and includes option "
            "exercise; ADJACENT to APEX-002 NSI -- any experiment must justify "
            "it as a distinct mechanism, not NSI with a cash-flow numerator"
        ),
        lineage="SF1.ARQ.ncfcommon (as-filed) / panel market cap",
        version="1.0.0",
        status=BUILT,
    ),

    # --- LIQUIDITY (declared, not yet built) -------------------------------
    _spec(
        feature_id="liq_amihud_illiquidity",
        feature_family="liquidity",
        economic_mechanism=(
            "Amihud (2002): |return| per dollar of volume, the price impact of "
            "trading. An illiquidity premium and a distinct market-structure "
            "mechanism. NOTE: any liquidity work must be justified from this "
            "architecture, NOT from APEX-002's post-mortem breadth observation."
        ),
        source_fields=("close_adj", "volume", "close_unadj"),
        transformation="mean(|daily return| / (volume * close)) over a window",
        formula={"kind": "price", "op": "amihud"},
        pit_rule="all inputs are prices/volumes known at T; no filing lag",
        frequency="daily",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations="builder not yet written; SEP volume + price present",
        lineage="SEP.volume, SEP.closeadj, SEP.closeunadj",
        version="0.1.0",
        status=DATA_AVAILABLE,
    ),
    _spec(
        feature_id="liq_turnover",
        feature_family="liquidity",
        economic_mechanism=(
            "Share turnover: dollar volume relative to market cap, a trading-"
            "intensity and attention proxy."
        ),
        source_fields=("volume", "close_unadj", "sharesbas"),
        transformation="volume / shares outstanding, averaged over a window",
        formula={"kind": "price", "op": "turnover"},
        pit_rule="volume and shares known at T",
        frequency="daily",
        universe="frozen section 3 eligible",
        directionality=UNSIGNED,
        limitations="builder not yet written",
        lineage="SEP.volume, DAILY-derived shares",
        version="0.1.0",
        status=DATA_AVAILABLE,
    ),

    # --- EVENT / UNDERREACTION (DATA GAP) ----------------------------------
    _spec(
        feature_id="evt_pead",
        feature_family="event",
        economic_mechanism=(
            "Post-earnings-announcement drift: prices underreact to earnings "
            "surprises and drift in the surprise direction for weeks."
        ),
        source_fields=("earnings_announcement_date",),
        transformation="cumulative abnormal return after the announcement",
        formula={"kind": "price", "op": "pead"},
        pit_rule="requires the true announcement date, which the vendor lacks",
        frequency="event",
        universe="frozen section 3 eligible",
        directionality=HIGHER_BETTER,
        limitations=(
            "DATA GAP. SF1 provides the FILING date, and a 10-Q follows the "
            "earnings press release, so drift measured from the filing starts "
            "late and from the wrong event. Not constructible from this vendor."
        ),
        lineage="none -- announcement date absent",
        version="0.0.0",
        status=DATA_GAP,
    ),

    # --- SENTIMENT / ATTENTION / POSITIONING (DATA GAP) --------------------
    _spec(
        feature_id="pos_short_interest",
        feature_family="positioning",
        economic_mechanism=(
            "Short interest as informed negative sentiment; heavily shorted "
            "firms subsequently underperform."
        ),
        source_fields=("short_interest",),
        transformation="short interest / shares outstanding",
        formula={"kind": "price", "op": "short_ratio"},
        pit_rule="requires a short-interest feed the vendor does not provide",
        frequency="biweekly",
        universe="frozen section 3 eligible",
        directionality=LOWER_BETTER,
        limitations=(
            "DATA GAP. No short interest, 13F, options, analyst estimates or "
            "news in this snapshot. The entire positioning/attention family is "
            "not constructible without a new dataset."
        ),
        lineage="none -- dataset absent",
        version="0.0.0",
        status=DATA_GAP,
    ),
)

FEATURE_REGISTRY: dict[str, FeatureSpec] = {s.feature_id: s for s in _SPECS}


def specs_by_status(status: str) -> tuple[FeatureSpec, ...]:
    return tuple(s for s in _SPECS if s.status == status)


def built_specs() -> tuple[FeatureSpec, ...]:
    return specs_by_status(BUILT)


def families() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in _SPECS:
        out.setdefault(s.feature_family, []).append(s.feature_id)
    return out
