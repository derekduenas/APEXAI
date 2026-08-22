"""BTC PERPS SLEEVE -- shared semantics for the 24/7 hunting ground.

Founded during weekend commissioning 2026-08-21/22. The sleeve's first
modules are SEMANTIC, not intelligent: BTC-L2 immediately caught raw
ticks masquerading as dollars, an expired contract's settlement method
contaminating the active one, and daily-published OI polled at 15s
looking real-time. Units and cadences are laws here, not comments.

decision_power: NONE -- BTC-L3+ cognition is NOT_AUTHORIZED.
"""
BTC_SLEEVE_POWER = "NONE_BTC_SLEEVE_L2"
