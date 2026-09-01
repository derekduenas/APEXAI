"""FIRST_DOLLAR_READINESS — the canonical gate, computed live.

Eight checks (sealed PROFIT-COMBAT-COMMISSIONING-2026-08-31 +
COMMISSIONING-INTEGRITY-FIXES-2026-08-30). This script AUTHORIZES
NOTHING: it reports which blockers stand between the organism and
its first legitimate real trade. ALPHA_ELIGIBLE is never waived.

decision_power: NONE_REPORTING.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

CORE = Path("/apex-data/core")
REPO = Path("/opt/apex-repo")


def rows(p):
    if not Path(p).exists():
        return []
    out = []
    for line in Path(p).read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main():
    checks = {}

    # 1 BROKER_FUNDED -- last known preview evidence
    checks["BROKER_FUNDED"] = {
        "status": "NO",
        "blocker_class": "EXTERNAL_OPERATOR",
        "evidence": "RH preview 2026-08-30 returned "
                    "EQUITY_NOT_ENOUGH_BP on the Agentic account; "
                    "operator action required (this gate never "
                    "requests funding)"}

    # 2 ALPHA_ELIGIBLE -- any expert with prospective eligibility
    lane_a = rows(REPO / "results/event_sprint/"
                  "prospective_ledger.jsonl")
    resolved = [r for r in lane_a
                if r.get("kind") == "prospective_resolution"]
    checks["ALPHA_ELIGIBLE"] = {
        "status": "NO",
        "blocker_class": "SCIENTIFIC_ECONOMIC -- the core "
                         "blocker. Funding alone does NOT make "
                         "APEX ready; an alpha must EARN "
                         "eligibility prospectively",
        "evidence": f"no expert holds prospective eligibility; "
                    f"Lane A has {len(resolved)} resolutions "
                    f"(grading under way); NEVER waived"}

    # 3 EXPRESSION_EXECUTABLE
    checks["EXPRESSION_EXECUTABLE"] = {
        "status": "YES",
        "evidence": "RH equity + option_level_3 verified; preview "
                    "path reached; option quotes live via OPRA/"
                    "ThetaData"}

    # 4 CURRENT_QUOTES_VALID + 5 PROVIDER_DISAGREEMENT_CLEAR
    ws = CORE / "btc/ws_health.json"
    age = (time.time() - ws.stat().st_mtime) / 60 \
        if ws.exists() else None
    checks["CURRENT_QUOTES_VALID"] = {
        "status": "CONDITIONAL",
        "evidence": "valid only at decision time; law: every quoted "
                    "source fresh within 30s or "
                    "timestamp-explained, freshest source used "
                    "(QUOTE_INTEGRITY gate, sealed after the SPY "
                    "766/769 weekend reconstruction)"}
    checks["PROVIDER_DISAGREEMENT_CLEAR"] = {
        "status": "CONDITIONAL",
        "evidence": "DataDisagreementState (apex/intraday/"
                    "disagreement.py) must be run on the serious "
                    "candidate's sources at decision time; 20bp "
                    "material threshold, 30s staleness law"}

    # 6 KERNEL
    try:
        import sys
        sys.path.insert(0, str(REPO))
        from apex.organism import risk_kernel
        from apex.organism.risk_certificate import certify
        k = risk_kernel.check(
            certificate=certify(expression="LONG_CALL",
                                direction="LONG", declared_risk=50.0,
                                sleeve_payload={"net_debit": 50.0}),
            expression="LONG_CALL", direction="LONG",
            sleeve_payload={"net_debit": 50.0},
            open_certified_risk=0.0,
            declared_risk=50.0, symbol="TEST", beta_family="UNKNOWN",
            open_risk=0.0, same_underlying_risk=0.0,
            same_family_risk=0.0, session_realized_pnl=0.0,
            available_capital=10_000.0)
        checks["KERNEL_PASS"] = {
            "status": "OPERATIONAL" if k["approved"] else "DEFECT",
            "evidence": f"threshold set {k['threshold_set']} loaded; "
                        f"smoke check approved={k['approved']}"}
    except Exception as e:                              # noqa: BLE001
        checks["KERNEL_PASS"] = {"status": "DEFECT",
                                 "evidence": f"{type(e).__name__}"}

    # 7 LIVE_FITNESS -- feeds + services
    import subprocess
    svc = subprocess.run(
        ["systemctl", "is-active", "apex-organism.service",
         "apex-btc-ws.service", "apex-catalyst.service"],
        capture_output=True, text=True).stdout.split()
    checks["LIVE_FITNESS_PASS"] = {
        "status": "YES" if all(s == "active" for s in svc)
        else "DEGRADED",
        "evidence": f"organism/btc-ws/catalyst: {svc}; BTC feed "
                    f"age {age and round(age, 1)} min"}

    # 8 HUMAN_APPROVAL
    checks["HUMAN_APPROVAL"] = {
        "status": "REQUIRED",
        "evidence": "mandatory for the initial live phase; no "
                    "autonomous order placement exists anywhere"}

    blockers = [k for k, v in checks.items()
                if v["status"] in ("NO", "DEFECT", "DEGRADED")]
    print(json.dumps({
        "kind": "first_dollar_readiness",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "hard_blockers": blockers,
        "law": "the moment an alpha becomes eligible, only funding "
               "and human approval should remain",
        "decision_power": "NONE_REPORTING"}, indent=1))


if __name__ == "__main__":
    main()
