"""The feature factory: computes registry features PIT-safely. No returns.

One interpreter for every descriptor kind, so a feature's behaviour follows
from its registry definition and not from bespoke code. The point-in-time
discipline is the one APEX-002 established and proved: earliest filing per
(ticker, reportperiod), admit only where the filing date is on or before the
formation date, never a restatement.

Every feature is emitted with a companion `known_from` frame recording the
filing date that made each cell knowable, so PIT compliance is MEASURED
(`apex.features.pit_validation`) rather than asserted from the shape of the
code -- exactly as `nsi.build_nsi_panel` does.

Computes no forward return, no IC, no predictive statistic.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from apex.contracts import Panel
from apex.features.registry import FeatureSpec

ARQ = "ARQ"


@dataclass
class FactoryReport:
    raw_arq_rows: int = 0
    dropped_impossible_filing: int = 0
    dropped_revisions: int = 0
    as_filed_rows: int = 0
    features_built: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "raw_arq_rows": self.raw_arq_rows,
            "dropped_impossible_filing": self.dropped_impossible_filing,
            "dropped_revisions": self.dropped_revisions,
            "as_filed_rows": self.as_filed_rows,
            "features_built": sorted(self.features_built),
        }


def _fields_needed(specs: tuple[FeatureSpec, ...]) -> set[str]:
    """SF1 columns any BUILT spec's descriptor references."""
    needed: set[str] = set()
    for s in specs:
        f = s.formula
        for key in ("num", "num2", "den", "field"):
            v = f.get(key)
            if isinstance(v, str):
                needed.add(v)
    # market-cap-based kinds take their fundamental from `num`; that is covered.
    return needed


def load_as_filed_fundamentals(
    root: Path, fields: set[str], report: FactoryReport
) -> pd.DataFrame:
    """Earliest filing per (ticker, reportperiod). The APEX-002 PIT discipline,
    generalised from one column (sharesbas) to many."""
    usecols = ["ticker", "dimension", "date", "reportperiod", *sorted(fields)]
    frames = [
        pd.read_csv(p, usecols=lambda c, k=set(usecols): c in k, low_memory=False)
        for p in sorted(glob.glob(str(root / "raw" / "SF1" / "*.csv")))
    ]
    if not frames:
        raise FileNotFoundError(f"no SF1 slices under {root}")
    frame = pd.concat(frames, ignore_index=True)
    frame = frame[frame["dimension"] == ARQ].copy()
    report.raw_arq_rows = len(frame)

    frame["date"] = pd.to_datetime(frame["date"])
    frame["reportperiod"] = pd.to_datetime(frame["reportperiod"])
    for col in fields:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    impossible = frame["date"] <= frame["reportperiod"]
    report.dropped_impossible_filing = int(impossible.sum())
    frame = frame[~impossible]

    before = len(frame)
    frame = (
        frame.sort_values("date", kind="mergesort")
        .groupby(["ticker", "reportperiod"], as_index=False, sort=False)
        .first()
    )
    report.dropped_revisions = before - len(frame)
    report.as_filed_rows = len(frame)
    return frame.sort_values(["ticker", "reportperiod"], kind="mergesort")


def _broadcast_latest(
    known_from: np.ndarray, values: np.ndarray, dates: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """For each formation date, the latest value whose knowability date <= T.

    Identical mechanic to nsi.build_nsi_panel: searchsorted on the ascending
    knowability dates, take the row strictly at or before T.
    """
    known_from = known_from.astype("datetime64[ns]")
    dates = dates.astype("datetime64[ns]")
    # searchsorted requires ascending knowability; filing dates usually are, but
    # a late-filed early period would break the assumption. Sort defensively.
    order = np.argsort(known_from, kind="mergesort")
    known_from, values = known_from[order], values[order]
    idx = np.searchsorted(known_from, dates, side="right") - 1
    usable = idx >= 0
    out_val = np.full(len(dates), np.nan)
    out_known = np.full(len(dates), np.datetime64("NaT"), dtype="datetime64[ns]")
    out_val[usable] = values[idx[usable]]
    out_known[usable] = known_from[idx[usable]]
    return out_val, out_known


def _per_security_stream(
    group: pd.DataFrame, spec: FeatureSpec
) -> tuple[np.ndarray, np.ndarray] | None:
    """(knowability_date, value) pairs for one security, ascending by knowability.

    Returns None when the descriptor cannot be formed for this security.
    """
    f = spec.formula
    kind = f["kind"]
    g = group.sort_values("reportperiod", kind="mergesort")
    filed = g["date"].to_numpy()

    if kind == "ratio":
        num = g[f["num"]].to_numpy(dtype="float64")
        if f.get("num_op") == "subtract":
            num = num - g[f["num2"]].to_numpy(dtype="float64")
        den = g[f["den"]].to_numpy(dtype="float64")
        with np.errstate(invalid="ignore", divide="ignore"):
            val = np.where(den != 0, num / den, np.nan)
        return filed, val

    if kind in ("log_ratio", "growth"):
        q = int(f["quarters"])
        x = g[f["field"]].to_numpy(dtype="float64")
        if len(x) <= q:
            return None
        cur, base = x[q:], x[:-q]
        known = np.maximum(filed[q:], filed[:-q])
        with np.errstate(invalid="ignore", divide="ignore"):
            if kind == "log_ratio":
                val = np.where((cur > 0) & (base > 0), np.log(cur / base), np.nan)
            else:
                val = np.where(base != 0, cur / base - 1.0, np.nan)
        order = np.argsort(known, kind="mergesort")
        return known[order], val[order]

    # valuation and scaled_flow need market cap; handled after the fundamental
    # numerator is broadcast. Here we return the fundamental itself, knowable at
    # the filing date; the market-cap divide happens in build_features.
    if kind in ("valuation", "scaled_flow"):
        num = g[f["num"]].to_numpy(dtype="float64") * float(f.get("sign", 1))
        return filed, num

    return None


def build_features(
    root: Path,
    panel: Panel,
    specs: tuple[FeatureSpec, ...],
    report: FactoryReport | None = None,
    formation_dates: pd.DatetimeIndex | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], FactoryReport]:
    """Wide feature frame + known_from frame per BUILT fundamental spec.

    `panel` supplies the security axis and, for valuation/scaled_flow,
    point-in-time market cap. `formation_dates` chooses which dates to compute
    on (default: every panel date); passing the rebalance grid alone avoids
    computing 20x more cells than a grid-based report reads. Returns feature
    values and their knowability dates; computes nothing about returns.
    """
    report = report or FactoryReport()
    fundamental = [s for s in specs if s.formula["kind"] in
                   ("ratio", "log_ratio", "growth", "valuation", "scaled_flow")]
    as_filed = load_as_filed_fundamentals(root, _fields_needed(tuple(fundamental)),
                                          report)

    dates = panel.dates if formation_dates is None else formation_dates
    securities = panel.securities
    ticker_to_security = dict(zip(panel.meta["ticker"], panel.meta.index))
    date_values = dates.to_numpy()

    # Point-in-time market cap for valuation/scaled_flow, from the panel.
    market_cap = panel.shares_out * panel.close_unadj  # both point-in-time

    values: dict[str, pd.DataFrame] = {}
    known: dict[str, pd.DataFrame] = {}

    for spec in fundamental:
        vframe = pd.DataFrame(np.nan, index=dates, columns=securities, dtype="float64")
        kframe = pd.DataFrame(pd.NaT, index=dates, columns=securities,
                              dtype="datetime64[ns]")

        for ticker, group in as_filed.groupby("ticker", sort=False):
            security = ticker_to_security.get(ticker)
            if security is None or security not in vframe.columns:
                continue
            stream = _per_security_stream(group, spec)
            if stream is None:
                continue
            known_from, raw = stream
            if not len(known_from):
                continue
            bval, bknown = _broadcast_latest(known_from, raw, date_values)
            vframe[security] = bval
            kframe[security] = bknown

        if spec.formula["kind"] in ("valuation", "scaled_flow"):
            # numerator broadcast above IS the fundamental; divide by cap at T.
            with np.errstate(invalid="ignore", divide="ignore"):
                mc = market_cap.reindex(index=dates, columns=securities)
                pos = mc.where(mc > 0)
                vframe = vframe.where(mc > 0) / pos
            # known_from stays the fundamental's filing date: market cap at T is
            # known at T, so it never postpones knowability.

        values[spec.feature_id] = vframe
        known[spec.feature_id] = kframe
        report.features_built.append(spec.feature_id)

    return values, known, report
