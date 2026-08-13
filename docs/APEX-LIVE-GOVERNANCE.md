# APEX Live Governance — research → paper → shadow → live

**Status:** governance text. No execution, broker, or monitoring code exists,
and none may until a monetisable backtest exists. **No broker is connected.**

## The promotion ladder and its state transitions

```
RESEARCH ─(validated + monetisable backtest + human sign-off)→ PAPER
PAPER    ─(paper track record + human sign-off)→ SHADOW
SHADOW   ─(shadow matches backtest within tolerance + human sign-off)→ LIVE
LIVE     ─(monitoring alert)→ REVIEW / PAUSE / KILL
```

Every transition is an **explicit, logged, human-authorised** state change. No
promotion is automatic. A monitoring alert may move a strategy DOWN the ladder
(REVIEW/PAUSE/KILL); nothing moves it up without a human.

## The one rule that keeps live trading from corrupting research

> Execution consumes approved target weights and emits fills. It generates no
> hypotheses, reads no research artifact, and its results re-enter research ONLY
> as a new, provenance-stamped dossier created by a human — never as a silent
> retrain or retune.
>
> Forbidden forever: `broker availability → strategy selection`.

## Execution — twelve specifications (firewall contract `execution`)

| | |
|---|---|
| **1. Purpose** | Turn approved portfolio weights into orders and fills, safely. |
| **2. Inputs** | Approved target weights from a promoted policy; pre-trade risk limits. |
| **3. Outputs** | Fills, implementation shortfall, post-trade reconciliation. |
| **4. Allowed dependencies** | a broker adapter (when authorised), `apex.risk` (pre-trade checks). |
| **5. Forbidden dependencies** | EVERYTHING upstream — registration, screening, discovery, evaluate, features. Firewall `execution.forbidden` is the widest in the table. |
| **6. Governance boundary** | Strictly a consumer. Generates no research, consumes no credit, touches no ledger. |
| **7. Provenance** | order id, policy version, weight snapshot, timestamp, fill record. |
| **8. What is a new hypothesis** | Nothing. Execution never proposes research. |
| **9. What consumes a credit** | Nothing. |
| **10. What can never access holdout** | Execution has no research-data access at all. |
| **11. What can never optimize** | Execution parameters are operational, not research; they never feed a signal or policy choice. |
| **12. Tests before activation** | firewall `execution` (widest forbidden set); a "no upstream import" closure test; pre-trade risk gate present; NO real broker credentials in any test. |

## Monitoring — twelve specifications (firewall contract `monitoring`)

| | |
|---|---|
| **1. Purpose** | Detect divergence between live behaviour and backtest expectation, and drift/decay, and raise REVIEW/PAUSE/KILL. |
| **2. Inputs** | Live fills and P&L; the backtest expectation; feature/regime state. |
| **3. Outputs** | Alerts and state-transition *requests* (never automatic retrains). |
| **4. Allowed dependencies** | read-only over the ledger and attribution. |
| **5. Forbidden dependencies** | registration, screening, discovery. Firewall `monitoring.forbidden`. |
| **6. Governance boundary** | May trigger REVIEW/PAUSE/KILL; may NOT retune, retrain, or reselect. A decay alert becomes a NEW dossier, authored by a human. |
| **7. Provenance** | alert id, metric, threshold, strategy id, timestamp. |
| **8. What is a new hypothesis** | A decay-driven new research question — created by hand, with declared provenance (descendant-of-live). |
| **9. What consumes a credit** | Nothing in monitoring; the new hypothesis it inspires does, later. |
| **10. What can never access holdout** | Monitoring reads live data, not the research holdout. |
| **11. What can never optimize** | It cannot silently retrain or retune a live model. Detect, alert, escalate — never adjust. |
| **12. Tests before activation** | a "monitoring cannot mutate a strategy" test; alert → REVIEW/PAUSE/KILL only; no retrain path. |

## Drift detection scope (design)

signal drift, feature drift, regime drift, performance decay, turnover drift,
cost drift, exposure drift, data-quality failures, model drift. Each has a
pre-declared threshold; crossing it raises an alert. **An alert is a request for
human judgement, not an action.**
