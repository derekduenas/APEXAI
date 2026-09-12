"""Measure the repaired append path on the disposable fixture, inside the
SAME 512 MiB cap the orchestrator runs under. The production ledger is not
read or written."""
import json, os, resource, sys
sys.path.insert(0, "/opt/apex-repo")

MODE = sys.argv[1]
PATH = sys.argv[2]

def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

def cgpeak():
    try:
        cg = "/sys/fs/cgroup" + open("/proc/self/cgroup").read().split(":")[-1].strip()
        return int(open(cg + "/memory.peak").read()) / 1048576.0
    except Exception:
        return None

print("mode=%s  file_mib=%.1f  rss_start=%.1f" % (MODE, os.path.getsize(PATH)/1048576, rss()), flush=True)

if MODE == "old":
    # the pre-repair fallback, replicated exactly: read the whole file
    import json as J
    size = os.path.getsize(PATH)
    with open(PATH, "rb") as fh:
        fh.seek(max(0, size-262144)); tail = fh.read().decode("utf-8", errors="replace")
    lines = [l for l in tail.splitlines() if l.strip()]
    if size > 262144 and lines: lines = lines[1:]
    found = False
    for l in reversed(lines):
        try: J.loads(l)["entry_hash"]; found = True; break
        except Exception: pass
    print("tail_window_found=%s rss=%.1f" % (found, rss()), flush=True)
    if not found:
        txt = open(PATH).read()
        print("read_text_done rss=%.1f" % rss(), flush=True)
        ls = txt.strip().splitlines()
        print("splitlines_done rss=%.1f lines=%d" % (rss(), len(ls)), flush=True)
else:
    from apex.governance.chain_ledger import chain_append
    from pathlib import Path
    before = os.path.getsize(PATH)
    rec = chain_append(Path(PATH), {"kind": "r1_measurement", "note": "disposable fixture"})
    print("append_done rss=%.1f" % rss(), flush=True)
    exp = json.load(open("/apex-data/tmp/oom001_r1/fixture.json"))["expected_prev_hash_for_next_append"]
    print("prev_hash        =", rec["prev_hash"], flush=True)
    print("expected         =", exp, flush=True)
    print("CHAIN_CONTINUITY =", "OK" if rec["prev_hash"] == exp else "BROKEN", flush=True)
    print("torn_flag        =", rec.get("recovered_from_torn_tail"), flush=True)
    print("bytes_grew_by    =", os.path.getsize(PATH) - before, flush=True)
print("MAXRSS_MIB=%.1f  CGROUP_PEAK_MIB=%s" % (rss(), cgpeak()), flush=True)
