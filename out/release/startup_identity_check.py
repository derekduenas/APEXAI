"""Process-start identity check: refuse to start unless the loaded code IS the manifest's release."""
import json, sys
sys.path.insert(0, ".")
from apex.options_pilot.runtime_identity import runtime_identity
m = json.load(open(sys.argv[1]))
ri = runtime_identity()
problems = []
if ri["git_commit"] not in (m["commit"], "NOT_A_GIT_CHECKOUT"):
    problems.append("commit %s != manifest %s" % (ri["git_commit"], m["commit"]))
for k, v in m["decision_path_module_digests"].items():
    if ri["decision_path_module_digests"].get(k) != v:
        problems.append("digest mismatch: %s" % k)
if ri["decision_path_tree_digest"] != m["decision_path_tree_digest"]:
    problems.append("tree digest mismatch")
print(json.dumps({"release": m["commit"], "loaded_tree_digest": ri["decision_path_tree_digest"], "problems": problems}, indent=1))
sys.exit(1 if problems else 0)
