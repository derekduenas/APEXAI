#!/bin/bash
# REGRESSION-OOM-001 shard runner: ONE fresh contained process per module.
# Containment is the EXISTING contract -- slice wmresearch.slice, MemoryMax=1400M.
# Neither the unit cap nor the slice ceiling is raised anywhere in this brick.
# Exit status is the pytest status, never a later command's.
MOD="$1"; OUT="$2"
SLICE_EV=/sys/fs/cgroup/wmresearch.slice/memory.events
oom_before=$(awk '/^oom_kill /{print $2}' $SLICE_EV 2>/dev/null || echo -1)
t0=$(date +%s.%N)
sudo -n systemd-run --quiet --wait --pipe --collect --uid=apex --gid=apex \
  --slice=wmresearch.slice -p MemoryMax=1400M -p MemorySwapMax=0 -p Nice=10 \
  --working-directory=/opt/apex-repo --setenv=PYTHONPATH=/opt/apex-repo \
  --setenv=HOME=/home/apex -- \
  /bin/bash -c '
    CG=/sys/fs/cgroup$(awk -F: "{print \$3}" /proc/self/cgroup | head -1)
    /opt/apex/shared/venv/bin/python -m pytest -q -p no:cacheprovider \
      --rootdir=/opt/apex-repo -rsxX "'"$MOD"'"
    rc=$?
    echo "__PEAK_BYTES__=$(cat $CG/memory.peak 2>/dev/null || echo NA)"
    echo "__UNIT_OOM__=$(awk "/^oom_kill /{print \$2}" $CG/memory.events 2>/dev/null || echo NA)"
    exit $rc' > "$OUT" 2>&1
rc=$?                                  # pytest status, captured immediately
t1=$(date +%s.%N)
oom_after=$(awk '/^oom_kill /{print $2}' $SLICE_EV 2>/dev/null || echo -1)
echo "__RC__=$rc"                        >> "$OUT"
echo "__SLICE_OOM_BEFORE__=$oom_before"  >> "$OUT"
echo "__SLICE_OOM_AFTER__=$oom_after"    >> "$OUT"
echo "__SECONDS__=$(echo "$t1 - $t0" | bc)" >> "$OUT"
exit $rc
