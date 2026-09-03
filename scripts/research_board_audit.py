"""RESEARCH-BOARD-STORAGE-001 -- split-brain detector.

On 2026-09-03 two research boards were found on this host, each a valid
hash chain from its own GENESIS, with ZERO overlapping record ids:

    /apex-data/core/edgeforge/     56 records, last written 2026-08-30
    /opt/apex-repo/results/...    129 records, still being written

chain_append() is called with the RELATIVE path
`results/edgeforge/research_board.jsonl`, which resolves against the
process working directory:

    cwd=/apex-data/runtime  (services)  -> the data volume
    cwd=/opt/apex-repo      (sessions)  -> the root disk

Nothing detected this for four days. This tool exists so that cannot
happen again: it enumerates every board on the host and reports whether
they are one chain or several. It READS ONLY -- reconciling a fork is a
governance decision, not a script's.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SEARCH_ROOTS = ("/apex-data", "/opt/apex-repo", "/opt/apex", "/mnt")
NAME = "research_board.jsonl"


def find_boards():
    out = []
    for root in SEARCH_ROOTS:
        if not Path(root).exists():
            continue
        r = subprocess.run(
            ["find", root, "-name", NAME, "-not", "-path", "*/.git/*",
             "-not", "-path", "*/pytest-of-*/*"],
            capture_output=True, text=True)
        out.extend(x for x in r.stdout.split("\n") if x.strip())
    # De-duplicate by FILE IDENTITY (st_dev, st_ino), not by path.
    # /apex-data/core and /mnt/volume_... are the same filesystem seen
    # through two mount points; Path.resolve() collapses symlinks but
    # NOT mount aliases, so resolving alone reports one board twice and
    # would raise a false fork.
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


def chain_report(p: Path) -> dict:
    lines = [ln for ln in p.read_text().split("\n") if ln.strip()]
    prev, broken_at = "GENESIS", None
    ids = []
    for i, ln in enumerate(lines):
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            broken_at = i + 1
            break
        body = dict(r)
        h = body.pop("entry_hash", None)
        calc = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()).hexdigest()
        if calc != h or r.get("prev_hash") != prev:
            broken_at = i + 1
            break
        prev = h
        if r.get("id"):
            ids.append(r["id"])
    return {"path": str(p), "records": len(lines), "head": prev,
            "intact": broken_at is None, "broken_at": broken_at,
            "ids": set(ids),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def main() -> int:
    boards = find_boards()
    print("=" * 76)
    print("RESEARCH BOARD AUDIT -- %d board(s) found" % len(boards))
    print("=" * 76)
    reps = []
    for b in boards:
        r = chain_report(b)
        reps.append(r)
        print("  %s" % r["path"])
        print("     records %-5d chain %s   head %s"
              % (r["records"], "INTACT" if r["intact"]
                 else "BROKEN@%s" % r["broken_at"], r["head"][:16]))
        print("     sha256  %s" % r["sha256"][:48])
    print()
    if len(reps) <= 1:
        print("  SINGLE BOARD -- no split brain.")
        return 0

    print("=" * 76)
    print("RELATIONSHIP")
    print("=" * 76)
    heads = {r["head"] for r in reps}
    if len(heads) == 1:
        print("  identical heads -- same chain, same state.")
        return 0
    # is any board a strict prefix of another?
    prefix_found = False
    for a in reps:
        for b in reps:
            if a is b or a["records"] >= b["records"]:
                continue
            la = [ln for ln in Path(a["path"]).read_text().split("\n")
                  if ln.strip()]
            lb = [ln for ln in Path(b["path"]).read_text().split("\n")
                  if ln.strip()]
            if la == lb[:len(la)]:
                prefix_found = True
                print("  PREFIX: %s is records 1..%d of %s"
                      % (a["path"], len(la), b["path"]))
                print("     -> continuation, safely appendable "
                      "(%d records behind)" % (len(lb) - len(la)))
    if not prefix_found:
        print("  RESEARCH_BOARD_FORK = TRUE")
        print("  No board is a byte-prefix of another. These are")
        print("  INDEPENDENT chains, not one chain with a longer branch.")
        for i, a in enumerate(reps):
            for b in reps[i + 1:]:
                shared = a["ids"] & b["ids"]
                print("     %s" % a["path"])
                print("       <-> %s" % b["path"])
                print("       shared record ids: %d" % len(shared))
        print()
        print("  DO NOT MERGE. Reconciliation is a governance decision:")
        print("  appending one to the other would either rewrite")
        print("  prev_hash (rewriting history) or append records whose")
        print("  prev_hash does not link (breaking the chain).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
