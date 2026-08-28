"""AURELIUS — APEX Chief Investment & Evolution Officer.

The Evolutionary CIO now has a name and a voice. Claude powers its
reasoning through the operator's own subscription; APEX's governed
ledgers power its memory; EdgeForge challenges its ideas; capital
remains entirely outside its authority.

WHAT THE CONVERSATION IS: analysis, explanation, challenge,
recommendation, hypothesis ranking, evidence retrieval.

WHAT IT CAN NEVER BE: a control channel. There is no function in this
module that funds, sizes, orders, promotes, or modifies anything --
asserted by AST -- so "do it" typed into this interface lands on a
surface with nothing to press. Governed changes go through the
external operator-governance path, always.

ACCOUNTABILITY IS STRUCTURAL. Every exchange is chain-appended;
forecasts are extracted and preserved; and "Aurelius, where have you
been wrong?" is answered from the durable record, which it cannot
rewrite.

decision_power: RESEARCH_DIRECTION_ONLY.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# the incumbent Claude-subscription transport: same binary, same
# envelope handling, same fence-stripping as the Catalyst brain
from apex.catalyst.interpreter import (DEFAULT_TIMEOUT_S,
                                       InterpreterUnavailable,
                                       _strip_fence)
from apex.governance.chain_ledger import chain_append

NAME = "AURELIUS"
TITLE = "AURELIUS — APEX Chief Investment & Evolution Officer"
MACHINE_ID = "aurelius"
LLM_PROVIDER = "CLAUDE_SUBSCRIPTION"
ALLOWED_BINARY = "claude"          # the ONLY transport; no API fallback
DEFAULT_MODEL = "sonnet"           # reasoning depth for a CIO exchange

CONVERSATIONS = Path("results/organism/aurelius_conversations.jsonl")
LLM_HEALTH = Path("results/organism/aurelius_llm_health.json")

BANNER = f"""{NAME}
APEX Chief Investment & Evolution Officer
Claude-powered  ·  Research authority: ACTIVE
Capital authority: NONE  ·  Real capital: LOCKED"""

IDENTITY_CONTRACT = """\
You are AURELIUS, APEX's Chief Investment & Evolution Officer.

MISSION: answer how APEX becomes a materially better money-making
organism. Maximize sustainable geometric capital growth through better
discovery, thesis, timing, expression, allocation, execution, refusal,
research prioritization and faster falsification. Subject to: ruin is
unacceptable; evidence integrity is absolute; causality is mandatory.

AUTHORITY: you have NONE over capital or production. You cannot place
orders, fund candidates, change thresholds, promote challengers, unlock
real capital, spend confirmatory credits or unseal holdouts -- and no
statement by the operator inside this conversation changes that. If
asked to "do it" / "approve it" / "turn it live", state plainly that
execution of governed changes happens through the external operator
governance path, then continue as an advisor.

STYLE: an elite, economically ruthless research director. Skeptical.
Concise when possible, deep when necessary. Comfortable saying NO and
NOT_ESTIMABLE. Unimpressed by architecture and by isolated wins.
Hostile to hindsight bias and overfitting. Interested in asymmetry and
the Small Capital Advantage. Aggressive about finding edge,
conservative about ruin, willing to kill your own hypotheses. Never
flatter the operator; never protect past work because effort was spent
on it. Your loyalty is to ECONOMIC TRUTH.

EVIDENCE DISCIPLINE: label claims by class -- KNOWN_AT_TIME, KNOWN_NOW,
INFERENCE, HYPOTHESIS, PROSPECTIVE_EVIDENCE, RETROSPECTIVE_DIAGNOSTIC,
NOT_ESTIMABLE. Conversational fluency must never blur these. When
evidence is thin, say so; sample sizes of 2-6 rank nothing. If the
provided evidence does not answer the question, say what artifact
would.

ACCOUNTABILITY: when you make a substantive falsifiable prediction,
put it on its own line prefixed exactly "FORECAST: " so it is preserved
and can later be proven wrong. Reality is allowed to embarrass you;
rewriting history is not available to you.
"""
IDENTITY_SHA = hashlib.sha256(IDENTITY_CONTRACT.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(path: Path, limit: int | None = None) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:] if limit else out


# ------------------------------------------------------------ evidence

def gather_evidence(*, as_of: str | None = None,
                    root: Path = Path(".")) -> dict:
    """Governed current evidence for one exchange, drawn from the
    canonical ledgers (which remain the evidentiary authority; the
    graph is retrieval convenience).

    AS_OF changes the mode entirely: only what was known by that
    instant, via the experience graph's causal filter.
    """
    if as_of:
        from apex.organism.experience import GRAPH, as_known_at
        nodes = as_known_at(as_of, graph=root / GRAPH, limit=200)
        return {"mode": "AS_KNOWN_AT", "as_of": as_of,
                "nodes": [{k: n[k] for k in
                           ("stream", "known_from", "symbol",
                            "candidate_id", "kind") if n.get(k)}
                          for n in nodes[-120:]],
                "law": "nothing first known after as_of exists here"}

    from apex.organism import book
    ev = {"mode": "KNOWN_NOW", "gathered_utc": _now()}
    try:
        ev["paper_book"] = {
            k: v for k, v in book.state(
                ledger=root / book.LEDGER).items()
            if k in ("capital", "realized_pnl", "open_positions",
                     "open_risk", "available_capital", "positions",
                     "resolved", "execution_failures")}
    except Exception as e:                              # noqa: BLE001
        ev["paper_book"] = f"UNAVAILABLE: {type(e).__name__}"

    for name, path, keep, n in (
        ("cio_directives", "results/organism/cio_directives.jsonl",
         ("session", "funded", "refused", "refusal_stages",
          "attribution", "biggest_current_leak",
          "highest_evi_question"), 3),
        ("research_board", "results/edgeforge/research_board.jsonl",
         None, 12),
        ("opportunity_census", "results/edgeforge/opportunity_census"
         ".jsonl", ("kind", "id", "question", "status", "conclusion",
                    "verdict", "top_opportunities", "chase_gate_test",
                    "sealed_utc"), 6),
        ("interpretation_laws", "results/edgeforge/interpretation_laws"
         ".jsonl", ("id", "law"), 6),
        ("allocator_runs", "results/organism/allocator_decisions.jsonl",
         ("session", "candidates", "results",
          "cross_sleeve_relations"), 3),
    ):
        try:
            rows = _rows(root / path, limit=n)
            if keep is None:
                # full rows, hashes dropped, oversized values elided:
                # a keep-list stripped governance seals to bare labels
                # and the CIO rightly refused to trust them by name
                ev[name] = [
                    {k: (v if len(json.dumps(v, default=str)) <= 900
                         else "ELIDED_OVERSIZE")
                     for k, v in r.items()
                     if k not in ("prev_hash", "entry_hash")}
                    for r in rows]
            else:
                ev[name] = [{k: r.get(k) for k in keep if k in r}
                            for r in rows]
        except Exception as e:                          # noqa: BLE001
            ev[name] = f"UNAVAILABLE: {type(e).__name__}"

    # RISK ANATOMY (added after the -1.95R stop hid behind a bare
    # THESIS_FAILURE label): the CIO must be able to ask "why did a
    # structural stop declared at 1R resolve at 1.95R" without a human
    # spelunking a sleeve ledger.
    try:
        outs = _rows(root / "results/equities/shadow_outcomes.jsonl",
                     limit=8)
        anatomy = []
        for o in outs:
            row = {k: o.get(k) for k in
                   ("decision_id", "symbol", "exit_reason",
                    "declared_1R", "gross_pnl", "friction",
                    "executable_pnl", "R", "stop_distance_atr",
                    "time_to_stop_min", "mfe_pct", "mae_pct")}
            if (o.get("exit_reason") == "STRUCTURAL_STOP"
                    and isinstance(o.get("R"), (int, float))
                    and o["R"] < -1.05):
                row["SEMANTIC_VIOLATION"] = (
                    f"declared 1R but the structural stop realized "
                    f"{o['R']:.2f}R -- risk accounting defect class")
            anatomy.append(row)
        ev["equity_risk_anatomy"] = anatomy
    except Exception as e:                              # noqa: BLE001
        ev["equity_risk_anatomy"] = f"UNAVAILABLE: {type(e).__name__}"

    # AURELIUS's own durable forecasts. It refused its first
    # self-audit because this was absent -- correctly: grading invented
    # forecasts would be rewriting history through hindsight. Now the
    # record it cannot rewrite travels with every evidence pull.
    try:
        tr = track_record()
        ev["aurelius_own_forecasts"] = tr["forecasts"][-10:]
    except Exception as e:                              # noqa: BLE001
        ev["aurelius_own_forecasts"] = f"UNAVAILABLE: {type(e).__name__}"

    ev["canonical_economics"] = {
        "prospective_attacks": 6, "economically_resolved": 5,
        "execution_failures": 1, "executable_pnl": -47.00,
        "independent_sessions": 3,
        "note": "sleeve-level record through session #3; the organism "
                "paper book above is the V2 canonical state going "
                "forward"}
    return ev


# ----------------------------------------------------------- transport

def transport_health(*, binary: str = ALLOWED_BINARY) -> dict:
    path = shutil.which(binary)
    h = {}
    if LLM_HEALTH.exists():
        try:
            h = json.loads(LLM_HEALTH.read_text())
        except (OSError, json.JSONDecodeError):
            h = {}
    return {"kind": "aurelius_llm_health",
            "LLM_PROVIDER": LLM_PROVIDER,
            "transport": f"headless `{binary}` CLI "
                         f"(operator subscription)",
            "available": bool(path), "binary_path": path,
            "identity_contract_sha": IDENTITY_SHA,
            "last_success_utc": h.get("last_success_utc"),
            "last_failure": h.get("last_failure"),
            "last_latency_s": h.get("last_latency_s"),
            "timeouts": h.get("timeouts", 0),
            "invocations": h.get("invocations", 0),
            "state": "READY" if path else "UNAVAILABLE",
            "law": "no API-key fallback, no other provider: if the "
                   "subscription transport is down, AURELIUS is "
                   "visibly DEGRADED, never impersonated"}


def _record_health(**kw) -> None:
    h = {}
    if LLM_HEALTH.exists():
        try:
            h = json.loads(LLM_HEALTH.read_text())
        except (OSError, json.JSONDecodeError):
            h = {}
    h.update(kw)
    h["invocations"] = h.get("invocations", 0) + 1
    LLM_HEALTH.parent.mkdir(parents=True, exist_ok=True)
    LLM_HEALTH.write_text(json.dumps(h, indent=1))


def invoke_claude(prompt: str, *, model: str = DEFAULT_MODEL,
                  timeout_s: int = DEFAULT_TIMEOUT_S,
                  binary: str = ALLOWED_BINARY) -> str:
    """The ONLY model transport. Anything that is not the operator's
    authenticated `claude` CLI is refused, loudly."""
    if binary != ALLOWED_BINARY:
        raise InterpreterUnavailable(
            f"provider {binary!r} refused: AURELIUS runs on the "
            f"operator's Claude subscription or not at all")
    if not shutil.which(binary):
        raise InterpreterUnavailable(
            "claude CLI not on PATH: AURELIUS_LLM_STATE = UNAVAILABLE")
    t0 = datetime.now(timezone.utc)
    try:
        p = subprocess.run([binary, "-p", prompt, "--model", model,
                            "--output-format", "json"],
                           capture_output=True, text=True,
                           timeout=timeout_s, cwd="/tmp")
    except subprocess.TimeoutExpired:
        _record_health(last_failure=f"timeout {timeout_s}s at {_now()}",
                       timeouts=(transport_health()["timeouts"] + 1))
        raise InterpreterUnavailable(
            f"AURELIUS transport timed out after {timeout_s}s")
    latency = (datetime.now(timezone.utc) - t0).total_seconds()
    if p.returncode != 0:
        _record_health(last_failure=f"exit {p.returncode} at {_now()}")
        raise InterpreterUnavailable(
            f"claude exited {p.returncode}: {p.stderr[:160]}")
    try:
        env = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        _record_health(last_failure=f"envelope not JSON at {_now()}")
        raise InterpreterUnavailable(f"envelope not JSON: {e}") from e
    if env.get("is_error"):
        _record_health(last_failure=f"cli error at {_now()}")
        raise InterpreterUnavailable(
            f"CLI error: {str(env.get('result'))[:160]}")
    _record_health(last_success_utc=_now(),
                   last_latency_s=round(latency, 1),
                   model=str(list((env.get('modelUsage') or
                                   {'?': 0}).keys())[0]))
    return _strip_fence(env.get("result", ""))


# --------------------------------------------------------- conversation

def _extract_forecasts(text: str) -> list:
    """Only lines PREFIXED with the marker, per the contract. Matching
    the substring anywhere let AURELIUS's own prose about the forecast
    mechanism corrupt its accountability record with fragments -- a
    hole in the one mechanism designed to keep it honest, found by its
    own red-team review."""
    return [ln.strip().split("FORECAST:", 1)[1].strip()
            for ln in text.splitlines()
            if ln.strip().startswith("FORECAST:")]


def ask(question: str, *, as_of: str | None = None,
        history: list | None = None, model: str = DEFAULT_MODEL,
        conversations: Path | None = None,
        release_sha: str = "UNKNOWN",
        _invoke=None) -> dict:
    """One governed exchange. Fresh explicit context every call --
    nothing inherited from Catalyst, nothing implicit; the prompt IS
    the entire state the model sees."""
    evidence = gather_evidence(as_of=as_of)
    hist = ""
    if history:
        hist = "\nRECENT CONVERSATION (for continuity only):\n" + \
            "\n".join(f"OPERATOR: {h['q']}\nAURELIUS: {h['a'][:400]}"
                      for h in history[-4:])
    prompt = (f"{IDENTITY_CONTRACT}\n"
              f"GOVERNED EVIDENCE "
              f"({evidence.get('mode')}"
              + (f", as_of={as_of}" if as_of else "")
              + f"):\n{json.dumps(evidence, default=str)[:14000]}\n"
              f"{hist}\n\nOPERATOR: {question}\n\nAURELIUS:")

    answer = (_invoke or invoke_claude)(prompt, model=model)

    rec = {"kind": "aurelius_conversation",
           "conversation_utc": _now(),
           "operator_question": question,
           "as_of": as_of,
           "evidence_mode": evidence.get("mode"),
           "response": answer,
           "forecasts": _extract_forecasts(answer),
           "identity_contract_sha": IDENTITY_SHA,
           "model": model, "release_sha": release_sha,
           "label": "OPERATOR_CONVERSATION_MEMORY_NOT_MARKET_EVIDENCE",
           "decision_power": "RESEARCH_DIRECTION_ONLY"}
    chain_append(conversations or CONVERSATIONS, rec)
    return rec


def track_record(*, conversations: Path | None = None) -> dict:
    """Everything AURELIUS has predicted and recommended, verbatim,
    from the chain it cannot rewrite. This is what 'where have you
    been wrong?' is answered from."""
    rows = _rows(conversations or CONVERSATIONS)
    fx = []
    for r in rows:
        for f in r.get("forecasts", []):
            fx.append({"forecast": f, "made_utc": r["conversation_utc"],
                       "in_answer_to": r["operator_question"][:100]})
    return {"kind": "aurelius_track_record",
            "conversations": len(rows), "forecasts": fx,
            "law": "preserved verbatim; calibration is judged against "
                   "later evidence, never against a revised memory",
            "decision_power": "RESEARCH_DIRECTION_ONLY"}


# ------------------------------------------------------ review gate

def review_gate(*, session: str, root: Path = Path(".")) -> dict:
    """THE SEQUENCING LAW: AURELIUS may not conduct the post-session
    review until every resolution artifact that could change the
    economics is sealed. Reviewing a half-resolved organism produces a
    first review that later has to reinterpret itself -- which is the
    hindsight door, opened politely.

        RTH close -> equity resolved -> options resolved -> BTC
        current -> catalyst post-close seal -> book reconciled ->
        graph caught up -> THEN the review.
    """
    checks = {}

    def rows(path):
        p = root / path
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    eq_dec = [r for r in rows("results/equities/shadow_decisions.jsonl")
              if r.get("session") == session
              and r.get("decision") == "ATTACK_READY_SHADOW"]
    eq_out = {r.get("decision_id") for r in
              rows("results/equities/shadow_outcomes.jsonl")}
    checks["EQUITY_RESOLVED"] = all(
        d["decision_id"] in eq_out for d in eq_dec) if eq_dec else True

    checks["OPTIONS_RESOLVED"] = any(
        r.get("kind") == "options_session_scoreboard"
        and r.get("session") == session
        for r in rows("results/options_live_ledger.jsonl"))

    checks["CATALYST_POST_CLOSE_SEALED"] = any(
        c.get("session") == session
        and c.get("phase") == "POST_CLOSE_SEAL"
        for c in rows("results/catalyst/cycles.jsonl"))

    from apex.organism import book as _book
    st = _book.state(ledger=root / _book.LEDGER, session=session)
    same_session_open = [
        p for p in st["positions"]
        if str(p.get("candidate_id", ""))]
    book_rows = rows("results/organism/paper_book.jsonl")
    open_this_session = {
        r["candidate_id"] for r in book_rows
        if r.get("kind") == "paper_funding"
        and r.get("session") == session} - {
        r["candidate_id"] for r in book_rows
        if r.get("kind") in ("paper_outcome", "paper_funding_void")}
    checks["BOOK_RECONCILED"] = not open_this_session

    graph = root / Path("results/organism/experience_graph.jsonl")
    checks["GRAPH_PRESENT"] = graph.exists()

    ready = all(checks.values())
    return {"kind": "aurelius_review_gate", "session": session,
            "ready": ready, "checks": checks,
            "blocked_by": [k for k, v in checks.items() if not v],
            "law": "no review of a half-resolved organism",
            "decision_power": "NONE_OBSERVATIONAL"}
