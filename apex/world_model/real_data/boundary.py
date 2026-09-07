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

WHAT CHANGED IN THE CLOSURE PASS (reviewer findings, 28153e1a)
  * Trust is checked along the WHOLE ANCESTOR CHAIN, not just the leaf. A
    root-owned admissions/ directory inside a research-owned parent can be
    renamed away and replaced; leaf ownership establishes nothing. Every
    component from / down must be non-research-owned and not
    group/other-writable (sticky world-writable dirs like /tmp are the one
    exception: sticky forbids renaming another owner's entry).
  * The signature verifier is resolved through an ABSOLUTE, root-owned
    executable whose own ancestor chain is root-owned, and is run with a
    controlled environment -- never through PATH.
  * Imported apex modules are verified BYTE-FOR-BYTE against the admitted
    commit, and source identity is recomputed at completion.

WHAT THIS DOES NOT PROTECT AGAINST -- STATED
Arbitrary privileged code, and any account that can become root. On a host
where the research account holds sudo, NOTHING here is a boundary against
that account: the operator must run research as an account that cannot
become root and cannot write any component of the trust chain. The verifier
checks what it can (ownership, mode, ancestry, executable provenance) and
refuses otherwise; it cannot check what it cannot see.
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
# A shared or deployed checkout is never a research execution checkout: other
# processes write it, so its content cannot be bound for the length of a run.
FORBIDDEN_CHECKOUT_ROOTS = ("/opt/apex-repo", "/opt/apex/current", "/opt/apex/releases")
TRUSTED_SSH_KEYGEN = "/usr/bin/ssh-keygen"
# Environment handed to the verifier subprocess. Nothing is inherited.
VERIFIER_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "IFS": " \t\n"}

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
    ssh_keygen: str = TRUSTED_SSH_KEYGEN
    relevant_source_paths: tuple = RELEVANT_SOURCE_PATHS
    forbidden_checkout_roots: tuple = FORBIDDEN_CHECKOUT_ROOTS


# The admission root and trust file must sit on an ancestor chain the research
# account cannot touch. /apex-data is owned by that account, so ANY directory
# beneath it can be renamed away and replaced -- measured on the host in
# results/si002_trust_path_audit.json. /etc is root-owned and is not.
# The dataset MANIFEST deliberately stays outside this chain: the signed
# decision commits to its sha256, so a swapped manifest is refused by content
# and it needs no trusted location.
PRODUCTION_ADMISSION_ROOT = Path("/etc/apex/admissions")
PRODUCTION_ALLOWED_SIGNERS = Path("/etc/apex/admissions/trust/allowed_signers")


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
    trust_chain: dict = field(default_factory=dict)
    verifier: str = ""
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


def verify_imports_against_commit(commit: str, root: Path,
                                  paths: tuple = RELEVANT_SOURCE_PATHS) -> dict:
    """Prove that the apex modules ACTUALLY IMPORTED are the admitted bytes.

    Recording a module's path establishes nothing: a path can hold anything.
    So every loaded apex.* module is hashed and compared with the blob at the
    admitted commit, and modules outside the bound source set are listed as
    execution dependencies the decision does not cover."""
    root = _resolved(root)
    bound_prefixes = tuple(paths)
    out = {"commit": commit, "checkout_root": str(root), "n_modules": 0, "verified": [],
           "mismatched": [], "outside_checkout": [], "untracked_at_commit": [],
           "unbound_dependencies": []}
    for name, mod in sorted(sys.modules.items()):
        if not name.startswith("apex.") and name != "apex":
            continue
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        p = _resolved(f)
        out["n_modules"] += 1
        if not _under(p, root):
            out["outside_checkout"].append({"module": name, "path": str(p)})
            continue
        rel = str(p.relative_to(root))
        r = subprocess.run(["git", "-C", str(root), "show", "%s:%s" % (commit, rel)],
                           capture_output=True, timeout=60)
        if r.returncode != 0:
            out["untracked_at_commit"].append({"module": name, "path": rel})
            continue
        blob = hashlib.sha256(r.stdout).hexdigest()
        disk = sha256_of(p)
        rec = {"module": name, "path": rel, "sha256": disk}
        if blob != disk:
            rec["commit_sha256"] = blob
            out["mismatched"].append(rec)
        else:
            out["verified"].append(rec)
        if not any(rel == b or rel.startswith(b.rstrip("/") + "/") for b in bound_prefixes):
            out["unbound_dependencies"].append(rel)
    out["all_imports_match_admitted_commit"] = not (out["mismatched"] or out["outside_checkout"]
                                                    or out["untracked_at_commit"])
    return out


def recheck_source_identity(grant: "Grant", trust: TrustConfig | None = None) -> dict:
    """Recompute source identity at COMPLETION and compare with the admitted
    identity. A run whose relevant source moved under it is not acceptable
    evidence, however it ended."""
    t = trust or production_trust()
    now = source_identity(_resolved(t.checkout_root), t.relevant_source_paths)
    same = (now["commit"] == grant.code_commit
            and now["tree_sha256"] == grant.source_identity["tree_sha256"]
            and not now["dirty"])
    return {"admitted": {k: grant.source_identity[k] for k in ("commit", "tree_sha256")},
            "at_completion": {k: now[k] for k in ("commit", "tree_sha256", "dirty")},
            "unchanged": same,
            "acceptance_qualification": "VALID" if same else "INVALID_SOURCE_CHANGED_DURING_RUN"}


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


def ancestors(p: Path) -> list:
    """Every path component from the filesystem root down to p, resolved."""
    rp = _resolved(p)
    return list(reversed([rp] + list(rp.parents)))


def path_facts(p) -> dict:
    """Ownership, mode, sticky bit and research-writability of one component."""
    st = os.stat(p)
    mode = stat.S_IMODE(st.st_mode)
    return {"path": str(p), "uid": st.st_uid, "gid": st.st_gid, "mode": "%o" % mode,
            "sticky": bool(st.st_mode & stat.S_ISVTX), "dir": stat.S_ISDIR(st.st_mode),
            "group_or_other_writable": bool(mode & (stat.S_IWGRP | stat.S_IWOTH)),
            "owned_by_euid": st.st_uid == os.geteuid()}


def _check_ancestor_chain(p: Path, trust: TrustConfig, what: str) -> list:
    """Refuse unless EVERY component from / down to p is beyond the research
    account's reach.

    Leaf ownership proves nothing: a root-owned directory inside a
    research-owned parent can be renamed away and replaced with an
    attacker-controlled one. So the whole chain is checked.

    A group/other-writable DIRECTORY is refused unless it carries the sticky
    bit, which forbids renaming or deleting entries owned by others (this is
    what makes /tmp usable as a chain component)."""
    facts = []
    try:
        chain = ancestors(p)
        for c in chain:
            facts.append(path_facts(c))
    except OSError as e:
        raise RealDataRefused("TRUST_PATH_MISSING: %s %s: %s" % (what, p, e)) from e
    for f in facts:
        c = f["path"]
        if f["group_or_other_writable"] and not (f["dir"] and f["sticky"]):
            raise RealDataRefused(
                "TRUST_PATH_WRITABLE: %s -- component %s is group/other-writable (mode %s) "
                "without the sticky bit; anything under it can be replaced" % (what, c, f["mode"]))
        if trust.enforce_ownership and f["owned_by_euid"] and not (f["dir"] and f["sticky"]):
            raise RealDataRefused(
                "TRUST_PATH_OWNED_BY_RESEARCH: %s -- component %s is owned by uid %d, the account "
                "running research; that account can rename or replace it, so nothing beneath it is "
                "trusted. Issuance and verification must not share an owner ANYWHERE on the chain."
                % (what, c, f["uid"]))
    return facts


def trusted_executable(trust: TrustConfig) -> str:
    """Resolve the signature verifier through a trusted absolute location.

    PATH is never consulted: a PATH lookup is a lookup in directories the
    caller can influence. The executable and every component above it must
    be root-owned and not group/other-writable."""
    exe = trust.ssh_keygen
    if not os.path.isabs(exe):
        raise RealDataRefused("VERIFIER_NOT_ABSOLUTE: %r would be resolved through PATH; the "
                              "signature verifier must be an absolute trusted path" % exe)
    rp = _resolved(exe)
    try:
        facts = [path_facts(c) for c in ancestors(rp)]
    except OSError as e:
        raise RealDataRefused("VERIFIER_MISSING: %s: %s" % (rp, e)) from e
    if facts[-1]["dir"] or not os.access(rp, os.X_OK):
        raise RealDataRefused("VERIFIER_NOT_EXECUTABLE: %s" % rp)
    for f in facts:
        if f["uid"] != 0:
            raise RealDataRefused("VERIFIER_NOT_ROOT_OWNED: component %s is owned by uid %d; the "
                                  "verifier and its whole path must be root-owned"
                                  % (f["path"], f["uid"]))
        if f["group_or_other_writable"] and not (f["dir"] and f["sticky"]):
            raise RealDataRefused("VERIFIER_PATH_WRITABLE: component %s is group/other-writable "
                                  "(mode %s)" % (f["path"], f["mode"]))
    return str(rp)


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
    _check_ancestor_chain(sig, trust, "signature")
    if not principal or not isinstance(principal, str):
        raise RealDataRefused("DECISION_PROVENANCE_INVALID: decided_by is empty; the signer principal is unknown")
    exe = trusted_executable(trust)
    try:
        with open(decision, "rb") as fh:
            r = subprocess.run([exe, "-Y", "verify", "-f", str(trust.allowed_signers),
                                "-I", principal, "-n", trust.namespace, "-s", str(sig)],
                               stdin=fh, capture_output=True, text=True, timeout=60,
                               env=dict(VERIFIER_ENV), cwd="/")
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
    trust_facts = {}
    for p, what in ((aroot, "admission_root"), (_resolved(trust.allowed_signers), "allowed_signers"),
                    (dp, "decision")):
        trust_facts[what] = _check_ancestor_chain(p, trust, what)
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
    for pr in trust.forbidden_checkout_roots:
        rp = _resolved(pr)
        if croot == rp or rp in croot.parents:
            raise RealDataRefused(
                "SHARED_CHECKOUT: research may not execute from %s (under %s). A shared or deployed "
                "checkout is written by other processes, so its content cannot be bound for the "
                "length of a run; use a dedicated checkout." % (croot, rp))
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
                 authority_classification=out["authority_classification"], provenance=dict(prov),
                 trust_chain=trust_facts, verifier=trusted_executable(trust))


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


def open_run(grant: Grant, *, label: str = "run", extra: dict | None = None) -> Path:
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
        "signature_mechanism": SIGNATURE_MECHANISM, "verifier": grant.verifier,
        "trust_chain": grant.trust_chain, **(extra or {})})
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
