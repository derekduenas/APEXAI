"""APEX_CHECKPOINT_GRAPH -- the official pipeline as an explicit funnel.

THE IDEA (Profit Predator v1, Phase 18, made permanent). "Function A
calls function B" is not a checkpoint. A checkpoint is a NAMED gate with
declared inputs, pass/refuse conditions, a fail behavior, and a durable
artifact -- so that for any opportunity, the question "which valve
stopped the blood flow, and why?" has a mechanical answer:

    NVDA / opportunity d128...
    CP01 SENSOR            PASS
    CP04 DATA SUFFICIENCY  REFUSED  (RVOL_WINDOW_COVERAGE_INSUFFICIENT)
    DOWNSTREAM:            NOT_EVALUATED

Every checkpoint declares `evidence_artifact` -- where its verdicts
actually land on disk -- and `instrumented`: a checkpoint whose gate
exists in code but whose verdicts are not yet durably written says so
here, visibly, instead of being quietly counted as done.

decision_power: NONE -- this module DESCRIBES the funnel; the gates
themselves live in their own modules.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

CHECKPOINT_GRAPH_VERSION = "v1_2026_08_20"


class CheckpointGraphError(RuntimeError):
    pass


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    name: str
    producer: str                      # module that owns the gate
    inputs: tuple                      # what crosses INTO this edge
    pass_condition: str
    refuse_condition: str
    fail_behavior: str                 # what downstream sees on refusal
    evidence_artifact: str             # where verdicts land on disk
    downstream: tuple                  # checkpoint_ids
    required_authority: str
    instrumented: bool                 # verdicts durably persisted today?

    def as_record(self) -> dict:
        return {"kind": "apex_checkpoint", **asdict(self),
                "inputs": list(self.inputs),
                "downstream": list(self.downstream)}


CHECKPOINTS = (
    Checkpoint(
        "CP01", "SOURCE -> RAW EVENT", "apex.intraday.alpaca_fabric",
        ("websocket frames",),
        "frame received and queued", "queue full (counted drop)",
        "frames_dropped counter + reconnect event",
        "results/intraday/alpaca_fabric_health.json + "
        "alpaca_reconnect_events.jsonl",
        ("CP02",), "NONE", True),
    Checkpoint(
        "CP02", "RAW EVENT -> CANONICAL BAR", "apex.intraday.alpaca_fabric",
        ("trades", "quotes"),
        "bar built from in-minute trades; persisted to the accumulating "
        "session stream",
        "duplicate / out-of-order / future-dated tick rejected",
        "counter increment, tick excluded",
        "data/live/alpaca_fabric/bars/*.json", ("CP03",), "NONE", True),
    Checkpoint(
        "CP03", "BAR -> FEATURE", "scripts/frontier2_shadow_runtime",
        ("canonical bars",),
        "feature series constructed (price/RS/sector/breadth)",
        "no bars for subject",
        "empty series -> downstream NO_SUPPORT",
        "in-cycle (series are inputs, not artifacts)", ("CP04",),
        "NONE", False),
    Checkpoint(
        "CP04", "FEATURE -> SUFFICIENCY",
        "apex.intraday.feature_sufficiency",
        ("feature series", "coverage", "freshness"),
        "verdict VALID/LIMITED (or DEGRADED with consumer opt-in)",
        "INVALID / NOT_ESTIMABLE / DEGRADED without opt-in",
        "feature feeds [] -> Curve dimension NO_SUPPORT with named "
        "SUFFICIENCY_* reason",
        "results/frontier2/feature_sufficiency_refusals.jsonl",
        ("CP05",), "NONE", True),
    Checkpoint(
        "CP05", "SUFFICIENT FEATURE -> MARKET STATE",
        "apex.market_state.cross_section",
        ("sector bars", "SPY bars"),
        "series sufficient=True at declared quality",
        "below member floor / coverage floor",
        "curve_points() returns [] -> NO_SUPPORT",
        "in-cycle (CrossSectionalSeries carries its own verdict fields)",
        ("CP06",), "NONE", False),
    Checkpoint(
        "CP06", "MARKET STATE -> CURVE", "apex.frontier2.curve",
        ("dimension point series",),
        "SUPPORTED dimension with V2 z-score",
        "INSUFFICIENT_HISTORY / NO_SUPPORT / sigma undefined",
        "dimension abstains from likelihood/direction",
        "results/frontier2/curve_ledger.jsonl", ("CP07", "CP08"),
        "NONE", True),
    Checkpoint(
        "CP07", "CURVE -> LEADING EDGE", "apex.frontier2.leading_edge_map",
        ("directional transitions", "candidate dims"),
        "ranked row with entry/direction quality",
        "no directional transition this cycle",
        "symbol keeps entry_quality UNKNOWN (honest, not silent)",
        "results/frontier2/leading_edge_ledger.jsonl", ("CP09",),
        "NONE", True),
    Checkpoint(
        "CP08", "COGNITIVE STATE -> ASSASSIN", "apex.frontier2.assassin2",
        ("curve", "observation integrity", "model market"),
        "mechanisms checked; familiarity + caution derived",
        "lethal defect -> DATA_CONFLICT ceiling",
        "caution_level floors escalation downstream",
        "results/frontier2/assassin2_ledger.jsonl", ("CP09",),
        "NONE", True),
    Checkpoint(
        "CP09", "ASSASSIN -> CAPTAIN", "apex.frontier2.captain_shadow",
        ("trigger-field snapshot",),
        "review produces a state on the declared graph",
        "lethal familiarity / INVALID data -> DEGRADE/INVALIDATE",
        "terminal lineage closes; new thesis needs a new id",
        "results/frontier2/captain_shadow_ledger.jsonl", ("CP10",),
        "NONE", True),
    Checkpoint(
        "CP10", "CAPTAIN -> OPPORTUNITY", "scripts/frontier2_shadow_runtime",
        ("captain state",),
        "SERIOUS / WAIT_FOR_ENTRY escalation",
        "any lower state",
        "no funnel entry (visible in captain ledger)",
        "results/frontier2/expression_funnel_ledger.jsonl", ("CP11",),
        "NONE", True),
    Checkpoint(
        "CP11", "OPPORTUNITY -> CAPITAL", "apex.hunter.capital",
        ("candidate record", "forecast slot", "portfolio state"),
        "APPROVED with weight (requires FORWARD_ELIGIBLE + calibrated "
        "forecast -- structurally impossible for shadow candidates today)",
        "governance failure / no calibrated forecast / risk gates",
        "REFUSED with named reason codes, persisted",
        "results/frontier2/expression_funnel_ledger.jsonl", ("CP12",),
        "CAPITAL_SOVEREIGN", True),
    Checkpoint(
        "CP12", "CAPITAL -> EXPRESSION",
        "apex.options_research.expression_engine",
        ("thesis", "horizon", "surface", "candidates"),
        "candidate admitted past every eligibility gate",
        "REFUSE_* gates (thesis/horizon/mechanism/surface/liquidity)",
        "refusal recorded per candidate; NO_TRADE always present",
        "results/options_research/before_cards.jsonl", ("CP13",),
        "NONE", True),
    Checkpoint(
        "CP13", "EXPRESSION -> BEFORE CARD",
        "apex.options_research.before_card",
        ("expression decision", "captain qualities"),
        "card sealed outcome-blind (forbidden-field law enforced)",
        "never -- sealing is unconditional once expression ran",
        "n/a",
        "results/options_research/before_cards.jsonl", ("CP14",),
        "NONE", True),
    Checkpoint(
        "CP14", "BEFORE CARD -> SHADOW EXECUTION / NO_TRADE",
        "scripts/frontier2_shadow_runtime",
        ("before card", "capital verdict"),
        "explicit terminal decision persisted "
        "(NO_TRADE_DECISION today, by construction)",
        "n/a -- NO_TRADE is a pass, not a refusal",
        "PIPELINE_NEVER_REACHED_EXPRESSION is distinguishable from "
        "NO_TRADE_DECISION by the presence/absence of the terminal row",
        "results/frontier2/expression_funnel_ledger.jsonl", ("CP15",),
        "EXECUTION_SEALED", True),
    Checkpoint(
        "CP15", "OUTCOME -> MEMORY", "apex.memory.daily_market_memory",
        ("session artifacts",),
        "exactly one canonical memory sealed post-close",
        "duplicate canonical memory",
        "seal refused",
        "results/memory/daily_market_memory.jsonl", (), "NONE", True),
)

BY_ID = {c.checkpoint_id: c for c in CHECKPOINTS}


def validate() -> list:
    """Structural violations: dangling downstream, cycles, duplicates."""
    problems = []
    ids = [c.checkpoint_id for c in CHECKPOINTS]
    if len(ids) != len(set(ids)):
        problems.append("duplicate checkpoint ids")
    for c in CHECKPOINTS:
        for d in c.downstream:
            if d not in BY_ID:
                problems.append(f"{c.checkpoint_id} -> {d}: dangling edge")
    # cycle detection (DFS)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {i: WHITE for i in BY_ID}

    def dfs(i):
        color[i] = GREY
        for d in BY_ID[i].downstream:
            if d not in color:
                continue
            if color[d] == GREY:
                problems.append(f"cycle through {i} -> {d}")
            elif color[d] == WHITE:
                dfs(d)
        color[i] = BLACK

    for i in BY_ID:
        if color[i] == WHITE:
            dfs(i)
    return problems


def uninstrumented() -> list:
    """Checkpoints whose verdicts are not yet durably persisted --
    honest debt, listed mechanically instead of forgotten."""
    return [c.checkpoint_id for c in CHECKPOINTS if not c.instrumented]


def as_records() -> list:
    return [c.as_record() for c in CHECKPOINTS]
