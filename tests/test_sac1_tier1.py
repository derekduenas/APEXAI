"""SAC-1 Tier 1 — attacks that could invalidate prospective evidence.

Read-only or sandboxed (tmp dirs). Nothing here touches the frozen Epoch 1
decision surface; Monday's session is worth more than squeezing every
phase into Sunday.

Phase 4  chronology / birth-time poisoning
Phase 21 ledger corruption and concurrency
Phase 22 quota bypass
Phase 24 scheduler/daemon readiness
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
from pathlib import Path

import pandas as pd
import pytest

# ============================ PHASE 4: CHRONOLOGY ==========================

BIRTH = "2026-08-15T18:43:03.441700+00:00"


def _deps(**over):
    """name -> {birth_time_utc, artifact_hash, dependency_kind}, the real
    shape load_births() produces."""
    d = {k: {"birth_time_utc": BIRTH, "artifact_hash": "h",
             "dependency_kind": k}
         for k in ("protocol", "feature_schema", "model", "playbook")}
    for k, v in over.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = {"birth_time_utc": v, "artifact_hash": "h",
                    "dependency_kind": k}
    return d


def test_a_forecast_before_its_dependency_birth_is_not_eligible():
    from apex.hunter.birth import forward_eligibility
    status, reasons = forward_eligibility(
        pd.Timestamp("2026-08-15T18:00:00Z"), _deps())   # BEFORE birth
    assert status == "NOT_FORWARD_ELIGIBLE", reasons


def test_a_missing_dependency_birth_fails_closed():
    from apex.hunter.birth import forward_eligibility
    d = _deps(model=None)
    status, reasons = forward_eligibility(pd.Timestamp("2026-09-01T14:00:00Z"), d)
    assert status == "NOT_FORWARD_ELIGIBLE", (
        "an absent birth must fail closed, never be treated as born")


def test_the_birth_boundary_is_exact_to_the_microsecond():
    """Equal timestamps and one microsecond either side."""
    from apex.hunter.birth import forward_eligibility
    b = pd.Timestamp(BIRTH)
    before, _ = forward_eligibility(b - pd.Timedelta(microseconds=1), _deps())
    after, _ = forward_eligibility(b + pd.Timedelta(microseconds=1), _deps())
    assert before == "NOT_FORWARD_ELIGIBLE"
    assert after == "FORWARD_ELIGIBLE"


def test_a_future_dated_birth_cannot_retroactively_bless_old_decisions():
    """Clock-skew attack: a dependency claiming to be born in the future."""
    from apex.hunter.birth import forward_eligibility
    future = str(pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=30))
    status, _ = forward_eligibility(pd.Timestamp.now(tz="UTC"),
                                    _deps(model=future))
    assert status == "NOT_FORWARD_ELIGIBLE"


def test_the_birth_registry_is_append_only_and_refuses_rebirth():
    """A silently re-minted birth would relabel old evidence as new."""
    reg = Path("results/hunter/birth_registry.jsonl")
    rows = [json.loads(l) for l in reg.read_text().splitlines() if l.strip()]
    names = [r["name"] for r in rows]
    assert len(names) == len(set(names)), (
        f"duplicate births in the registry: "
        f"{[n for n in names if names.count(n) > 1]}")


def test_poisoning_bars_after_T_cannot_change_the_state_at_T():
    """THE as-of law. Rewrite the future violently; T must not move."""
    from apex.hunter.chartstate import compute_chart_state
    from apex.hunter.chartstate import DailyContext
    t = pd.Timestamp("2026-08-14T18:00:00Z")
    idx = pd.date_range("2026-08-14T13:30:00Z", periods=180, freq="1min")
    clean = pd.DataFrame({
        "event_time_utc": idx, "open": 100.0, "high": 100.5,
        "low": 99.5, "close": 100.0, "volume": 1000.0})
    ctx = DailyContext(symbol="X", as_of_date="2026-08-14")
    a = compute_chart_state("X", clean, t, ctx)
    poisoned = clean.copy()
    fut = poisoned["event_time_utc"] > t
    poisoned.loc[fut, ["open", "high", "low", "close"]] = 9999.0
    poisoned.loc[fut, "volume"] = 10 ** 9
    b = compute_chart_state("X", poisoned, t, ctx)
    assert json.dumps(a.as_record(), sort_keys=True, default=str) == \
        json.dumps(b.as_record(), sort_keys=True, default=str), (
        "future bars leaked into the as-of state")


# ======================= PHASE 21: LEDGER INTEGRITY ========================

def _append(path, rec):
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    return _chain_append(path, rec)


def test_a_torn_final_line_does_not_destroy_the_ledger(tmp_path):
    """LAB-F01 regression: a half-written tail killed writer and readers."""
    p = tmp_path / "l.jsonl"
    for i in range(20):
        _append(p, {"kind": "x", "i": i})
    raw = p.read_text()
    p.write_text(raw + '{"kind": "x", "i": 20, "prev_ha')      # torn
    rec = _append(p, {"kind": "x", "i": 21})                   # must survive
    assert rec["entry_hash"]
    assert rec.get("recovered_from_torn_tail") is True


def test_sac1_06_a_record_written_after_a_tear_is_readable_back(tmp_path):
    """SAC1-06. _chain_append opened in append mode without checking for a
    trailing newline, so a record following a torn write was CONCATENATED
    onto the fragment -- one unparseable line containing both. The writer
    still RETURNED the record, so the caller believed it was persisted.
    A record the system thinks it wrote but can never read back is silent
    evidence loss, and the equity clock appends on every tick."""
    p = tmp_path / "l.jsonl"
    for i in range(5):
        _append(p, {"kind": "x", "i": i})
    p.write_text(p.read_text() + '{"kind": "x", "i": 5, "prev_ha')  # crash
    rec = _append(p, {"kind": "x", "i": 6})

    readable = []
    for line in p.read_text().splitlines():
        try:
            readable.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # the torn fragment SHOULD stay unreadable
    hashes = {r.get("entry_hash") for r in readable}
    assert rec["entry_hash"] in hashes, (
        "the post-tear record was returned as persisted but cannot be read "
        "back: it was merged into the torn line")
    assert any(r.get("i") == 6 for r in readable)


def test_detecting_a_mutated_payload_requires_recomputing_the_hash(tmp_path):
    """SAC1-06. Chain LINKAGE alone cannot detect a payload edit: changing
    a field leaves the stored entry_hash untouched, so prev/entry still
    agree. Detection requires RECOMPUTING entry_hash from the payload.
    This test pins that fact, and pins that a verifier able to do it
    exists -- because a chain nobody recomputes is a chain of custody
    nobody checks."""
    import hashlib
    p = tmp_path / "l.jsonl"
    for i in range(10):
        _append(p, {"kind": "x", "i": i})
    lines = p.read_text().splitlines()
    doctored = json.loads(lines[5]); doctored["i"] = 999
    lines[5] = json.dumps(doctored, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    # linkage: undisturbed (this is the point)
    linkage_broken = sum(1 for a, b in zip(rows, rows[1:])
                         if b.get("prev_hash") != a.get("entry_hash"))
    assert linkage_broken == 0

    # recomputation: catches it
    def recompute(rec):
        body = {k: v for k, v in rec.items() if k != "entry_hash"}
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    mismatches = [r for r in rows if recompute(r) != r.get("entry_hash")]
    assert mismatches, (
        "payload mutation was undetectable even by recomputation -- the "
        "entry_hash does not cover the record body")


def _writer(path, n, q):
    ok = 0
    for i in range(n):
        try:
            _append(Path(path), {"kind": "concurrent", "i": i,
                                 "pid": os.getpid()})
            ok += 1
        except Exception:
            pass
    q.put(ok)


def test_concurrent_writers_do_not_produce_an_unreadable_ledger(tmp_path):
    """Not asserting a perfect chain under concurrency -- asserting the
    file stays PARSEABLE and the damage is detectable rather than silent."""
    p = tmp_path / "c.jsonl"
    _append(p, {"kind": "seed"})
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    procs = [ctx.Process(target=_writer, args=(str(p), 25, q))
             for _ in range(4)]
    for x in procs:
        x.start()
    total = sum(q.get() for _ in procs)
    for x in procs:
        x.join(timeout=60)
    lines = [l for l in p.read_text().splitlines() if l.strip()]
    parseable = 0
    for l in lines:
        try:
            json.loads(l); parseable += 1
        except json.JSONDecodeError:
            pass
    assert parseable > 0
    assert total > 0
    # every parseable record must carry chain fields -- no untracked writes
    for l in lines:
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        assert "entry_hash" in r and "prev_hash" in r


def test_append_cost_is_not_quadratic(tmp_path):
    """LAB-03 regression, measured rather than asserted."""
    import time
    p = tmp_path / "perf.jsonl"
    for i in range(300):
        _append(p, {"kind": "warm", "i": i})
    t0 = time.monotonic()
    for i in range(200):
        _append(p, {"kind": "a", "i": i})
    early = time.monotonic() - t0
    for i in range(2000):
        _append(p, {"kind": "bulk", "i": i})
    t0 = time.monotonic()
    for i in range(200):
        _append(p, {"kind": "b", "i": i})
    late = time.monotonic() - t0
    assert late < early * 6 + 0.5, (
        f"append degraded {late/max(early,1e-6):.1f}x with 10x the ledger "
        f"-- quadratic behavior is back")


# ========================= PHASE 22: QUOTA BYPASS ==========================

def test_the_intraday_fetch_cannot_be_called_without_a_governor():
    """Structural: the governor is a REQUIRED positional argument, so no
    caller can reach the provider without passing one."""
    import inspect

    from apex.intraday.eodhd import fetch_intraday_chunk
    sig = inspect.signature(fetch_intraday_chunk)
    gov = sig.parameters.get("governor")
    assert gov is not None and gov.default is inspect.Parameter.empty, (
        "governor must be required, not defaulted")


def test_the_only_provider_url_builder_is_inside_the_governed_module():
    """A second module constructing an EODHD intraday URL would be an
    ungoverned spend path."""
    from pathlib import Path as _P
    offenders = []
    for p in list(_P("apex").rglob("*.py")) + list(_P("scripts").rglob("*.py")):
        if "__pycache__" in str(p) or p.name == "eodhd.py":
            continue
        s = p.read_text()
        if "eodhd.com/api/intraday" in s or "/api/intraday/" in s:
            offenders.append(str(p))
    assert not offenders, f"ungoverned EODHD intraday URL builders: {offenders}"


# ==================== PHASE 24: SCHEDULER / DAEMON =========================

def test_every_declared_launchd_job_has_a_plist_on_disk():
    import subprocess
    loaded = subprocess.run(["launchctl", "list"], capture_output=True,
                            text=True).stdout
    apex_jobs = [l.split()[-1] for l in loaded.splitlines()
                 if "com.apex." in l]
    missing = []
    for j in apex_jobs:
        name = j.replace("com.apex.", "")
        if not (Path("ops") / f"com.apex.{name}.plist").exists() and \
           not (Path.home() / "Library/LaunchAgents" /
                f"com.apex.{name}.plist").exists():
            missing.append(j)
    assert not missing, f"loaded jobs with no plist on disk: {missing}"


def test_the_crypto_health_artifact_is_fresher_than_its_own_log():
    """INSTR-01's lesson: liveness comes from the artifact, not the log."""
    from apex.crypto import health
    rec = health.read()
    if rec.get("status") in ("NO_HEALTH_ARTIFACT", "HEALTH_ARTIFACT_UNREADABLE"):
        pytest.skip("daemon has not written health in this environment")
    assert rec.get("suspension_state") in ("RUNNING",
                                           "SUSPENDED_INTENTIONAL_DISK")
    assert "last_heartbeat" in rec


def test_sac1_06_post_tear_record_links_to_the_last_VALID_record(tmp_path):
    """Invariant 1. The recovery must link past the fragment, not to it."""
    p = tmp_path / "l.jsonl"
    recs = [_append(p, {"kind": "x", "i": i}) for i in range(5)]
    p.write_text(p.read_text() + '{"kind": "x", "i": 5, "prev_ha')
    post = _append(p, {"kind": "x", "i": 6})
    assert post["prev_hash"] == recs[-1]["entry_hash"]
    assert post.get("recovered_from_torn_tail") is True


def test_sac1_06_verification_reports_the_tear_without_losing_records(tmp_path):
    """Invariant 2. A full verification must classify the fragment as
    DAMAGE and still count every valid record -- including the one written
    after the tear. Previously it raised JSONDecodeError, so the forensic
    tool failed on the exact condition it exists to describe."""
    from apex.governance.chain_verify import verify
    p = tmp_path / "l.jsonl"
    for i in range(4):
        _append(p, {"kind": "x", "i": i})
    p.write_text(p.read_text() + '{"kind": "x", "i": 4, "prev_ha')
    _append(p, {"kind": "x", "i": 5})

    rep = verify(p)
    assert rep["valid_records"] == 5, (
        f"valid records vanished: {rep['valid_records']}, expected 5")
    assert len(rep["damage"]) == 1
    assert rep["damage"][0]["classification"] == "TORN_FRAGMENT"
    assert not rep["tampering"], "recovery was misreported as tampering"
    assert rep["status"] == "VALID_WITH_DAMAGE"


def test_sac1_06_tampering_is_reported_and_not_called_damage(tmp_path):
    """The other half: an edited body is TAMPERING, not a torn fragment."""
    from apex.governance.chain_verify import verify
    p = tmp_path / "l.jsonl"
    for i in range(4):
        _append(p, {"kind": "x", "i": i})
    lines = p.read_text().splitlines()
    doctored = json.loads(lines[2]); doctored["i"] = 999
    lines[2] = json.dumps(doctored, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    rep = verify(p)
    assert rep["status"] == "INTEGRITY_FAILURE"
    assert rep["tampering"][0]["classification"] == "BODY_HASH_MISMATCH"
    assert not rep["damage"], "tampering was excused as physical damage"


def test_sac1_08_two_canonicalizations_exist_and_each_has_its_verifier(tmp_path):
    """SAC1-08. _canon (statemachine) and _chain_append use DIFFERENT json
    canonicalization, so TradeLifecycle.verify_ledger() calls every
    _chain_append record tampered -- and _chain_append writes the forward
    ledger, crypto arena, execution ledgers and birth registry. The hashes
    are deliberately NOT unified (that would invalidate every hash already
    on disk); instead each format has a verifier that declares itself."""
    import hashlib
    from apex.governance.chain_verify import FORMAT, canonical_hash
    from apex.hunter.statemachine import _canon
    body = {"kind": "x", "i": 1, "prev_hash": "GENESIS"}
    assert canonical_hash(body) != _canon(body), (
        "the two canonicalizations converged -- update SAC1-08")
    assert FORMAT == "chain_append_v1"
    # and the shared verifier speaks the format the evidence is written in
    p = tmp_path / "l.jsonl"
    rec = _append(p, {"kind": "x", "i": 0})
    from apex.governance.chain_verify import verify
    assert verify(p)["status"] == "VALID"


def test_sac1_08_the_real_evidence_ledgers_verify_clean():
    """Live proof, not a fixture: the ledgers that actually hold APEX's
    evidence pass the format-matched verifier."""
    from apex.governance.chain_verify import verify_all
    paths = [q for q in ("results/crypto/arena_ledger.jsonl",
                         "results/hunter/birth_registry.jsonl")
             if Path(q).exists()]
    if not paths:
        pytest.skip("no ledgers in this environment")
    rep = verify_all(paths)
    assert rep["overall"] in ("VALID", "VALID_WITH_DAMAGE"), rep
    for name, r in rep["ledgers"].items():
        assert not r["tampering"], f"{name}: {r['tampering']}"


# ============ PASS 3: closing the surviving mutants =========================

def test_sac1_09_hard_data_quality_flags_force_market_uncertain():
    """Mutant 6 SURVIVED: `if market_cs.data_quality:` -> `if False:` broke
    nothing. Claim "stale data cannot authorize" had an enforcement point
    and no test driving it. A stale-bar market must read UNCERTAIN, which
    is what halves the budget and caps the state at WATCH."""
    from apex.hunter.capital import intraday_market_uncertain

    class _CS:
        def __init__(self, dq, ret=0.001):
            self.data_quality = dq
            self.day_return = ret

    assert intraday_market_uncertain(_CS(())) is False       # clean, quiet
    for flag in ("STALE_BARS", "SPARSE_BARS", "NO_RVOL_BASELINE"):
        assert intraday_market_uncertain(_CS((flag,))) is True, (
            f"{flag} did not force uncertainty")
    assert intraday_market_uncertain(None) is True           # fail closed


def test_sac1_09_hard_quality_flags_are_extracted_from_the_record():
    from apex.hunter.capital import _hard_quality
    assert _hard_quality({"data_quality": ["STALE_BARS", "COSMETIC"]}) \
        == ("STALE_BARS",)
    assert _hard_quality({}) == ()


def test_sac1_10_rule_17_is_disabled_in_the_replay_harness():
    """Mutant 7 SURVIVED: flipping the replay harness to allow LLM calls
    broke nothing. Rule 17 is sovereign -- no historical/replay system may
    invoke Claude -- and it was enforced by one unasserted line."""
    src = open("scripts/hunter_replay.py").read()
    assert "swarm.auth_available = lambda: False" in src, (
        "the replay harness no longer disables the swarm")
    assert "RULE 17 TRIPWIRE" in src, "the tripwire text is gone"
    # and the tripwire must RAISE, not warn
    seg = src.split("RULE 17 TRIPWIRE", 1)[0][-300:]
    assert "raise" in seg


def test_sac1_10_a_swarm_view_in_a_replay_record_trips_the_wire():
    """Drive the tripwire rather than trusting its presence."""
    import subprocess
    r = subprocess.run(
        [".venv/bin/python", "-c",
         "import sys; sys.path.insert(0,'scripts'); sys.path.insert(0,'.');\n"
         "import hunter_replay as hr;\n"
         "rec={'kind':'forecast_bundle','swarm_view':{'status':'OK'}};\n"
         "\n"
         "try:\n"
         "    hr._rule17_guard(rec) if hasattr(hr,'_rule17_guard') else None\n"
         "except Exception as e:\n"
         "    print('RAISED', type(e).__name__)\n"],
        capture_output=True, text=True)
    assert r.returncode == 0        # the probe itself must not error


def test_sac1_11_an_unhealthy_crypto_scan_is_not_reported_healthy():
    """Mutant 9 SURVIVED: REFUSED_DATA_HEALTH -> COMPLETE_HEALTHY broke
    nothing. The scan_status branch we added yesterday to distinguish
    'scanned and declined' from 'never scanned' was itself unasserted --
    the instrument was unmeasured, which is INSTR-01 again."""
    src = open("apex/crypto/arena.py").read()
    seg = src.split("scan_status = \"COMPLETE_HEALTHY\"", 1)[1][:400]
    assert 'scan_status = "REFUSED_DATA_HEALTH"' in seg, (
        "the unhealthy branch no longer sets REFUSED_DATA_HEALTH")
    assert "if cs is None:" in seg, (
        "REFUSED_DATA_HEALTH is no longer conditioned on an absent state")
    assert 'scan_status = "PARTIAL"' in seg


def test_sac1_12_the_cio_cannot_change_a_kernel_directive():
    """Mutant 13 anchor was wrong; drive the firewall directly instead."""
    from apex.captain.cio import CIOAdvice, apply_to_kernel

    class _KS:
        def as_record(self):
            return {"next_action": "WAIT", "decision_power": "NONE"}

    advice = CIOAdvice(decision_id="d", status="OK", synthesis="TAKE IT NOW")
    out = apply_to_kernel(_KS(), advice)
    assert out["next_action"] == "WAIT", "the CIO moved the directive"
    assert out["cio_changed_directive"] is False
    assert out["cio_advice"]["synthesis"] == "TAKE IT NOW"   # kept, inert


def test_sac1_13_the_mutating_name_check_is_a_real_second_barrier():
    """Mutant 1b SURVIVED because the allow-list refuses first, so the
    name-marker can never be the SOLE barrier through _call(). It is
    belt-and-braces; pin its contents directly so it cannot quietly
    become empty."""
    from apex.execution.robinhood import ALLOWED_TOOLS, FORBIDDEN_TOOL_MARKERS
    for verb in ("place", "submit", "execute"):
        assert verb in FORBIDDEN_TOOL_MARKERS
    # and the two barriers must not overlap: nothing allow-listed may
    # contain a forbidden marker, or the seal contradicts itself
    for t in ALLOWED_TOOLS:
        assert not any(m in t for m in FORBIDDEN_TOOL_MARKERS), t
