"""Verifies the factual claims the master architecture audit makes.

An architecture audit that asserts "ML is absent" or "execution cannot reach
research" is only as trustworthy as those claims are checkable. This file makes
the load-bearing claims mechanical: if someone later wires an ML model, a
broker, or a portfolio optimiser into the research path, a claim here fails and
the audit is known to be stale.

No feature, experiment, credit, or holdout is touched. These are read-only
structural assertions over the source tree.
"""

from __future__ import annotations

from pathlib import Path

from apex.audit.execution_path import module_closure

REPO = Path(__file__).resolve().parents[1]
APEX = REPO / "apex"


def _all_source() -> str:
    return "\n".join(
        p.read_text() for p in APEX.rglob("*.py") if "__pycache__" not in str(p)
    )


# --- claims of ABSENCE (§1, §3, §13) ---------------------------------------

def test_no_machine_learning_dependency_exists():
    """Audit claim: ML is ABSENT. If a model library appears, ML has entered
    without the governance §6 requires -- the claim, and the governance, are
    then stale and must be revisited."""
    src = _all_source().lower()
    for lib in ("import sklearn", "import xgboost", "import lightgbm",
                "import torch", "import tensorflow", "from sklearn"):
        assert lib not in src, (
            f"{lib!r} present: ML has entered the codebase. The audit claims ML "
            f"is ABSENT and requires governance (§6) BEFORE any model. Update "
            f"both before proceeding."
        )


def test_no_execution_or_broker_dependency_exists():
    """Audit claim: no LIVE execution exists. Updated 2026-08-15 (Hunter P0):
    apex/hunter/broker.py deliberately NAMES place_order in order to SEAL it
    -- the method raises always and subclasses cannot re-enable it (proven in
    test_hunter_p0). Updated 2026-08-16 (ERD-1): apex/execution/sealing.py and
    robinhood.py likewise NAME the placement verbs in order to forbid them (a
    deny-list and a tripwire scanner cannot be written without naming what
    they refuse). Those three modules are exempt from the NAME scan only --
    the stronger invariant, that no module anywhere DEFINES a placement
    function, is proven mechanically below and in test_execution_erd1.
    Updated 2026-08-17 (Phase 0.4, PRIMARY_BROAD_SENSOR): alpaca_fabric.py
    and provider_interface.py NAME "Alpaca" because it is now a legitimate
    market-DATA vendor (operator-authorized Algo Trader Plus), not a broker
    relationship -- the module subscribes trades/quotes over the vendor's
    own websocket library only; no alpaca-py/alpaca_trade_api SDK is
    imported, and no order/placement function is defined (same invariant,
    proven the same way below). Updated 2026-08-18 (Options Research V1,
    F O24): apex/options_research/market_state.py NAMES "Alpaca" for the
    identical reason -- from_alpaca_snapshot() parses the shape of
    Alpaca's OPRA /v1beta1/options/snapshots/{symbol} response dict; it
    takes the dict as a plain argument, makes no HTTP call itself, imports
    no Alpaca SDK, and defines no order/placement function (proven by
    test_options_research_firewall.py's own broker/order-keyword scan).

    Updated 2026-08-18 (Phase 1.0 continuity truth):
    apex/intraday/reconnect_ledger.py NAMES "Alpaca" for the same
    market-DATA reason as alpaca_fabric.py -- it is the durable event
    record for that sensor's reconnects, built because the counter
    reached 388 with zero corresponding log lines. It defines no order
    or placement function and imports no SDK (proven by
    test_intraday_continuity_truth.py and by the placement scan below).
    """
    # Updated 2026-08-20 (Profit Predator v1): checkpoint_graph.py NAMES
    # the sensor module and its artifact paths because it is the
    # DOCUMENTARY funnel map -- an audit artifact that obfuscated its own
    # producers would defeat its purpose. It defines no placement
    # function and imports nothing (the mechanical invariant below still
    # covers it).
    # 2026-08-23 (Options PAPER_EXPLORATORY): options_feed.py is the
    # market-DATA sensor for the live options loop and NAMES its data
    # vendors for the same reason alpaca_fabric.py does. It was placed
    # in the sensor layer specifically so the research package
    # (apex/predators/options/live_world.py) could consume feeds
    # through neutral names and stay vendor-ignorant -- the firewall
    # was obeyed by moving the code, not by exempting research.
    exempt = {"broker.py", "sealing.py", "robinhood.py", "alpaca_fabric.py",
             "provider_interface.py", "market_state.py", "reconnect_ledger.py",
             "checkpoint_graph.py", "options_feed.py",
             # 2026-08-28 (Evolution Engine V2): organism/health.py
             # NAMES the fabric unit + its artifact because it IS the
             # service-identity monitor -- SERVICE_IDENTITY_VALIDITY
             # requires checking that the expected executable produces
             # the expected stream, and a monitor that obfuscated which
             # program it verifies would defeat its purpose (same
             # reasoning as checkpoint_graph.py). It defines no
             # placement function and imports no vendor SDK; the
             # mechanical placement scan below still covers it.
             "health.py",
             # 2026-08-24: evidence_registry.py NAMES artifact paths --
             # including a non-authoritative one -- because its entire
             # job is declaring which file is canonical for a governed
             # metric. A registry that obfuscated its own sources would
             # defeat its purpose, the same reasoning that exempts
             # checkpoint_graph.py. It defines no placement function
             # and imports no SDK.
             "evidence_registry.py",
             # 2026-09-01 (Phase 1 closure): the prospective sensor
             # lane NAMES its market-DATA endpoint for exactly the
             # reason alpaca_fabric.py, options_feed.py and
             # reconnect_ledger.py do. microstructure.py and
             # options_surface.py import ONLY the standard library
             # (json/math/os/csv/io/statistics/urllib), pull no vendor
             # SDK, hold no broker relationship and define no order or
             # placement function -- verified before exempting, and
             # the stronger mechanical placement scan below still
             # covers them. They are SHADOW_PROSPECTIVE_ONLY sensors
             # with zero authority.
             "microstructure.py", "options_surface.py"}
    # PATH-scoped exemptions (2026-08-20): name-based exemption of
    # "__init__.py" would blind the scan across every package, so files
    # that must name the sensor module get exempted individually.
    # apex/market_state/__init__.py imports the canonical bar-stream
    # path FROM the sensor module (single source of truth) -- a data
    # dependency on the audited sensor, not a broker relationship.
    # apex/execution_paper (2026-08-21): the PAPER adapter must name the
    # vendor's paper endpoint; its own commissioning tests forbid the
    # live trading URL from appearing anywhere in the package and prove
    # the live host is refused by allowlist -- a stronger guarantee than
    # this name scan provides.
    exempt_paths = {"apex/market_state/__init__.py",
                    "apex/execution_paper/__init__.py",
                    "apex/execution_paper/harness.py"}
    src = "\n".join(
        p.read_text() for p in APEX.rglob("*.py")
        if "__pycache__" not in str(p) and p.name not in exempt
        and str(p.relative_to(APEX.parent)) not in exempt_paths
    ).lower()
    for term in ("import ib_insync", "robin_stocks", "alpaca", "order_management",
                 "place_order", "submit_order"):
        assert term not in src, f"{term!r} present: execution has entered research"
    # and the sealed module itself must contain no broker LIBRARY
    broker_src = (APEX / "hunter" / "broker.py").read_text().lower()
    for lib in ("import ib_insync", "robin_stocks", "alpaca"):
        assert lib not in broker_src, f"{lib!r} inside the sealed adapter"
    # The claim that actually matters: the exempted modules may SAY these
    # words, but nothing in apex may DEFINE a callable that places an order.
    from apex.execution.sealing import scan_package_for_placement
    scan = scan_package_for_placement("apex")
    assert scan["clean"], f"a placement surface exists: {scan}"


def test_no_causal_inference_dependency_exists():
    """Audit claim: causal inference is ABSENT (only placebo/neutralised tests
    are data-justified, and none is built yet)."""
    src = _all_source().lower()
    for term in ("import dowhy", "import econml", "causalgraph", "import linearmodels"):
        assert term not in src, f"{term!r} present: a causal library has entered"


# --- claims about the FIREWALL (§4, §5) ------------------------------------

def test_the_discovery_layer_cannot_reach_registration_or_the_ledger():
    """§4/§5: discovery imports no path to the ledger or gated pipeline.

    This is the same property gate.assert_not_auto_registerable checks; asserted
    here too so the ARCHITECTURE claim is independently verified, not delegated.
    """
    forbidden = {"apex.pipeline", "apex.registration", "apex.governance.ledger"}
    for module in (APEX / "research").glob("*.py"):
        name = ("apex.research." + module.stem) if module.stem != "__init__" else "apex.research"
        reached = module_closure(REPO, name) & forbidden
        assert not reached, f"{name} reaches {sorted(reached)}: the firewall leaks up"


def test_the_screen_cannot_be_read_by_the_evaluation_path():
    """§5: S13 -- a screening outcome is never evidence. The evaluation modules
    must not import the screen."""
    for entry in ("apex.pipeline", "apex.evaluate.ic", "apex.evaluate.criteria",
                  "apex.evaluate.verdict", "apex.report.attribution"):
        assert "apex.governance.screening" not in module_closure(REPO, entry), (
            f"{entry} reaches the screen; a screening verdict could become evidence"
        )


def test_the_evaluation_path_reaches_no_research_discovery_module():
    """The firewall's up-direction: validation must not depend on discovery.

    If evaluation imported the swarm or novelty engine, a discovery signal could
    influence a verdict -- the exact contamination the layering forbids.
    """
    research = {f"apex.research.{m.stem}" for m in (APEX / "research").glob("*.py")}
    for entry in ("apex.pipeline", "apex.evaluate.ic", "apex.evaluate.verdict"):
        reached = module_closure(REPO, entry) & research
        assert not reached, f"{entry} reaches discovery modules {sorted(reached)}"


# --- claims of PRESENCE (§1) -- the audit must not undersell either ---------

def test_the_certified_layers_the_audit_claims_are_actually_present():
    """§1/§3 class-A claims: the modules the audit calls built must exist."""
    must_exist = [
        "features/registry.py", "features/factory.py", "features/redundancy.py",
        "features/pit_validation.py",
        "research/twin.py", "research/swarm.py", "research/novelty.py",
        "research/hypothesis.py", "research/gate.py",
        "governance/screening.py", "governance/ledger.py",
        "evaluate/ic.py", "evaluate/deciles.py", "evaluate/reference.py",
        "evaluate/turnover.py", "evaluate/criteria.py",
        "audit/lookahead.py", "audit/cross_sectional.py", "audit/execution_path.py",
    ]
    missing = [m for m in must_exist if not (APEX / m).exists()]
    assert not missing, f"audit claims these are built but they are absent: {missing}"


def test_the_absent_layers_the_audit_claims_have_no_module():
    """§3 class-C claims: the layers the audit calls ABSENT have no directory,
    so the audit cannot be quietly falsified by a stub appearing."""
    # Genuinely absent engines (need a validated alpha or a broker first).
    # ERD-1 (2026-08-16) moved `execution` out of this set deliberately: the
    # READ/REVIEW half is built and the contract now says so. It is guarded by
    # the placement scan above, not by absence.
    for absent_dir in ("backtest", "risk", "monitoring"):
        assert not (APEX / absent_dir).exists(), (
            f"apex/{absent_dir}/ exists but the audit classifies it ABSENT/planned; "
            f"reconcile the audit before building further"
        )
    # UNDER_CONSTRUCTION governance substrate (ml/causal/regime) may exist, but
    # the real invariant holds: NO model-fitting library, and no .fit() in it.
    from apex.audit.execution_path import executable_source
    for uc_dir in ("ml", "causal", "regime", "portfolio"):
        # executable code only -- the search-ledger docstring legitimately names
        # ".fit()" to say it is prohibited (the prose-vs-code trap, guarded).
        code = "\n".join(
            executable_source(f.read_text()) for f in (APEX / uc_dir).rglob("*.py")
            if "__pycache__" not in str(f)
        ).lower()
        for lib in ("import sklearn", "import xgboost", "import lightgbm",
                    "import torch", ".fit("):
            assert lib not in code, (
                f"apex/{uc_dir}/ contains {lib!r}: a model is being fit before the "
                f"ML governance contract is satisfied"
            )
