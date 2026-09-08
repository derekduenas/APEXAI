#!/bin/bash
# Probe the research launch containment WITHOUT performing any setup.
#
# It creates a two-file temporary dataset view, runs the exact sandbox
# composition from RESEARCH_ACTIVATION_PACKAGE.md section 6 as a NON-ROOT
# user, records what that process could and could not reach, and removes the
# view. It creates no account, changes no permission, mounts nothing
# persistent and touches neither the corpus nor production.
#
#   scripts/si004_sandbox_probe.sh <out.json> [user] [checkout]
#
# The probe user stands in for apexresearch, which does not exist yet: the
# containment is what is being measured, not the account.
set -u
OUT="${1:?usage: si004_sandbox_probe.sh <out.json> [user] [checkout]}"
PROBE_USER="${2:-apex}"
CHECKOUT="${3:-$(cd "$(dirname "$0")/.." && pwd)}"
V=$(mktemp -d /apex-data/tmp/si004_view_XXXXXX)
CORPUS=/apex-data/history-b/etf_continuous/bars
ADMITTED=SPY_2019-06-03.json          # inside train+validation
DENIED=SPY_2023-06-01.json            # evaluation period: must NOT be visible

mkdir -p "$V/etf_continuous/bars"
cp -p "$CORPUS/$ADMITTED" "$V/etf_continuous/bars/" || { echo "cannot stage view"; exit 2; }
SRC_SHA=$(sha256sum "$CORPUS/$ADMITTED" | cut -d' ' -f1)
VIEW_SHA=$(sha256sum "$V/etf_continuous/bars/$ADMITTED" | cut -d' ' -f1)

RAW=$(sudo -n systemd-run --quiet --wait --pipe --collect --slice=wmresearch.slice \
  -p User="$PROBE_USER" -p Group="$PROBE_USER" \
  -p MemoryMax=512M -p TasksMax=64 \
  -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
  -p PrivateNetwork=yes -p NoNewPrivileges=yes -p RestrictSUIDSGID=yes \
  -p TemporaryFileSystem=/apex-data/history-b \
  -p BindReadOnlyPaths="$V/etf_continuous/bars:$CORPUS" \
  -p InaccessiblePaths=/apex-data/core \
  -p InaccessiblePaths=/apex-data/history-a \
  -p ReadOnlyPaths=/apex-data/governance \
  --setenv=GIT_CONFIG_GLOBAL=/dev/null --setenv=GIT_CONFIG_NOSYSTEM=1 \
  /bin/sh -c "
    echo whoami=\$(id -un)
    echo visible_files=\$(ls $CORPUS 2>/dev/null | wc -l)
    test -r $CORPUS/$ADMITTED && echo admitted_readable=true || echo admitted_readable=false
    test -r $CORPUS/$DENIED && echo evaluation_readable=true || echo evaluation_readable=false
    test -e /apex-data/history-b/etf_continuous/integrity.jsonl && echo other_corpus_files_visible=true || echo other_corpus_files_visible=false
    ls /apex-data/core >/dev/null 2>&1 && echo core_evidence_readable=true || echo core_evidence_readable=false
    ls /apex-data/history-a >/dev/null 2>&1 && echo history_a_readable=true || echo history_a_readable=false
    cat /home/apex/.apex-secrets/ALPACA_API_KEY_ID >/dev/null 2>&1 && echo secrets_readable=true || echo secrets_readable=false
    touch $CORPUS/probe_write 2>/dev/null && echo corpus_writable=true || echo corpus_writable=false
    test -r /apex-data/governance/admissions/manifests/etf_continuous_SPY_manifest_v0.json && echo manifest_readable=true || echo manifest_readable=false
    getent hosts github.com >/dev/null 2>&1 && echo network_reachable=true || echo network_reachable=false
    cd $CHECKOUT 2>/dev/null && git status --porcelain -- apex/world_model >/dev/null 2>&1 && echo git_status_ok=true || echo git_status_ok=false
  " 2>&1)
RC=$?
rm -rf "$V"

python3 - "$OUT" "$RC" "$SRC_SHA" "$VIEW_SHA" "$PROBE_USER" "$CHECKOUT" <<PY
import json, sys, datetime
out, rc, src, view, user, checkout = sys.argv[1:7]
raw = """$RAW"""
kv = {}
for line in raw.splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        kv[k.strip()] = True if v == "true" else False if v == "false" else v
rec = {
 "produced_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
 "what_this_is": "read-only probe of the launch containment; no setup performed",
 "probe_user": user, "probe_user_stands_in_for": "apexresearch (not yet created)",
 "checkout": checkout, "systemd_run_rc": int(rc),
 "view_copy_matches_corpus_sha256": src == view, "corpus_sha256_prefix": src[:16],
 "observations": kv,
 "expected": {
   "admitted_readable": True, "evaluation_readable": False,
   "other_corpus_files_visible": False, "core_evidence_readable": False,
   "history_a_readable": False, "secrets_readable": False,
   "corpus_writable": False, "manifest_readable": True,
   "network_reachable": False, "git_status_ok": True},
 "raw": raw.splitlines(),
}
rec["all_expectations_met"] = all(kv.get(k) == v for k, v in rec["expected"].items())
rec["deviations"] = {k: {"expected": v, "observed": kv.get(k)}
                     for k, v in rec["expected"].items() if kv.get(k) != v}
rec["limitations"] = [
 "measures the containment, not the apexresearch account, which does not exist yet",
 "a root-capable account is unaffected by any of this; the administrator remains trusted",
 "the real view holds 1,511 admitted sessions; this probe stages one",
]
open(out, "w").write(json.dumps(rec, indent=1, sort_keys=True))
print(json.dumps({"all_expectations_met": rec["all_expectations_met"],
                  "deviations": rec["deviations"],
                  "observations": kv}, indent=1))
PY
