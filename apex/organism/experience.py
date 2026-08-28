"""THE EXPERIENCE GRAPH — the organism's memory, never its truth.

A derived, rebuildable projection over the source ledgers, joined on
candidate_id / event_id / session. The hash-chained ledgers remain the
evidentiary authority; deleting this file loses nothing but time.

AS_KNOWN_AT IS THE MANDATORY QUERY. "What did we actually know at
10:31?" must be answerable without future contamination, so every node
carries known_from and the query filters on it -- the same single fence
that guards Catalyst.

decision_power: NONE_DERIVED.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    "options_decision": Path("results/outbox/v1_decisions.jsonl"),
    "equity_decision": Path("results/outbox/equity_shadow_decisions"
                            ".jsonl"),
    "btc_decision": Path("results/btc/paper_ledger.jsonl"),
    "catalyst_event": Path("results/catalyst/events.jsonl"),
    "catalyst_reaction": Path("results/catalyst/reactions.jsonl"),
    "paper_book": Path("results/organism/paper_book.jsonl"),
    "allocator": Path("results/organism/allocator_decisions.jsonl"),
    "research_board": Path("results/edgeforge/research_board.jsonl"),
    "census": Path("results/edgeforge/opportunity_census.jsonl"),
    # PARALLAX observations enter the MEMORY only -- the graph is
    # derived and nothing on a trading path reads it at decision time.
    # Stream names carry provenance so AS_KNOWN_AT answers arrive
    # tier-labeled: prospective vs retrospective commissioning.
    "parallax_prospective": Path("results/parallax/violations.jsonl"),
    "parallax_commissioning": Path("results/parallax/commissioning"
                                   ".jsonl"),
}

GRAPH = Path("results/organism/experience_graph.jsonl")


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _known_from(rec: dict) -> str:
    for k in ("known_from", "funded_utc", "refused_utc", "attached_utc",
              "sealed_utc", "run_utc", "recorded_utc", "T",
              "emitted_utc"):
        v = rec.get(k)
        if v:
            return str(v)
    return "UNKNOWN"


def rebuild(*, sources: dict | None = None,
            graph: Path | None = None) -> dict:
    """Project every source ledger into one queryable node stream.
    Overwrite-rebuild is legal precisely because the graph is derived:
    the ledgers are the truth and this is a view of them."""
    src = sources or SOURCES
    out = Path(graph or GRAPH)
    out.parent.mkdir(parents=True, exist_ok=True)
    counts, nodes = {}, []
    for stream, path in src.items():
        rows = _rows(Path(path))
        counts[stream] = len(rows)
        for rec in rows:
            payload = rec.get("payload") or rec
            nodes.append({
                "stream": stream,
                "known_from": _known_from(rec),
                "session": rec.get("session") or payload.get("session"),
                "candidate_id": (payload.get("candidate_id")
                                 or payload.get("evaluation_id")
                                 or payload.get("decision_id")),
                "symbol": payload.get("symbol"),
                "event_id": payload.get("event_id"),
                "kind": (rec.get("record_kind") or rec.get("kind")),
                "record": rec})
    nodes.sort(key=lambda n: n["known_from"])
    with out.open("w") as f:
        for n in nodes:
            f.write(json.dumps(n) + "\n")
    return {"kind": "experience_graph_rebuild",
            "rebuilt_utc": datetime.now(timezone.utc).isoformat(),
            "nodes": len(nodes), "streams": counts,
            "law": "derived and rebuildable; the ledgers are the truth",
            "decision_power": "NONE_DERIVED"}


def as_known_at(timestamp: str, *, symbol: str | None = None,
                candidate_id: str | None = None,
                streams: tuple | None = None,
                graph: Path | None = None, limit: int = 500) -> list:
    """Everything the organism knew at `timestamp` -- and NOTHING that
    was first known later, however relevant it became."""
    ts = str(timestamp)
    out = []
    for n in _rows(Path(graph or GRAPH)):
        if n["known_from"] == "UNKNOWN" or n["known_from"] > ts:
            continue
        if symbol and n.get("symbol") != symbol:
            continue
        if candidate_id and n.get("candidate_id") != candidate_id:
            continue
        if streams and n["stream"] not in streams:
            continue
        out.append(n)
        if len(out) >= limit:
            break
    return out


def trace(candidate_id: str, *, graph: Path | None = None) -> dict:
    """The end-to-end causal chain for one funded paper trade:
    decision -> allocation -> funding -> outcome, in known_from order."""
    nodes = [n for n in _rows(Path(graph or GRAPH))
             if n.get("candidate_id") == candidate_id
             or candidate_id in json.dumps(n.get("record", {}))[:4000]]
    nodes.sort(key=lambda n: n["known_from"])
    return {"kind": "causal_trace", "candidate_id": candidate_id,
            "links": [{"stream": n["stream"],
                       "known_from": n["known_from"],
                       "record_kind": n["kind"]} for n in nodes],
            "n_links": len(nodes),
            "decision_power": "NONE_DERIVED"}
