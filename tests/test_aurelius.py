"""AURELIUS — identity, transport law, memory, and the absent throne.

The most important tests prove what the conversation CANNOT do: there
is no function to press when the operator types "do it"."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from apex.catalyst.interpreter import InterpreterUnavailable
from apex.organism import aurelius as AU


# ============================================================ IDENTITY

def test_the_cio_has_a_name():
    assert AU.NAME == "AURELIUS"
    assert AU.MACHINE_ID == "aurelius"
    assert "Chief Investment & Evolution Officer" in AU.TITLE
    assert "Capital authority: NONE" in AU.BANNER


def test_the_identity_contract_is_sha_stamped():
    import hashlib
    assert AU.IDENTITY_SHA == hashlib.sha256(
        AU.IDENTITY_CONTRACT.encode()).hexdigest()[:16]
    for law in ("ECONOMIC TRUTH", "NOT_ESTIMABLE", "FORECAST: ",
                "cannot place"):
        assert law in AU.IDENTITY_CONTRACT


# ==================================================== TRANSPORT LAW

def test_only_the_claude_subscription_transport_is_accepted():
    with pytest.raises(InterpreterUnavailable, match="refused"):
        AU.invoke_claude("hi", binary="openai")
    with pytest.raises(InterpreterUnavailable, match="refused"):
        AU.invoke_claude("hi", binary="ollama")


def test_no_api_key_dependency_exists():
    src = Path(AU.__file__).read_text()
    for banned in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "api_key",
                   "Authorization", "Bearer"):
        assert banned not in src, f"aurelius references {banned}"


def test_missing_cli_is_visible_degradation_not_impersonation(
        monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda b: None)
    with pytest.raises(InterpreterUnavailable, match="UNAVAILABLE"):
        AU.invoke_claude("hi")
    th = AU.transport_health()
    assert th["state"] == "UNAVAILABLE"
    assert th["LLM_PROVIDER"] == "CLAUDE_SUBSCRIPTION"


# ========================================= THE ABSENT CONTROL SURFACE

def test_the_conversation_has_nothing_to_press():
    """'Do it' typed at AURELIUS must land on a surface with no lever:
    no function in the module funds, orders, sizes or promotes, and it
    never imports a book mutator."""
    tree = ast.parse(Path(AU.__file__).read_text())
    banned_calls = {"fund", "refuse", "attach_outcome", "allocate",
                    "place_order", "submit_order", "void_funding",
                    "promote", "compete", "seal_decision"}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert n.name not in banned_calls
        if isinstance(n, ast.Call):
            f = n.func
            name = (f.id if isinstance(f, ast.Name)
                    else f.attr if isinstance(f, ast.Attribute)
                    else None)
            assert name not in banned_calls, f"aurelius calls {name}()"
        if isinstance(n, ast.ImportFrom):
            assert not any(a.name in banned_calls for a in n.names)


def test_the_cli_wrapper_is_equally_unarmed():
    tree = ast.parse(Path("scripts/aurelius.py").read_text())
    for n in ast.walk(tree):
        mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module or ""] if isinstance(n, ast.ImportFrom)
                else [])
        for m in mods:
            assert "book" not in m and "allocator" not in m, \
                f"the chat CLI imports {m}"


def test_the_contract_itself_refuses_authorization_language():
    assert "do it" in AU.IDENTITY_CONTRACT.lower()
    assert "external operator" in AU.IDENTITY_CONTRACT
    assert "governance path" in AU.IDENTITY_CONTRACT


# ================================================= CONVERSATION MEMORY

def _fake_invoke(answer):
    def f(prompt, model="sonnet"):
        f.last_prompt = prompt
        return answer
    f.last_prompt = None
    return f


def test_an_exchange_is_chain_appended_and_forecasts_extracted(tmp_path):
    conv = tmp_path / "conv.jsonl"
    rec = AU.ask("what next?", conversations=conv,
                 _invoke=_fake_invoke(
                     "Evidence is thin.\n"
                     "FORECAST: CHASE-BAND will weaken across the next "
                     "five sessions.\nNothing else is estimable."))
    assert rec["forecasts"] == ["CHASE-BAND will weaken across the "
                                "next five sessions."]
    on_disk = [json.loads(l) for l in conv.read_text().splitlines()]
    assert on_disk[0]["kind"] == "aurelius_conversation"
    assert on_disk[0]["label"] == \
        "OPERATOR_CONVERSATION_MEMORY_NOT_MARKET_EVIDENCE"


def test_where_have_you_been_wrong_reads_the_durable_record(tmp_path):
    conv = tmp_path / "conv.jsonl"
    AU.ask("q1", conversations=conv,
           _invoke=_fake_invoke("FORECAST: equity beats options in "
                                "trend states."))
    AU.ask("q2", conversations=conv,
           _invoke=_fake_invoke("no new forecast."))
    tr = AU.track_record(conversations=conv)
    assert tr["conversations"] == 2
    assert len(tr["forecasts"]) == 1
    assert "equity beats options" in tr["forecasts"][0]["forecast"]
    assert "never against a revised memory" in tr["law"]


# ======================================================== AS_KNOWN_AT

def test_as_of_switches_to_causal_mode(tmp_path, monkeypatch):
    from apex.organism import experience as EX
    g = tmp_path / "g.jsonl"
    g.write_text(json.dumps(
        {"stream": "paper_book", "known_from": "2026-08-28 10:00:00",
         "symbol": "SPY", "candidate_id": "c1", "kind": "paper_funding",
         "record": {}}) + "\n" + json.dumps(
        {"stream": "paper_book", "known_from": "2026-08-28 15:00:00",
         "symbol": "SPY", "candidate_id": "c2", "kind": "paper_outcome",
         "record": {}}) + "\n")
    monkeypatch.setattr(EX, "GRAPH", g)
    import os
    monkeypatch.chdir("/")           # root prefix makes GRAPH absolute
    ev = AU.gather_evidence(as_of="2026-08-28 12:00:00",
                            root=Path("/"))
    assert ev["mode"] == "AS_KNOWN_AT"
    ids = [n.get("candidate_id") for n in ev["nodes"]]
    assert "c1" in ids and "c2" not in ids, \
        "a 15:00 outcome leaked into a 12:00 question"


def test_the_prompt_carries_only_explicit_context(tmp_path):
    """No shared mutable state with Catalyst and no implicit carryover:
    the prompt is rebuilt from governed evidence each call."""
    conv = tmp_path / "c.jsonl"
    inv = _fake_invoke("ok")
    AU.ask("first", conversations=conv, _invoke=inv)
    p1 = inv.last_prompt
    AU.ask("second", conversations=conv, _invoke=inv)
    p2 = inv.last_prompt
    assert "first" not in p2, "prior exchange leaked without history"
    assert AU.IDENTITY_CONTRACT[:60] in p1 and \
        AU.IDENTITY_CONTRACT[:60] in p2
    # catalyst's brain contract is a different document entirely
    from apex.catalyst.brain import PROMPT_CONTRACT
    assert PROMPT_CONTRACT[:60] not in p1


def test_history_is_opt_in_and_bounded(tmp_path):
    conv = tmp_path / "c.jsonl"
    inv = _fake_invoke("ok")
    AU.ask("later question", conversations=conv,
           history=[{"q": "earlier question", "a": "earlier answer"}],
           _invoke=inv)
    assert "earlier question" in inv.last_prompt
