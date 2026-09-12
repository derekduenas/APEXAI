"""FORECAST FUSION, DECISION SUPERVISION, EXPERIENCE AND ENRICHMENT (M5).

    fusion       combination of valid component forecasts with weights estimated on genuinely out-of-fold
                 forecasts, frozen before evaluation, compared to the strongest OOF-selected baseline, with
                 leave-one-out ablations; lineage and target compatibility enforced
    supervision  PRIME-late decision supervision: ACT or ABSTAIN with named reasons (stale data, unsupported
                 state, model disagreement, quote uncertainty, insufficient margin, risk limits, missing
                 prerequisites); every "confidence" names its mathematical meaning; production authority NONE
    experience   immutable joins of pre-outcome forecasts/decisions to outcomes with error attribution classes
                 (ambiguous stays ambiguous); challenger proposals only; no history edits, no auto-tuning
    enrichment   LLM event-record schema with source links, clocks, dedup, extraction uncertainty and
                 prompt/model versions; no LLM call is made by this build

Offline design and synthetic integration only. Nothing here has production authority."""
