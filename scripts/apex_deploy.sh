#!/usr/bin/env bash
# APEX RELEASE DEPLOYMENT -- immutable runtime.
#
# Development happens in the repo. Services run from an immutable
# release. The two must never be the same directory, because a
# `git checkout` under a running daemon is what killed the Phase A
# acquisition service on 2026-08-23.
#
#   /opt/apex-repo              mutable: sync, checkout, bundle freely
#   /opt/apex/releases/<sha>/   immutable: read-only, stamped
#   /opt/apex/current           pointer to the approved release
#   /opt/apex/shared/venv       interpreter shared across releases
#
# Deploying does NOT restart anything. Activation is an explicit,
# separate act, so a sync can never silently change what is running.
set -euo pipefail

REPO="${APEX_CANONICAL_REPO:-/opt/apex-repo}"
ROOT="${APEX_RELEASE_ROOT:-/opt/apex}"

# --- activation is a separate, explicit act
if [ "${1:-}" = "--activate" ]; then
  TARGET="$ROOT/releases/${2:?activate needs a commit sha}"
  [ -d "$TARGET" ] || { echo "no such release: $TARGET" >&2; exit 2; }
  [ -f "$TARGET/RELEASE.json" ] || { echo "release unstamped" >&2; exit 2; }
  # atomic pointer swap: a reader never sees a missing 'current'
  sudo ln -sfn "$TARGET" "$ROOT/.current.new"
  sudo mv -T "$ROOT/.current.new" "$ROOT/current"
  echo "current -> $(readlink -f "$ROOT/current")"
  echo "restart services to pick it up:"
  echo "  sudo systemctl restart apex-options-acquire.service"
  exit 0
fi

REF="${1:-HEAD}"

SHA="$(git -C "$REPO" rev-parse "$REF")"
SHORT="${SHA:0:8}"
DEST="$ROOT/releases/$SHA"

echo "deploying $SHORT from $REPO -> $DEST"

# CANONICAL-HISTORY GUARD: refuse to deploy a commit that exists only
# here. This is the exact failure that destroyed the Linux secret
# backend -- a cloud-only commit with no upstream copy.
if git -C "$REPO" rev-parse --verify -q "origin/main" >/dev/null 2>&1; then
  if ! git -C "$REPO" merge-base --is-ancestor "$SHA" origin/main; then
    echo "REFUSED: $SHORT is not an ancestor of origin/main." >&2
    echo "A host working tree is not a backup -- push it first." >&2
    exit 2
  fi
else
  echo "WARNING: no origin/main to check against; cannot prove this" >&2
  echo "commit exists anywhere but this host." >&2
fi

if [ -d "$DEST" ]; then
  echo "release already deployed (immutable, reusing)"
else
  sudo mkdir -p "$DEST"
  git -C "$REPO" archive "$SHA" | sudo tar -x -C "$DEST"
  printf '{\n "kind": "apex_release",\n "commit": "%s",\n "deployed_utc": "%s",\n "deployed_from": "%s",\n "deployed_by": "%s"\n}\n' \
    "$SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$REPO" "$(whoami)" \
    | sudo tee "$DEST/RELEASE.json" >/dev/null
  # IMMUTABLE: read+execute only. A later checkout cannot touch this.
  sudo chmod -R a-w "$DEST"
  echo "release written and sealed read-only"
fi

echo "deployed. NOT activated -- activation is explicit:"
echo "  $0 --activate $SHA"
