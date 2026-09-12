"""PULSE / DIGITAL MARKET TWIN for the options pilot (M2).

    ingest     event-time ingestion: trades or provider bars -> completed 1-minute bars
               with availability and receipt clocks; dedupe, out-of-order, revisions, late data
    snapshot   one immutable as-of state (OPTIONS_TWIN_STATE_V0) built only from what was
               available by the as-of instant; every field is a pulse.twin.Field
    features   ONE feature implementation for replay and live inference (the frozen
               artifact's recipe), with prefix invariance
    inference  the frozen-artifact adapter (EXP-002 L arm, INVALID_NULL_CONTROL provenance,
               no validated-edge claim) that reproduces the reference forecasts
    providers  adapter interfaces + synthetic fixtures; production connectivity is disabled
               unless credentials and an explicit operator switch are present"""
