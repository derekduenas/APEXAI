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
echo "== market time vs local time =="
# The plists carry LOCAL trigger times derived from MARKET (America/New_York) targets. This prints both, the UTC
# instant, the host zone and the binding check, so a shifted morning is visible before it happens.
cd "$HOME/apex-equities" 2>/dev/null && .venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "."); sys.path.insert(0, "ops/premarket_repair")
from apex.frontier import market_time as MT
from apex.frontier import premarket_stages as PS
host = MT.host_timezone()
binding = MT.load_binding()
print("host timezone       %s  (%s)" % (host["name"], host["evidence"]))
print("market timezone     %s  (authoritative)" % MT.MARKET_TZ)
try:
    print("binding             %s" % MT.verify_binding(binding, host)["status"])
except MT.TimezoneConfigurationMismatch as e:
    print("binding             REFUSED\n%s" % e)
nxt = MT.next_market_session()
print("next market session %s" % nxt)
stages = list(PS.STAGE_SCHEDULE) + [("reconcile", 9, 40)]
print("   %-20s %-10s %-8s %-26s %s" % ("STAGE", "MARKET", "LOCAL", "UTC INSTANT", "MKT-LOC"))
for r in MT.schedule_table(stages, host["name"] if host["resolved"] else "UTC", nxt):
    print("   %-20s %-10s %-8s %-26s %+.1fh"
          % (r["stage"], r["market_time"] + " ET", r["local_time"], r["utc_instant"],
             r["market_minus_local_hours"]))
PY
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
