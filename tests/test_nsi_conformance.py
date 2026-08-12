"""Does the implementation execute the FROZEN APEX-002 specification exactly?

Each test names the invariant it guards. These are conformance tests: they
compare code against the specification, never against whichever result looks
economically attractive.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from apex.features import nsi

REPO = Path(__file__).resolve().parent.parent
FROZEN_HASH = "63703d1020893a59a4b43ed9698c4920ccb392e7f76bc77030ef019693ea9bda"


def _sf1(rows):
    return pd.DataFrame(rows, columns=["ticker", "dimension", "date", "reportperiod", "sharesbas"])


# --- INVARIANT 1: PIT selection --------------------------------------------

def test_earliest_filing_wins_not_the_restatement(tmp_path):
    """3.45% of pairs carry revisions. `.last()` picks the restated figure."""
    (tmp_path / "raw" / "SF1").mkdir(parents=True)
    _sf1([
        ["AAA", "ARQ", "2020-05-01", "2020-03-31", 1_000_000],   # as-filed
        ["AAA", "ARQ", "2021-08-01", "2020-03-31", 1_250_000],   # RESTATEMENT
    ]).to_csv(tmp_path / "raw" / "SF1" / "a.csv", index=False)

    report = nsi.NSIReport()
    out = nsi.load_as_filed(tmp_path, report)

    assert len(out) == 1
    assert out.iloc[0]["sharesbas"] == 1_000_000, "selected the restatement"
    assert out.iloc[0]["date"] == pd.Timestamp("2020-05-01")
    assert report.dropped_revisions == 1


def test_the_loader_never_calls_last():
    source = inspect.getsource(nsi.load_as_filed)
    assert ".last()" not in source
    assert ".first()" in source
    assert 'sort_values("date"' in source


def test_impossible_filings_are_dropped(tmp_path):
    (tmp_path / "raw" / "SF1").mkdir(parents=True)
    _sf1([
        ["AAA", "ARQ", "2020-03-15", "2020-03-31", 1_000_000],   # filed BEFORE period end
        ["BBB", "ARQ", "2020-05-01", "2020-03-31", 2_000_000],
    ]).to_csv(tmp_path / "raw" / "SF1" / "a.csv", index=False)

    report = nsi.NSIReport()
    out = nsi.load_as_filed(tmp_path, report)

    assert report.dropped_impossible_filing == 1
    assert set(out["ticker"]) == {"BBB"}


def test_nonpositive_shares_are_dropped(tmp_path):
    (tmp_path / "raw" / "SF1").mkdir(parents=True)
    _sf1([
        ["AAA", "ARQ", "2020-05-01", "2020-03-31", 0],
        ["BBB", "ARQ", "2020-05-01", "2020-03-31", -5],
        ["CCC", "ARQ", "2020-05-01", "2020-03-31", 10],
    ]).to_csv(tmp_path / "raw" / "SF1" / "a.csv", index=False)

    report = nsi.NSIReport()
    out = nsi.load_as_filed(tmp_path, report)

    assert report.dropped_nonpositive_shares == 2
    assert set(out["ticker"]) == {"CCC"}


def test_only_arq_is_used(tmp_path):
    """MRQ is the most-recent-RESTATED dimension and must never be admitted."""
    (tmp_path / "raw" / "SF1").mkdir(parents=True)
    _sf1([
        ["AAA", "MRQ", "2020-05-01", "2020-03-31", 9_999],
        ["AAA", "ARQ", "2020-05-01", "2020-03-31", 1_000],
    ]).to_csv(tmp_path / "raw" / "SF1" / "a.csv", index=False)

    out = nsi.load_as_filed(tmp_path, nsi.NSIReport())

    assert len(out) == 1 and out.iloc[0]["sharesbas"] == 1_000


# --- INVARIANT 2: the formula ----------------------------------------------

def _panel(shares, filings, periods, dates, events=None):
    frame = pd.DataFrame({
        "ticker": ["AAA"] * len(shares),
        "date": pd.to_datetime(filings),
        "reportperiod": pd.to_datetime(periods),
        "sharesbas": shares,
    })
    return nsi.build_nsi_panel(
        frame, events or {}, {"AAA": "SEC1"},
        pd.DatetimeIndex(pd.to_datetime(dates)), pd.Index(["SEC1"]), nsi.NSIReport(),
    )


def test_nsi_is_the_log_ratio_over_four_quarters():
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]
    shares = [1_000_000, 990_000, 980_000, 970_000, 900_000]

    out = _panel(shares, filings, periods, ["2021-06-01"])

    assert out.loc[pd.Timestamp("2021-06-01"), "SEC1"] == pytest.approx(np.log(900_000 / 1_000_000))


def test_a_repurchase_is_negative_and_issuance_positive():
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]

    buyback = _panel([1000, 1000, 1000, 1000, 900], filings, periods, ["2021-06-01"])
    issue = _panel([1000, 1000, 1000, 1000, 1100], filings, periods, ["2021-06-01"])

    assert buyback.loc[pd.Timestamp("2021-06-01"), "SEC1"] < 0
    assert issue.loc[pd.Timestamp("2021-06-01"), "SEC1"] > 0


def test_a_uniform_rebasing_factor_cancels():
    """`sharesbas` is retroactively split-rebased. The factor MUST cancel --
    this is why the specification mandates a ratio rather than a level."""
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]
    base = [1000, 990, 980, 970, 900]

    plain = _panel(base, filings, periods, ["2021-06-01"])
    rebased = _panel([s * 28 for s in base], filings, periods, ["2021-06-01"])

    assert plain.loc[pd.Timestamp("2021-06-01"), "SEC1"] == pytest.approx(
        rebased.loc[pd.Timestamp("2021-06-01"), "SEC1"]
    ), "a 28x split rebasing changed the signal; the ratio is not cancelling"


def test_no_winsorisation_clipping_or_smoothing_anywhere():
    """Scan EXECUTABLE code only.

    A naive scan of the raw source matches this module's own docstring, which
    states the prohibition in words -- the prohibition would flag itself.
    Docstrings and comments are stripped so the test reads what actually runs.
    """
    import ast, io, tokenize

    raw = inspect.getsource(nsi)
    tree = ast.parse(raw)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    code = "".join(
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(raw).readline)
        if tok.type != tokenize.COMMENT
        and not (tok.type == tokenize.STRING and tok.string.strip("\"'") in docstrings)
    )

    for banned in ("clip(", "winsor", "rolling(", "ewm(", ".quantile(", "fillna("):
        assert banned not in code, f"'{banned}' is EXECUTED in the NSI implementation"

    # and prove the scan is not vacuous
    assert "np.log(" in code, "the scan stripped the code it was meant to read"


def test_an_extreme_value_survives_untouched():
    """p99 is +1.74 and the max is +12. Real financings, retained by the spec."""
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]

    out = _panel([1000, 1000, 1000, 1000, 50_000], filings, periods, ["2021-06-01"])

    assert out.loc[pd.Timestamp("2021-06-01"), "SEC1"] == pytest.approx(np.log(50))


# --- INVARIANT 1 (continued): availability is the FILING date ---------------

def test_the_signal_is_invisible_before_it_is_filed():
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]
    shares = [1000, 1000, 1000, 1000, 900]

    out = _panel(shares, filings, periods, ["2021-04-30", "2021-05-01", "2021-05-02"])

    assert np.isnan(out.loc[pd.Timestamp("2021-04-30"), "SEC1"]), (
        "the FY2021Q1 figure was visible the day BEFORE it was filed"
    )
    assert not np.isnan(out.loc[pd.Timestamp("2021-05-02"), "SEC1"])


def test_a_fiscal_period_label_does_not_confer_availability():
    """Period end 2021-03-31 but filed 2021-05-01: invisible on 2021-04-15."""
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]

    out = _panel([1000] * 4 + [900], filings, periods, ["2021-04-15"])

    assert np.isnan(out.loc[pd.Timestamp("2021-04-15"), "SEC1"])


# --- INVARIANT 3: corporate actions ----------------------------------------

def test_an_excluding_action_in_the_window_removes_the_observation():
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]
    events = {"AAA": [pd.Timestamp("2020-09-15")]}   # spin-off inside the window

    out = _panel([1000, 1000, 1000, 1000, 900], filings, periods, ["2021-06-01"], events)

    assert np.isnan(out.loc[pd.Timestamp("2021-06-01"), "SEC1"])


def test_an_action_outside_the_window_does_not_exclude():
    periods = ["2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31"]
    filings = ["2020-05-01", "2020-08-01", "2020-11-01", "2021-02-01", "2021-05-01"]
    events = {"AAA": [pd.Timestamp("2019-01-01")]}

    out = _panel([1000, 1000, 1000, 1000, 900], filings, periods, ["2021-06-01"], events)

    assert not np.isnan(out.loc[pd.Timestamp("2021-06-01"), "SEC1"])


def test_splits_are_NOT_in_the_exclusion_set():
    """The vendor's rebasing already removes them exactly; excluding or
    re-adjusting would double-count."""
    assert "split" not in nsi.EXCLUDING_ACTIONS
    assert "adrratiosplit" not in nsi.EXCLUDING_ACTIONS
    for required in ("spinoff", "mergerto", "acquisitionby", "conversion"):
        assert required in nsi.EXCLUDING_ACTIONS


# --- INVARIANTS 4-5: universe ordering and ranking --------------------------

def test_ranking_is_ascending_so_repurchasers_rank_first():
    dates = pd.DatetimeIndex(["2021-06-01"])
    secs = pd.Index(["A", "B", "C"])
    signal = pd.DataFrame([[-0.20, 0.0, +0.30]], index=dates, columns=secs)
    eligible = pd.DataFrame(True, index=dates, columns=secs)

    ranks = nsi.rank_ascending(signal, eligible)

    assert ranks.loc[dates[0], "A"] < ranks.loc[dates[0], "C"], (
        "the largest repurchaser must rank ahead of the largest issuer"
    )


def test_ineligible_securities_never_enter_the_cross_section():
    """Invariant 4: eligibility first. NSI must not widen the universe."""
    dates = pd.DatetimeIndex(["2021-06-01"])
    secs = pd.Index(["A", "B"])
    signal = pd.DataFrame([[-0.5, -0.9]], index=dates, columns=secs)
    eligible = pd.DataFrame([[True, False]], index=dates, columns=secs)

    ranks = nsi.rank_ascending(signal, eligible)

    assert np.isnan(ranks.loc[dates[0], "B"])
    assert ranks.loc[dates[0], "A"] == pytest.approx(1.0)


def test_ties_are_broken_deterministically():
    """4.63% tie at exactly zero. C10: method='first' on a sorted security axis."""
    dates = pd.DatetimeIndex(["2021-06-01"])
    secs = pd.Index(["A", "B", "C"])
    signal = pd.DataFrame([[0.0, 0.0, 0.0]], index=dates, columns=secs)
    eligible = pd.DataFrame(True, index=dates, columns=secs)

    first = nsi.rank_ascending(signal, eligible)
    again = nsi.rank_ascending(signal, eligible)

    pd.testing.assert_frame_equal(first, again)
    assert first.loc[dates[0]].nunique() == 3, "ties must resolve to distinct ranks"


# --- INVARIANT 6: governance ------------------------------------------------

def test_the_frozen_protocol_hash_is_intact():
    actual = hashlib.sha256(
        (REPO / "APEX-002-Protocol-Net-Share-Issuance.md").read_bytes()
    ).hexdigest()
    assert actual == FROZEN_HASH, "the #002 pre-registration was modified after signing"


def test_the_nsi_module_cannot_reach_experiment_001():
    source = inspect.getsource(nsi)
    assert "APEX-001" not in source
    assert "Experiment-001" not in source


# --- JOIN CORRECTNESS UNDER MISSINGNESS -------------------------------------

def _frames(nsi_vals, elig_vals):
    dates = pd.DatetimeIndex(["2021-06-01", "2021-06-02"])
    secs = pd.Index(["A", "B", "C"])
    return (pd.DataFrame(nsi_vals, index=dates, columns=secs),
            pd.DataFrame(elig_vals, index=dates, columns=secs))


def test_ranked_set_equals_eligible_and_nsi_present():
    signal, eligible = _frames(
        [[-0.1, np.nan, 0.2], [0.3, -0.4, np.nan]],
        [[True, True, True], [True, True, True]],
    )
    ranks = nsi.rank_ascending(signal, eligible)

    out = nsi.assert_cross_section_alignment(ranks, signal, eligible)

    assert out["alignment"].startswith("EXACT")
    assert out["ranked_security_dates"] == 4   # 2 per date


def test_an_ineligible_security_that_got_ranked_is_caught():
    """Universe breach: NSI availability must never widen the cross-section."""
    signal, eligible = _frames(
        [[-0.1, 0.2, 0.3], [-0.1, 0.2, 0.3]],
        [[True, False, True], [True, False, True]],
    )
    ranks = nsi.rank_ascending(signal, eligible)
    ranks.iloc[0, 1] = 0.5    # simulate a leaked ineligible name

    with pytest.raises(nsi.CrossSectionMisaligned) as excinfo:
        nsi.assert_cross_section_alignment(ranks, signal, eligible)
    assert "ranked-but-ineligible" in str(excinfo.value)


def test_a_silently_dropped_eligible_security_is_caught():
    """The subtle one: a row dropped before ranking leaves global stats intact."""
    signal, eligible = _frames(
        [[-0.1, 0.2, 0.3], [-0.1, 0.2, 0.3]],
        [[True, True, True], [True, True, True]],
    )
    ranks = nsi.rank_ascending(signal, eligible)
    ranks.iloc[1, 2] = np.nan   # simulate a silent drop on the second date

    with pytest.raises(nsi.CrossSectionMisaligned) as excinfo:
        nsi.assert_cross_section_alignment(ranks, signal, eligible)
    assert "unranked" in str(excinfo.value)


def test_alignment_holds_when_eligibility_changes_between_dates():
    """Cross-sections legitimately differ day to day; alignment is PER DATE."""
    signal, eligible = _frames(
        [[-0.1, 0.2, np.nan], [np.nan, 0.2, 0.3]],
        [[True, True, True], [False, True, True]],
    )
    ranks = nsi.rank_ascending(signal, eligible)

    out = nsi.assert_cross_section_alignment(ranks, signal, eligible)
    assert out["ranked_security_dates"] == 4
