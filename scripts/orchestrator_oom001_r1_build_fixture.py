"""Build a DISPOSABLE ledger reproducing the observed production shape:
~438 MB, valid hash chain, final record 262275 bytes. The production
ledger is never read or written here."""
import hashlib, json, os, sys
OUT = "/apex-data/tmp/oom001_r1/fixture.jsonl"
TARGET = 438867453
FINAL = 262275
os.makedirs(os.path.dirname(OUT), exist_ok=True)

def h(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

prev = "GENESIS"
written = 0
n = 0
with open(OUT, "w") as fh:
    while True:
        # leave room for exactly one final record of FINAL bytes
        remaining = TARGET - written - (FINAL + 1)
        if remaining <= 0:
            break
        pad = min(37000, remaining - 200)
        if pad < 10:
            break
        body = {"kind": "tick", "i": n, "pad": "z" * pad, "prev_hash": prev}
        body["entry_hash"] = h(body)
        line = json.dumps(body, sort_keys=True)
        if written + len(line) + 1 > TARGET - (FINAL + 1):
            break
        fh.write(line + "\n"); written += len(line) + 1; prev = body["entry_hash"]; n += 1
    # the final record, sized to exactly FINAL bytes
    fill = 0
    while True:
        body = {"kind": "final", "i": n, "pad": "z" * fill, "prev_hash": prev}
        body["entry_hash"] = h(body)
        line = json.dumps(body, sort_keys=True)
        if len(line) == FINAL:
            break
        fill += FINAL - len(line)
    fh.write(line + "\n"); written += len(line) + 1; n += 1
    final_hash = body["entry_hash"]

size = os.path.getsize(OUT)
print("fixture      :", OUT)
print("size_bytes   :", size, "(production 438867453)")
print("records      :", n)
print("final_record :", FINAL, "bytes")
print("final_hash   :", final_hash)
# the same test the primitive performs, to confirm the shape reproduces the fault
with open(OUT, "rb") as fh:
    fh.seek(size - 262144); lines = [l for l in fh.read().decode("utf-8","replace").splitlines() if l.strip()]
if size > 262144 and lines: lines = lines[1:]
ok = any((json.loads(l).get("entry_hash") if l.strip().startswith("{") else None) for l in reversed(lines) if l.strip())
print("old_256KiB_window_finds_a_hash:", bool(ok), "-> reproduces the fault" if not ok else "-> DOES NOT reproduce")
json.dump({"path": OUT, "size": size, "records": n, "final_record_bytes": FINAL,
           "expected_prev_hash_for_next_append": final_hash},
          open("/apex-data/tmp/oom001_r1/fixture.json", "w"), indent=1)
