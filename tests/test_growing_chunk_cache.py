"""The cache must not freeze a session that is still producing bars.

OBSERVED IN PRODUCTION, 2026-09-14. The premarket producer runs four stages against the SAME cache key --
(symbol, prior_session, today) -- so the 08:15 stage fetched and wrote the chunk, and the 08:32, 09:05 and 09:20
"refreshes" each read that same file. The download ledger shows it exactly: quota_used=145u on the first
absorption and 0u on the other three. Four stages, one fetch. Had premarket prints appeared at 09:00 they could
not have reached the 09:20 packet.

The same key shape is used by closing_run (five checkpoints on (day, day)) and by FastWatch's last-resort
fallback, so this was never only a premarket problem.
"""
from __future__ import annotations

import gzip
import json
import time

import pandas as pd
import pytest

from apex.intraday import eodhd


class FakeGov:
    def __init__(self, allow=True):
        self.allow, self.used, self.calls = allow, 0, 0

    def acquire(self, cost):
        self.calls += 1
        if not self.allow:
            return False
        self.used += cost
        return True

    def backoff(self, attempt, retry_after=None):
        return 0.0


@pytest.fixture(autouse=True)
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr(eodhd, "LAKE", tmp_path)
    monkeypatch.setattr(eodhd, "token", lambda: "TEST")
    return tmp_path


def write_cache(symbol, lo, hi, rows, *, age_s=0.0):
    cp = eodhd.cache_path(symbol, lo, hi)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_bytes(gzip.compress(json.dumps(rows).encode()))
    if age_s:
        t = time.time() - age_s
        import os
        os.utime(cp, (t, t))
    return cp


def opener_returning(rows):
    def _open(url):
        return json.dumps(rows).encode()
    return _open


TODAY = str(pd.Timestamp.now(tz="America/New_York").date())
PRIOR = str((pd.Timestamp.now(tz="America/New_York") - pd.Timedelta(days=3)).date())
OLD_LO, OLD_HI = "2026-01-05", "2026-01-09"


class TestGrowingChunkDetection:
    def test_a_finished_past_date_is_not_growing(self):
        assert eodhd.chunk_is_growing(OLD_HI) is False

    def test_today_is_growing(self):
        assert eodhd.chunk_is_growing(TODAY) is True

    def test_the_test_is_market_time_not_utc(self):
        """At 23:30 ET the UTC date is already tomorrow. A chunk ending on the CURRENT TRADING DATE is still
        growing regardless of what UTC thinks the date is."""
        now = pd.Timestamp("2026-09-14 23:30", tz="America/New_York").tz_convert("UTC")
        assert now.date().isoformat() == "2026-09-15"
        assert eodhd.chunk_is_growing("2026-09-14", now=now) is True


class TestTheRefreshActuallyRefreshes:
    def test_a_finished_chunk_is_served_from_cache_forever(self):
        write_cache("SPY.US", OLD_LO, OLD_HI, [{"timestamp": 1}], age_s=10 ** 7)
        gov = FakeGov()
        rows, src = eodhd.fetch_intraday_chunk("SPY.US", OLD_LO, OLD_HI, gov)
        assert src == "cache" and gov.calls == 0 and rows == [{"timestamp": 1}]

    def test_a_growing_chunk_inside_the_ttl_is_served_from_cache(self):
        write_cache("SPY.US", PRIOR, TODAY, [{"timestamp": 1}], age_s=10.0)
        gov = FakeGov()
        _rows, src = eodhd.fetch_intraday_chunk("SPY.US", PRIOR, TODAY, gov)
        assert src == "cache" and gov.calls == 0

    def test_a_STALE_growing_chunk_is_REFETCHED(self):
        """The defect, as a test. Before the fix this returned the one-bar cache and spent nothing."""
        write_cache("SPY.US", PRIOR, TODAY, [{"timestamp": 1}],
                    age_s=eodhd.GROWING_CHUNK_TTL_S + 60)
        gov = FakeGov()
        rows, src = eodhd.fetch_intraday_chunk(
            "SPY.US", PRIOR, TODAY, gov, opener=opener_returning([{"timestamp": 1}, {"timestamp": 2}]))
        assert src == "network", "a refresh that reads its own stale file is not a refresh"
        assert len(rows) == 2 and gov.used == eodhd.INTRADAY_CALL_COST

    def test_the_refetch_overwrites_the_cache_so_the_next_stage_sees_the_newer_bars(self):
        write_cache("SPY.US", PRIOR, TODAY, [{"timestamp": 1}],
                    age_s=eodhd.GROWING_CHUNK_TTL_S + 60)
        eodhd.fetch_intraday_chunk("SPY.US", PRIOR, TODAY, FakeGov(),
                                   opener=opener_returning([{"timestamp": 1}, {"timestamp": 2}]))
        rows, src = eodhd.fetch_intraday_chunk("SPY.US", PRIOR, TODAY, FakeGov())
        assert src == "cache" and len(rows) == 2

    def test_four_stages_seventeen_minutes_apart_each_fetch(self):
        """The production shape: one morning, four stages, one cache key."""
        gov = FakeGov()
        seen = []
        for stage in range(4):
            n = stage + 1
            rows, src = eodhd.fetch_intraday_chunk(
                "SPY.US", PRIOR, TODAY, gov,
                opener=opener_returning([{"timestamp": i} for i in range(n)]))
            seen.append((src, len(rows)))
            cp = eodhd.cache_path("SPY.US", PRIOR, TODAY)
            import os
            t = time.time() - (eodhd.GROWING_CHUNK_TTL_S + 60)
            os.utime(cp, (t, t))                     # the next stage is ~17 minutes later
        assert [s for s, _n in seen] == ["network"] * 4, seen
        assert [n for _s, n in seen] == [1, 2, 3, 4], "each stage must see the growing tape"
        assert gov.used == 4 * eodhd.INTRADAY_CALL_COST


class TestAFailedRefreshDoesNotLoseData:
    def test_a_provider_failure_returns_the_stale_rows_LABELLED(self):
        write_cache("SPY.US", PRIOR, TODAY, [{"timestamp": 1}],
                    age_s=eodhd.GROWING_CHUNK_TTL_S + 60)

        def boom(url):
            raise OSError("provider down")
        rows, src = eodhd.fetch_intraday_chunk("SPY.US", PRIOR, TODAY, FakeGov(), opener=boom)
        assert src == "cache_stale" and rows == [{"timestamp": 1}], \
            "a refresh that fails must not turn a stale-but-usable packet into a failed stage"

    def test_an_exhausted_local_budget_returns_the_stale_rows_rather_than_raising(self):
        write_cache("SPY.US", PRIOR, TODAY, [{"timestamp": 1}],
                    age_s=eodhd.GROWING_CHUNK_TTL_S + 60)
        rows, src = eodhd.fetch_intraday_chunk("SPY.US", PRIOR, TODAY, FakeGov(allow=False))
        assert src == "cache_stale" and rows == [{"timestamp": 1}]

    def test_with_no_cache_at_all_a_provider_failure_still_raises(self):
        def boom(url):
            raise OSError("provider down")
        with pytest.raises(eodhd.IntradayDataError):
            eodhd.fetch_intraday_chunk("SPY.US", PRIOR, TODAY, FakeGov(), opener=boom)

    def test_the_bypass_and_the_stale_fallback_are_both_recorded_in_the_ledger(self):
        write_cache("SPY.US", PRIOR, TODAY, [{"timestamp": 1}],
                    age_s=eodhd.GROWING_CHUNK_TTL_S + 60)

        def boom(url):
            raise OSError("provider down")
        eodhd.fetch_intraday_chunk("SPY.US", PRIOR, TODAY, FakeGov(), opener=boom)
        events = [json.loads(x) for x in
                  (eodhd.LAKE / "manifests" / "eodhd_download_ledger.jsonl").read_text().splitlines() if x.strip()]
        kinds = [e.get("event") for e in events]
        assert "cache_bypassed_growing_chunk" in kinds and "refresh_failed_serving_stale_cache" in kinds, kinds
