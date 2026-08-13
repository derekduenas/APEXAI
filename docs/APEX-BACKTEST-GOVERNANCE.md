# APEX Backtest Governance — an evaluator, never an optimiser

**Status:** governance text. No backtest code exists. Built only AFTER signal,
policy, and cost objects are separate (see portfolio governance).

## The one thing a backtest may not do

> A backtester evaluates a fully-specified {signal, policy, cost model} triple.
> It may NOT modify the hypothesis, select parameters, or choose among policies.
> The moment a backtest picks the best of several configurations, it is an
> optimiser, and the credit system has been bypassed.

## The twelve specifications (firewall contract `backtest`)

| | |
|---|---|
| **1. Purpose** | Simulate a pre-declared signal+policy over PIT history with realistic frictions, and produce a complete, immutable audit artifact. |
| **2. Inputs** | A validated signal, a versioned policy, a versioned cost model, the PIT universe and features, explicit rebalance and execution-timing rules. |
| **3. Outputs** | A net return path and a full audit artifact (every rebalance, fill assumption, cost, and constraint hit). |
| **4. Allowed dependencies** | `apex.features`, `apex.portfolio`, `apex.evaluate.turnover`, `apex.risk`. |
| **5. Forbidden dependencies** | registration core, screening, discovery. Firewall `backtest.forbidden`. |
| **6. Governance boundary** | Monetisation research. Consumes no credit. But it must not be run repeatedly over policy variants to find a winner — that is a search and requires governance. |
| **7. Provenance** | signal id, policy version, cost version, dataset fingerprint, universe snapshot, execution-rule version, seed, repo SHA — stamped on the audit artifact. |
| **8. What is a new hypothesis** | Nothing in a single declared backtest. Searching backtests over parameters IS a new experiment. |
| **9. What consumes a credit** | A single declared backtest: none. |
| **10. What can never access holdout** | A research backtest runs on in-sample and validation history that the experiment already paid for; it never opens the holdout. |
| **11. What can never optimize** | Execution rules, rebalance dates, cost assumptions, universe — all frozen inputs. The backtester reads them; it never selects them. |
| **12. Tests before activation** | next-bar execution (no same-bar fill); PIT universe/feature enforcement; a "backtest cannot mutate signal or policy" immutability test; delisting/corporate-action handling test. |

## Required realism (design)

PIT universe and features; explicit signal timestamp vs execution timestamp;
next-session execution; transaction costs, spread/slippage, turnover, borrow;
delisting handling (Shumway); corporate actions; missing-data handling;
capacity and market-impact assumptions; portfolio constraints. Each is a
declared input with a version, recorded in the audit artifact.

## The audit artifact

Every backtest emits an immutable record reconstructible from its provenance
stamp. Two runs of the same triple must be bit-identical (the determinism
discipline the dry run already established). A backtest whose result cannot be
reproduced from its stamp is not evidence.
