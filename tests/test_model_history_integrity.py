import numpy as np
import pandas as pd
import pytest
from apex.hunter import model_history as H
from apex.hunter import intelligence_wiring as W

CUTOFF = pd.Timestamp('2026-09-14T13:35Z').timestamp()


def frame(day, n):
    times = pd.date_range(day + ' 13:30', periods=n, freq='min', tz='UTC')
    px = 100 * np.exp(np.cumsum(np.random.default_rng(42).normal(0, .001, n)))
    return pd.DataFrame(dict(event_time_utc=times, open=px, high=px,
                             low=px, close=px, volume=100))


def build(monkeypatch, prior, today):
    monkeypatch.setattr(H, 'prior_session_dates', lambda *a: ['2026-09-11'])
    rows = prior.assign(timestamp=prior.event_time_utc.map(lambda t: t.timestamp())).drop(
        columns='event_time_utc').to_dict('records')
    return H.build('SPY', today, as_of_epoch=CUTOFF, gov=object(),
                   fetch=lambda *a: (rows, 'synthetic'))


def test_mixed_availability_reaches_real_simulation(monkeypatch):
    today = frame('2026-09-14', 5)
    today['available_epoch'] = today.event_time_utc.map(lambda t: t.timestamp() + 60)
    history, provenance = build(monkeypatch, frame('2026-09-11', 390), today)
    result = W.simulation_view({}, today, as_of_epoch=CUTOFF, history=history,
                               history_sessions=2, prefer_garch=False, n_paths=20)
    assert result.calibration_status == 'SIMULATED_UNCALIBRATED', result.reasons
    assert result.provenance['return_rows'] == 393
    assert provenance['availability_basis'] == 'MIXED_PER_ROW'
    assert history.available_epoch.notna().all()


@pytest.mark.parametrize('field', ['close', 'volume', 'available_epoch'])
def test_conflicts_exclude_timestamp_regardless_of_order(monkeypatch, field):
    prior = frame('2026-09-11', 3)
    if field == 'available_epoch':
        prior[field] = prior.event_time_utc.map(lambda t: t.timestamp() + 60)
    changed = prior.iloc[[1]].copy()
    changed[field] += 1
    bad = pd.concat([prior, changed], ignore_index=True)
    a, pa = build(monkeypatch, bad, frame('2026-09-14', 5))
    b, pb = build(monkeypatch, bad.iloc[::-1].reset_index(drop=True), frame('2026-09-14', 5))
    pd.testing.assert_frame_equal(a, b)
    assert prior.event_time_utc.iloc[1] not in list(a.event_time_utc)
    assert pa['conflicting_bars'][0]['reason'] == 'CONFLICTING_MODEL_HISTORY_BAR'
    assert len(pb['conflicting_bars']) == 1


def test_identical_duplicates_collapse(monkeypatch):
    prior = frame('2026-09-11', 3)
    out, p = build(monkeypatch, pd.concat([prior, prior], ignore_index=True), frame('2026-09-14', 5))
    assert len(out) == 8
    assert p['identical_duplicates_collapsed'] == 3
    assert p['conflicting_bars'] == []


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), CUTOFF + 1])
def test_supplied_unknown_or_future_history_is_not_backdated(monkeypatch, bad):
    prior = frame('2026-09-11', 3)
    prior['available_epoch'] = bad
    out, _ = build(monkeypatch, prior, frame('2026-09-14', 5))
    visible = W._visible_simulation_bars(out, cutoff_epoch=CUTOFF, sessions=2)
    assert len(visible) == 5
    assert set(visible.event_time_utc.dt.date.astype(str)) == {'2026-09-14'}


def test_the_same_observation_from_two_sources_is_currently_excluded_as_a_conflict():
    """A BOUNDED HAZARD, recorded rather than fixed, because it is not reachable today.

    Conflict detection runs on the FULL row after `_with_availability` has tagged each input family. So one
    identical observation -- same timestamp, same OHLCV -- arriving from both the adapter cache and the live
    feed differs only in `availability_basis`, is therefore NOT "exactly equivalent", and the whole timestamp is
    excluded as conflicting. That is over-exclusion: the two rows agree about the market.

    It is unreachable through `build()` today because prior sessions are date-filtered to exclude the decision's
    own market date, so the two families cannot overlap. It becomes reachable the moment history is widened to
    include part of the current session from a second source. Stated here so it is found by a test rather than
    by a silently shrinking sample."""
    import pandas as pd
    from apex.hunter.model_history import _with_availability

    t = pd.Timestamp("2026-09-14 13:30", tz="UTC")
    row = dict(event_time_utc=t, close=100.0, open=100.0, high=100.0, low=100.0, volume=1000)
    historical = _with_availability(pd.DataFrame([row]))
    live = pd.DataFrame([row])
    live["available_epoch"] = t.timestamp() + 60
    live = _with_availability(live)

    merged = pd.concat([historical, live], ignore_index=True)
    identical = merged.drop_duplicates()
    assert len(identical) == 2, "the two rows differ only in availability_basis"
    conflicting = identical["event_time_utc"].duplicated(keep=False)
    assert conflicting.all(), "so the timestamp is currently excluded rather than collapsed"

    # and the same two rows DO agree about every market fact
    market_cols = ["event_time_utc", "open", "high", "low", "close", "volume"]
    assert historical[market_cols].equals(live[market_cols])
