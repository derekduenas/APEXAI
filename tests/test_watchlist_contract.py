"""THE WATCHLIST CONTRACT — natural-shape fixtures (Phase 0.2).

Every fixture here is the REAL persisted dict shape
(apex/hunter/watchlist.py), never a handcrafted positional tuple. That
exact mismatch — scanner.py persists dicts, microscope.py unpacked
positional tuples — is why the 2026-08-17 defect went undetected until a
real production watchlist arrived: the OLD test suite's tuple fixtures
accidentally "worked" against the buggy code.
"""
from __future__ import annotations

import json

import pytest

from apex.hunter.microscope import select_targets
from apex.hunter.watchlist import (
    RVOL_INVALID_SESSION, RVOL_UNKNOWN, RVOL_VALID, WATCHLIST_SCHEMA_VERSION,
    make_entry, parse_watchlist, parse_watchlist_entry,
)


def _scan(watchlist, t_utc="2026-08-17T15:00:00Z"):
    return {"kind": "scan", "t_utc": t_utc, "watchlist": watchlist}


# --------------------------------------------------------------- fixtures
def test_empty_watchlist():
    entries, errors = parse_watchlist([])
    assert entries == () and errors == ()
    entries, errors = parse_watchlist(None)
    assert entries == () and errors == ()


def test_one_real_dict_entry():
    raw = [make_entry("CBRS", ["GAP_AND_GO"], 0.08).as_record()]
    entries, errors = parse_watchlist(raw)
    assert not errors
    assert len(entries) == 1
    assert entries[0].symbol == "CBRS"
    assert entries[0].rvol_status == RVOL_VALID


def test_multiple_real_dict_entries():
    raw = [make_entry(s, ["GAP_AND_GO"], 0.1 * i).as_record()
          for i, s in enumerate(["AAOI", "CIEN", "ALAB"], start=1)]
    entries, errors = parse_watchlist(raw)
    assert not errors and len(entries) == 3


def test_signals_list_preserved_as_tuple():
    raw = [make_entry("AXTI", ["GAP_AND_GO", "RELATIVE_STRENGTH"],
                      0.03).as_record()]
    entries, _ = parse_watchlist(raw)
    assert entries[0].signals == ("GAP_AND_GO", "RELATIVE_STRENGTH")


def test_missing_optional_rvol_is_none_not_zero():
    raw = [{"symbol": "ADBE", "signals": ["RELATIVE_WEAKNESS"]}]
    entry, err = parse_watchlist_entry(raw[0])
    assert err is None
    assert entry.rvol is None
    assert entry.rvol_status == RVOL_UNKNOWN
    assert entry.rvol != 0.0                    # never laundered to zero


def test_invalid_rvol_from_session_integrity_gate():
    """The exact real-world shape: chartstate.py v1.2 sets rvol_tod=None
    under an invalid session anchor; the producer must persist that as
    rvol=None + a NAMED reason, never a fabricated number."""
    entry = make_entry("X", ["GAP_AND_GO"], None,
                       rvol_status=RVOL_INVALID_SESSION)
    raw = entry.as_record()
    parsed, err = parse_watchlist_entry(raw)
    assert err is None
    assert parsed.rvol is None
    assert parsed.rvol_status == RVOL_INVALID_SESSION


def test_unknown_signal_is_accepted_the_scanner_owns_signal_vocabulary():
    """The watchlist contract validates SHAPE, not signal semantics --
    apex/hunter/scanner.py owns which signal names are real; a future
    signal must not require this contract to change."""
    raw = [make_entry("Y", ["SOME_FUTURE_SIGNAL_NOT_YET_INVENTED"],
                      1.0).as_record()]
    entries, errors = parse_watchlist(raw)
    assert not errors
    assert "SOME_FUTURE_SIGNAL_NOT_YET_INVENTED" in entries[0].signals


def test_schema_version_mismatch_is_refused_not_best_effort():
    raw = [{**make_entry("Z", ["RVOL"], 1.0).as_record(),
           "schema_version": "watchlist_schema_v99_from_the_future"}]
    entries, errors = parse_watchlist(raw)
    assert not entries
    assert len(errors) == 1
    assert errors[0]["error"].startswith("REFUSE_SCHEMA_VERSION")


def test_missing_schema_version_field_is_treated_as_v1_not_refused():
    """Legacy/pre-contract records (today's real 2026-08-17 watchlist
    predates this module) have no schema_version key at all -- absence
    means v1, the only version that has ever existed, not a refusal."""
    raw = [{"symbol": "LEGACY", "signals": ["RVOL"], "rvol": 1.5}]
    entries, errors = parse_watchlist(raw)
    assert not errors and entries[0].symbol == "LEGACY"


def test_duplicate_symbol_across_scans_keeps_the_stronger_entry():
    scans = [_scan([make_entry("DUP", ["RVOL"], 1.0).as_record()]),
            _scan([make_entry("DUP", ["RVOL", "RS"], 2.0).as_record()])]
    targets, errors = select_targets(decisions=[], scans=scans)
    assert not errors
    dup = [t for t in targets if t.symbol == "DUP"]
    assert len(dup) == 1
    assert "signals=2" in dup[0].reason_selected   # the stronger entry won


def test_malformed_entry_is_skipped_and_recorded_never_raises():
    raw = [
        make_entry("GOOD1", ["RVOL"], 1.0).as_record(),
        {"symbol": "BAD_NO_SIGNALS"},              # missing signals
        ["NOT", "A", "DICT"],                       # the original 2026-08-17
                                                     # shape mismatch itself
        42,
        None,
        {"symbol": "BAD_RVOL_TYPE", "signals": ["RVOL"], "rvol": "high"},
        make_entry("GOOD2", ["RVOL"], 2.0).as_record(),
    ]
    entries, errors = parse_watchlist(raw)
    assert {e.symbol for e in entries} == {"GOOD1", "GOOD2"}
    assert len(errors) == 5


def test_candidate_and_watchlist_overlap_candidate_wins():
    dec = [{"kind": "decision", "decision_id": "D1", "symbol": "OVERLAP",
           "playbook_id": "HUNTER-001_v1", "t_utc": "2026-08-17T15:05:00Z"}]
    scans = [_scan([make_entry("OVERLAP", ["RVOL"], 5.0).as_record()])]
    targets, errors = select_targets(decisions=dec, scans=scans)
    assert not errors
    hit = [t for t in targets if t.symbol == "OVERLAP"][0]
    assert "hunter_candidate" in hit.reason_selected
    assert sum(1 for t in targets if t.symbol == "OVERLAP") == 1


def test_deterministic_tie_breaks_lexicographically_by_symbol():
    raw = [make_entry(s, ["RVOL"], 1.0).as_record()
          for s in ("ZEBRA", "ALPHA", "MIKE")]
    targets_a, _ = select_targets(decisions=[], scans=[_scan(raw)])
    targets_b, _ = select_targets(decisions=[], scans=[_scan(list(reversed(raw)))])
    order_a = [t.symbol for t in targets_a]
    order_b = [t.symbol for t in targets_b]
    assert order_a == order_b == ["ALPHA", "MIKE", "ZEBRA"]


def test_large_watchlist_is_capped_and_ordered():
    raw = [make_entry(f"S{i:03d}", ["RVOL"], float(i)).as_record()
          for i in range(500)]
    targets, errors = select_targets(decisions=[], scans=[_scan(raw)])
    assert not errors
    from apex.hunter.microscope import MAX_QUOTE_TARGETS
    assert len(targets) <= MAX_QUOTE_TARGETS
    # highest rvol first among equal (1) signal counts
    assert targets[0].symbol == "S499"


def test_unknown_rvol_ranks_below_known_rvol_at_equal_signal_count():
    """Never treats missing rvol as zero: a real rvol of 0.01 must rank
    ABOVE an unknown rvol, and an unknown rvol must never look like a
    confident zero-rvol reading."""
    raw = [make_entry("KNOWN_LOW", ["RVOL"], 0.01).as_record(),
          make_entry("UNKNOWN", ["RVOL"], None).as_record()]
    targets, _ = select_targets(decisions=[], scans=[_scan(raw)])
    order = [t.symbol for t in targets]
    assert order.index("KNOWN_LOW") < order.index("UNKNOWN")


# ---------------------------------------------------- process survival
def test_one_malformed_entry_never_kills_selection(tmp_path, monkeypatch):
    """Requirement: a malformed entry must not kill FastWatch, must not
    be silently swallowed, and valid entries must still be processed."""
    scans = [_scan([
        ["totally", "wrong", "shape"],
        make_entry("SURVIVOR", ["RVOL"], 1.0).as_record(),
    ])]
    targets, errors = select_targets(decisions=[], scans=scans)
    assert len(errors) == 1
    assert any(t.symbol == "SURVIVOR" for t in targets)


# --------------------------------------------------------- live rehearsal
def test_live_style_rehearsal_two_cycles_no_crash(tmp_path, monkeypatch):
    """Rehearse the EXACT 2026-08-17 failure shape: an empty watchlist,
    then the first natural (real, dict-shaped) entry arrives, across two
    consecutive cycles -- the transition that actually crashed FastWatch
    and stalled Frontier that morning."""
    ledger = tmp_path / "forward_ledger.jsonl"
    from apex.hunter.watchlist import ERRORS_LEDGER
    monkeypatch.setattr(
        "apex.hunter.watchlist.ERRORS_LEDGER", tmp_path / "errors.jsonl")

    # cycle 1: empty watchlist (this is how the real morning started)
    scan1 = _scan([], t_utc="2026-08-17T14:20:00Z")
    ledger.write_text(json.dumps(scan1) + "\n")
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    scans = [r for r in rows if r.get("kind") == "scan"]
    targets1, errors1 = select_targets(decisions=[], scans=scans[-4:])
    assert targets1 == () and errors1 == ()

    # cycle 2: the first REAL, dict-shaped, non-empty watchlist (this is
    # the exact moment the old code raised an uncaught KeyError)
    scan2 = _scan([
        make_entry("CBRS", ["GAP_AND_GO"], None,
                  rvol_status=RVOL_INVALID_SESSION).as_record(),
        make_entry("AXTI", ["GAP_AND_GO"], None,
                  rvol_status=RVOL_INVALID_SESSION).as_record(),
    ], t_utc="2026-08-17T14:52:10Z")
    with ledger.open("a") as f:
        f.write(json.dumps(scan2) + "\n")
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    scans = [r for r in rows if r.get("kind") == "scan"]
    targets2, errors2 = select_targets(decisions=[], scans=scans[-4:])
    assert not errors2                           # no malformed entries this time
    assert {t.symbol for t in targets2} == {"CBRS", "AXTI"}
    assert all(t.reason_selected.startswith("watchlist:")
              for t in targets2)
    # RVOL honesty survives the full round trip
    assert "rvol=UNKNOWN" in targets2[0].reason_selected \
        or "rvol=UNKNOWN" in targets2[1].reason_selected
