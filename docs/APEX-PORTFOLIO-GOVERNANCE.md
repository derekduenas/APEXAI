# APEX Portfolio Governance — signal is not policy

**Status:** governance text. No portfolio code exists. Gated on a **validated**
alpha; building it before one exists is optimising a portfolio of nothing.

## The distinction the whole layer rests on

```
SIGNAL            "high gross profitability ranks stocks"        <- a prediction
PORTFOLIO POLICY  "top quintile long / bottom short /            <- an implementation
                   sector-neutral / weekly rebalance /            choice
                   2% position cap / 20% turnover budget"
```

These are **separate objects**. A signal is validated; a policy is *chosen* and
*versioned*. Policy parameters may NEVER be silently optimised from validation
results — that is fitting the implementation to the answer.

## The twelve specifications (firewall contract `portfolio`)

| | |
|---|---|
| **1. Purpose** | Turn a validated signal into an investable, versioned portfolio policy, and ask whether the signal survives implementation. |
| **2. Inputs** | A VALIDATED signal (lifecycle `VALIDATED_ALPHA`); a pre-declared policy spec; the cost model; the risk limits. |
| **3. Outputs** | Target weights per rebalance date, and the policy object (versioned). |
| **4. Allowed dependencies** | `apex.features` (signal values), `apex.evaluate.turnover` (costs), `apex.risk` (limits, once it exists). |
| **5. Forbidden dependencies** | registration core, screening, discovery, and validation *statistics as a tuning target*. Firewall contract `portfolio.forbidden`. |
| **6. Governance boundary** | Portfolio construction is monetisation research, NOT a new predictive hypothesis. It does not consume a credit. But a policy chosen by searching over validation performance IS a hidden experiment and is forbidden. |
| **7. Provenance** | signal id + validation result reference, policy version, cost model version, risk limit version, config hash, repo SHA. |
| **8. What is a new hypothesis** | Nothing in policy construction — UNLESS the policy encodes a new predictive claim (e.g. "only trade the signal in high-breadth regimes"), which is a regime hypothesis and consumes a credit. |
| **9. What consumes a credit** | Portfolio construction alone: none. A regime- or signal-conditioned policy that makes a new predictive claim: one credit. |
| **10. What can never access holdout** | The policy is chosen and versioned without any holdout look; the holdout remains the single validation event. |
| **11. What can never optimize** | Position sizing, caps, turnover budget, rebalance frequency, neutralisation choices — all PRE-DECLARED and versioned, never tuned to make a backtest look better. |
| **12. Tests before activation** | signal-object != policy-object type separation; a "policy params are versioned, not derived from validation" provenance test; firewall contract `portfolio`. |

## Supported policy architectures (design)

rank / long-short / dollar-neutral / beta-neutral / sector-neutral portfolios;
volatility targeting; position caps; concentration, turnover, liquidity and
capacity constraints; transaction costs, slippage, borrow costs, short
availability; rebalance frequency. **Every one is an explicit, versioned policy
parameter — an input, never an optimiser output.**

## The rule that prevents the classic overfit

A backtest may report that policy A nets more than policy B. It may NOT be used
to SELECT policy A, because that selection is an unregistered comparison over
the validation data. Policies are pre-declared; the backtest evaluates the
declared one. Choosing among policies by backtest performance is a new,
credit-consuming experiment.
