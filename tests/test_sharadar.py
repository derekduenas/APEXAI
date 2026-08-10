"""The Sharadar snapshot adapter -- primary and authoritative (CONVENTIONS A-002).

WHY A SNAPSHOT AND NOT AN API CALL

Section 31 requires every result to be traceable to a data snapshot. A live API
cannot deliver that: the vendor restates, backfills and corrects, so two runs a
week apart against "the same" endpoint are two different datasets and neither is
reproducible. The adapter therefore reads a FROZEN local bulk export and hashes
every file into a manifest that is stamped on the run.

THE FAILURE MODE THIS FILE EXISTS TO PREVENT

Sharadar recycles tickers, exactly as every other vendor does. SEP and DAILY are
keyed by (ticker, date); TICKERS carries the stable `permaticker` plus the
window each ticker was active. Joining SEP to TICKERS on ticker ALONE would
staple one company's prices onto another company's identity, which is the
survivorship contamination `contracts.py` bans. Every join here is date-aware,
and any (ticker, date) that resolves to zero or to more than one permaticker is
EXCLUDED and REPORTED rather than guessed.

SCHEMA ASSUMPTIONS ARE CHECKED, NOT TRUSTED

This adapter was written without live vendor access. Every column it expects and
every unit it assumes -- notably that `DAILY.marketcap` is denominated in USD
millions -- is declared explicitly and validated on load. A snapshot that does
not match produces a loud, specific error naming the discrepancy. It must never
produce quietly wrong numbers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.data.sharadar import (
    ExclusionReason,
    SchemaError,
    SharadarSnapshot,
    UnitSanityError,
)

DATES = pd.bdate_range("2020-01-01", periods=30)


# ---------------------------------------------------------------------------
# fixture snapshot
# ---------------------------------------------------------------------------


def _write(root, name, rows, columns):
    pd.DataFrame(rows, columns=columns).to_csv(root / name, index=False)


def write_snapshot(
    root,
    *,
    tickers=None,
    sep=None,
    daily=None,
    actions=None,
    include_benchmark=True,
):
    """A minimal but schema-complete Sharadar bulk export."""
    root.mkdir(parents=True, exist_ok=True)

    tickers = tickers if tickers is not None else [
        _ticker_row(199001, "AAA", first=DATES[0], last=DATES[-1]),
        _ticker_row(199002, "BBB", first=DATES[0], last=DATES[-1]),
    ]
    if include_benchmark:
        tickers = tickers + [
            _ticker_row(
                900001, "SPY", first=DATES[0], last=DATES[-1],
                category="Domestic ETF", exchange="NYSEARCA",
            )
        ]

    if sep is None:
        sep = []
        for tkr in [t["ticker"] for t in tickers]:
            for i, date in enumerate(DATES):
                sep.append(_sep_row(tkr, date, 100.0 + i))
    if daily is None:
        daily = []
        for tkr in [t["ticker"] for t in tickers]:
            for date in DATES:
                daily.append(_daily_row(tkr, date, marketcap=5000.0))  # $5,000m = $5B
    actions = actions if actions is not None else []

    # The benchmark is fixture infrastructure, not the subject of any test here.
    # A test that supplies its own SEP rows still needs SPY to exist, or it fails
    # for a reason unrelated to what it is asserting.
    if include_benchmark and not any(r["ticker"] == "SPY" for r in sep):
        sep = sep + [_sep_row("SPY", d, 300.0) for d in DATES]
    if include_benchmark and not any(r["ticker"] == "SPY" for r in daily):
        daily = daily + [_daily_row("SPY", d, 5000.0) for d in DATES]

    _write(root, "TICKERS.csv", tickers, list(_ticker_row(0, "X").keys()))
    _write(root, "SEP.csv", sep, list(_sep_row("X", DATES[0], 1.0).keys()))
    _write(root, "DAILY.csv", daily, list(_daily_row("X", DATES[0], 1.0).keys()))
    _write(root, "ACTIONS.csv", actions, list(_action_row(DATES[0], "x", "X").keys()))
    pd.DataFrame(
        {"date": DATES, "close": [20.0] * len(DATES)}
    ).to_csv(root / "VIX.csv", index=False)
    return root


def _ticker_row(permaticker, ticker, *, first=None, last=None,
                category="Domestic Common Stock", exchange="NYSE",
                isdelisted="N", sector="Technology"):
    return {
        "table": "SEP",
        "permaticker": permaticker,
        "ticker": ticker,
        "name": f"{ticker} Inc",
        "exchange": exchange,
        "isdelisted": isdelisted,
        "category": category,
        "sector": sector,
        "firstpricedate": (first or DATES[0]).strftime("%Y-%m-%d"),
        "lastpricedate": (last or DATES[-1]).strftime("%Y-%m-%d"),
    }


def _sep_row(ticker, date, close, volume=5e6):
    return {
        "ticker": ticker,
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": volume,
        "closeadj": close, "closeunadj": close,
        "lastupdated": "2026-06-30",
    }


def _daily_row(ticker, date, marketcap):
    return {
        "ticker": ticker,
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "lastupdated": "2026-06-30",
        "ev": marketcap, "evebit": 10.0, "evebitda": 8.0,
        "marketcap": marketcap, "pb": 3.0, "pe": 20.0, "ps": 4.0,
    }


def _action_row(date, action, ticker, contraticker=""):
    return {
        "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "action": action, "ticker": ticker, "name": f"{ticker} Inc",
        "value": "", "contraticker": contraticker, "contraname": "",
    }


@pytest.fixture(scope="module")
def config():
    return load_config("experiment", "costs", "synthetic", "sharadar")


@pytest.fixture
def snapshot(tmp_path, config):
    return SharadarSnapshot(write_snapshot(tmp_path / "snap"), config)


# ---------------------------------------------------------------------------
# SNAPSHOT AND LINEAGE
# ---------------------------------------------------------------------------


def test_the_snapshot_is_hashed_for_lineage(snapshot):
    """Section 31: every result traces to a data snapshot."""
    manifest = snapshot.manifest

    assert len(manifest.digest) == 64
    for name in ("TICKERS.csv", "SEP.csv", "DAILY.csv", "ACTIONS.csv"):
        assert name in manifest.files
    assert manifest.row_counts["SEP.csv"] > 0


def test_the_digest_changes_when_the_data_changes(tmp_path, config):
    first = SharadarSnapshot(write_snapshot(tmp_path / "a"), config).manifest.digest

    root = write_snapshot(tmp_path / "b")
    frame = pd.read_csv(root / "SEP.csv")
    frame.loc[0, "close"] = 999.0
    frame.to_csv(root / "SEP.csv", index=False)
    second = SharadarSnapshot(root, config).manifest.digest

    assert first != second


def test_the_adapter_requires_a_signed_registration(snapshot):
    """Real vendor data, unlike the synthetic rig."""
    assert snapshot.requires_signed_registration is True


def test_a_missing_column_is_a_loud_error_naming_it(tmp_path, config):
    root = write_snapshot(tmp_path / "snap")
    frame = pd.read_csv(root / "DAILY.csv").drop(columns=["marketcap"])
    frame.to_csv(root / "DAILY.csv", index=False)

    with pytest.raises(SchemaError) as excinfo:
        SharadarSnapshot(root, config).load()
    assert "marketcap" in str(excinfo.value)


def test_a_missing_table_is_a_loud_error(tmp_path, config):
    root = write_snapshot(tmp_path / "snap")
    (root / "DAILY.csv").unlink()

    with pytest.raises(SchemaError) as excinfo:
        SharadarSnapshot(root, config)
    assert "DAILY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# TICKER RECYCLING -- the reason every join here is date-aware
# ---------------------------------------------------------------------------


def test_a_recycled_ticker_resolves_to_the_right_company_on_each_date(tmp_path, config):
    """Two companies share 'RCY' in disjoint windows. Neither may absorb the other."""
    early_last, late_first = DATES[9], DATES[10]
    tickers = [
        _ticker_row(500001, "RCY", first=DATES[0], last=early_last),
        _ticker_row(500002, "RCY", first=late_first, last=DATES[-1]),
    ]
    sep, daily = [], []
    for i, date in enumerate(DATES):
        price = 10.0 if date <= early_last else 900.0
        sep.append(_sep_row("RCY", date, price))
        daily.append(_daily_row("RCY", date, marketcap=5000.0))

    root = write_snapshot(
        tmp_path / "snap", tickers=tickers, sep=sep, daily=daily, include_benchmark=True
    )
    panel = SharadarSnapshot(root, config).load()

    first, second = "500001", "500002"
    assert first in panel.securities and second in panel.securities

    # The early company must carry only the early prices, and vice versa.
    assert panel.close_adj.loc[DATES[0], first] == pytest.approx(10.0)
    assert np.isnan(panel.close_adj.loc[DATES[-1], first]), (
        "the pre-2020-02 company is carrying prices from the company that took "
        "its ticker afterwards -- a ticker join, and survivorship contamination"
    )
    assert panel.close_adj.loc[DATES[-1], second] == pytest.approx(900.0)
    assert np.isnan(panel.close_adj.loc[DATES[0], second])


def test_the_security_id_is_the_permaticker_not_the_ticker(snapshot):
    """contracts.py rejects a panel whose security_id equals its ticker."""
    panel = snapshot.load()

    assert "AAA" not in set(panel.securities)
    assert "199001" in set(panel.securities)
    assert panel.meta.loc["199001", "ticker"] == "AAA"


def test_an_ambiguous_ticker_date_is_excluded_and_reported(tmp_path, config):
    """Overlapping active windows for one ticker: identity is not guessable."""
    tickers = [
        _ticker_row(600001, "AMB", first=DATES[0], last=DATES[-1]),
        _ticker_row(600002, "AMB", first=DATES[0], last=DATES[-1]),
    ]
    sep = [_sep_row("AMB", d, 50.0) for d in DATES]
    daily = [_daily_row("AMB", d, 5000.0) for d in DATES]

    source = SharadarSnapshot(
        write_snapshot(tmp_path / "snap", tickers=tickers, sep=sep, daily=daily), config
    )
    source.load()
    report = source.exclusions()

    assert report.by_reason[ExclusionReason.AMBIGUOUS_IDENTITY.value] > 0
    assert "AMB" in report.tickers_excluded


# ---------------------------------------------------------------------------
# PIT MARKET CAP
# ---------------------------------------------------------------------------


def test_market_cap_units_are_converted_from_millions(snapshot, config):
    """A $5,000m DAILY figure is a $5B company, not a $5,000 one."""
    panel = snapshot.load()

    cap = panel.market_cap.loc[DATES[-1], "199001"]
    assert cap == pytest.approx(5e9, rel=1e-6)
    assert cap >= float(config.get("universe.min_market_cap_usd"))


def test_an_implausible_market_cap_scale_fails_loudly(tmp_path, config):
    """The unit assumption is checked, never trusted.

    If Sharadar ever reports whole dollars rather than millions, the $1B filter
    would silently admit nothing. That must be an error, not an empty universe.
    """
    daily = [_daily_row(t, d, marketcap=2.0e-6) for t in ("AAA", "BBB", "SPY") for d in DATES]
    root = write_snapshot(tmp_path / "snap", daily=daily)

    with pytest.raises(UnitSanityError) as excinfo:
        SharadarSnapshot(root, config).load()
    assert "marketcap" in str(excinfo.value).lower()


def test_a_security_date_with_no_daily_row_has_no_market_cap(tmp_path, config):
    """The hard rule: excluded and reported, never filled."""
    daily = [
        _daily_row(t, d, 5000.0)
        for t in ("AAA", "BBB", "SPY")
        for d in DATES
        if not (t == "AAA" and d in set(DATES[5:10]))
    ]
    source = SharadarSnapshot(write_snapshot(tmp_path / "snap", daily=daily), config)
    panel = source.load()

    gap = panel.shares_out.loc[DATES[5:10], "199001"]
    assert gap.isna().all(), (
        "a security-date with no PIT market cap was filled rather than excluded"
    )
    assert source.exclusions().by_reason[ExclusionReason.NO_PIT_MARKET_CAP.value] == 5


def test_market_cap_is_never_forward_filled(tmp_path, config):
    """A stale figure carried forward is not a point-in-time figure."""
    daily = [
        _daily_row(t, d, 5000.0)
        for t in ("AAA", "BBB", "SPY")
        for d in DATES
        if not (t == "AAA" and d > DATES[20])
    ]
    panel = SharadarSnapshot(write_snapshot(tmp_path / "snap", daily=daily), config).load()

    assert panel.shares_out.loc[DATES[25], "199001"] != panel.shares_out.loc[DATES[20], "199001"]
    assert np.isnan(panel.shares_out.loc[DATES[25], "199001"])


# ---------------------------------------------------------------------------
# CATEGORY, EXCHANGE, SURVIVORSHIP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    ["Domestic Common Stock Primary Class", "Domestic Common Stock Secondary Class"],
)
def test_common_stock_variants_are_admitted(tmp_path, config, category):
    tickers = [_ticker_row(700001, "CCC", category=category)]
    sep = [_sep_row("CCC", d, 50.0) for d in DATES]
    daily = [_daily_row("CCC", d, 5000.0) for d in DATES]

    panel = SharadarSnapshot(
        write_snapshot(tmp_path / "s", tickers=tickers, sep=sep, daily=daily), config
    ).load()

    assert panel.meta.loc["700001", "security_type"] == "common"


@pytest.mark.parametrize(
    "category",
    ["Domestic ETF", "ADR Common Stock", "Domestic Preferred Stock", "Canadian Common Stock"],
)
def test_non_common_categories_are_typed_so_the_universe_filter_excludes_them(
    tmp_path, config, category
):
    tickers = [_ticker_row(700002, "DDD", category=category)]
    sep = [_sep_row("DDD", d, 50.0) for d in DATES]
    daily = [_daily_row("DDD", d, 5000.0) for d in DATES]

    panel = SharadarSnapshot(
        write_snapshot(tmp_path / "s", tickers=tickers, sep=sep, daily=daily), config
    ).load()

    assert panel.meta.loc["700002", "security_type"] != "common"


def test_delisted_securities_are_retained(tmp_path, config):
    """Section 3: they remain in the universe until their delisting date."""
    tickers = [
        _ticker_row(800001, "GONE", first=DATES[0], last=DATES[14], isdelisted="Y"),
        _ticker_row(199002, "BBB"),
    ]
    sep = [_sep_row("GONE", d, 50.0) for d in DATES[:15]]
    sep += [_sep_row("BBB", d, 50.0) for d in DATES]
    sep += [_sep_row("SPY", d, 300.0) for d in DATES]
    daily = [_daily_row("GONE", d, 5000.0) for d in DATES[:15]]
    daily += [_daily_row(t, d, 5000.0) for t in ("BBB", "SPY") for d in DATES]

    panel = SharadarSnapshot(
        write_snapshot(tmp_path / "s", tickers=tickers, sep=sep, daily=daily), config
    ).load()

    assert "800001" in panel.securities, "a delisted security was dropped -- survivorship bias"
    assert not np.isnan(panel.close_adj.loc[DATES[10], "800001"])
    assert pd.Timestamp(panel.meta.loc["800001", "delist_date"]) == DATES[14]


# ---------------------------------------------------------------------------
# DELISTING CLASSIFICATION -- CONVENTIONS section 1, pre-registered fallback
# ---------------------------------------------------------------------------


def _delisted_snapshot(tmp_path, config, actions):
    tickers = [_ticker_row(800001, "GONE", first=DATES[0], last=DATES[14], isdelisted="Y")]
    sep = [_sep_row("GONE", d, 50.0) for d in DATES[:15]]
    sep += [_sep_row("SPY", d, 300.0) for d in DATES]
    daily = [_daily_row("GONE", d, 5000.0) for d in DATES[:15]]
    daily += [_daily_row("SPY", d, 5000.0) for d in DATES]
    return SharadarSnapshot(
        write_snapshot(tmp_path / "s", tickers=tickers, sep=sep, daily=daily, actions=actions),
        config,
    ).load()


def test_a_merger_action_is_classified_as_a_merger(tmp_path, config):
    panel = _delisted_snapshot(
        tmp_path, config, [_action_row(DATES[14], "merger", "GONE", contraticker="ACQ")]
    )
    assert panel.meta.loc["800001", "delist_reason"] == "merger"


def test_an_acquisition_action_is_classified_as_a_merger(tmp_path, config):
    panel = _delisted_snapshot(
        tmp_path, config, [_action_row(DATES[14], "acquisition", "GONE", contraticker="ACQ")]
    )
    assert panel.meta.loc["800001", "delist_reason"] == "merger"


def test_an_unclassifiable_delisting_falls_back_to_performance(tmp_path, config):
    """CONVENTIONS section 1 item 1, in the conservative direction.

    'Treat any delisting not affirmatively identifiable as M&A or voluntary as
    performance-related.' This is what triggers the -30% Shumway haircut.
    """
    panel = _delisted_snapshot(tmp_path, config, [_action_row(DATES[14], "delisted", "GONE")])
    assert panel.meta.loc["800001", "delist_reason"] == "performance"


def test_a_delisting_with_no_action_row_at_all_falls_back_to_performance(tmp_path, config):
    panel = _delisted_snapshot(tmp_path, config, [])
    assert panel.meta.loc["800001", "delist_reason"] == "performance"


# ---------------------------------------------------------------------------
# THE PANEL CONTRACT
# ---------------------------------------------------------------------------


def test_the_panel_satisfies_its_contract(snapshot):
    """Construction validates; reaching here means every invariant held."""
    panel = snapshot.load()

    assert panel.dates.is_monotonic_increasing and panel.dates.is_unique
    assert panel.securities.is_unique
    assert not panel.meta["ticker"].equals(panel.meta["security_id"])
    assert panel.benchmark_tr.notna().all()
    assert panel.vol_index.notna().all()


def test_the_benchmark_comes_from_the_configured_ticker(snapshot, config):
    """C4: the S&P 500 TOTAL RETURN basis, via SPY's adjusted close."""
    panel = snapshot.load()
    assert panel.benchmark_tr.loc[DATES[0]] == pytest.approx(100.0)
    assert config.get("sharadar.benchmark_ticker") == "SPY"


def test_the_benchmark_is_not_in_the_investable_universe(snapshot):
    """SPY supplies the benchmark; it must not be rankable as a holding."""
    panel = snapshot.load()
    assert panel.meta.loc["900001", "security_type"] != "common"


def test_a_missing_benchmark_is_a_loud_error(tmp_path, config):
    root = write_snapshot(tmp_path / "s", include_benchmark=False)

    with pytest.raises(SchemaError) as excinfo:
        SharadarSnapshot(root, config).load()
    assert "SPY" in str(excinfo.value)


def test_every_excluded_security_date_is_accounted_for(snapshot):
    snapshot.load()
    report = snapshot.exclusions()

    assert isinstance(report.total, int)
    assert report.as_dict()["rule"].startswith("a security-date")
