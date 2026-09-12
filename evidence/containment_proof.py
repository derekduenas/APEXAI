"""Prove the research process receives the intended cgroup and memory
boundary. Prints its cgroup and limits, then allocates past the unit
limit; the expected outcome is being killed by the cgroup OOM killer,
which the chain records as the proof (exit code 137 / SIGKILL)."""
import os, sys, time
cg = open("/proc/self/cgroup").read().strip().split("::")[-1]
print("cgroup      :", cg, flush=True)
own = "/sys/fs/cgroup" + cg
print("memory.max  :", open(own + "/memory.max").read().strip(), "(unit)", flush=True)
print("slice max   :", open("/sys/fs/cgroup/wmresearch.slice/memory.max").read().strip(), "(wmresearch.slice)", flush=True)
ok = cg.startswith("/wmresearch.slice/")
print("in dedicated WM slice:", ok, flush=True)
import subprocess
tree = subprocess.run(["systemd-cgls", "--no-pager", "/wmresearch.slice"], capture_output=True, text=True).stdout
prod = [l for l in tree.splitlines() if "apex-" in l and ".service" in l]
print("PRODUCTION_SERVICES_IN_WM_SLICE =", len(prod), flush=True)
ok = ok and not prod
if "--no-alloc" in sys.argv:
    sys.exit(0 if ok else 3)
print("ALLOC_ATTEMPT: 100 MiB chunks up to 1800 MiB; the unit limit is 1400M, slice 1536M", flush=True)
chunks = []
for i in range(18):
    chunks.append(bytearray(100 * 1024 * 1024))
    for j in range(0, len(chunks[-1]), 4096):
        chunks[-1][j] = 1
    print("  allocated %d MiB" % ((i + 1) * 100), flush=True)
    time.sleep(0.05)
print("NOT KILLED -- containment NOT enforced", flush=True)
sys.exit(4)
