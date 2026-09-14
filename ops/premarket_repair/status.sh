#!/bin/zsh
# The question the 19-day gap could not answer: did it run, and when will it next?
echo "== launchd =="
launchctl print "gui/$(id -u)/com.apex.premarket" 2>/dev/null | grep -E "state|runs|last exit|path" || echo "NOT LOADED"
echo "== last completed packet =="
ls -t "$HOME/apex-equities/results/frontier/premarket"/*.json 2>/dev/null | head -1 || echo "NONE"
echo "== last 3 run records =="
ls -t "$HOME/apex-equities/results/frontier/premarket/runs"/*.json 2>/dev/null | head -3 || echo "NONE (run accounting not yet active)"
echo "== next scheduled =="
echo "Mon-Fri 05:14 local, per StartCalendarInterval. NOTE: a missed calendar run is NOT retried by launchd."
