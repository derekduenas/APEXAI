"""HISTORICAL FLIGHT SIMULATOR (backtest workbench).

Replays the FROZEN pilot policy — frozen artifact forecast, heuristic direction, PILOT_RULE_V1
contract selection, RISK_ENVELOPE_V1 cap, EXECUTION_POLICY_V1 fill rules, EXIT_AT_HORIZON_15M_V1,
synthetic fee schedule — over the validated options-quote corpus with a temporal firewall, and
evaluates it against declared controls. Every record it writes carries
evidence_class HISTORICAL_DEVELOPMENT_REPLAY. Nothing here is prospective evidence, nothing is fitted,
and the pilot's own ledger/boundary is never written (the boundary refuses replay labels by design)."""
