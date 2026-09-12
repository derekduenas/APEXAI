"""Enumerate external test inputs for both candidates.

A source scan finds literals. It does NOT prove every runtime dependency was
found -- an interpreter resolved from PATH, a relative path resolved against a
cwd, or an import from site-packages leaves no literal to see. Recorded as a
discovery aid, with runtime auditing done separately.
"""
import ast, hashlib, json, os, subprocess, sys

WT = sys.argv[1]          # tree to scan
LABEL = sys.argv[2]
OUT = sys.argv[3]

def sh(*a, cwd=WT):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True).stdout.strip()

def h(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except OSError as e:
        return "UNREADABLE:%s" % type(e).__name__

mods = [f for f in sh("git", "ls-files", "tests/").splitlines()
        if os.path.basename(f).startswith("test_") and f.endswith(".py")]

ROLES = {
    "interpreter": lambda v: v.endswith("/bin/python") or "/bin/python" in v,
    "audit_subject_or_checkout": lambda v: v.rstrip("/") in ("/opt/apex-repo", "/opt/apex/current"),
    "fixture_or_data": lambda v: os.path.splitext(v)[1] in (".jsonl", ".json", ".csv", ".yaml", ".yml", ".txt"),
}

findings = []
for m in mods:
    path = os.path.join(WT, m)
    try:
        tree = ast.parse(open(path).read())
    except Exception:
        continue
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            v = n.value
            if not v.startswith("/") or len(v) < 2:
                continue
            if v.startswith("/tmp") or v.startswith("/proc") or v == "/":
                continue
            role = next((r for r, f in ROLES.items() if f(v)), "other_absolute_path")
            findings.append({"module": m, "line": n.lineno, "literal": v,
                             "role": role,
                             "inside_candidate": os.path.abspath(v).startswith(os.path.abspath(WT)),
                             "resolved_exists": os.path.exists(v),
                             "resolved_sha256": h(v) if os.path.isfile(v) else None,
                             "candidate_copy": None})

# where the same relative path exists inside the candidate, hash that too
for f in findings:
    if f["literal"].startswith("/opt/apex-repo/"):
        rel = f["literal"][len("/opt/apex-repo/"):]
        cand = os.path.join(WT, rel)
        if os.path.isfile(cand):
            f["candidate_copy"] = {"path": cand, "sha256": h(cand),
                                   "matches_external": h(cand) == f["resolved_sha256"]}

# which nodeids are affected
for f in findings:
    ids = subprocess.run([os.environ.get("PY", "/opt/apex/shared/venv/bin/python"),
                          "-m", "pytest", f["module"], "--collect-only", "-q",
                          "-p", "no:cacheprovider"], cwd=WT, capture_output=True,
                         text=True, env={**os.environ, "PYTHONPATH": WT, "HOME": "/home/apex"})
    f["module_nodeids"] = len([l for l in ids.stdout.splitlines()
                               if l.startswith(f["module"] + "::")])

doc = {"kind": "external_test_input_inventory", "candidate": LABEL,
       "tree": WT, "commit": sh("git", "rev-parse", "HEAD"),
       "method": "AST scan for absolute string constants in test modules",
       "limitation": "a source scan is a DISCOVERY AID, not proof that every "
                     "runtime dependency was found. An interpreter resolved "
                     "from PATH, a path built at runtime, or an import from "
                     "site-packages leaves no literal to find. Runtime "
                     "auditing is recorded separately.",
       "modules_scanned": len(mods),
       "findings": sorted(findings, key=lambda x: (x["module"], x["line"])),
       "external_findings": [f for f in findings if not f["inside_candidate"]],
       "affected_modules": sorted({f["module"] for f in findings if not f["inside_candidate"]})}
json.dump(doc, open(OUT, "w"), indent=1)
print("%s: %d modules scanned, %d absolute literals, %d external, %d affected modules"
      % (LABEL, len(mods), len(findings), len(doc["external_findings"]),
         len(doc["affected_modules"])))
for f in doc["external_findings"]:
    print("  %-44s :%-4d %-26s %s" % (f["module"].replace("tests/", ""), f["line"],
                                      f["role"], f["literal"][:60]))
    if f["candidate_copy"]:
        print("      candidate copy matches external: %s" % f["candidate_copy"]["matches_external"])
