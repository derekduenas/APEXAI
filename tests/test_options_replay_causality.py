"""OPTIONS REPLAY -- temporal firewall + evidence-class property tests.

Historical replay is combat REHEARSAL. These tests make it structurally
impossible for rehearsal to masquerade as prospective evidence, or for
the future to leak into a decision.
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.options.replay import (  # noqa: E402
    EVIDENCE_CLASS, LONG_LEG_FILL, SHORT_LEG_FILL, ReplayViolation,
    ReplayWorld, sample_accounting, seal_before_card)


def _world(tmp_path):
    """Synthetic symbol-session: 5 underlying bars, quotes at 5 instants."""
    d = tmp_path / "TEST"
    d.mkdir(parents=True)
    t0 = pd.Timestamp("2024-05-22T13:30:00Z")     # 09:30 ET
    bars = [{"t": str(t0 + pd.Timedelta(minutes=i)),
             "c": 100.0 + i, "session": "REGULAR"} for i in range(5)]
    gzip.open(d / "underlying_20240522.json.gz", "wt").write(
        json.dumps({"source": "TEST", "bars": bars}))
    rows = []
    for i in range(5):
        rows.append({"symbol": "TEST", "expiration": "2024-06-21",
                     "strike": "100.000", "right": "CALL",
                     "timestamp": f"2024-05-22T09:3{i}:00.000",
                     "bid_size": "10", "bid": f"{2.0 + i:.2f}",
                     "ask_size": "10", "ask": f"{2.1 + i:.2f}",
                     "moneyness_status": "CAUSAL"})
    with gzip.open(d / "quotes_20240522.csv.gz", "wt") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        [w.writerow(r) for r in rows]
    return ReplayWorld.load(tmp_path, "TEST", "2024-05-22")


def test_frozen_state_contains_no_future_rows(tmp_path):
    """THE FIREWALL: the future is ABSENT from the object, not hidden."""
    w = _world(tmp_path)
    st = w.at("2024-05-22T09:32:00")
    assert len(st.option_quotes) == 3            # 09:30, 09:31, 09:32
    for r in st.option_quotes:
        assert pd.Timestamp(r["timestamp"]) <= pd.Timestamp(
            "2024-05-22T09:32:00")
    # and the raw payload genuinely lacks later data
    assert "09:34" not in json.dumps(st.option_quotes)


def test_underlying_respects_start_of_bar(tmp_path):
    """A bar labeled L is knowable only at L+1min."""
    w = _world(tmp_path)
    st = w.at("2024-05-22T09:32:00")
    assert st.spot_ref == 101.0                  # bar 09:31's close
    assert st.spot_ref_source_label.endswith("09:31:00")
    early = w.at("2024-05-22T09:30:00")
    assert early.spot_ref is None                # nothing closed yet


def test_future_cannot_be_revealed_without_a_sealed_card(tmp_path):
    w = _world(tmp_path)
    with pytest.raises(ReplayViolation, match="sealed BEFORE card"):
        w.reveal_after("2024-05-22T09:32:00", "")
    with pytest.raises(ReplayViolation):
        w.reveal_after("2024-05-22T09:32:00", "tooshort")
    card = seal_before_card({"symbol": "TEST", "direction": "LONG"})
    fq, fb = w.reveal_after("2024-05-22T09:32:00", card["card_hash"])
    assert len(fq) == 2                          # 09:33, 09:34


def test_sealed_card_is_marked_rehearsal_not_evidence(tmp_path):
    card = seal_before_card({"symbol": "TEST", "setup_family": "X"})
    assert card["evidence_class"] == EVIDENCE_CLASS
    assert card["live_promotion_eligible"] is False
    assert card["decision_power"] == "NONE_REPLAY"
    assert "never prospective evidence" in card["law"]
    # hash covers the content: mutating anything changes it
    other = seal_before_card({"symbol": "TEST", "setup_family": "Y"})
    assert card["card_hash"] != other["card_hash"]


def test_sample_accounting_refuses_pseudo_replication():
    """90 minutes of one setup firing is ONE episode, not 90 trades."""
    recs = [{"symbol": "NVDA", "session": "2024-05-22",
             "setup_family": "PULLBACK"} for _ in range(90)]
    acc = sample_accounting(recs)
    assert acc["n_raw"] == 90
    assert acc["n_effective_lower_bound"] == 1
    assert "NEVER implies independence" in acc["law"]
    recs += [{"symbol": "AAPL", "session": "2024-06-03",
              "setup_family": "TRAP"}]
    acc = sample_accounting(recs)
    assert acc["n_effective_lower_bound"] == 2
    assert acc["unique_symbols"] == 2


def test_only_causal_rows_are_loaded(tmp_path):
    """ELIGIBILITY LAW: NOT_ESTIMABLE rows are preserved on disk but
    may never teach the Predator."""
    d = tmp_path / "TEST"
    d.mkdir(parents=True)
    rows = [{"symbol": "TEST", "expiration": "2024-06-21",
             "strike": "100.000", "right": "CALL",
             "timestamp": "2024-05-22T09:30:00.000", "bid_size": "1",
             "bid": "2.0", "ask_size": "1", "ask": "2.1",
             "moneyness_status": s} for s in ("CAUSAL", "NOT_ESTIMABLE")]
    with gzip.open(d / "quotes_20240522.csv.gz", "wt") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        [w.writerow(r) for r in rows]
    world = ReplayWorld.load(tmp_path, "TEST", "2024-05-22")
    assert len(world._quotes) == 1
    assert world._quotes[0]["moneyness_status"] == "CAUSAL"


def test_fill_convention_is_quoted_sides_only():
    assert LONG_LEG_FILL == "ASK" and SHORT_LEG_FILL == "BID"
    src = Path("apex/predators/options/replay.py").read_text()
    assert "never a midpoint that never traded" in src
