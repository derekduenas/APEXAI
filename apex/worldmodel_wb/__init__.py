"""WORLD MODEL WORKBENCH (M3) — model contracts, executable synthetic candidates, tournament.

    contracts       ForecastObject (declares mean | quantiles | density | paths; unsupported -> refuse),
                    Model interface (fit / forecast / serialize / load / describe), fit-count accounting,
                    deterministic artifact digests
    vol_models      RollingVariance, EWMA, GARCH(1,1), GJR-GARCH(1,1) with standardized Student-t
                    innovations; convention tests; analytic and simulated horizon aggregation
    quantile_tree   bounded quantile gradient boosting (stumps) with ordered-quantile enforcement and
                    crossing measured BEFORE correction
    dist_boost      NGBoost-style natural-gradient boosting of a Normal(mu, sigma) with the log score
    regime          two-state Gaussian Markov-switching estimator; FILTERED probabilities only for
                    decisions; abstention when unsupported
    tournament      walk-forward folds with purge + embargo, as-of data firewall, scoring, calibration,
                    common-row comparison, trial registry with a registered search budget
    foundation      Chronos-2 / TimesFM 2.5 adapter interfaces; BLOCKED_RESOURCE / BLOCKED_LICENSE states
    study_contract  what every proposed historical study must declare before any access

Nothing here fits historical data. Every fit in the tests is on synthetic worlds."""
