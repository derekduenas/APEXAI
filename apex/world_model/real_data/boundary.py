"""WORLD_MODEL_REAL_DATA_BOUNDARY_V0 -- fail-closed admission of REAL
historical data to a research process, bound to an external decision.

WHAT THIS IS
The laboratory boundary (apex.world_model.sources) answers one question:
"is this file a fixture?" and refuses everything real. This module answers
a different question for a different route: "has THIS dataset, for THIS
purpose, in THIS code, been ADMITTED by someone who is not the caller?"

FOUR DECISIONS THAT ARE KEPT APART
  1. the data are technically readable          (the OS says so)
  2. the data are ASSESSED eligible for a use   (an eligibility document)
  3. that use has been AUTHORIZED               (an admission decision)
  4. an experiment has PASSED                   (its own sealed result)
This module implements (3) and enforces that (1) and (2) never stand in
for it. It has no opinion on (4).

HOW THE CALLER IS PREVENTED FROM ADMITTING ITSELF
An admission decision is a JSON document whose body is committed by a
digest and BOUND by an HMAC under a key the research code never writes.
The document must live under the admission root -- not inside the code
checkout, not inside the output root -- so a caller cannot admit itself by
editing a file it owns. It must name the dataset (by manifest digest), the
permitted families, fields, universe and temporal range, the availability
and corporate-action semantics, the experiment and registration it serves,
the code identity it was decided for, the output root and its authority
classification, and who decided it and when. Any of these absent,
contradictory, or different from what the caller presents is a NAMED
refusal. There is no boolean, no environment variable and no force flag.

HONEST LIMITATION -- STATED, NOT HIDDEN
The binding key is a file readable by the service account, so this is an
AUTHORIZATION-PROVENANCE boundary, not a sandbox against that account. An
actor with the key can forge a decision; an engineering caller reaching for
a convenient file cannot. That is the failure this defends against, and
the limitation is reported as BINDING_SPOOF_RESISTANCE = PARTIAL until the
key is held outside the research host.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REAL_DATA_CONTRACT = "WORLD_MODEL_REAL_DATA_BOUNDARY_V0"
BINDING_SPOOF_RESISTANCE = "PARTIAL"   # key readable by the service account

# ---- the research authority of this route: prohibitions only ------------
REAL_DATA_RESEARCH_AUTHORITY_V0 = {
    "contract": "REAL_DATA_RESEARCH_AUTHORITY_V0",
    "REAL_HISTORICAL_READ": "BY_ADMISSION_DECISION_ONLY",
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

# Roots that hold prospective outcomes, book state, live capture or
# releases. NO admission decision can open these on this route: a decision
# naming one is itself refused.
PROHIBITED_DATASET_ROOTS = (
    "/apex-data/core", "/apex-data/runtime", "/opt/apex-repo/results",
    "/opt/apex/releases", "/apex-research/world-model-fixtures",
)
# Roots that may be named by a decision on this route (historical corpora).
PERMITTED_HISTORICAL_ROOTS = ("/apex-data/history-a", "/apex-data/history-b")

ADMISSION_ROOT = Path("/apex-data/governance/admissions")
ADMISSION_KEY_PATH = Path("/home/apex/.apex-secrets/WM_ADMISSION_KEY")
OUTPUT_AUTHORITY_FILE = "_AUTHORITY.json"

# Availability vocabularies. Anything outside these is refused, not
# defaulted: "unknown" is a named value, not an absence.
AVAILABILITY_KINDS = frozenset({"PER_ROW", "PER_FILE", "BULK", "NOT_AVAILABLE"})
CORPORATE_ACTION_TREATMENTS = frozenset({
    "RAW_UNADJUSTED_EXPLICIT", "ADJUSTED_DECLARED", "NOT_APPLICABLE"})
AUTHORITY_CLASSIFICATIONS = frozenset({"RESEARCH_HISTORICAL"})
ISO_DATE = "%Y-%m-%d"

REQUIRED_BODY = {
    "contract": None, "decision": None,
    "dataset": ("dataset_id", "root", "manifest_path", "manifest_sha256"),
    "scope": ("source_families", "fields", "universe", "temporal_range"),
    "availability": ("event_time", "receipt_time", "publication_time",
                     "revision_time", "corporate_actions", "restricted_use"),
    "purpose": ("research_purpose", "experiment_id", "registration_hash"),
    "code": ("commit",),
    "output": ("root", "authority_classification"),
    "provenance": ("decided_by", "decided_utc", "review_reference"),
}


class RealDataRefused(Exception):
    """Refused on this route. No override exists."""


@dataclass(frozen=True)
class Grant:
    """What a verified decision permits. Immutable; carries its own digest so
    every output can cite the decision it ran under."""
    contract: str
    decision_path: str
    decision_digest: str
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
    output_root: str
    authority_classification: str
    provenance: dict
    authority: dict = field(default_factory=lambda: dict(REAL_DATA_RESEARCH_AUTHORITY_V0))


# ---------------------------------------------------------------- helpers
def _resolved(p) -> Path:
    return Path(p).expanduser().resolve(strict=False)


def _under(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def body_digest(body: dict) -> str:
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def binding_for(body: dict, key: bytes) -> dict:
    d = body_digest(body)
    return {"body_sha256": d,
            "hmac_sha256": hmac.new(key, d.encode(), hashlib.sha256).hexdigest()}


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def checkout_root() -> Path:
    """The checkout THIS module was imported from -- not the cwd."""
    return Path(__file__).resolve().parents[3]


def checkout_commit(root: Path | None = None) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root or checkout_root()), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _date(s: str, what: str) -> datetime:
    try:
        return datetime.strptime(s, ISO_DATE).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise RealDataRefused("MALFORMED_DATE: %s=%r (want YYYY-MM-DD)" % (what, s))


def _check_availability(av: dict) -> None:
    """Refuse unknown or contradictory availability metadata. NOT_AVAILABLE
    is a legal, named value; an unrecognised word is not."""
    for k in ("event_time", "receipt_time", "publication_time", "revision_time"):
        v = av.get(k)
        kind = v.get("kind") if isinstance(v, dict) else None
        if kind not in AVAILABILITY_KINDS:
            raise RealDataRefused(
                "AVAILABILITY_INVALID: %s.kind=%r not in %s"
                % (k, kind, sorted(AVAILABILITY_KINDS)))
    if av["event_time"]["kind"] == "NOT_AVAILABLE":
        raise RealDataRefused("AVAILABILITY_INVALID: event_time cannot be NOT_AVAILABLE "
                              "-- a row without an event time has no place on a timeline")
    rc = av["receipt_time"]
    if rc["kind"] == "BULK":
        at = rc.get("at")
        if not at:
            raise RealDataRefused("AVAILABILITY_INVALID: BULK receipt needs 'at'")
        ev_end = av["event_time"].get("latest")
        if ev_end and _date(str(at)[:10], "receipt_time.at") < _date(ev_end, "event_time.latest"):
            raise RealDataRefused(
                "AVAILABILITY_INVALID: receipt %s precedes the latest event %s -- "
                "contradictory; refused rather than reinterpreted" % (at, ev_end))
    if av.get("corporate_actions") not in CORPORATE_ACTION_TREATMENTS:
        raise RealDataRefused(
            "AVAILABILITY_INVALID: corporate_actions=%r not in %s"
            % (av.get("corporate_actions"), sorted(CORPORATE_ACTION_TREATMENTS)))
    # publication/revision unknown => the decision MUST name the restriction.
    if (av["publication_time"]["kind"] == "NOT_AVAILABLE"
            or av["revision_time"]["kind"] == "NOT_AVAILABLE"):
        ru = av.get("restricted_use")
        if not isinstance(ru, str) or not ru.strip():
            raise RealDataRefused(
                "AVAILABILITY_INVALID: publication or revision time NOT_AVAILABLE "
                "requires a named restricted_use; silent acceptance is refused")


# ------------------------------------------------------------ verification
def verify_decision(decision_path, *, key_path=None, admission_root=None,
                    permitted_roots=None, code_commit=None,
                    experiment_id=None, registration_hash=None) -> Grant:
    """Verify an admission decision and return the Grant it confers.

    Keyword overrides exist so tests can use disposable roots and keys; a
    production caller passes none of them. Every override narrows or
    relocates -- none of them can turn a refusal into an admission.
    """
    aroot = _resolved(admission_root or ADMISSION_ROOT)
    kpath = _resolved(key_path or ADMISSION_KEY_PATH)
    proots = tuple(_resolved(r) for r in (permitted_roots or PERMITTED_HISTORICAL_ROOTS))
    croot = checkout_root()

    if decision_path is None:
        raise RealDataRefused("NO_DECISION: no admission decision was supplied; "
                              "real historical data are not readable on this route "
                              "without one")
    dp = _resolved(decision_path)
    if not dp.exists():
        raise RealDataRefused("NO_DECISION: %s does not exist" % dp)
    if not _under(dp, aroot):
        raise RealDataRefused("DECISION_OUTSIDE_ADMISSION_ROOT: %s is not under %s" % (dp, aroot))
    if _under(dp, croot):
        raise RealDataRefused("DECISION_INSIDE_CHECKOUT: %s lives in the code checkout %s; "
                              "a caller may not admit itself" % (dp, croot))
    try:
        doc = json.loads(dp.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RealDataRefused("DECISION_UNREADABLE: %s" % e) from e
    if not isinstance(doc, dict):
        raise RealDataRefused("DECISION_UNREADABLE: not a mapping")

    # ---- shape --------------------------------------------------------
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
        raise RealDataRefused("DECISION_NOT_ADMIT: decision=%r. A proposal, an eligibility "
                              "assessment or a refusal admits nothing" % (doc["decision"],))

    # ---- binding: digest + HMAC under the external key ---------------
    binding = doc.get("binding")
    if not isinstance(binding, dict) or not binding.get("hmac_sha256"):
        raise RealDataRefused("UNBOUND_DECISION: no binding block; an unbound document is "
                              "a draft, not an admission")
    body = {k: v for k, v in doc.items() if k != "binding"}
    if body_digest(body) != binding.get("body_sha256"):
        raise RealDataRefused("BODY_DIGEST_MISMATCH: the decision body changed after it was "
                              "committed")
    if not kpath.exists():
        raise RealDataRefused("NO_ADMISSION_KEY: %s absent; the binding cannot be verified, "
                              "so nothing is admitted" % kpath)
    key = kpath.read_bytes().strip()
    if len(key) < 16:
        raise RealDataRefused("ADMISSION_KEY_INVALID: key shorter than 16 bytes")
    if not hmac.compare_digest(binding_for(body, key)["hmac_sha256"], binding["hmac_sha256"]):
        raise RealDataRefused("BINDING_MISMATCH: the decision is not bound under the admission "
                              "key; it was not issued by the admission authority, or was edited")

    # ---- provenance: who decided must not be the caller --------------
    prov = doc["provenance"]
    if str(prov.get("decided_by", "")).strip().upper() in ("", "CALLER", "ENGINEERING", "SELF"):
        raise RealDataRefused("DECISION_PROVENANCE_INVALID: decided_by=%r" % (prov.get("decided_by"),))
    try:
        datetime.fromisoformat(str(prov["decided_utc"]).replace("Z", "+00:00"))
    except ValueError:
        raise RealDataRefused("DECISION_PROVENANCE_INVALID: decided_utc=%r" % (prov["decided_utc"],))

    # ---- dataset: root and manifest commitment -----------------------
    ds = doc["dataset"]
    droot = _resolved(ds["root"])
    for pr in PROHIBITED_DATASET_ROOTS:
        if _under(droot, _resolved(pr)):
            raise RealDataRefused("PROHIBITED_DATASET_ROOT: %s is under %s, which holds "
                                  "prospective outcomes, book state, live capture, releases or "
                                  "laboratory fixtures. No decision opens it on this route"
                                  % (droot, pr))
    if not any(_under(droot, pr) for pr in proots):
        raise RealDataRefused("DATASET_ROOT_NOT_PERMITTED: %s is not under any permitted "
                              "historical root %s" % (droot, [str(p) for p in proots]))
    mpath = _resolved(ds["manifest_path"])
    if not mpath.exists():
        raise RealDataRefused("MANIFEST_MISSING: %s" % mpath)
    actual = sha256_of(mpath)
    if actual != ds["manifest_sha256"]:
        raise RealDataRefused("MANIFEST_HASH_MISMATCH: decision commits to %s but the manifest "
                              "is %s -- the dataset description changed after admission"
                              % (str(ds["manifest_sha256"])[:16], actual[:16]))
    try:
        manifest = json.loads(mpath.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RealDataRefused("MANIFEST_UNREADABLE: %s" % e) from e
    if manifest.get("dataset_id") != ds["dataset_id"]:
        raise RealDataRefused("DATASET_MISMATCH: decision names %r, manifest is %r"
                              % (ds["dataset_id"], manifest.get("dataset_id")))
    if _resolved(manifest.get("root", "")) != droot:
        raise RealDataRefused("DATASET_MISMATCH: manifest root %r != decision root %s"
                              % (manifest.get("root"), droot))
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
    t0, t1 = _date(tr["start"], "temporal_range.start"), _date(tr["end"], "temporal_range.end")
    if t1 < t0:
        raise RealDataRefused("SCOPE_INVALID: temporal_range end precedes start")
    mfam = set(manifest.get("source_families") or [])
    if mfam and not set(sc["source_families"]) <= mfam:
        raise RealDataRefused("SCOPE_INVALID: source_families %s not all present in manifest %s"
                              % (sc["source_families"], sorted(mfam)))

    # ---- availability ---------------------------------------------------
    av = doc["availability"]
    _check_availability(av)
    mav = manifest.get("availability")
    if isinstance(mav, dict):
        for k in ("event_time", "receipt_time", "publication_time", "revision_time"):
            if mav.get(k, {}).get("kind") != av[k]["kind"]:
                raise RealDataRefused("AVAILABILITY_INVALID: decision says %s=%s but the manifest "
                                      "says %s -- contradictory"
                                      % (k, av[k]["kind"], mav.get(k, {}).get("kind")))
        if mav.get("corporate_actions") != av["corporate_actions"]:
            raise RealDataRefused("AVAILABILITY_INVALID: corporate_actions differ between decision "
                                  "(%s) and manifest (%s)"
                                  % (av["corporate_actions"], mav.get("corporate_actions")))

    # ---- purpose and code identity -------------------------------------
    pu = doc["purpose"]
    if experiment_id is not None and pu["experiment_id"] != experiment_id:
        raise RealDataRefused("EXPERIMENT_MISMATCH: decision serves %r, caller is %r"
                              % (pu["experiment_id"], experiment_id))
    if registration_hash is not None and pu["registration_hash"] != registration_hash:
        raise RealDataRefused("REGISTRATION_MISMATCH: decision was made for registration %s, "
                              "caller runs %s" % (str(pu["registration_hash"])[:16],
                                                  str(registration_hash)[:16]))
    have = code_commit or checkout_commit(croot)
    if have is None:
        raise RealDataRefused("CODE_IDENTITY_UNKNOWN: the checkout commit could not be "
                              "determined; refused rather than assumed")
    if doc["code"]["commit"] != have:
        raise RealDataRefused("CODE_IDENTITY_MISMATCH: decision was made for %s, running %s"
                              % (str(doc["code"]["commit"])[:12], have[:12]))

    # ---- output --------------------------------------------------------
    out = doc["output"]
    oroot = _resolved(out["root"])
    if out["authority_classification"] not in AUTHORITY_CLASSIFICATIONS:
        raise RealDataRefused("OUTPUT_AUTHORITY_INVALID: %r not in %s"
                              % (out["authority_classification"], sorted(AUTHORITY_CLASSIFICATIONS)))
    for pr in PROHIBITED_DATASET_ROOTS + PERMITTED_HISTORICAL_ROOTS:
        if _under(oroot, _resolved(pr)):
            raise RealDataRefused("OUTPUT_ROOT_INVALID: %s is under %s; research outputs may "
                                  "not be written into evidence, book, release or corpus roots"
                                  % (oroot, pr))
    if _under(oroot, croot):
        raise RealDataRefused("OUTPUT_ROOT_INVALID: %s is inside the checkout" % oroot)
    if _under(dp, oroot):
        raise RealDataRefused("DECISION_INSIDE_OUTPUT_ROOT: the decision may not live where "
                              "the research writes")

    return Grant(
        contract=REAL_DATA_CONTRACT, decision_path=str(dp),
        decision_digest=binding["body_sha256"],
        dataset_id=ds["dataset_id"], dataset_root=str(droot),
        manifest=manifest, manifest_sha256=actual,
        source_families=tuple(sc["source_families"]), fields=tuple(sc["fields"]),
        universe=tuple(sc["universe"]),
        temporal_range=(tr["start"], tr["end"]), availability=dict(av),
        experiment_id=pu["experiment_id"], registration_hash=pu["registration_hash"],
        code_commit=have, output_root=str(oroot),
        authority_classification=out["authority_classification"],
        provenance=dict(prov))


# ------------------------------------------------------------------ reads
def open_file(grant: Grant, path, *, symbol: str, session_date: str,
              fields: tuple | list | None = None) -> dict:
    """Open ONE committed file under the grant. Returns the raw bytes and an
    admission record; the caller parses. Every check is by the artifact."""
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
        raise RealDataRefused("SYMBOL_MISMATCH: manifest says %r for %s, caller says %r"
                              % (rec.get("symbol"), key, symbol))
    d = _date(session_date, "session_date")
    lo, hi = (_date(x, "temporal_range") for x in grant.temporal_range)
    if not (lo <= d <= hi):
        raise RealDataRefused("OUTSIDE_TEMPORAL_SCOPE: %s is outside %s..%s"
                              % (session_date, *grant.temporal_range))
    if rec.get("session_date") not in (None, session_date):
        raise RealDataRefused("DATE_MISMATCH: manifest says %r for %s, caller says %r"
                              % (rec.get("session_date"), key, session_date))
    want = tuple(fields or grant.fields)
    extra = [f for f in want if f not in grant.fields]
    if extra:
        raise RealDataRefused("FIELD_NOT_PERMITTED: %s not in admitted fields %s"
                              % (extra, list(grant.fields)))
    if not rp.exists():
        raise RealDataRefused("MISSING_SOURCE: %s" % rp)
    raw = rp.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != rec.get("sha256"):
        raise RealDataRefused("CONTENT_CHANGED: %s committed as %s, now %s"
                              % (key, str(rec.get("sha256"))[:16], actual[:16]))
    return {"contract": REAL_DATA_CONTRACT, "path": str(rp), "sha256": actual,
            "fields": want, "symbol": symbol, "session_date": session_date,
            "decision_digest": grant.decision_digest, "dataset_id": grant.dataset_id,
            "availability": grant.availability,
            "restricted_use": grant.availability.get("restricted_use"),
            "raw": raw}


def open_output(grant: Grant, name: str) -> Path:
    """Create (or reuse) an output directory under the grant's output root,
    stamped with the authority classification. Outputs written here carry
    NO order, trading, capital, live-decision or promotion authority."""
    oroot = _resolved(grant.output_root)
    if "/" in name or name in ("", ".", ".."):
        raise RealDataRefused("OUTPUT_NAME_INVALID: %r" % name)
    out = oroot / name
    out.mkdir(parents=True, exist_ok=True)
    stamp = {"contract": REAL_DATA_CONTRACT,
             "authority_classification": grant.authority_classification,
             "authority": dict(REAL_DATA_RESEARCH_AUTHORITY_V0),
             "decision_digest": grant.decision_digest, "decision_path": grant.decision_path,
             "dataset_id": grant.dataset_id, "manifest_sha256": grant.manifest_sha256,
             "experiment_id": grant.experiment_id, "registration_hash": grant.registration_hash,
             "code_commit": grant.code_commit,
             "binding_spoof_resistance": BINDING_SPOOF_RESISTANCE,
             "law": "outputs here are RESEARCH_HISTORICAL; nothing downstream may treat them "
                    "as a live decision, a broker instruction or a promotion"}
    (out / OUTPUT_AUTHORITY_FILE).write_text(json.dumps(stamp, indent=1, sort_keys=True))
    return out


def output_authority(path) -> dict:
    """Read the stamp of an output directory. Absent stamp = no authority
    classification = the outputs are not research outputs of this route."""
    p = _resolved(path) / OUTPUT_AUTHORITY_FILE
    if not p.exists():
        raise RealDataRefused("OUTPUT_UNSTAMPED: %s" % p)
    return json.loads(p.read_text())


def _default_key_present() -> bool:
    return os.path.exists(ADMISSION_KEY_PATH)
