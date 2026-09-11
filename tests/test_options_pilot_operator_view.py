"""M6 — the operator view renders only persisted records, each linked by seq; the scale script's checks hold."""
import json

from apex.options_pilot import ledger as L, operator_view as OV, session as S
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0


def test_operator_view_links_every_item_to_a_persisted_record(tmp_path):
    h = SyntheticHarness(tmp_path / "p.jsonl", session_id="OV-1", risk="certified")
    src = h.sources(); src.pop("exit_quote_fn")
    d = S.scan(h.bd, symbol="SPY", seq=1, **src)
    fill = d["receipts"]["fill"]
    h.t = L.read_all(h.ledger)[fill["seq"] - 1]["exit_schedule"]["exit_due_epoch"]
    S.resolve(h.bd, fill_receipt=fill, exit_quote_fn=h.exit_quotes)
    h.quotes.fail_with = ConnectionError("down")
    S.scan(h.bd, symbol="SPY", seq=2, **src)
    view = OV.build_view(h.ledger, session_id="OV-1", now_epoch=h.now(), release="synthetic-release",
                         model_versions={"forecast": "SYNTHETIC_FIXTURE_MODEL"}, feed_status={"status": "SYNTHETIC_FIXTURE", "last_bar_available_epoch": h.now() - 30})
    rows = L.read_all(h.ledger)
    for group, items in view["recent"].items():
        for it in items:
            rec = rows[it["seq"] - 1]
            assert rec["entry_hash"].startswith(it["entry_hash"]) and rec["session_id"] == "OV-1"
    assert view["recent"]["fills"][0]["status"] == "FILLED" and view["recent"]["outcomes"][0]["pnl"] == 18.03
    assert view["recent"]["fills"][1]["decision"] == "REFUSE" and view["recent"]["decisions"][1]["decision"] == "REFUSE"
    assert view["book"]["cash_identity"]["holds"] and view["process_health"]["chain_verified"] is True
    assert view["feed"]["last_bar_age_s"] == 30 and view["policy"]["fee_provenance"] == "SYNTHETIC_FIXTURE"
    assert view["law"].startswith("every item links to a persisted record")
    txt = OV.render_text(view)
    assert "seq=" in txt and "chain_ok=True" in txt and "gauge" not in txt.lower()
    json.dumps(view, allow_nan=False, default=str)
