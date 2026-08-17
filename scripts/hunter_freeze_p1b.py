#!/usr/bin/env python
"""Freeze P1B dependencies: hash each artifact and register its BIRTH.

Run once per version. A birth is append-only; re-running refuses names
already registered (a changed artifact is a new version under a new name).
From each birth forward — and only forward — that dependency's forecasts
can qualify as EODHD_FORWARD evidence.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402

from apex.hunter.birth import REGISTRY, load_births  # noqa: E402

ARTIFACTS = {
    "HUNTER-FORWARD-PROTOCOL_v1": (
        "protocol", ("HUNTER-FORWARD-PROTOCOL.md",)),
    "hunter_feature_schema_v1": (
        "feature_schema", ("apex/hunter/chartstate.py",
                           "apex/hunter/relstrength.py")),
    "hunter_rule_model_v1": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py")),
    # v1.1: forward_pass ledger readers fixed post-mint (chain entries are
    # flat, not wrapped) BEFORE any forecast existed; birth.py (the
    # eligibility law itself) now hashed too. Append-only: v1 stays.
    "hunter_rule_model_v1.1": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py", "apex/hunter/birth.py")),
    "HUNTER-001_v1": (
        "playbook", ("docs/HUNTER-001-PLAYBOOK.md",
                     "apex/hunter/playbooks_v1.py")),
    "HUNTER-002_v1": (
        "playbook", ("docs/HUNTER-002-PLAYBOOK.md",
                     "apex/hunter/playbooks_v1.py")),
    # Phase 2: frozen baselines are a dependency like any playbook —
    # a baseline decision's forward evidence starts at THIS birth
    "HUNTER-BASELINES_v1": (
        "playbook", ("apex/hunter/baselines.py",)),
    # v1.2: baselines wired into decision_pass, geometry-free realization,
    # neff + scoreboard added. Append-only; v1/v1.1 stay.
    "hunter_rule_model_v1.2": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py", "apex/hunter/birth.py",
                  "apex/hunter/baselines.py", "apex/hunter/neff.py")),
    # v1.3 (Phase 4): APEX CAPITAL gate wired into the decision pass —
    # candidate -> risk -> cost -> capacity -> portfolio -> reasoned final
    # state; forecast slot typed NOT_YET_AVAILABLE; no execution path.
    "hunter_rule_model_v1.3": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py", "apex/hunter/birth.py",
                  "apex/hunter/baselines.py", "apex/hunter/neff.py",
                  "apex/hunter/capital.py")),
    # v1.4 (full spine): every DECISION-AFFECTING file in the intelligence
    # pass — bundle assembly, analog retrieval (feeds capital caution),
    # memory firewall, swarm interface, monotone-caution capital. The
    # simulator/ML/paper modules are NOT decision-affecting in production
    # (diagnostic / UNTRAINED / NOT_AUTHORIZED) and enter the artifact
    # when they gain influence.
    "hunter_rule_model_v1.4": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py", "apex/hunter/birth.py",
                  "apex/hunter/baselines.py", "apex/hunter/neff.py",
                  "apex/hunter/capital.py", "apex/hunter/forecast.py",
                  "apex/analog/engine.py", "apex/hunter/memory.py",
                  "apex/hunter/swarm.py")),
    # v1.5 (red-team remediation): torn-write-tolerant readers, analog
    # v1.1 symbol-diversity support guard, FLAT regime label, deterministic
    # content-derived decision ids, sovereign liquidity constants
    # (contracts.py now in-artifact), 2026 calendar (sessions.py governs
    # visibility, now in-artifact). Engineering defects only — no
    # predicate, threshold, baseline, or criteria change.
    "hunter_rule_model_v1.5": (
        "model", ("apex/hunter/scanner.py", "apex/hunter/playbooks_v1.py",
                  "apex/hunter/forward_pass.py", "apex/hunter/birth.py",
                  "apex/hunter/baselines.py", "apex/hunter/neff.py",
                  "apex/hunter/capital.py", "apex/hunter/forecast.py",
                  "apex/analog/engine.py", "apex/hunter/memory.py",
                  "apex/hunter/swarm.py", "apex/hunter/contracts.py",
                  "apex/intraday/sessions.py")),
    # Swarm chair activation — pre-authorized by HUNTER-EPOCH-1.md within
    # Epoch 1: transport commissioned after operator CLI login + live
    # smoke (results/SWARM-SMOKE.json). Assessments count prospectively
    # from THIS birth; conservative-only downstream (flags -> caution).
    "hunter_swarm_producer_v1": (
        "model", ("apex/hunter/swarm.py",)),
    # v1.5.1: per-tick swarm budget in the decision pass (archive outranks
    # enrichment; over-budget candidates get honest NOT_REQUESTED). Part
    # of the pre-authorized swarm commissioning, not an epoch break.
    "hunter_rule_model_v1.5.1": (
        "model", ("apex/hunter/forward_pass.py", "apex/hunter/swarm.py")),
    # v1.5.2 (the ordering law): scan + candidates persist BEFORE any
    # optional enrichment (enrichment_pass reads only persisted records);
    # swarm ablation telemetry (facts_supplied, per-agent ms, CLI id).
    # The archive outranks Claude, structurally and tested.
    "hunter_rule_model_v1.5.2": (
        "model", ("apex/hunter/forward_pass.py", "apex/hunter/swarm.py")),
    # Swarm producer v2 (operator: "make the changes now"): the charter's
    # trade-moment desk — per-role prompts, Thesis/MarketContext/
    # Adversary(structured verdict+axes)/Synthesis, conservative-only
    # wiring, partial-deadline honesty. Live 4-seat smoke:
    # results/SWARM-SMOKE-V2.json.
    "hunter_swarm_producer_v2": (
        "model", ("apex/hunter/swarm.py", "docs/SWARM-CHARTER.md")),
    "hunter_rule_model_v1.5.3": (
        "model", ("apex/hunter/forward_pass.py", "apex/hunter/swarm.py")),
    # Swarm producer v3 (tiered scheduling): Tier-1 assassin
    # (Adversary+Context, 120s) kills cheaply on MATERIAL_OBJECTION; the
    # committee (Thesis+Synthesis) convenes for survivors only; partial
    # honesty on blown budgets; terse-mode prompts; latency telemetry.
    "hunter_swarm_producer_v3": (
        "model", ("apex/hunter/swarm.py", "docs/SWARM-CHARTER.md")),
    "hunter_rule_model_v1.5.4": (
        "model", ("apex/hunter/forward_pass.py", "apex/hunter/swarm.py")),
    # v1.5.5 (Profit Machine blueprint): the ASSASSIN as a formal recorded
    # stage between Oracle and Capital — every kill attempt in the ledger,
    # wounds feed the monotone caution law (identical semantics, now
    # attributed); rejection-economics funnel in the scoreboard.
    "hunter_assassin_v1": (
        "model", ("apex/hunter/assassin.py",
                  "docs/PROFIT-MACHINE-BLUEPRINT.md")),
    "hunter_rule_model_v1.5.5": (
        "model", ("apex/hunter/forward_pass.py", "apex/hunter/swarm.py",
                  "apex/hunter/assassin.py")),
    # DIGITAL WORLD v2 (observational, decision_power NONE in Epoch 1):
    # correlation, leadership, risk-on/off, intraday structure facets,
    # ONLINE daily regime (SFP+bridge, never revised), per-facet freshness.
    "hunter_twin_v2": (
        "model", ("apex/world/twin2.py",)),
    # Alpha half-life + intelligence routing (scheduling only; can only
    # REDUCE LLM spend; assassin always runs; conservative default).
    "hunter_halflife_v1": (
        "model", ("apex/hunter/halflife.py",)),
    "hunter_rule_model_v1.5.6": (
        "model", ("apex/hunter/forward_pass.py", "apex/hunter/swarm.py",
                  "apex/hunter/assassin.py", "apex/hunter/halflife.py")),
    # v1.5.7 (FINAL Epoch 1 lineage): semantic honesty — the routing
    # metric is an EDGE_PERSISTENCE_HORIZON (last checkpoint >= half of
    # peak), NOT a fitted half-life; field/status names now say what is
    # actually known. Prediction semantics FROZEN from here.
    "hunter_rule_model_v1.5.7": (
        "model", ("apex/hunter/forward_pass.py", "apex/hunter/swarm.py",
                  "apex/hunter/assassin.py", "apex/hunter/halflife.py")),
    # CRYPTO SHADOW ARENA (Epoch 0, zero capital forever by construction;
    # separate evidence class; NEVER equity evidence)
    "crypto_feature_schema_v1": (
        "feature_schema", ("apex/crypto/perception.py",)),
    "CRYPTO-001_v1": (
        "playbook", ("apex/crypto/playbooks.py",
                     "docs/CRYPTO-FORWARD-EPOCH-0.md")),
    "CRYPTO-002_v1": (
        "playbook", ("apex/crypto/playbooks.py",
                     "docs/CRYPTO-FORWARD-EPOCH-0.md")),
    "crypto_arena_model_v1": (
        "model", ("apex/crypto/arena.py", "apex/crypto/feed.py",
                  "apex/crypto/playbooks.py", "apex/crypto/perception.py")),
    # Market Fabric: WebSocket transport + execution fidelity + LAB-06
    # bounded archive. Strategy semantics unchanged (arena v2 = same
    # predicates, live senses).
    "crypto_market_fabric_v1.1": (
        "model", ("apex/crypto/fabric.py",)),
    "crypto_arena_model_v2": (
        "model", ("apex/crypto/arena.py", "apex/crypto/fabric.py",
                  "apex/crypto/playbooks.py", "apex/crypto/perception.py")),
    # execution-readiness hardening: disk sovereignty, decision-time book
    # evidence, bar-gap provenance. Infrastructure only; predicates frozen.
    "crypto_disk_governor_v1": (
        "model", ("apex/crypto/diskgov.py",)),
    # THE CAPTAIN — CIO/meta-brain. Observational in Epoch 1
    # (decision_power NONE): records what the desk SHOULD do next and
    # changes no outcome. Capital remains sovereign over money.
    "apex_captain_kernel_v1": (
        "model", ("apex/captain/kernel.py", "apex/captain/conviction.py",
                  "apex/captain/board.py", "docs/CAPTAIN-DOCTRINE.md")),
    # ERD-1 execution readiness: broker-aware, ORDER_READY, vault sealed.
    # Crypto Epoch 0 observability/orchestration repair (2026-08-16).
    # NOT a decision-surface change: the matchers' returns are byte-identical
    # with and without tracing (proved in test_crypto_observability), so this
    # is an instrumentation birth, not an Epoch break.
    # EYES-1/T1 sensory stack (2026-08-17): all observational, decision
    # power NONE_OBSERVATIONAL_EPOCH1; instrumentation births, no Epoch break.
    # FRONTIER-1 (2026-08-17): Desk B shadow instrumentation, power
    # NONE_FRONTIER_SHADOW throughout; the Epoch-1 control is untouched.
    "apex_premarket_context_v1": (
        "model", ("apex/frontier/premarket.py",)),
    "apex_decision_card_v1": (
        "model", ("apex/frontier/decision_card.py",)),
    "apex_frontier_senses_v1": (
        "model", ("apex/frontier/senses.py",)),
    "apex_frontier_learning_registry_v1": (
        "model", ("apex/frontier/learning.py",)),
    "apex_captain_eyes_v1": (
        "model", ("apex/captain/context.py", "apex/vision/render.py",
                  "apex/vision/challenger.py")),
    "apex_event_eyes_v1": (
        "model", ("apex/events/catalyst.py", "apex/events/cik_bridge.py")),
    "apex_microscope_v1": (
        "model", ("apex/hunter/microscope.py",)),
    "crypto_observability_v1": (
        "model", ("apex/crypto/health.py",)),
    "crypto_disk_governor_v1.1": (
        "model", ("apex/crypto/diskgov.py",)),
    "apex_execution_gateway_v1": (
        "model", ("apex/execution/contracts.py", "apex/execution/gateway.py",
                  "apex/execution/robinhood.py", "apex/execution/sealing.py",
                  "apex/execution/killswitch.py")),
    "apex_expression_v2": (
        "model", ("apex/execution/expression_v2.py",)),
    "apex_claude_cio_v1": (
        "model", ("apex/captain/cio.py",)),
    "crypto_arena_model_v3": (
        "model", ("apex/crypto/arena.py", "apex/crypto/fabric.py",
                  "apex/crypto/diskgov.py", "apex/crypto/playbooks.py",
                  "apex/crypto/perception.py")),
    # v1.1 (LAB-01): empty-frame guard in visible_bars — a not-yet-listed
    # symbol crashed the whole scan tick (found by the replay campaign's
    # first minute; also a latent Monday robustness bug). Crash guard
    # only; feature semantics unchanged.
    "hunter_feature_schema_v1.1": (
        "feature_schema", ("apex/hunter/chartstate.py",
                           "apex/hunter/relstrength.py")),
}


def main() -> int:
    existing = load_births()
    now = str(pd.Timestamp.now(tz="UTC"))
    for name, (kind, files) in ARTIFACTS.items():
        if name in existing:
            print(f"already born: {name} at "
                  f"{existing[name]['birth_time_utc']} (refusing re-birth)")
            continue
        h = hashlib.sha256()
        for f in files:
            h.update(Path(f).read_bytes())
        e = _chain_append(REGISTRY, {
            "kind": "birth", "name": name, "dependency_kind": kind,
            "artifact_hash": h.hexdigest()[:16],
            "artifact_files": list(files), "birth_time_utc": now})
        print(f"BORN {name} ({kind}) {h.hexdigest()[:16]} at {now} "
              f"[{e['entry_hash'][:12]}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
