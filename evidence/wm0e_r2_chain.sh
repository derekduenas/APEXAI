#!/bin/bash
# WM-0E-R2 execution chain. Runs under nohup on the box. Every compute
# step goes through wm_contained.sh. No step reads a result to change a
# parameter; a failure stops the chain and is sealed as a failure.
W=/opt/apex-research/world-model-shadow
LOG=/tmp/wm0e_r2_chain.log
exec >>"$LOG" 2>&1
say(){ echo "$(date -u +%FT%TZ) $*"; }
CT=/home/apex/bin/wm_contained.sh
PY=/opt/apex/shared/venv/bin/python

say "chain v2 start (dedicated wmresearch.slice) -- waiting: observer inactive AND clock >= 20:11Z"
while :; do
  now=$(date -u +%H%M); obs=$(systemctl is-active apex-gate2-observer.service)
  if [ "$obs" != "active" ] && [ "$now" -ge 2011 ]; then break; fi
  sleep 60
done
say "window closed: observer=$obs stop=$(systemctl is-active apex-gate2-stop.service)"

say "STEP 1: seal Gate-2 BLOCKED / NOT_RUN"
$PY /home/apex/bin/seal_gate2_blocked.py || { say "gate2 seal refused/failed -> abort"; exit 1; }

say "STEP 2: isolation proof -- production cgroup paths:"
for u in $(systemctl list-units --no-legend --plain --state=active "apex*.service" | awk '{print $1}'); do echo "  $u $(systemctl show $u -p ControlGroup --value)"; done
echo "  wmresearch.slice members: $(systemd-cgls --no-pager /wmresearch.slice 2>/dev/null | grep -c '\.service')"
say "STEP 2b: containment negative control (expect SIGKILL on over-allocation)"
$CT $PY /home/apex/bin/containment_proof.py; rc=$?; say "proof exit=$rc (137/SIGKILL = contained; 4 = NOT contained)"
[ "$rc" = "4" ] && { say "containment NOT enforced -> abort"; touch /tmp/wm0e_r2_chain.DONE; exit 1; }

say "STEP 3: focused WM tests (contained)"
$CT $PY -m pytest tests/test_world_model_bootstrap.py tests/test_world_model_inference.py tests/test_world_model_court.py -q -p no:cacheprovider || { say "focused tests FAILED -> abort"; touch /tmp/wm0e_r2_chain.DONE; exit 1; }

say "STEP 4: calibration exercise (contained)"
$CT $PY evidence/wm0e_r2_calibrate_bootstrap.py evidence/wm0e_r2_calibration_exercise.json || { say "calibration script error -> abort"; touch /tmp/wm0e_r2_chain.DONE; exit 1; }
cd "$W" && git add evidence && git -c user.name=apex -c user.email=apex@apex.local commit -q -m "WM-0E-R2: bootstrap calibration exercise (pre-acceptance, envelope predeclared)"
SHA=$(git rev-parse --short HEAD); say "calibration committed at $SHA sha256=$(sha256sum evidence/wm0e_r2_calibration_exercise.json | cut -c1-16)"
V=$(python3 -c "import json;print(json.load(open('$W/evidence/wm0e_r2_calibration_exercise.json'))['envelope_verdict'])")
say "ENVELOPE_VERDICT=$V"
if [ "$V" != "PASS" ]; then say "calibration FAILED envelope -> STOP; court NOT convened"; touch /tmp/wm0e_r2_chain.DONE; exit 0; fi

say "STEP 5: convene NULL_COURT_V2 once (contained)"
$CT $PY evidence/wm0e_r2_convene_v2.py "$SHA" evidence/wm0e_r2_calibration_exercise.json "evidence/court_v2_${SHA}.json"; say "court runner exit=$?"
cd "$W" && git add evidence && git -c user.name=apex -c user.email=apex@apex.local commit -q -m "WM-0E-R2: NULL_COURT_V2_BLOCK_BOOTSTRAP sitting evidence (as it ran)"
say "court committed at $(git rev-parse --short HEAD)"

say "STEP 6: full regression (contained, 1200M unit cap)"
$CT $PY -m pytest tests/ -q -p no:cacheprovider > /tmp/wm0e_r2_full.txt 2>&1; say "regression exit=$? :: $(tail -c 160 /tmp/wm0e_r2_full.txt | tr '\n' ' ')"
touch /tmp/wm0e_r2_chain.DONE; say "chain done"
