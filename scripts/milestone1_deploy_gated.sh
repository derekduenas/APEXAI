#!/bin/bash
# MILESTONE 1 -- gated deployment of the recovery candidate. FAIL-STOP.
# Every precondition is checked by command; the first failure aborts before
# the symlink moves. Nothing here restarts any service.
set -uo pipefail
REC=73fc712d355032e0a66b41675ba114491b04799d
INT=295d80e4243077ebd6b38875a45dd4cb6959f517
DEP=5eff1cf5e00f21b02c537f25bcd74b1c1d317546
REL=/opt/apex/releases/$REC
EV=/apex-data/tmp/m1_deploy; mkdir -p $EV
say(){ printf "  %-44s %s\n" "$1" "$2"; }
gate(){ if [ "$2" = "OK" ]; then say "$1" "ok"; else say "$1" "FAIL <<< $2"; echo "ABORT at gate: $1"; exit 10; fi; }
echo "=== GATED DEPLOY $(date -u +%Y-%m-%dT%H:%M:%SZ) target=$REC ==="

# ---- 1. regressions, on the exact commits, with unchanged manifests
for run in recovery3 integration3; do
  f=/apex-data/tmp/m1_runs/$run/regression.json
  [ -f "$f" ] || gate "$run present" "MISSING"
  v=$(python3 -c "import json;d=json.load(open('$f'));print(d['verdict'],d['commit'],d['source_identity_held'])")
  want=$([ $run = recovery3 ] && echo $REC || echo $INT)
  [ "$v" = "PASS $want True" ] && gate "$run PASS on $want manifest held" OK || gate "$run" "$v"
done
# ---- 2. the candidate is exactly what was reviewed
git -C /opt/apex-repo cat-file -e $REC^{commit} && gate "candidate commit exists" OK || gate "candidate commit" "MISSING"
n=$(git -C /opt/apex-repo diff --name-only $DEP $REC | wc -l); [ "$n" = "7" ] && gate "7-file inventory vs deployed" OK || gate "inventory" "$n files"
p=$(git -C /opt/apex-repo diff --name-only $DEP $REC | grep -vc "^tests/"); [ "$p" = "2" ] && gate "2 production files" OK || gate "production files" "$p"
# ---- 3. production state is what the package describes
[ "$(readlink -f /opt/apex/current)" = "/opt/apex/releases/$DEP" ] && gate "current = deployed 5eff1cf5" OK || gate "current" "$(readlink -f /opt/apex/current)"
[ "$(systemctl show apex-orchestrator.service -p MemoryMax --value)" = "536870912" ] && gate "unit MemoryMax 512M unchanged" OK || gate "MemoryMax" "changed"
[ "$(systemctl show apex-orchestrator.service -p Result --value)" = "oom-kill" ] && gate "orchestrator still in the OOM loop" OK || gate "orchestrator" "$(systemctl show apex-orchestrator.service -p Result --value)"
# ---- 4. maintenance compliance: blocks present, drop-ins declare them, orchestrator starts via systemctl
for n_ in equity_fabric btc_resolver; do [ -f /apex-data/core/ops/MAINTENANCE_BLOCK_$n_ ] && gate "block $n_ present" OK || gate "block $n_" "ABSENT"; done
grep -q "ConditionPathExists=!/apex-data/core/ops/MAINTENANCE_BLOCK_equity_fabric" /etc/systemd/system/apex-equity-fabric.service.d/10-maintenance-block.conf && gate "equity-fabric drop-in declares the block" OK || gate "drop-in" "MISSING"
SA=$(systemd-analyze condition "ConditionPathExists=!/apex-data/core/ops/MAINTENANCE_BLOCK_equity_fabric" 2>&1 || true)
# systemd-analyze exits NONZERO when the condition fails; that is the answer we want, so test the text, never the pipeline status
case "$SA" in *"Conditions failed"*) gate "systemd refuses equity-fabric start" OK ;; *) gate "systemd condition" "would allow: $SA" ;; esac
git -C /opt/apex-repo show $REC:apex/ops/orchestrator.py | grep -q 'SYSTEMCTL = ("/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start")' && gate "orchestrator starts via systemctl" OK || gate "start path" "not systemctl"
git -C /opt/apex-repo show $REC:scripts/apex_orchestrator.py | grep -q "def maintenance_status" && gate "R3 preflight present in candidate" OK || gate "R3" "absent"
if git -C /opt/apex-repo show $REC:scripts/apex_orchestrator.py | grep -q 'outcome="STARTED"'; then gate "R4: STARTED outcome removed" "still present"; else gate "R4: STARTED outcome removed" OK; fi
# ---- 5. ledger prefixes and unit baseline, captured NOW
for L in /apex-data/core/ops/orchestrator.jsonl /apex-data/core/historical/continuous/decisions.jsonl /apex-data/core/btc/derivatives_ledger.jsonl /apex-data/core/btc/ws_book_ledger.g2.jsonl /apex-data/core/historical/continuous/outcomes.jsonl; do
  N=$(stat -c %s "$L"); H=$(head -c "$N" "$L" | sha256sum | cut -d" " -f1); echo "$L $N $H"; done > $EV/pre_deploy_ledger_prefixes.txt
[ "$(wc -l < $EV/pre_deploy_ledger_prefixes.txt)" = "5" ] && gate "5 ledger prefix hashes captured" OK || gate "prefix hashes" "incomplete"
grep -q "orchestrator.jsonl 438867453 " $EV/pre_deploy_ledger_prefixes.txt && gate "orchestrator ledger still 438867453 bytes" OK || gate "orchestrator ledger size" "changed: $(grep orchestrator.jsonl $EV/pre_deploy_ledger_prefixes.txt | cut -d' ' -f2)"
systemctl show apex-orchestrator.service -p NRestarts -p Result -p ExecMainStatus > $EV/pre_deploy_unit.txt
python3 -c "import json;d=json.load(open('/apex-data/core/heartbeats/orchestrator.json'));print(d['last_work_utc'],d['work_completed'])" > $EV/pre_deploy_hb.txt
say "baseline" "$(tr '\n' ' ' < $EV/pre_deploy_unit.txt) hb=$(cat $EV/pre_deploy_hb.txt)"
# ---- 6. host headroom and disk
a=$(free -m | awk '/^Mem:/{print $7}'); [ "$a" -gt 3000 ] && gate "host available memory ${a}MiB" OK || gate "memory" "${a}MiB"
d=$(df -BG --output=avail /opt | tail -1 | tr -dc 0-9); [ "$d" -gt 20 ] && gate "disk ${d}G free" OK || gate "disk" "${d}G"
echo; echo "ALL GATES PASSED."
if [ "${1:-}" != "--execute" ]; then echo "(dry-run: nothing deployed. Re-run with --execute to swap.)"; exit 0; fi
# ---- 7. build the immutable release and swap
sudo -u apex git -C /opt/apex-repo worktree add --detach $REL $REC && gate "release worktree built" OK || gate "release worktree" "FAILED"
[ "$(git -C $REL rev-parse HEAD)" = "$REC" ] && gate "release HEAD is the candidate" OK || gate "release HEAD" "$(git -C $REL rev-parse HEAD)"
sudo chmod -R a-w $REL && gate "release made read-only" OK || gate "chmod" "FAILED"
sudo ln -sfn $REL /opt/apex/current.new && sudo mv -T /opt/apex/current.new /opt/apex/current && gate "symlink swapped" OK || gate "symlink swap" "FAILED"
echo "current -> $(readlink -f /opt/apex/current)   $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee $EV/swap.txt
echo "DEPLOYED. No service was restarted; the orchestrator picks up the release on its next ~31 s restart."
