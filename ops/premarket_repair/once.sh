#!/bin/zsh
# Same entry point the scheduler uses, for one stage.
#   ./once.sh 0815_ET_initial
# A stage invoked outside its window records TOO_EARLY or MISSED_WINDOW and exits. It does not wait.
exec /bin/zsh "$HOME/apex-equities/ops/premarket.sh" "${1:?usage: once.sh <stage>}"
