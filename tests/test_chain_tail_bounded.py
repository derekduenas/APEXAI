"""ORCHESTRATOR-OOM-001-R1: the bounded previous-hash lookup.

Every case drives the REAL append path on a disposable fixture, and the
appended prev_hash is checked against a hash established independently --
recomputed from the bytes on disk, never taken from the writer's own
return value. A refused append must leave the file byte-for-byte identical.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from apex.governance import chain_ledger as CL
from apex.governance.chain_ledger import (INITIAL_TAIL_BYTES,
                                          MAX_TAIL_SEARCH_BYTES,
                                          ChainTailUnresolved, chain_append)

W = INITIAL_TAIL_BYTES


# --------------------------------------------------------------- helpers
def independent_hash(record: dict) -> str:
    """Recompute entry_hash from a record's own body, the way a verifier
    would -- not by trusting the value stored beside it."""
    body = {k: v for k, v in record.items() if k != "entry_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def last_valid_from_disk(p: Path) -> dict:
    """The last parseable record, read back from the file itself."""
    for line in reversed(p.read_text(errors="replace").splitlines()):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "entry_hash" in r:
            return r
    raise AssertionError("no valid record on disk")


def pad_to(p: Path, target_len: int, **extra) -> dict:
    """Append one record whose SERIALISED line is exactly target_len bytes."""
    fill = 0
    while True:
        rec = chain_append(p, {"kind": "big", "pad": "z" * fill, **extra})
        line = json.dumps(rec, sort_keys=True)
        if len(line) == target_len:
            return rec
        # undo and retry with a corrected pad
        lines = p.read_text().splitlines()
        p.write_text("\n".join(lines[:-1]) + ("\n" if len(lines) > 1 else ""))
        fill += target_len - len(line)
        assert fill >= 0, "target shorter than the empty record"


def seed(p: Path, n: int = 5) -> list:
    return [chain_append(p, {"kind": "x", "i": i}) for i in range(n)]


# ------------------------------------------------------- 1. ordinary ledger
def test_ordinary_valid_ledger_links_to_the_last_record(tmp_path):
    p = tmp_path / "l.jsonl"
    recs = seed(p, 6)
    nxt = chain_append(p, {"kind": "x", "i": 99})
    disk = last_valid_from_disk(tmp_path / "l.jsonl")
    assert nxt["prev_hash"] == recs[-1]["entry_hash"]
    assert nxt["prev_hash"] == independent_hash(recs[-1])
    assert disk["entry_hash"] == independent_hash(disk)
    assert "recovered_from_torn_tail" not in nxt
    # and the whole chain verifies link by link
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    assert all(rows[i]["prev_hash"] == rows[i - 1]["entry_hash"]
               for i in range(1, len(rows)))
    assert all(r["entry_hash"] == independent_hash(r) for r in rows)


def test_first_ever_append_is_genesis(tmp_path):
    p = tmp_path / "new.jsonl"
    r = chain_append(p, {"kind": "first"})
    assert r["prev_hash"] == "GENESIS" and r["entry_hash"] == independent_hash(r)


def test_an_empty_file_is_genesis_not_an_error(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_bytes(b"")
    r = chain_append(p, {"kind": "after-empty"})
    assert r["prev_hash"] == "GENESIS"


# ------------------------------- 2. the exact production shape: 262275 bytes
def test_final_record_of_262275_bytes_is_still_found(tmp_path):
    """The observed defect. 262275 > the 262144 window, so the old code
    could never see it and read the whole file instead."""
    p = tmp_path / "big.jsonl"
    seed(p, 3)
    big = pad_to(p, 262275)
    assert len(json.dumps(big, sort_keys=True)) == 262275 > W
    nxt = chain_append(p, {"kind": "after-big"})
    assert nxt["prev_hash"] == big["entry_hash"] == independent_hash(big)
    assert "recovered_from_torn_tail" not in nxt, "a valid record is not a tear"


def test_the_search_widens_only_as_far_as_it_must(tmp_path, monkeypatch):
    """The common case must still read exactly one 256 KiB window."""
    p = tmp_path / "reads.jsonl"
    seed(p, 3)
    sizes = []
    real = CL.Path.open

    def spy(self, *a, **k):
        fh = real(self, *a, **k)
        if a and "b" in str(a[0]):
            orig = fh.read

            def read(n=-1):
                out = orig(n)
                sizes.append(len(out))
                return out
            fh.read = read
        return fh
    monkeypatch.setattr(CL.Path, "open", spy)
    chain_append(p, {"kind": "y"})
    assert max(sizes) <= W, "a small ledger read more than one window"


# ------------------------------------------- 3. exact window-boundary alignment
def test_window_starting_exactly_on_a_record_boundary_keeps_that_record(tmp_path):
    """The cut-guard used to drop the window's first line unconditionally.
    When the window opens exactly after a newline that line is COMPLETE,
    and discarding it threw away a valid final record."""
    p = tmp_path / "aligned.jsonl"
    seed(p, 3)
    target = pad_to(p, W - 1)            # line + "\n" == W bytes exactly
    size = p.stat().st_size
    assert size - W >= 0
    with p.open("rb") as fh:
        fh.seek(size - W - 1)
        assert fh.read(1) == b"\n", "fixture is not boundary-aligned"
    nxt = chain_append(p, {"kind": "after-aligned"})
    assert nxt["prev_hash"] == target["entry_hash"] == independent_hash(target)
    assert "recovered_from_torn_tail" not in nxt


# ------------------------------------ 4. multibyte character across the boundary
def test_chain_append_itself_only_ever_writes_ascii(tmp_path):
    """Worth pinning, because it bounds where a split character can come
    from: json.dumps escapes non-ASCII by default, so a ledger written by
    this primitive is pure ASCII and its window edge can never land inside
    a multibyte sequence. Only a FOREIGN writer, or a torn fragment of raw
    UTF-8, can put one there -- which is what the next test builds."""
    p = tmp_path / "ascii.jsonl"
    chain_append(p, {"kind": "wide", "text": "\u4e2d" * 50})
    raw = p.read_bytes()
    assert raw.decode("ascii")                       # would raise otherwise
    assert b"\\u4e2d" in raw


def test_multibyte_character_split_by_the_window_edge(tmp_path):
    """The window edge lands INSIDE a 3-byte character, in raw UTF-8 left
    behind by a foreign writer. errors="replace" may damage only the
    leading partial line, which an unaligned window discards anyway. The
    record we link to must be untouched."""
    for k in range(3):                       # shift the phase one byte at a time
        p = tmp_path / ("utf8_%d.jsonl" % k)
        recs = seed(p, 3)
        blob = (b" " * k + b'{"kind": "foreign", "text": "'
                + "\u4e2d".encode("utf-8") * ((W // 3) + 4000))
        with p.open("ab") as fh:
            fh.write(blob)                   # raw, unterminated: a torn tail
        size = p.stat().st_size
        with p.open("rb") as fh:
            fh.seek(size - W)
            first = fh.read(1)[0]
        if 0x80 <= first < 0xC0:
            break
    else:
        pytest.fail("could not build a fixture that splits a character")
    assert size > W

    nxt = chain_append(p, {"kind": "after-utf8"})
    assert nxt["prev_hash"] == recs[-1]["entry_hash"] == independent_hash(recs[-1])
    assert nxt.get("recovered_from_torn_tail") is True
    # the earlier valid records survived the boundary decode unharmed
    on_disk = p.read_bytes()
    for r in recs:
        assert json.dumps(r, sort_keys=True).encode() in on_disk
    # and the new record is readable back rather than merged into the blob
    readable = []
    for line in p.read_text(errors="replace").splitlines():
        try:
            readable.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    assert nxt["entry_hash"] in {r.get("entry_hash") for r in readable}


# --------------------------------------------------- 5. torn trailing record
def test_torn_trailing_record_links_past_the_fragment(tmp_path):
    """SAC1-06, preserved: link to the last VALID record and SAY so."""
    p = tmp_path / "torn.jsonl"
    recs = seed(p, 5)
    with p.open("a") as fh:
        fh.write('{"kind": "x", "i": 5, "prev_ha')
    nxt = chain_append(p, {"kind": "x", "i": 6})
    assert nxt["prev_hash"] == recs[-1]["entry_hash"] == independent_hash(recs[-1])
    assert nxt.get("recovered_from_torn_tail") is True
    # and the post-tear record is readable back, not merged into the fragment
    readable = []
    for line in p.read_text().splitlines():
        try:
            readable.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    assert nxt["entry_hash"] in {r.get("entry_hash") for r in readable}


def test_torn_fragment_larger_than_one_window(tmp_path):
    p = tmp_path / "bigtorn.jsonl"
    recs = seed(p, 3)
    with p.open("a") as fh:
        fh.write('{"kind": "torn", "pad": "' + "q" * (W + 5000))
    nxt = chain_append(p, {"kind": "after"})
    assert nxt["prev_hash"] == recs[-1]["entry_hash"]
    assert nxt.get("recovered_from_torn_tail") is True


# ------------------------------------- 6. complete but malformed trailing record
def test_complete_malformed_trailing_record_is_treated_as_damage(tmp_path):
    """A whole line that is valid JSON but carries no entry_hash, and a
    whole line that is not JSON at all. Neither may be linked to."""
    for tail in ('{"kind": "no-hash", "i": 7}\n', 'not json at all\n'):
        p = tmp_path / ("m%d.jsonl" % len(tail))
        recs = seed(p, 4)
        with p.open("a") as fh:
            fh.write(tail)
        nxt = chain_append(p, {"kind": "after"})
        assert nxt["prev_hash"] == recs[-1]["entry_hash"], tail
        assert nxt.get("recovered_from_torn_tail") is True, tail


def test_a_file_of_only_garbage_is_genesis_because_the_whole_file_was_read(tmp_path):
    """Unchanged behaviour: the search covered every byte, so GENESIS is a
    measurement, not a guess."""
    p = tmp_path / "junk.jsonl"
    p.write_text("garbage\nmore garbage\n")
    r = chain_append(p, {"kind": "x"})
    assert r["prev_hash"] == "GENESIS"
    assert r.get("recovered_from_torn_tail") is True


# ------------------------------------------- 7. beyond the search ceiling
def _beyond_ceiling(p: Path) -> list:
    recs = seed(p, 3)
    with p.open("a") as fh:
        fh.write("x" * (MAX_TAIL_SEARCH_BYTES + 65536) + "\n")
    return recs


def test_record_beyond_the_ceiling_raises_and_writes_nothing(tmp_path):
    p = tmp_path / "ceiling.jsonl"
    _beyond_ceiling(p)
    before = p.read_bytes()
    with pytest.raises(ChainTailUnresolved) as e:
        chain_append(p, {"kind": "refused"})
    assert "Nothing was written" in str(e.value)
    assert str(p) in str(e.value)
    assert p.read_bytes() == before, "a refused append changed the file"


def test_the_refusal_is_never_downgraded_to_genesis(tmp_path):
    p = tmp_path / "nogen.jsonl"
    _beyond_ceiling(p)
    with pytest.raises(ChainTailUnresolved):
        chain_append(p, {"kind": "refused"})
    rows = [l for l in p.read_text(errors="replace").splitlines() if l.strip()]
    assert not any('"prev_hash": "GENESIS"' in l for l in rows[3:])


def test_a_valid_final_record_larger_than_the_ceiling_refuses(tmp_path):
    p = tmp_path / "huge.jsonl"
    seed(p, 2)
    chain_append(p, {"kind": "huge", "pad": "p" * (MAX_TAIL_SEARCH_BYTES + 4096)})
    before = p.read_bytes()
    with pytest.raises(ChainTailUnresolved):
        chain_append(p, {"kind": "after-huge"})
    assert p.read_bytes() == before


def test_the_declared_ceiling_is_what_the_module_says(tmp_path):
    assert INITIAL_TAIL_BYTES == 262144
    assert MAX_TAIL_SEARCH_BYTES == 8 * 1024 * 1024


def _bytes_read_appending_to(p, monkeypatch):
    total = []
    real = CL.Path.open

    def spy(self, *a, **k):
        fh = real(self, *a, **k)
        orig = fh.read

        def read(n=-1):
            out = orig(n)
            total.append(len(out) if out else 0)
            return out
        fh.read = read
        return fh
    monkeypatch.setattr(CL.Path, "open", spy)
    with pytest.raises(ChainTailUnresolved):
        chain_append(p, {"kind": "refused"})
    monkeypatch.undo()
    return total


def test_reads_are_bounded_by_a_constant_not_by_the_file(tmp_path, monkeypatch):
    """The property that matters is INDEPENDENCE FROM LEDGER SIZE. Two
    files differing by 40 MB must cost the same number of bytes read.

    Note the total across the geometric widening (256 KiB + 512 KiB + ... +
    8 MiB, about 16 MB) can exceed a file that is only just past the
    ceiling. That is fine and is not a regression: the old code's cost grew
    without limit with the file, and this one does not grow at all."""
    small = tmp_path / "small.jsonl"
    _beyond_ceiling(small)
    big = tmp_path / "big.jsonl"
    seed(big, 3)
    with big.open("a") as fh:
        fh.write("x" * (MAX_TAIL_SEARCH_BYTES + 40 * 1024 * 1024) + "\n")
    assert big.stat().st_size - small.stat().st_size > 39 * 1024 * 1024

    t_small = _bytes_read_appending_to(small, monkeypatch)
    t_big = _bytes_read_appending_to(big, monkeypatch)
    assert max(t_small) <= MAX_TAIL_SEARCH_BYTES
    assert max(t_big) <= MAX_TAIL_SEARCH_BYTES
    assert sum(t_small) == sum(t_big), "the cost still depends on ledger size"
    assert sum(t_big) < 2 * MAX_TAIL_SEARCH_BYTES + 4096


# --------------------------------------------- 8. locking behaviour unchanged
def test_thread_race_still_produces_an_unbroken_chain(tmp_path):
    p = tmp_path / "race.jsonl"
    chain_append(p, {"kind": "genesis"})
    barrier = threading.Barrier(4)

    def worker(tag):
        barrier.wait()
        for i in range(25):
            chain_append(p, {"kind": "racer", "tag": tag, "i": i})
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    assert len(rows) == 101
    assert all(rows[i]["prev_hash"] == rows[i - 1]["entry_hash"]
               for i in range(1, len(rows)))
    assert len({r["entry_hash"] for r in rows}) == len(rows)
    assert all(r["entry_hash"] == independent_hash(r) for r in rows)


def test_the_flock_sidecar_is_still_used(tmp_path):
    p = tmp_path / "lockcheck.jsonl"
    chain_append(p, {"kind": "x"})
    assert (tmp_path / "lockcheck.jsonl.lock").exists()


# The checkout under test, derived from THIS FILE rather than hard-coded.
# A literal path would let a child process import a different checkout than
# the parent -- in a worktree, a second clone, or an installed copy -- and a
# test that cannot say which implementation it ran proves nothing about this
# one.
ROOT = Path(__file__).resolve().parents[1]


def _implementation_identity(module) -> tuple:
    """(resolved module file, sha256 of its source). What actually ran."""
    src = Path(module.__file__).resolve()
    return str(src), hashlib.sha256(src.read_bytes()).hexdigest()


CHILD = (
    "import hashlib, json, sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, {root!r})\n"
    "from apex.governance import chain_ledger as CL\n"
    "src = Path(CL.__file__).resolve()\n"
    # the child says WHICH implementation it resolved, before it writes
    "sys.stdout.write(json.dumps({{'module': str(src),\n"
    "    'sha256': hashlib.sha256(src.read_bytes()).hexdigest(),\n"
    "    'ceiling': CL.MAX_TAIL_SEARCH_BYTES}}) + chr(10))\n"
    "sys.stdout.flush()\n"
    "target = Path({ledger!r})\n"
    "for i in range({n}):\n"
    "    CL.chain_append(target, {{'kind': 'mp', 'tag': sys.argv[1], 'i': i}})\n"
)


def test_multiprocess_appends_do_not_lose_records(tmp_path):
    """The flock layer's job: a second WRITER PROCESS on one host.

    Also pins PROVENANCE. Each child reports the chain_ledger it resolved and
    that file's hash, and the parent asserts they are the same bytes it
    imported itself. Without that, the record count proves only that SOME
    implementation serialised correctly -- not this one."""
    import os
    import subprocess
    import sys
    p = tmp_path / "mp.jsonl"
    first = chain_append(p, {"kind": "genesis"})
    parent_module, parent_sha = _implementation_identity(CL)
    assert Path(parent_module).is_relative_to(ROOT), (
        "the parent imported %s, outside the checkout under test %s"
        % (parent_module, ROOT))

    code = CHILD.format(root=str(ROOT), ledger=str(p), n=40)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    procs = [subprocess.Popen([sys.executable, "-c", code, str(t)],
                              stdout=subprocess.PIPE, text=True, env=env)
             for t in range(3)]
    reports = []
    for x in procs:
        out, _ = x.communicate()
        assert x.returncode == 0, out
        reports.append(json.loads(out.splitlines()[0]))

    # PROVENANCE: every child ran the same bytes the parent tested
    assert len(reports) == 3
    for r in reports:
        assert r["module"] == parent_module, (
            "a child imported %s but the parent tested %s"
            % (r["module"], parent_module))
        assert r["sha256"] == parent_sha, "a child ran different source bytes"
        assert r["ceiling"] == MAX_TAIL_SEARCH_BYTES

    # the original assertions, kept
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    assert len(rows) == 121
    assert len({r["entry_hash"] for r in rows}) == len(rows)
    # and every adjacent link plus every hash recomputed from its own body
    assert rows[0]["entry_hash"] == first["entry_hash"]
    assert rows[0]["prev_hash"] == "GENESIS"
    for i in range(1, len(rows)):
        assert rows[i]["prev_hash"] == rows[i - 1]["entry_hash"], i
    for r in rows:
        assert r["entry_hash"] == independent_hash(r)


def test_no_hard_coded_checkout_path_in_this_module(tmp_path):
    """A literal path in a child would silently test another checkout.

    Checked over the module's STRING CONSTANTS via the parse tree, not by
    searching the file's text. A text search for the offending path would
    match its own assertion and pass or fail for the wrong reason -- the
    same trap that made an earlier preservation check report a docstring as
    if it were code."""
    import ast
    tree = ast.parse(Path(__file__).read_text())
    absolute = sorted({n.value for n in ast.walk(tree)
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and n.value.startswith("/") and len(n.value) > 1})
    assert not absolute, "hard-coded absolute paths: %s" % absolute
    assert "ROOT = Path(__file__).resolve().parents[1]" in Path(__file__).read_text()
    mod, _ = _implementation_identity(CL)
    assert Path(mod).is_relative_to(ROOT), (
        "the implementation under test lives outside the derived checkout")


# --------------------------------------------- serialization is untouched
def test_serialisation_and_hash_semantics_are_unchanged(tmp_path):
    p = tmp_path / "ser.jsonl"
    r = chain_append(p, {"kind": "x", "b": 2, "a": 1})
    line = p.read_text().splitlines()[-1]
    assert line == json.dumps(r, sort_keys=True)          # sorted keys, exact
    assert r["entry_hash"] == independent_hash(r)
    assert p.read_bytes().endswith(b"\n")
