"""MULTIVERSE + MARKET-IMPLIED COMPARISON workbench (M4).

    simulator        transparent conditional joint simulator: underlying path (GARCH-t recursion), variance path,
                     an IV state process that is DECLARED (fixed / stressed / drift), an execution-condition
                     process; seeds, cutoffs, parameter hashes, discretization preserved; sampling error
                     reported separately from model uncertainty; unweighted stress branches kept separate
    pricing          quote sanitation, European reference pricer (Black-Scholes-Merton with continuous yield),
                     IV inversion with no-arbitrage bounds, declared Greeks, CRR binomial American engine,
                     instrument metadata with exercise/settlement/multiplier/adjustment conventions
    surface          SVI slice fit to total implied variance with Durrleman butterfly and calendar diagnostics;
                     failures recorded, never projected into a clean surface
    expression_war   finite expression comparison (WAIT + the deterministic long-option baseline + candidates)
                     under COMMON paths and documented costs at the actual 15-minute exit horizon; expected
                     economic value is marked UNESTABLISHED unless future IV is credibly modeled

No market data. Every number in the tests comes from a synthetic world."""
