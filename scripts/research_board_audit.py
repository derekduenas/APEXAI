"""RESEARCH BOARD AUDIT -- V2 authority and legacy integrity.

On 2026-09-03 two research boards were found on this host, each a valid
chain from its own GENESIS, with zero overlapping record ids. Nothing
detected it for four days. The cause was a RELATIVE path resolving
against two different working directories.

RESEARCH_BOARD_V2 closed that: one absolute canonical board, both
legacy boards frozen read-only, and a reconciliation record whose
hashed body COMMITS to both legacy files. This audit proves that
arrangement still holds. It reads only.

Exit 0 = healthy. Exit 1 = a finding.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/apex-repo")
from apex.governance.research_board import (            # noqa: E402
    CANONICAL_BOARD, LEGACY_BOARDS, RECONCILIATION_RECORD_ID,
    legacy_commitment, legacy_manifest, verify_chain)

SEARCH_ROOTS = ("/apex-data", "/opt/apex-repo", "/opt/apex", "/mnt")
findings = []
ok = []


def find_boards():
    out = []
    for root in SEARCH_ROOTS:
        if not Path(root).exists():
            continue
        r = subprocess.run(
            ["find", root, "-name", "research_board*.jsonl", "-not",
             "-path", "*/.git/*", "-not", "-path", "*/pytest-of-*/*"],
            capture_output=True, text=True)
        out.extend(x for x in r.stdout.split("\n") if x.strip())
    # De-duplicate by FILE IDENTITY, not path: /apex-data/core and
    # /mnt/volume_... are the same filesystem through two mount points,
    # and resolve() collapses symlinks but NOT mount aliases -- dedup by
    # path alone reported one board twice and raised a FALSE fork.
    seen, uniq = {}, []
    for p in sorted(out):
        try:
            st = Path(p).stat()
        except OSError:
            continue
        key = (st.st_dev, st.st_ino)
        if key in seen:
            continue
        seen[key] = p
        uniq.append(Path(p))
    return uniq


bar = "=" * 76
print(bar)
print("RESEARCH BOARD AUDIT")
print(bar)

# --- 1. canonical V2 exists and verifies -----------------------------
if not CANONICAL_BOARD.exists():
    findings.append("canonical V2 board absent: %s" % CANONICAL_BOARD)
else:
    v = verify_chain(CANONICAL_BOARD)
    if not v["intact"]:
        findings.append("V2 chain BROKEN at record %s (%s)"
                        % (v["broken_at"], v.get("reason")))
    else:
        ok.append("V2 chain intact, %d records, head %s"
                  % (v["records"], v["head"][:16]))
    recs = [json.loads(x) for x in
            CANONICAL_BOARD.read_text().split("\n") if x.strip()]
    if not recs or recs[0].get("id") != RECONCILIATION_RECORD_ID:
        findings.append("V2 record 1 is not %s" % RECONCILIATION_RECORD_ID)
    else:
        ok.append("V2 opens with %s" % RECONCILIATION_RECORD_ID)

        # --- 2. legacy boards match what V2 COMMITTED to -------------
        committed = recs[0].get("legacy_commitments") or {}
        for ident, path in LEGACY_BOARDS.items():
            if not path.exists():
                findings.append("legacy board MISSING: %s (%s)"
                                % (ident, path))
                continue
            now = legacy_commitment(legacy_manifest(ident, path))
            was = committed.get(ident)
            if was is None:
                findings.append("V2 made no commitment for %s" % ident)
            elif now != was:
                findings.append(
                    "LEGACY BOARD ALTERED SINCE RECONCILIATION: %s\n"
                    "        committed %s\n        now       %s"
                    % (ident, was[:32], now[:32]))
            else:
                ok.append("%s unchanged since reconciliation" % ident)

# --- 3. legacy boards are read-only ----------------------------------
for ident, path in LEGACY_BOARDS.items():
    if not path.exists():
        continue
    mode = path.stat().st_mode & 0o222
    if mode:
        findings.append("legacy board is WRITABLE (mode %o): %s"
                        % (path.stat().st_mode & 0o777, ident))
    else:
        ok.append("%s frozen read-only" % ident)

# --- 4. exactly one writable authority -------------------------------
boards = find_boards()
writable = [p for p in boards if p.stat().st_mode & 0o222]
print("  boards on host: %d" % len(boards))
for p in boards:
    v = verify_chain(p)
    w = "WRITABLE" if p.stat().st_mode & 0o222 else "read-only"
    print("     %-58s %-9s %3d rec  %s"
          % (str(p)[-58:], w, v["records"],
             "INTACT" if v["intact"] else "BROKEN@%s" % v["broken_at"]))
if len(writable) == 0:
    findings.append("no writable board authority exists")
elif len(writable) > 1:
    findings.append("MULTIPLE WRITABLE BOARD AUTHORITIES (%d): %s"
                    % (len(writable), [str(x) for x in writable]))
elif writable[0] != CANONICAL_BOARD:
    findings.append("the writable authority is not the canonical board: %s"
                    % writable[0])
else:
    ok.append("exactly one writable authority, and it is canonical")

# --- 5. no authoritative writer may pick its board from cwd ----------
if not CANONICAL_BOARD.is_absolute():
    findings.append("CANONICAL_BOARD is not absolute")
else:
    ok.append("CANONICAL_BOARD is absolute")

rel = subprocess.run(
    ["grep", "-rn", "--include=*.py", "-e",
     r"chain_append(\s*[\"']results/", "/opt/apex-repo/apex",
     "/opt/apex-repo/scripts"], capture_output=True, text=True)
hits = [x for x in rel.stdout.split("\n") if x.strip()]
if hits:
    findings.append("relative-path board writers still present:\n        "
                    + "\n        ".join(hits[:8]))
else:
    ok.append("no authoritative writer selects a board by relative path")

print()
print(bar)
for x in ok:
    print("  ok       %s" % x)
for x in findings:
    print("  FINDING  %s" % x)
print(bar)
print("  %s" % ("PASS -- one canonical authority, legacy intact"
                if not findings else
                "FAIL -- %d finding(s)" % len(findings)))
sys.exit(1 if findings else 0)
