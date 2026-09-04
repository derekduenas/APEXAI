#!/bin/bash
# WORLD_MODEL_COMPUTE_CONTAINMENT_V0
#
# Every World Model compute -- pytest, regression, courts, calibration,
# bootstrap, model fitting -- goes through this wrapper and nowhere else.
# It places the command in wmresearch.slice: a DEDICATED top-level
# slice (sibling of apex.slice, not a child of it) that contains NO
# production service. Slice MemoryMax=1536M, CPUQuota=150%, CPUWeight=30;
# the unit gets its own MemoryMax=1400M, CPUWeight=30, Nice=10. A runaway
# research job is killed by its own boundary and can never compete inside
# a bounded slice with production. Existing cgroups are never touched.
#
# INFRA-RESEARCH-LOAD-UNCONTAINED-001, two failed forms before this:
#   1. unrestricted user.slice (peak 7608 MiB of 7941; could have blocked
#      Gate-2 had timing differed)
#   2. shared apex-research.slice (2 GiB parent holding edgeforge-
#      observatory + equity-field): a 1200M unit cap still competes with
#      production inside the same aggregate ceiling -- rejected by CSO.
set -u
W=/opt/apex-research/world-model-shadow
exec sudo -n systemd-run --quiet --wait --pipe --collect \
  --uid=apex --gid=apex --slice=wmresearch.slice \
  --description="WM contained: $*" \
  -p MemoryAccounting=yes -p MemoryMax=1400M -p MemorySwapMax=0 \
  -p CPUWeight=30 -p Nice=10 -p TasksMax=256 \
  --working-directory="$W" \
  --setenv=PYTHONPATH="$W" --setenv=HOME=/home/apex \
  --setenv=PYTHONDONTWRITEBYTECODE=1 --setenv=WM_CONTAINED=1 \
  -- "$@"
