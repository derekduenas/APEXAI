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
