"""The distribution estimator -- the transition from signal to probability.

"I have a signal" becomes "I have a probabilistic view of what happens
next", with the provenance chain intact:

    signal -> conditioning information -> estimation window -> methodology
           -> distribution -> calibration status

Four statuses, distinguished and NEVER conflated: CALIBRATED (reality-loop
evidence, minted only against a verifiable report), UNCALIBRATED_MODEL,
HISTORICAL_EMPIRICAL, SYNTHETIC. Downstream code structurally cannot treat
an uncalibrated distribution as calibrated: the mapping into the expression
engine's DistributionSource is total, explicit, and refuses to upgrade.
"""
