# APEX Feature Library — Readiness Report

Infrastructure readiness. No forward returns, no IC, no performance
ranking. Feature-to-feature only, in-sample (no statistical standing).

```
CURRENT FEATURE COUNT      23  (9 pre-existing + 14 new factory features)
FEATURES ADDED             14  fundamental, PIT-safe
REGISTRY: BUILT            14
REGISTRY: DATA_AVAILABLE   2  (fields present, builder pending)
REGISTRY: DATA_GAP         2  (dataset absent)
PIT STATUS                 14/14 features 100.000000% compliant
REDUNDANCIES (identical)   0 among new features
REDUNDANCIES (correlated)  13 among new features
CREDITS CONSUMED           0
HOLDOUT STATUS             SEALED
APEX-003 STATUS            NOT CREATED
```

## Alpha-family status

| family | features | status |
|---|---|---|
| accruals | 1 | BUILT |
| balance_sheet | 1 | BUILT |
| capital_allocation | 1 | BUILT |
| event | 1 | DATA_GAP |
| growth | 2 | BUILT |
| liquidity | 2 | DATA_AVAILABLE |
| positioning | 1 | DATA_GAP |
| profitability | 6 | BUILT |
| valuation | 3 | BUILT |

## New features: coverage and PIT

| feature | family | direction | coverage | PIT |
|---|---|---|---|---|
| accr_total_accruals | accruals | lower_better | 99.6% | 100.0000% (0 viol) |
| bs_leverage | balance_sheet | unsigned | 100.0% | 100.0000% (0 viol) |
| cap_net_buyback_yield | capital_allocation | higher_better | 99.6% | 100.0000% (0 viol) |
| grow_asset_growth | growth | lower_better | 98.6% | 100.0000% (0 viol) |
| grow_sales_growth | growth | unsigned | 97.8% | 100.0000% (0 viol) |
| prof_gross_margin | profitability | higher_better | 99.4% | 100.0000% (0 viol) |
| prof_gross_profitability | profitability | higher_better | 99.7% | 100.0000% (0 viol) |
| prof_net_margin | profitability | higher_better | 99.4% | 100.0000% (0 viol) |
| prof_operating_profitability | profitability | higher_better | 99.7% | 100.0000% (0 viol) |
| prof_return_on_assets | profitability | higher_better | 99.7% | 100.0000% (0 viol) |
| prof_return_on_equity | profitability | higher_better | 99.7% | 100.0000% (0 viol) |
| val_book_to_market | valuation | higher_better | 100.0% | 100.0000% (0 viol) |
| val_earnings_yield | valuation | higher_better | 99.7% | 100.0000% (0 viol) |
| val_sales_to_price | valuation | higher_better | 99.7% | 100.0000% (0 viol) |

## Effective dimension estimate (new features)

Greedy clustering: a feature joins an existing cluster when its mean
cross-sectional rank correlation with that cluster's lead is >= 0.70.
This counts distinct information, not predictive power.

New-feature clusters (|rho| >= 0.70): **12**
  - accr_total_accruals
  - bs_leverage
  - cap_net_buyback_yield
  - grow_asset_growth
  - grow_sales_growth
  - prof_gross_margin
  - prof_gross_profitability
  - prof_net_margin
  - prof_operating_profitability, prof_return_on_assets, prof_return_on_equity
  - val_book_to_market
  - val_earnings_yield
  - val_sales_to_price

Effective NEW dimensions ~= 12; pre-existing ~= 4 (momentum block, 2 volatility, NSI).

## Redundancy findings

### Identical information (same feature, would be flagged for review)
None among the new features.

### Correlated information (related, explicitly NOT for removal)
- `grow_asset_growth` ~ `grow_sales_growth`: rank rho +0.5521 -- related, NOT flagged for removal
- `prof_gross_margin` ~ `val_sales_to_price`: rank rho -0.6828 -- related, NOT flagged for removal
- `prof_gross_profitability` ~ `prof_operating_profitability`: rank rho +0.6329 -- related, NOT flagged for removal
- `prof_gross_profitability` ~ `prof_return_on_assets`: rank rho +0.5898 -- related, NOT flagged for removal
- `prof_gross_profitability` ~ `val_book_to_market`: rank rho -0.5446 -- related, NOT flagged for removal
- `prof_net_margin` ~ `prof_return_on_assets`: rank rho +0.6088 -- related, NOT flagged for removal
- `prof_net_margin` ~ `prof_return_on_equity`: rank rho +0.5443 -- related, NOT flagged for removal
- `prof_net_margin` ~ `val_earnings_yield`: rank rho +0.5361 -- related, NOT flagged for removal
- `prof_operating_profitability` ~ `prof_return_on_assets`: rank rho +0.9151 -- related, NOT flagged for removal
- `prof_operating_profitability` ~ `prof_return_on_equity`: rank rho +0.7167 -- related, NOT flagged for removal
- `prof_return_on_assets` ~ `prof_return_on_equity`: rank rho +0.7725 -- related, NOT flagged for removal
- `prof_return_on_assets` ~ `val_earnings_yield`: rank rho +0.5043 -- related, NOT flagged for removal
- `prof_return_on_equity` ~ `val_earnings_yield`: rank rho +0.5965 -- related, NOT flagged for removal

### Structural (descriptor-level, whole registry)
No identical or algebraically-equivalent formulas in the registry.

## Guarantees

- No forward return, IC, or t-statistic computed.
- No feature ranked by predictive performance.
- PIT measured per feature: 14/14 at 100.000000%.
- APEX-002's post-mortem did NOT motivate any feature. Liquidity
  features are justified from the data architecture and remain
  DATA_AVAILABLE, unbuilt, pending independent justification.
- Credits 2/5 unchanged; holdout sealed; APEX-003 not created.
