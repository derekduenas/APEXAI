"""THE FORECAST LAYER -- math estimates, LLM explains, gates decide.

The single largest blocker between "decision organism" and "profit
organism" (operator ruling, 2026-08-20): Capital correctly refuses
every opportunity because nothing can hand it a calibrated forecast.
This package is the socket that will eventually fill -- built
EMPIRICALLY from the prospective outcome corpus, never from a language
model's opinion and never from a backtest fitted to look good.

    pattern / market state
        -> prospective analog/outcome corpus   (resolution.outcome_corpus)
        -> empirical distribution              (this package)
        -> calibrated mathematical forecast    (only after gates + calibration)

THE LAW: most outputs say FORECAST_NOT_ESTIMABLE for a long time, and
that is correct. A ForwardDistribution with numbers exists ONLY when the
support gates pass AND the corpus is large enough AND calibration has
been demonstrated out-of-sample. Until then the object still exists --
carrying its blockers, so every refusal is inspectable -- but its
quantiles are None and its status is honest.

decision_power: NONE -- this layer estimates; Capital decides.
"""
FORECAST_POWER = "NONE_FORECAST_LAYER"

FORECAST_NOT_ESTIMABLE = "FORECAST_NOT_ESTIMABLE"
FORECAST_ESTIMABLE_UNCALIBRATED = "FORECAST_ESTIMABLE_UNCALIBRATED"
FORECAST_CALIBRATED = "FORECAST_CALIBRATED"
