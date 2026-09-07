"""WORLD_MODEL_REAL_DATA_BOUNDARY_V1 -- fail-closed admission of REAL
historical data to a research process, bound to a SIGNED external decision.

WHAT CHANGED FROM V0 (reviewer findings, 566600dc)
  * HMAC replaced by OpenSSH signatures (ssh-keygen -Y). Research holds
    only the allowed_signers (public keys); the signing key never exists on
    the research path. Verification and issuance are different capabilities.
  * The production entry point takes NO injection parameters. Tests use
    verify_decision_with(trust=TrustConfig(...)) explicitly.
  * Execution binds to verified SOURCE CONTENT: HEAD must match, the
    relevant source tree hash must match, and the relevant paths must be
    clean. Runtime import provenance is recorded in every run.
  * Runs are exclusive directories; identity and authority records are
    written once and never rewritten.

FOUR DECISIONS KEPT APART
  readable (OS) / assessed eligible (document) / AUTHORIZED (signed
  decision) / passed (the experiment's own sealed result). This module is
  (3) and enforces that nothing else stands in for it.

WHAT THIS DOES NOT PROTECT AGAINST -- STATED
Arbitrary privileged code on the host, or an actor who can replace the
allowed_signers file. The trust paths must therefore be OWNED BY A
DIFFERENT UID than the research account and not writable by it; the
verifier checks mode and (in production) ownership and refuses otherwise.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REAL_DATA_CONTRACT = "WORLD_MODEL_REAL_DATA_BOUNDARY_V1"
SIGNATURE_MECHANISM = "OPENSSH_SSHSIG (ssh-keygen -Y sign/verify, ed25519)"
SIGNATURE_NAMESPACE = "apex-admission"

REAL_DATA_RESEARCH_AUTHORITY_V0 = {
    "contract": "REAL_DATA_RESEARCH_AUTHORITY_V0",
    "REAL_HISTORICAL_READ": "BY_SIGNED_ADMISSION_DECISION_ONLY",
    "ADMISSION_ISSUANCE": "NONE (no signing key on the research path)",
    "PROSPECTIVE_OUTCOME_ACCESS": "FORBIDDEN",
    "BOOK_OUTCOME_ACCESS": "FORBIDDEN",
    "P_AND_L_ACCESS": "FORBIDDEN",
    "ROBINHOOD_ACCESS": "FORBIDDEN",
    "ORDER_AUTHORITY": "NONE",
    "TRADING_AUTHORITY": "NONE",
    "CAPITAL_AUTHORITY": "NONE",
    "LIVE_DECISION_AUTHORITY": "NONE",
    "MODEL_PROMOTION_AUTHORITY": "NONE",
    "PRODUCTION_DEPLOYMENT": "FORBIDDEN",
}

PROHIBITED_DATASET_ROOTS = ("/apex-data/core", "/apex-data/runtime", "/opt/apex-repo/results",
                            "/opt/apex/releases", "/apex-research/world-model-fixtures")
PERMITTED_HISTORICAL_ROOTS = ("/apex-data/history-a", "/apex-data/history-b")
# Source paths whose CONTENT the decision binds. Anything here modified,
# untracked or different from the decided tree hash refuses execution.
RELEVANT_SOURCE_PATHS = ("apex/world_model", "apex/governance/chain_ledger.py",
                         "apex/intraday/sessions.py", "scripts/alpha_exp_real_execute.py")

AVAILABILITY_KINDS = frozenset({"PER_ROW", "PER_FILE", "BULK", "NOT_AVAILABLE"})
CORPORATE_ACTION_TREATMENTS = frozenset({"RAW_UNADJUSTED_EXPLICIT", "ADJUSTED_DECLARED", "NOT_APPLICABLE"})
AUTHORITY_CLASSIFICATIONS = frozenset({"RESEARCH_HISTORICAL"})
ISO_DATE = "%Y-%m-%d"
REQUIRED_BODY = {
    "contract": None, "decision": None,
    "dataset": ("dataset_id", "root", "manifest_path", "manifest_sha256"),
    "scope": ("source_families", "fields", "universe", "temporal_range"),
    "availability": ("event_time", "receipt_time", "publication_time", "revision_time",
                     "corporate_actions", "restricted_use"),
    "purpose": ("research_purpose", "experiment_id", "registration_hash"),
    "code": ("commit", "source_tree_sha256"),
    "output": ("root", "authority_classification"),
    "provenance": ("decided_by", "decided_utc", "review_reference"),
}
AUTHORITY_FILE, RUN_FILE, RESULT_FILE = "_AUTHORITY.json", "_RUN.json", "_RESULT.json"


class RealDataRefused(Exception):
    """Refused on this route. No override exists."""


def checkout_root() -> Path:
    """The checkout THIS module was imported from -- not the cwd."""
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class TrustConfig:
    """Everything the verifier trusts. Production builds exactly one of
    these from constants; tests build their own with disposable paths.
    No field can turn a refusal into an admission -- they relocate trust,
    they do not weaken it, except enforce_ownership which tests must set
    False because tmp files are owned by the test user (mode is still
    enforced)."""
    admission_root: Path
    allowed_signers: Path
    checkout_root: Path
    permitted_roots: tuple = PERMITTED_HISTORICAL_ROOTS
    prohibited_roots: tuple = PROHIBITED_DATASET_ROOTS
    namespace: str = SIGNATURE_NAMESPACE
    enforce_ownership: bool = True
    ssh_keygen: str = "ssh-keygen"
    relevant_source_paths: tuple = RELEVANT_SOURCE_PATHS


PRODUCTION_ADMISSION_ROOT = Path("/apex-data/governance/admissions")
PRODUCTION_ALLOWED_SIGNERS = Path("/apex-data/governance/admissions/trust/allowed_signers")


def production_trust() -> TrustConfig:
    return TrustConfig(admission_root=PRODUCTION_ADMISSION_ROOT,
                       allowed_signers=PRODUCTION_ALLOWED_SIGNERS,
                       checkout_root=checkout_root(), enforce_ownership=True)


@dataclass(frozen=True)
class Grant:
    contract: str
    decision_path: str
    decision_sha256: str
    signer: str
    dataset_id: str
    dataset_root: str
    manifest: dict
    manifest_sha256: str
    source_families: tuple
    fields: tuple
    universe: tuple
    temporal_range: tuple
    availability: dict
    experiment_id: str
    registration_hash: str
    code_commit: str
    source_identity: dict
    output_root: str
    authority_classification: str
    provenance: dict
    authority: dict = field(default_factory=lambda: dict(REAL_DATA_RESEARCH_AUTHORITY_V0))


# ---------------------------------------------------------------- helpers
def _resolved(p) -> Path:
    return Path(p).expanduser().resolve(strict=False)


def _under(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(root: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RealDataRefused("GIT_UNAVAILABLE: git %s failed in %s: %s"
                              % (" ".join(args), root, r.stderr.strip()[:200]))
    return r.stdout


def source_identity(root: Path, paths: tuple = RELEVANT_SOURCE_PATHS) -> dict:
    """Commit, dirtiness and CONTENT hash of the relevant source tree.
    tree_sha256 = sha256 over sorted 'relpath sha256(file bytes)' lines of
    the TRACKED files under `paths`; dirty lists anything modified, deleted
    or untracked under `paths`."""
    root = _resolved(root)
    commit = _git(root, "rev-parse", "HEAD").strip()
    dirty = [l for l in _git(root, "status", "--porcelain", "--untracked-files=all", "--", *paths).splitlines() if l]
    tracked = sorted(l for l in _git(root, "ls-files", "--", *paths).splitlines() if l)
    lines = []
    for rel in tracked:
        p = root / rel
        if p.exists():
            lines.append("%s %s" % (rel, sha256_of(p)))
    tree = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return {"commit": commit, "tree_sha256": tree, "n_files": len(lines), "dirty": dirty,
            "paths": list(paths), "checkout_root": str(root)}


def runtime_provenance() -> dict:
    mods = {n: getattr(m, "__file__", None) for n, m in sorted(sys.modules.items())
            if n.startswith("apex.") and getattr(m, "__file__", None)}
    return {"executable": sys.executable, "python": sys.version.split()[0],
            "cwd": os.getcwd(), "pid": os.getpid(), "euid": os.geteuid(),
            "apex_module_files": mods, "n_apex_modules": len(mods)}


def _date(s, what) -> datetime:
    try:
        return datetime.strptime(s, ISO_DATE).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise RealDataRefused("MALFORMED_DATE: %s=%r (want YYYY-MM-DD)" % (what, s))


def _check_trust_path(p: Path, trust: TrustConfig, what: str) -> None:
    """A trust path writable by the research account is no trust path."""
    try:
        st = os.stat(p)
    except OSError as e:
        raise RealDataRefused("TRUST_PATH_MISSING: %s %s: %s" % (what, p, e)) from e
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RealDataRefused("TRUST_PATH_WRITABLE: %s %s is group/other-writable (mode %o)"
                              % (what, p, stat.S_IMODE(st.st_mode)))
    if trust.enforce_ownership and st.st_uid == os.geteuid():
        raise RealDataRefused("TRUST_PATH_OWNED_BY_RESEARCH: %s %s is owned by uid %d, the research "
                              "account; issuance and verification must not share an owner"
                              % (what, p, st.st_uid))


def _check_availability(av: dict) -> None:
    for k in ("event_time", "receipt_time", "publication_time", "revision_time"):
        v = av.get(k)
        kind = v.get("kind") if isinstance(v, dict) else None
        if kind not in AVAILABILITY_KINDS:
            raise RealDataRefused("AVAILABILITY_INVALID: %s.kind=%r not in %s" % (k, kind, sorted(AVAILABILITY_KINDS)))
    if av["event_time"]["kind"] == "NOT_AVAILABLE":
        raise RealDataRefused("AVAILABILITY_INVALID: event_time cannot be NOT_AVAILABLE")
    rc = av["receipt_time"]
    if rc["kind"] == "BULK":
        at = rc.get("at")
        if not at:
            raise RealDataRefused("AVAILABILITY_INVALID: BULK receipt needs 'at'")
        ev_end = av["event_time"].get("latest")
        if ev_end and _date(str(at)[:10], "receipt_time.at") < _date(ev_end, "event_time.latest"):
            raise RealDataRefused("AVAILABILITY_INVALID: receipt %s precedes the latest event %s" % (at, ev_end))
    if av.get("corporate_actions") not in CORPORATE_ACTION_TREATMENTS:
        raise RealDataRefused("AVAILABILITY_INVALID: corporate_actions=%r" % (av.get("corporate_actions"),))
    if av["publication_time"]["kind"] == "NOT_AVAILABLE" or av["revision_time"]["kind"] == "NOT_AVAILABLE":
        ru = av.get("restricted_use")
        if not isinstance(ru, str) or not ru.strip():
            raise RealDataRefused("AVAILABILITY_INVALID: publication or revision time NOT_AVAILABLE "
                                  "requires a named restricted_use")


def _verify_signature(decision: Path, sig: Path, principal: str, trust: TrustConfig) -> None:
    if not sig.exists():
        raise RealDataRefused("UNSIGNED_DECISION: %s has no detached signature %s" % (decision.name, sig.name))
    if not principal or not isinstance(principal, str):
        raise RealDataRefused("DECISION_PROVENANCE_INVALID: decided_by is empty; the signer principal is unknown")
    try:
        with open(decision, "rb") as fh:
            r = subprocess.run([trust.ssh_keygen, "-Y", "verify", "-f", str(trust.allowed_signers),
                                "-I", principal, "-n", trust.namespace, "-s", str(sig)],
                               stdin=fh, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise RealDataRefused("SIGNATURE_UNVERIFIABLE: %s" % e) from e
    if r.returncode != 0:
        raise RealDataRefused("SIGNATURE_INVALID: ssh-keygen -Y verify refused for principal %r: %s"
                              % (principal, (r.stderr or r.stdout).strip()[:200]))


# ------------------------------------------------------------ verification
def verify_decision(decision_path, *, experiment_id=None, registration_hash=None) -> Grant:
    """PRODUCTION entry point. No injection parameters exist here."""
    return verify_decision_with(decision_path, production_trust(),
                                experiment_id=experiment_id, registration_hash=registration_hash)


def verify_decision_with(decision_path, trust: TrustConfig, *, experiment_id=None,
                         registration_hash=None) -> Grant:
    """Verification against an explicit TrustConfig (tests; audited callers)."""
    aroot = _resolved(trust.admission_root)
    croot = _resolved(trust.checkout_root)
    if decision_path is None:
        raise RealDataRefused("NO_DECISION: no admission decision was supplied; real historical data are "
                              "not readable on this route without one")
    dp = _resolved(decision_path)
    if not dp.exists():
        raise RealDataRefused("NO_DECISION: %s does not exist" % dp)
    if not _under(dp, aroot):
        raise RealDataRefused("DECISION_OUTSIDE_ADMISSION_ROOT: %s is not under %s" % (dp, aroot))
    if _under(dp, croot):
        raise RealDataRefused("DECISION_INSIDE_CHECKOUT: %s lives in the code checkout; a caller may not "
                              "admit itself" % dp)
    for p, what in ((aroot, "admission_root"), (_resolved(trust.allowed_signers), "allowed_signers"),
                    (_resolved(trust.allowed_signers).parent, "trust dir"), (dp, "decision")):
        _check_trust_path(p, trust, what)
    try:
        doc = json.loads(dp.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RealDataRefused("DECISION_UNREADABLE: %s" % e) from e
    if not isinstance(doc, dict):
        raise RealDataRefused("DECISION_UNREADABLE: not a mapping")
    for k, sub in REQUIRED_BODY.items():
        if k not in doc:
            raise RealDataRefused("MISSING_FIELD: %s" % k)
        if sub:
            if not isinstance(doc[k], dict):
                raise RealDataRefused("MISSING_FIELD: %s is not a mapping" % k)
            for s in sub:
                if s not in doc[k]:
                    raise RealDataRefused("MISSING_FIELD: %s.%s" % (k, s))
    if doc["contract"] != REAL_DATA_CONTRACT:
        raise RealDataRefused("CONTRACT_MISMATCH: %r != %s" % (doc["contract"], REAL_DATA_CONTRACT))
    if doc["decision"] != "ADMIT":
        raise RealDataRefused("DECISION_NOT_ADMIT: decision=%r. A proposal, an eligibility assessment or a "
                              "refusal admits nothing" % (doc["decision"],))
    prov = doc["provenance"]
    principal = str(prov.get("decided_by", "")).strip()
    if principal.upper() in ("", "CALLER", "ENGINEERING", "SELF"):
        raise RealDataRefused("DECISION_PROVENANCE_INVALID: decided_by=%r" % (prov.get("decided_by"),))
    try:
        datetime.fromisoformat(str(prov["decided_utc"]).replace("Z", "+00:00"))
    except ValueError:
        raise RealDataRefused("DECISION_PROVENANCE_INVALID: decided_utc=%r" % (prov["decided_utc"],))
    # ---- signature over the exact file bytes, by the named principal --
    _verify_signature(dp, dp.with_name(dp.name + ".sig"), principal, trust)
    decision_sha = sha256_of(dp)

    # ---- dataset ----------------------------------------------------------
    ds = doc["dataset"]
    droot = _resolved(ds["root"])
    for pr in trust.prohibited_roots:
        if _under(droot, _resolved(pr)):
            raise RealDataRefused("PROHIBITED_DATASET_ROOT: %s is under %s; no decision opens it on this route"
                                  % (droot, pr))
    if not any(_under(droot, _resolved(pr)) for pr in trust.permitted_roots):
        raise RealDataRefused("DATASET_ROOT_NOT_PERMITTED: %s is not under any permitted historical root %s"
                              % (droot, list(trust.permitted_roots)))
    mpath = _resolved(ds["manifest_path"])
    if not mpath.exists():
        raise RealDataRefused("MANIFEST_MISSING: %s" % mpath)
    actual = sha256_of(mpath)
    if actual != ds["manifest_sha256"]:
        raise RealDataRefused("MANIFEST_HASH_MISMATCH: decision commits to %s but the manifest is %s"
                              % (str(ds["manifest_sha256"])[:16], actual[:16]))
    try:
        manifest = json.loads(mpath.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RealDataRefused("MANIFEST_UNREADABLE: %s" % e) from e
    if manifest.get("dataset_id") != ds["dataset_id"] or _resolved(manifest.get("root", "")) != droot:
        raise RealDataRefused("DATASET_MISMATCH: decision names %r at %s; manifest says %r at %r"
                              % (ds["dataset_id"], droot, manifest.get("dataset_id"), manifest.get("root")))
    if not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise RealDataRefused("MANIFEST_EMPTY: no files committed")

    # ---- scope ---------------------------------------------------------
    sc = doc["scope"]
    for k in ("source_families", "fields", "universe"):
        if not isinstance(sc[k], list) or not sc[k] or not all(isinstance(x, str) for x in sc[k]):
            raise RealDataRefused("SCOPE_INVALID: %s must be a non-empty list of names" % k)
    tr = sc["temporal_range"]
    if not isinstance(tr, dict) or "start" not in tr or "end" not in tr:
        raise RealDataRefused("SCOPE_INVALID: temporal_range needs start and end")
    if _date(tr["end"], "end") < _date(tr["start"], "start"):
        raise RealDataRefused("SCOPE_INVALID: temporal_range end precedes start")
    mfam = set(manifest.get("source_families") or [])
    if mfam and not set(sc["source_families"]) <= mfam:
        raise RealDataRefused("SCOPE_INVALID: source_families %s not all in manifest %s" % (sc["source_families"], sorted(mfam)))

    # ---- availability -----------------------------------------------------
    av = doc["availability"]
    _check_availability(av)
    mav = manifest.get("availability")
    if isinstance(mav, dict):
        for k in ("event_time", "receipt_time", "publication_time", "revision_time"):
            if mav.get(k, {}).get("kind") != av[k]["kind"]:
                raise RealDataRefused("AVAILABILITY_INVALID: decision says %s=%s, manifest says %s"
                                      % (k, av[k]["kind"], mav.get(k, {}).get("kind")))
        if mav.get("corporate_actions") != av["corporate_actions"]:
            raise RealDataRefused("AVAILABILITY_INVALID: corporate_actions differ between decision and manifest")

    # ---- purpose ----------------------------------------------------------
    pu = doc["purpose"]
    if experiment_id is not None and pu["experiment_id"] != experiment_id:
        raise RealDataRefused("EXPERIMENT_MISMATCH: decision serves %r, caller is %r" % (pu["experiment_id"], experiment_id))
    if registration_hash is not None and pu["registration_hash"] != registration_hash:
        raise RealDataRefused("REGISTRATION_MISMATCH: decision was made for registration %s, caller runs %s"
                              % (str(pu["registration_hash"])[:16], str(registration_hash)[:16]))

    # ---- code: HEAD, content and cleanliness of the relevant source ----
    ident = source_identity(croot, trust.relevant_source_paths)
    if ident["dirty"]:
        raise RealDataRefused("SOURCE_DIRTY: relevant source differs from the commit: %s" % ident["dirty"][:5])
    if doc["code"]["commit"] != ident["commit"]:
        raise RealDataRefused("CODE_IDENTITY_MISMATCH: decision was made for %s, running %s"
                              % (str(doc["code"]["commit"])[:12], ident["commit"][:12]))
    if doc["code"]["source_tree_sha256"] != ident["tree_sha256"]:
        raise RealDataRefused("SOURCE_IDENTITY_MISMATCH: decision binds source tree %s, running %s"
                              % (str(doc["code"]["source_tree_sha256"])[:16], ident["tree_sha256"][:16]))

    # ---- output -----------------------------------------------------------
    out = doc["output"]
    oroot = _resolved(out["root"])
    if out["authority_classification"] not in AUTHORITY_CLASSIFICATIONS:
        raise RealDataRefused("OUTPUT_AUTHORITY_INVALID: %r" % (out["authority_classification"],))
    # evidence, corpus, release and fixture roots are never output roots --
    # the PRODUCTION constants apply here regardless of the trust config
    never = set(PROHIBITED_DATASET_ROOTS + PERMITTED_HISTORICAL_ROOTS) | set(trust.prohibited_roots) \
        | set(str(p) for p in trust.permitted_roots)
    for pr in sorted(never):
        if _under(oroot, _resolved(pr)):
            raise RealDataRefused("OUTPUT_ROOT_INVALID: %s is under %s" % (oroot, pr))
    if _under(oroot, croot):
        raise RealDataRefused("OUTPUT_ROOT_INVALID: %s is inside the checkout" % oroot)
    if _under(dp, oroot):
        raise RealDataRefused("DECISION_INSIDE_OUTPUT_ROOT: the decision may not live where the research writes")

    return Grant(contract=REAL_DATA_CONTRACT, decision_path=str(dp), decision_sha256=decision_sha,
                 signer=principal, dataset_id=ds["dataset_id"], dataset_root=str(droot),
                 manifest=manifest, manifest_sha256=actual,
                 source_families=tuple(sc["source_families"]), fields=tuple(sc["fields"]),
                 universe=tuple(sc["universe"]), temporal_range=(tr["start"], tr["end"]),
                 availability=dict(av), experiment_id=pu["experiment_id"],
                 registration_hash=pu["registration_hash"], code_commit=ident["commit"],
                 source_identity=ident, output_root=str(oroot),
                 authority_classification=out["authority_classification"], provenance=dict(prov))


# ------------------------------------------------------------------ reads
def open_file(grant: Grant, path, *, symbol: str, session_date: str, fields=None) -> dict:
    rp = _resolved(path)
    droot = _resolved(grant.dataset_root)
    if not _under(rp, droot):
        raise RealDataRefused("OUTSIDE_DATASET_ROOT: %s is not under %s" % (rp, droot))
    key = str(rp.relative_to(droot))
    rec = grant.manifest["files"].get(key)
    if rec is None:
        raise RealDataRefused("UNCOMMITTED_FILE: %s is not in the committed manifest" % key)
    if symbol not in grant.universe:
        raise RealDataRefused("OUTSIDE_UNIVERSE: %s not in %s" % (symbol, list(grant.universe)))
    if rec.get("symbol") not in (None, symbol):
        raise RealDataRefused("SYMBOL_MISMATCH: manifest says %r for %s" % (rec.get("symbol"), key))
    d = _date(session_date, "session_date")
    lo, hi = (_date(x, "temporal_range") for x in grant.temporal_range)
    if not (lo <= d <= hi):
        raise RealDataRefused("OUTSIDE_TEMPORAL_SCOPE: %s is outside %s..%s" % (session_date, *grant.temporal_range))
    if rec.get("session_date") not in (None, session_date):
        raise RealDataRefused("DATE_MISMATCH: manifest says %r for %s" % (rec.get("session_date"), key))
    want = tuple(fields or grant.fields)
    extra = [f for f in want if f not in grant.fields]
    if extra:
        raise RealDataRefused("FIELD_NOT_PERMITTED: %s not in admitted fields %s" % (extra, list(grant.fields)))
    if not rp.exists():
        raise RealDataRefused("MISSING_SOURCE: %s" % rp)
    raw = rp.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != rec.get("sha256"):
        raise RealDataRefused("CONTENT_CHANGED: %s committed as %s, now %s" % (key, str(rec.get("sha256"))[:16], actual[:16]))
    return {"contract": REAL_DATA_CONTRACT, "path": str(rp), "sha256": actual, "fields": want,
            "symbol": symbol, "session_date": session_date, "decision_sha256": grant.decision_sha256,
            "dataset_id": grant.dataset_id, "availability": grant.availability,
            "restricted_use": grant.availability.get("restricted_use"), "raw": raw}


# ------------------------------------------------------------------- runs
def _write_once(path: Path, obj: dict) -> None:
    with open(path, "x") as fh:                      # O_EXCL: never rewrite a record
        json.dump(obj, fh, indent=1, sort_keys=True, default=str)


def open_run(grant: Grant, *, label: str = "run") -> Path:
    """Create a UNIQUE run directory with exclusive creation and write the
    immutable identity and authority records once. Any collision refuses."""
    if "/" in label or label in ("", ".", ".."):
        raise RealDataRefused("RUN_LABEL_INVALID: %r" % label)
    runs = _resolved(grant.output_root) / grant.experiment_id / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run_id = "%s-%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), label, secrets.token_hex(4))
    run = runs / run_id
    try:
        run.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        raise RealDataRefused("RUN_EXISTS: %s already exists; runs are never reused" % run)
    _write_once(run / AUTHORITY_FILE, {
        "contract": REAL_DATA_CONTRACT, "authority_classification": grant.authority_classification,
        "authority": dict(REAL_DATA_RESEARCH_AUTHORITY_V0),
        "law": "outputs here are RESEARCH_HISTORICAL; nothing downstream may treat them as a live "
               "decision, a broker instruction or a promotion"})
    _write_once(run / RUN_FILE, {
        "run_id": run_id, "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "experiment_id": grant.experiment_id, "registration_hash": grant.registration_hash,
        "decision_path": grant.decision_path, "decision_sha256": grant.decision_sha256,
        "signer": grant.signer, "dataset_id": grant.dataset_id, "manifest_sha256": grant.manifest_sha256,
        "source_identity": grant.source_identity, "runtime": runtime_provenance(),
        "signature_mechanism": SIGNATURE_MECHANISM})
    return run


def seal_result(run_dir, record: dict) -> Path:
    """Write the result once. A second result in the same run is refused."""
    p = _resolved(run_dir) / RESULT_FILE
    try:
        _write_once(p, record)
    except FileExistsError:
        raise RealDataRefused("RESULT_EXISTS: %s already sealed; a run has exactly one result" % p)
    return p


def run_records(run_dir) -> dict:
    d = _resolved(run_dir)
    out = {}
    for name in (AUTHORITY_FILE, RUN_FILE):
        p = d / name
        if not p.exists():
            raise RealDataRefused("RUN_UNSTAMPED: %s missing" % p)
        out[name] = json.loads(p.read_text())
    return out
