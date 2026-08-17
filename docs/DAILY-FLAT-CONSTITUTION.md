# APEX DAILY-FLAT CONSTITUTION
## Intraday Edge Does Not Grant Overnight Authority

**OVERNIGHT_POSITION_AUTHORITY = NONE.** No current strategy, Hunter,
Captain state, Capital state, visual observation, catalyst, dislocation,
or option expression may intentionally carry risk through the
regular-session close. The reasons are architectural, not discretionary:
target horizons are intraday (15–90m); the overnight return
distribution, gap risk, and overnight catalyst risk are uncalibrated;
extended-hours liquidity and execution differ materially; no Hunter was
validated as an overnight strategy. INTRADAY_EDGE != OVERNIGHT_EDGE.

CLOSE-1 exists to answer *"what did today's auction teach us?"* — never
*"should we hold this overnight?"* Closing intelligence feeds MARKET
MEMORY; it does not create exposure. Daily-flat applies equally to
stock, long calls, long puts, and debit spreads — limited-loss options
do not eliminate overnight risk.

Future position lifecycle (when paper/live authorization ever exists):
every position carries session_date, entry_time, maximum_holding_horizon,
mandatory_flat_time; legal states are OPEN_INTRADAY / EXIT_PENDING /
FLAT / FORCED_FLAT_EXCEPTION / ERROR_NOT_FLAT. No OVERNIGHT, SWING, or
HOLD_FOR_TOMORROW state exists. Flat requires MEASURED broker position
state — "exit requested" is never "flat" — and a broker/network failure
near the close is a P0 operational state, escalated through
EXIT_REQUESTED → EXIT_ACKNOWLEDGED → PARTIALLY_FLAT → CONFIRMED_FLAT |
UNABLE_TO_CONFIRM_FLAT, never fabricated. The late-entry cutoff is a
frozen policy chosen before paper activation, not tonight's intuition.

**The overnight firewall:** if APEX should ever hold overnight, that is
a NEW STRATEGY FAMILY (e.g. HUNTER-OVERNIGHT-001) with its own protocol,
birth, evidence lineage, gap-risk model, sizing, validation, and Capital
authorization. It cannot inherit authority from intraday performance.

APEX MAY REMEMBER OVERNIGHT. APEX MAY OBSERVE OVERNIGHT. APEX MAY THINK
OVERNIGHT. **CURRENT APEX MAY NOT HOLD OVERNIGHT.**
