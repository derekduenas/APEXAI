"""READ-ONLY reproduction of chain_append._chain_append_locked prev-hash
lookup against the live ledger. Reads only; appends nothing; starts no
service. Reports RSS at each step."""
import json, os, resource, sys
p = "/apex-data/runtime/results/ops/orchestrator.jsonl"
def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
print("step=start                 maxrss_mib=%.1f" % rss(), flush=True)
size = os.path.getsize(p)
with open(p, "rb") as fh:
    fh.seek(max(0, size - 262144)); tail = fh.read().decode("utf-8", errors="replace")
lines = [l for l in tail.splitlines() if l.strip()]
if size > 262144 and lines: lines = lines[1:]
found = False
for line in reversed(lines):
    try:
        json.loads(line)["entry_hash"]; found = True; break
    except Exception: pass
print("step=tail_window_done      maxrss_mib=%.1f  found_in_tail=%s" % (rss(), found), flush=True)
if not found:
    print("step=entering_full_walk    maxrss_mib=%.1f" % rss(), flush=True)
    txt = open(p).read()                       # the pathological line
    print("step=read_text_done        maxrss_mib=%.1f  chars=%d" % (rss(), len(txt)), flush=True)
    s = txt.strip()
    print("step=strip_done            maxrss_mib=%.1f" % rss(), flush=True)
    ls = s.splitlines()
    print("step=splitlines_done       maxrss_mib=%.1f  lines=%d" % (rss(), len(ls)), flush=True)
print("step=end                   maxrss_mib=%.1f" % rss(), flush=True)
