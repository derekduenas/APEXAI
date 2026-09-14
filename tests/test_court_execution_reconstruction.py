"""Independent execution checks on the retained synthetic FULL flight.

Rehashed corruption fixtures test semantic checks separately from chain hashes.
No market data, provider calls, model fitting or operational authorization.
"""
import hashlib
import json
from pathlib import Path

import pytest

from apex.court.verify import reconstruct


FIXTURE = Path(__file__).resolve().parents[1] / "docs/evidence/organism_court_001/runs/fc-FULL-500"


@pytest.fixture
def run(tmp_path):
    for name in ("ledger.jsonl", "court_run.json"):
        (tmp_path / name).write_bytes((FIXTURE / name).read_bytes())
    return tmp_path


def rewrite(run, mutate, *, rehash=True):
    rows = [json.loads(line) for line in (run / "ledger.jsonl").read_text().splitlines()]
    by = {r["kind"]: r for r in rows}
    mutate(by, rows)
    if rehash:
        previous = "GENESIS"
        for row in rows:
            # Preserve valid reference hashes so the tested failure is semantic.
            for value in row.values():
                if isinstance(value, dict) and "seq" in value and "entry_hash" in value:
                    value["entry_hash"] = rows[value["seq"] - 1]["entry_hash"]
            row["prev_hash"] = previous
            body = {k: v for k, v in row.items() if k != "entry_hash"}
            row["entry_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            previous = row["entry_hash"]
    (run / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_full_funnel_round_trip_is_reconstructed(run):
    result = reconstruct(run)
    assert result["problems"] == []
    proof = result["execution_verification"]
    assert proof["chain_verified"] and proof["funnel_link_verified"]
    assert proof["selection_rule"].startswith("FULL_FUNNEL_V1")
    assert proof["entry_debit"] == 250
    assert proof["gross_recomputed"] == 20
    assert proof["pnl_recomputed"] == 19.91
    assert proof["open_positions"] == 0
    assert result["pnl_agrees"] is True


def test_producer_summary_is_not_accounting_evidence(run):
    summary = json.loads((run / "court_run.json").read_text())
    summary.update(policy="PILOT_RULE_V2", decision="WAIT", pnl=99999)
    (run / "court_run.json").write_text(json.dumps(summary))
    assert reconstruct(run)["execution_verification"]["pnl_recomputed"] == 19.91


@pytest.mark.parametrize("kind,field,value,reason", [
    ("pilot_outcome", "cashflow_exit", 999, "exit_cashflow"),
    ("pilot_fill", "cashflow_entry", -1, "entry_cashflow"),
    ("pilot_outcome", "exit_price", 3, "exit_bid"),
    ("pilot_fill", "price", 3, "entry_ask"),
    ("pilot_outcome", "contract_id", "WRONG", "OUTCOME_FILL_MISMATCH"),
    ("pilot_fill", "quantity_filled", True, "INVALID_FILL_QUANTITY"),
    ("pilot_fill", "quantity_filled", 2, "INVALID_FILL_QUANTITY"),
])
def test_consistently_rehashed_accounting_corruption_refuses(run, kind, field, value, reason):
    rewrite(run, lambda by, rows: by[kind].update({field: value}))
    result = reconstruct(run)
    assert result["execution_verification"]["chain_verified"]
    assert any(reason in p for p in result["problems"])


def test_matching_false_gross_and_net_do_not_fool_verifier(run):
    rewrite(run, lambda by, rows: by["pilot_outcome"].update(gross_pnl=100, pnl=99.91))
    assert "VALUE_MISMATCH:gross_pnl" in reconstruct(run)["problems"]


def test_chain_corruption_refuses_before_accounting(run):
    rewrite(run, lambda by, rows: by["pilot_session_close"].update(completion="ALTERED"), rehash=False)
    result = reconstruct(run)
    assert result["problems"] == ["CHAIN_INVALID:8"]
    assert not result["execution_verification"]["chain_verified"]


def test_unknown_fee_is_not_zero(run):
    rewrite(run, lambda by, rows: by["pilot_outcome"]["fees_exit"].update(total=None))
    assert any("UNKNOWN_OR_INVALID_NUMBER" in p for p in reconstruct(run)["problems"])


def test_fee_identity_change_refuses_despite_identical_total(run):
    def mutate(by, rows):
        by["pilot_outcome"]["fees_exit"]["fee_identity"]["authorization_digest"] = "other"
    rewrite(run, mutate)
    assert "FEE_IDENTITY_MISMATCH:SELL" in reconstruct(run)["problems"]


def test_proposal_change_cannot_disappear_at_intent(run):
    rewrite(run, lambda by, rows: by["pilot_funnel"]["proposal"].update(reference_ask=9))
    assert "PROPOSAL_INTENT_MISMATCH:reference_ask" in reconstruct(run)["problems"]


def test_duplicate_discharge_refuses(run):
    rewrite(run, lambda by, rows: rows.append(dict(by["pilot_outcome"])))
    assert "DUPLICATE_DISCHARGE" in reconstruct(run)["problems"]


def test_incomplete_book_does_not_pass_as_closed(run):
    rewrite(run, lambda by, rows: by["pilot_session_close"]["book"].update(n_positions=1))
    assert "VALUE_MISMATCH:book_positions" in reconstruct(run)["problems"]


@pytest.mark.parametrize("text", ['{"x": NaN}', '{"x":1e999}', '{"x":1,"x":2}', 'null', '{'])
def test_malformed_records_return_named_failure(run, text):
    (run / "ledger.jsonl").write_text(text)
    assert reconstruct(run)["problems"][0].startswith("INPUT_INVALID:")


def test_empty_ledger_is_not_a_successful_no_trade(run):
    (run / "ledger.jsonl").write_text("")
    assert reconstruct(run)["problems"] == ["EMPTY_LEDGER"]


def test_cli_exit_status_tracks_verification(run):
    import subprocess
    import sys
    command = [sys.executable, "-m", "apex.court.verify", str(run)]
    good = subprocess.run(command, capture_output=True, text=True)
    assert good.returncode == 0, good.stderr
    assert json.loads(good.stdout)["execution_verification"]["funnel_link_verified"]
    (run / "ledger.jsonl").write_text("{}\n")
    bad = subprocess.run(command, capture_output=True, text=True)
    assert bad.returncode == 1
    assert json.loads(bad.stdout)["problems"]
