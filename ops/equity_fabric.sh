#!/bin/zsh
# Vendor-neutral entrypoint for the equity market-data fabric.
# The architecture guard forbids broker/vendor names inside apex/**,
# so the orchestrator's roster points here and this wrapper owns the
# concrete transport script.
exec /bin/zsh /Users/derekduenas/apex-equities/ops/alpaca_fabric.sh
