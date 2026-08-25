"""CHRONOS EPOCHS — the organism's beliefs, reconstructable at any
historical moment.

The question an epoch answers is exactly this one:

    WHAT DID EDGEFORGE BELIEVE THEN?

not "what does today's EdgeForge think would have been smart then".
The difference is the entire value of the replay. Today's model
grading yesterday's world with today's knowledge is a flattering
historian; an epoch chain is a diary written in ink.

Epochs are hash-chained and append-only. Each carries the knowledge
cutoff, the code identity, the live edge library, the retirements,
the hallucination rate as measured THEN, and the world-source
authorities as they stood THEN. Reconstruction reads the chain up to
a timestamp and refuses to synthesize anything the chain does not
contain.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.chronos import EVIDENCE_LABEL
from apex.chronos.clock import ChronosViolation, _parse
from apex.governance.chain_ledger import chain_append

EPOCH_FIELDS = (
    "epoch_id", "knowledge_cutoff", "code_sha", "dataset_boundary",
    "active_edge_library", "retired_edges", "candidate_registry",
    "credibility_state", "world_source_authority",
    "research_hallucination_rate", "capital_policy_state")


def write_epoch(ledger: Path, *, epoch: dict) -> dict:
    """Append one epoch checkpoint. Every field present, always --
    an epoch with a hole is a belief nobody can reconstruct."""
    missing = [f for f in EPOCH_FIELDS if f not in epoch]
    if missing:
        raise ChronosViolation(
            f"epoch refuses to seal with missing fields {missing}: a "
            f"checkpoint with a hole is a belief nobody can "
            f"reconstruct")
    prior = read_epochs(ledger)
    if prior:
        last = prior[-1]
        if _parse(epoch["knowledge_cutoff"]) <= \
                _parse(last["knowledge_cutoff"]):
            raise ChronosViolation(
                f"epoch knowledge_cutoff {epoch['knowledge_cutoff']} "
                f"does not advance past {last['knowledge_cutoff']}: "
                f"the organism does not un-know things")
    rec = {"kind": "chronos_epoch",
           "evidence_label": EVIDENCE_LABEL, **epoch}
    chain_append(ledger, rec)
    return rec


def read_epochs(ledger: Path) -> list:
    if not ledger.exists():
        return []
    out = []
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "chronos_epoch":
            out.append(r)
    return out


def beliefs_at(ledger: Path, *, timestamp: str) -> dict:
    """Reconstruct what the organism believed at a historical moment:
    the latest epoch whose knowledge_cutoff does not exceed the
    timestamp. Nothing is synthesized; if no epoch predates the
    moment, the honest answer is that the organism did not exist yet."""
    t = _parse(timestamp)
    candidates = [e for e in read_epochs(ledger)
                  if _parse(e["knowledge_cutoff"]) <= t]
    if not candidates:
        return {"kind": "beliefs_at", "timestamp": timestamp,
                "verdict": "ORGANISM_DID_NOT_EXIST_YET",
                "decision_power": "NONE_RESEARCH"}
    e = candidates[-1]
    return {"kind": "beliefs_at", "timestamp": timestamp,
            "verdict": "RECONSTRUCTED",
            "epoch_id": e["epoch_id"],
            "knowledge_cutoff": e["knowledge_cutoff"],
            "beliefs": {f: e[f] for f in EPOCH_FIELDS},
            "law": "what did the organism believe THEN -- never what "
                   "today's organism thinks would have been smart "
                   "then",
            "decision_power": "NONE_RESEARCH"}


def intelligence_trajectory(ledger: Path) -> dict:
    """APEX intelligence through time: is the organism becoming
    harder to fool? Plotted from what each epoch measured about
    itself at the time -- hallucination rate, library size,
    retirements -- never recomputed with hindsight."""
    epochs = read_epochs(ledger)
    if len(epochs) < 2:
        return {"kind": "intelligence_trajectory",
                "verdict": "INSUFFICIENT_EPOCHS",
                "n_epochs": len(epochs),
                "decision_power": "NONE_RESEARCH"}
    rows = []
    for e in epochs:
        rh = e.get("research_hallucination_rate") or {}
        rows.append({
            "epoch_id": e["epoch_id"],
            "knowledge_cutoff": e["knowledge_cutoff"],
            "null_over_bar_rate": rh.get("null_over_bar_rate"),
            "false_discovery_restraint":
                rh.get("false_discovery_restraint"),
            "n_active_edges": len(e.get("active_edge_library", [])),
            "n_retired": len(e.get("retired_edges", []))})
    rates = [r["null_over_bar_rate"] for r in rows
             if isinstance(r["null_over_bar_rate"], (int, float))]
    first_half = rates[: len(rates) // 2]
    second_half = rates[len(rates) // 2:]
    hardening = None
    if first_half and second_half:
        import statistics
        hardening = (statistics.median(second_half)
                     < statistics.median(first_half))
    return {"kind": "intelligence_trajectory",
            "n_epochs": len(epochs), "rows": rows,
            "becoming_harder_to_fool": hardening,
            "law": "measured by what each epoch knew about itself at "
                   "the time, never recomputed with hindsight",
            "decision_power": "NONE_RESEARCH"}
