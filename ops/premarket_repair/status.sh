#!/bin/zsh
# The question the 19-day gap could not answer: did it run, and when will it next?
STAGES=(0815_ET_initial 0832_ET_post_macro 0905_ET_refresh 0920_ET_final seal reconcile)
echo "== launchd =="
for s in $STAGES; do
  printf '%-20s ' "$s"
  launchctl print "gui/$(id -u)/com.apex.premarket.$s" 2>/dev/null \
    | grep -E "^\s+(state|runs|last exit code)" | tr -d '\n' || printf 'NOT LOADED'
  echo
done
printf '%-20s ' "(superseded single)"
launchctl print "gui/$(id -u)/com.apex.premarket" >/dev/null 2>&1 \
  && echo "STILL LOADED -- it should not be; run install.sh" || echo "absent, as intended"
echo "== scheduler timezone =="
# The plists carry LOCAL times derived from ET. They are only correct while this host tracks US Eastern.
TZN="$(readlink /etc/localtime | sed 's|.*zoneinfo/||')"
[[ "$TZN" == "America/Los_Angeles" ]] && echo "$TZN (matches the zone the plists were generated for)" \
  || echo "$TZN -- MISMATCH: the prepared plists assume America/Los_Angeles; regenerate them"
echo "== last completed packet =="
ls -t "$HOME/apex-equities/results/frontier/premarket"/????-??-??.json 2>/dev/null | head -1 || echo "NONE"
echo "== today's journal =="
D="$HOME/apex-equities/results/frontier/premarket/journal/$(date +%Y-%m-%d)"
if [[ -f "$D/events.jsonl" ]]; then
  echo "$(wc -l < "$D/events.jsonl") events; last states:"
  tail -6 "$D/events.jsonl" | python3 -c "import sys,json
for l in sys.stdin:
    e=json.loads(l); print('   seq %3d %-20s %s' % (e['seq'], e['stage'], e['state']))"
else
  echo "NONE for today"
fi
echo "== next scheduled =="
echo "Mon-Fri, one agent per stage: 05:15 05:32 06:05 06:20 06:25 06:40 local."
echo "NOTE: a StartCalendarInterval run missed because the machine was ASLEEP is COALESCED and fires once on"
echo "wake (man 5 launchd.plist). That is exactly the early start the staged producer now refuses: a coalesced"
echo "stage arriving hours after its window records MISSED_WINDOW instead of absorbing stale data."
