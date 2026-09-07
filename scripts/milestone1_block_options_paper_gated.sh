#!/bin/bash
# MILESTONE 1 -- LAUNCH-AUTHORIZATION RECONCILIATION: hold the restriction on
# apex-options-paper.service at the next RTH phase (2026-09-08T13:30Z) using
# the SAME maintenance-block convention that already governs equity-fabric and
# btc-resolver. Fail-stop. Dry-run by default; --execute applies.
#
# NOT EXECUTED BY THE AGENT. --execute performs a systemd configuration change
# (a root-owned drop-in plus daemon-reload), which the recovery authorization
# does not cover. It is prepared here so the reviewer decides from the exact
# files and can apply or refuse it in one step, before 13:30Z.
#
# REVERSAL: rm the marker (block lifts immediately, no reload needed), or rm
# the drop-in and daemon-reload. Nothing else is touched.
set -uo pipefail
UNIT=apex-options-paper.service
MARK=/apex-data/core/ops/MAINTENANCE_BLOCK_options_paper
DROP=/etc/systemd/system/$UNIT.d/10-maintenance-block.conf
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
say(){ printf "  %-50s %s\n" "$1" "$2"; }
gate(){ if [ "$2" = "OK" ]; then say "$1" "ok"; else say "$1" "FAIL <<< $2"; echo "ABORT at gate: $1"; exit 10; fi; }
echo "=== OPTIONS-PAPER LAUNCH HOLD  $NOW  RTH opens 2026-09-08T13:30:00Z ==="

# ---- preconditions: the state this arrangement assumes
[ "$(systemctl show $UNIT -p ActiveState --value)" = "inactive" ] && gate "$UNIT is inactive" OK || gate "$UNIT state" "$(systemctl show $UNIT -p ActiveState --value)"
[ ! -f "$MARK" ] && gate "no marker yet" OK || gate "marker" "already present: $MARK"
[ ! -f "$DROP" ] && gate "no drop-in yet" OK || gate "drop-in" "already present: $DROP"
[ "$(readlink -f /opt/apex/current)" = "/opt/apex/releases/73fc712d355032e0a66b41675ba114491b04799d" ] && gate "current release is 73fc712d (R3 preflight present)" OK || gate "current release" "$(readlink -f /opt/apex/current)"
grep -q 'ConditionPathExists=!/apex-data/core/ops/MAINTENANCE_BLOCK_equity_fabric' /etc/systemd/system/apex-equity-fabric.service.d/10-maintenance-block.conf && gate "convention reference (equity-fabric drop-in) intact" OK || gate "convention reference" "missing"

echo
echo "--- marker that would be written: $MARK"
cat <<EOF | sed 's/^/    /'
OPTIONS_PAPER_STATUS = MAINTENANCE_BLOCKED_PENDING_LAUNCH_AUTHORIZATION
applied_utc = $NOW
reason = the recovery deployment authorization excludes launches of inactive
         services merely because the orchestrator deems them eligible. The
         recovered orchestrator (73fc712d) would issue systemctl start for
         this unit at the next RTH phase (demonstrated in dry-run, 2026-09-07).
         This is NOT a defect in the service; it is a pending authorization.
evidence = docs/MILESTONE1_LAUNCH_RECONCILIATION.md
authority = launch requires an explicit reviewer decision
reversal = rm this file (or rm the drop-in and systemctl daemon-reload)
EOF
echo "--- drop-in that would be written: $DROP"
cat <<EOF | sed 's/^/    /'
# OPTIONS_PAPER_STATUS = MAINTENANCE_BLOCKED_PENDING_LAUNCH_AUTHORIZATION
# Applied $NOW. REVERSIBLE: delete the flag file, or delete this drop-in + daemon-reload.
# Blocks orchestrator starts, boot starts, AND systemd Restart=on-failure.
# Does NOT change MemoryMax. Does NOT delete the unit or any evidence.
[Unit]
ConditionPathExists=!$MARK
EOF

if [ "${1:-}" != "--execute" ]; then
  echo; echo "(dry-run: nothing written, nothing reloaded. Re-run with --execute to apply.)"; exit 0
fi

# ---- apply, in the order that is safe if interrupted: marker first (inert
# until a drop-in declares it), drop-in second, reload last
cat > "$MARK" <<EOF
OPTIONS_PAPER_STATUS = MAINTENANCE_BLOCKED_PENDING_LAUNCH_AUTHORIZATION
applied_utc = $NOW
reason = the recovery deployment authorization excludes launches of inactive services merely because the orchestrator deems them eligible. The recovered orchestrator (73fc712d) would issue systemctl start for this unit at the next RTH phase (demonstrated in dry-run, 2026-09-07). This is NOT a defect in the service; it is a pending authorization.
evidence = docs/MILESTONE1_LAUNCH_RECONCILIATION.md
authority = launch requires an explicit reviewer decision
reversal = rm this file (or rm the drop-in and systemctl daemon-reload)
EOF
[ -f "$MARK" ] && gate "marker written" OK || gate "marker write" "FAILED"
sudo mkdir -p "$(dirname "$DROP")" && sudo tee "$DROP" >/dev/null <<EOF
# OPTIONS_PAPER_STATUS = MAINTENANCE_BLOCKED_PENDING_LAUNCH_AUTHORIZATION
# Applied $NOW. REVERSIBLE: delete the flag file, or delete this drop-in + daemon-reload.
# Blocks orchestrator starts, boot starts, AND systemd Restart=on-failure.
# Does NOT change MemoryMax. Does NOT delete the unit or any evidence.
[Unit]
ConditionPathExists=!$MARK
EOF
[ -f "$DROP" ] && gate "drop-in written" OK || gate "drop-in write" "FAILED"
sudo systemctl daemon-reload && gate "daemon-reload" OK || gate "daemon-reload" "FAILED"

# ---- verify: systemd refuses, the drop-in is loaded, and the DEPLOYED R3
# preflight now says BLOCKED for this unit (read-only probe)
SA=$(systemd-analyze condition "ConditionPathExists=!$MARK" 2>&1 || true)
case "$SA" in *"Conditions failed"*) gate "systemd refuses $UNIT start" OK ;; *) gate "systemd condition" "would allow: $SA" ;; esac
systemctl show $UNIT -p DropInPaths --value | grep -q "10-maintenance-block.conf" && gate "drop-in loaded by systemd" OK || gate "drop-in loaded" "not listed"
PF=$(cd /opt/apex/current && PYTHONPATH=/opt/apex/current /opt/apex/shared/venv/bin/python -c "
import importlib.util
from apex.ops.orchestrator import default_roster
s=importlib.util.spec_from_file_location('o','/opt/apex/current/scripts/apex_orchestrator.py'); O=importlib.util.module_from_spec(s); s.loader.exec_module(O)
sp=[x for x in default_roster('cloud') if x.name=='options-paper'][0]; print(O.maintenance_status(sp)[0])")
[ "$PF" = "BLOCKED" ] && gate "deployed R3 preflight says BLOCKED for options-paper" OK || gate "R3 preflight" "$PF"
echo; echo "APPLIED $NOW. At 13:30Z the orchestrator will record MAINTENANCE_BLOCKED for options-paper and attempt nothing."
echo "Reversal: rm $MARK"
