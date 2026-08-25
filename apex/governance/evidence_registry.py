"""AUTHORITATIVE EVIDENCE REGISTRY.

VERIFY THE ARTIFACT, NOT THE ECHO answered: is this artifact real and
current? It never answered the question that actually bit us twice on
2026-08-24:

    IS THIS THE CANONICAL ARTIFACT FOR THIS METRIC?

Both failures were the same shape. Asked for the equity L2 reconnect
count, I read `alpaca_reconnect_events.jsonl` -- a real, current,
plausibly-named file that happened to be empty -- and reported "zero
reconnects" while the authoritative fabric health counters said 13.
Asked whether the acquisition daemon was healthy, I read its
application log, which was silent because the kernel had SIGKILLed it,
and called a 69-restart OOM loop "exits cleanly".

Plausible-looking is the trap. As the number of artifacts grows,
SOURCE SELECTION becomes its own epistemic problem, and a wrong source
produces a confident, well-formatted, entirely false number.

    VERIFY THE SOURCE, NOT JUST THE ARTIFACT.

Governed metrics resolve through this registry or not at all. Ambiguity
fails closed: two candidate sources with no declared authority is an
error, never a coin flip.

Deliberately minimal -- it solves the demonstrated failure class and
does not attempt to be a data-governance platform.

decision_power: NONE -- a governance primitive.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

NOT_ESTIMABLE = "NOT_ESTIMABLE"


class SourceAmbiguity(RuntimeError):
    """Refused: the metric has no single declared authoritative source."""


class NonCanonicalSource(RuntimeError):
    """Refused: a governed metric was read from a non-authoritative file."""


@dataclass(frozen=True)
class MetricSource:
    metric_id: str
    authoritative_source: str
    accessor: str                  # how to read it, in words
    authority: str                 # who/what makes it canonical
    freshness_requirement_s: float | None
    known_non_authoritative: tuple = ()
    why: str = ""

    def as_record(self) -> dict:
        return {"kind": "metric_source", **asdict(self)}


# Governed metrics. Each entry exists because getting it wrong has
# already cost us, or would cost us, a false conclusion.
REGISTRY: dict[str, MetricSource] = {
    "equity_l2_reconnect_count": MetricSource(
        metric_id="equity_l2_reconnect_count",
        authoritative_source="results/intraday/alpaca_fabric_health.json",
        accessor="counters.reconnects (and health_axes.reconnects_per_hour)",
        authority="the fabric process itself counts its own reconnects",
        freshness_requirement_s=600,
        known_non_authoritative=(
            "results/intraday/alpaca_reconnect_events.jsonl",),
        why="the events ledger records only reconnects the ledger writer "
            "observed; it was empty on 2026-08-24 while the fabric had "
            "counted 13, and that discrepancy produced a false "
            "'zero reconnects' in a live report"),
    "equity_l2_tape_continuity": MetricSource(
        metric_id="equity_l2_tape_continuity",
        authoritative_source="results/intraday/alpaca_fabric_health.json",
        accessor="health_axes.tape_continuity",
        authority="coverage measured against expected session minutes",
        freshness_requirement_s=600,
        known_non_authoritative=("coverage_fraction",),
        why="coverage_fraction reports symbols reachable, NOT minutes "
            "captured; it read 1.0 on a day that lost 16% of the tape"),
    "service_liveness": MetricSource(
        metric_id="service_liveness",
        authoritative_source="systemd unit state + NRestarts",
        accessor="systemctl show -p NRestarts -p Result; journalctl",
        authority="the supervisor observes deaths the process cannot log",
        freshness_requirement_s=None,
        known_non_authoritative=("the service's own application log",),
        why="a SIGKILLed process writes no traceback; the acquisition "
            "daemon's silent log looked like a clean exit while systemd "
            "had restarted it 69 times"),
    "options_day_pnl": MetricSource(
        metric_id="options_day_pnl",
        authoritative_source="options_live_ledger.jsonl "
                             "(kind=options_outcome)",
        accessor="pnl per resolved outcome",
        authority="quote-derived executable marks at sealed sides",
        freshness_requirement_s=None,
        known_non_authoritative=("scoreboard summary counts",),
        why="the scoreboard aggregates; the ledger is the record"),
    "options_thesis_outcome": MetricSource(
        metric_id="options_thesis_outcome",
        authoritative_source="results/day1_corrected/"
                             "day1_corrections.jsonl",
        accessor="corrected_fields (supersedes the original outcome)",
        authority="repaired resolver, official session-close boundary",
        freshness_requirement_s=None,
        known_non_authoritative=(
            "results/day1_frozen/options_live_ledger.jsonl "
            "(historical truth, SUPERSEDED interpretation)",),
        why="Day-1 originals carry defective directional labels; they "
            "are historical evidence, never training labels"),
}


def resolve_metric(metric_id: str, *, source: str | None = None) -> dict:
    """Look up a governed metric's canonical source, failing closed."""
    m = REGISTRY.get(metric_id)
    if m is None:
        raise SourceAmbiguity(
            f"{metric_id!r} is not in the registry -- a governed metric "
            f"with no declared authority may not be reported")
    if source is not None:
        if source in m.known_non_authoritative:
            raise NonCanonicalSource(
                f"{metric_id!r} was read from {source!r}, which is "
                f"explicitly NON-AUTHORITATIVE. Canonical: "
                f"{m.authoritative_source}. {m.why}")
        if source != m.authoritative_source:
            raise NonCanonicalSource(
                f"{metric_id!r} must come from "
                f"{m.authoritative_source!r}, not {source!r}")
    return m.as_record()


def assert_canonical(metric_id: str, source: str) -> dict:
    """Guard for report code: prove the source before printing a number."""
    return resolve_metric(metric_id, source=source)


def audit_registry() -> dict:
    """Every governed metric must have exactly one authoritative source."""
    problems = []
    for mid, m in REGISTRY.items():
        if not m.authoritative_source:
            problems.append(f"{mid}: no authoritative source")
        if m.authoritative_source in m.known_non_authoritative:
            problems.append(f"{mid}: source listed as both canonical "
                            f"and non-authoritative")
        if not m.why:
            problems.append(f"{mid}: no reason recorded")
    return {"kind": "registry_audit", "metrics": len(REGISTRY),
            "problems": problems,
            "verdict": "REGISTRY_COHERENT" if not problems
                       else "REGISTRY_INCOHERENT",
            "law": "VERIFY THE SOURCE, NOT JUST THE ARTIFACT"}
