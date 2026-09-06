#!/bin/bash
# PULSE-007 bounded regression: one fresh CONTAINED process per test module.
#
# A single pytest process over all 210 modules exceeded the wmresearch.slice
# ceiling (1536M) and was OOM-killed at ~52% -- the same failure mode the
# world-model branch met and solved with fresh-process module sharding. The
# slice ceiling is not raised; the work is divided instead.
#
# This branch contains no apex/world_model, no courts/ and no acceptance seed
# machinery (verified before running), so no shard can execute an acceptance
# court or consume acceptance data.
REPO=/opt/apex-repo
OUT=$REPO/results/pulse009_regression
LOG=/tmp/p7_shard_regression.log
exec >>"$LOG" 2>&1
mkdir -p "$OUT"
cd "$REPO" || exit 1
COMMIT=$(git rev-parse --short HEAD); TREE=$(git write-tree); DIRTY=$(git status --short | wc -l)
echo "$(date -u +%FT%TZ) SHARDED REGRESSION start commit=$COMMIT tree=$TREE staged_or_dirty=$DIRTY"
PASS=0; FAIL=0; ERR=0; SKIP=0; XF=0; XP=0; SHARDS=0; BAD=""; OOM_BEFORE=$(awk '/^oom_kill /{print $2}' /sys/fs/cgroup/wmresearch.slice/memory.events)
PEAK=0
for m in $(ls tests/test_*.py | sort); do
  SHARDS=$((SHARDS+1))
  R=$(sudo -n systemd-run --quiet --wait --pipe --collect --uid=apex --gid=apex \
        --slice=wmresearch.slice -p MemoryAccounting=yes -p MemoryMax=1400M \
        -p MemorySwapMax=0 -p CPUWeight=30 -p Nice=10 -p TasksMax=256 \
        --working-directory=$REPO --setenv=PYTHONPATH=$REPO --setenv=HOME=/home/apex \
        --setenv=PYTHONDONTWRITEBYTECODE=1 \
        -- /opt/apex/shared/venv/bin/python -m pytest -q -p no:cacheprovider \
           --rootdir=$REPO "$m" 2>&1)
  RC=$?
  LINE=$(echo "$R" | grep -E "^[0-9]+ (passed|failed)|passed|failed|error" | tail -1)
  p=$(echo "$LINE" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+"); p=${p:-0}
  f=$(echo "$LINE" | grep -oE "[0-9]+ failed" | grep -oE "[0-9]+"); f=${f:-0}
  e=$(echo "$LINE" | grep -oE "[0-9]+ error" | grep -oE "[0-9]+"); e=${e:-0}
  s=$(echo "$LINE" | grep -oE "[0-9]+ skipped" | grep -oE "[0-9]+"); s=${s:-0}
  xf=$(echo "$LINE" | grep -oE "[0-9]+ xfailed" | grep -oE "[0-9]+"); xf=${xf:-0}
  xp=$(echo "$LINE" | grep -oE "[0-9]+ xpassed" | grep -oE "[0-9]+"); xp=${xp:-0}
  PASS=$((PASS+p)); FAIL=$((FAIL+f)); ERR=$((ERR+e)); SKIP=$((SKIP+s)); XF=$((XF+xf)); XP=$((XP+xp))
  echo "$R" > "$OUT/$(basename "$m" .py).txt"
  if [ "$RC" != "0" ] && [ "$RC" != "5" ]; then
    BAD="$BAD $m(rc=$RC)"
    printf "  %-56s rc=%-3s %s\n" "$m" "$RC" "$LINE"
  fi
done
OOM_AFTER=$(awk '/^oom_kill /{print $2}' /sys/fs/cgroup/wmresearch.slice/memory.events)
echo "$(date -u +%FT%TZ) SHARDS=$SHARDS PASS=$PASS FAIL=$FAIL ERROR=$ERR SKIP=$SKIP XFAIL=$XF XPASS=$XP"
echo "oom_kill slice $OOM_BEFORE -> $OOM_AFTER | problem shards:${BAD:- none}"
python3 - "$COMMIT" "$TREE" "$SHARDS" "$PASS" "$FAIL" "$ERR" "$SKIP" "$XF" "$XP" "$OOM_BEFORE" "$OOM_AFTER" "$BAD" <<'PY'
import json, sys, datetime
k = sys.argv
doc = {"kind": "pulse007_bounded_regression", "version": "PULSE007_SHARDED_REGRESSION_V1",
       "law": "one fresh contained process per test module; the slice ceiling is not raised",
       "commit": k[1], "tree": k[2], "shards": int(k[3]),
       "totals": {"PASS": int(k[4]), "FAIL": int(k[5]), "ERROR": int(k[6]),
                  "SKIP": int(k[7]), "XFAIL": int(k[8]), "XPASS": int(k[9])},
       "slice_oom_kill_before": int(k[10]), "slice_oom_kill_after": int(k[11]),
       "problem_shards": k[12].split() if k[12].strip() else [],
       "acceptance_surface_on_this_branch": "NONE (no apex/world_model, no courts/, no seed machinery)",
       "utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
doc["verdict"] = ("PASS" if (doc["totals"]["FAIL"] == 0 and doc["totals"]["ERROR"] == 0
                             and not doc["problem_shards"]
                             and doc["slice_oom_kill_after"] == doc["slice_oom_kill_before"])
                  else "FAIL")
json.dump(doc, open("/opt/apex-repo/results/pulse009_bounded_regression.json", "w"), indent=1)
print("VERDICT:", doc["verdict"], doc["totals"])
PY
touch /tmp/p7_shard_regression.DONE
