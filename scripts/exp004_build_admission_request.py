"""Build the UNSIGNED EXP-004 admission request from the committed manifest,
dry-validate it against the REAL boundary with a disposable key, and collect
preservation checks.

Wording note: this DOES sign — with a disposable key, to prove the document
parses and binds. What is never signed here is a PRODUCTION admission; the
production signing key is never on this host.

This creates a REQUEST, not a decision. It is unsigned, its decision field is
REQUESTED_NOT_GRANTED, and its provenance names no principal. The throwaway key
exists only to prove the document parses and binds correctly; it is generated
in a temporary directory, and the record reports the OBSERVED post-cleanup
state of that directory rather than asserting the key was destroyed. The
production signing key is never on this host.

Run: python3 scripts/exp004_build_admission_request.py <out_request.json> <out_checks.json>
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from apex.world_model.exp001b.registration import EXPERIMENT_ID as EXP001B_ID
from apex.world_model.exp001b.registration import registration_hash as exp001b_hash
from apex.world_model.exp002.registration import EXPERIMENT_ID as EXP002_ID
from apex.world_model.exp002.registration import registration_hash as exp002_hash
from apex.world_model.exp004.registration import (EXPERIMENT_ID, INSTRUMENT, PERIODS,
                                                  SEALED_NEVER_REQUESTED, registration_hash)
from apex.world_model.real_data import boundary
from apex.world_model.real_data.boundary import RealDataRefused, TrustConfig

PIN = "ea87faa42537a14678bb6fc5cb1e9aacc83cf40f"
MANIFEST = Path("/apex-data/governance/admissions/manifests/etf_continuous_SPY_manifest_v0.json")
DATASET_ROOT = Path("/apex-data/history-b/etf_continuous/bars")
DECISION_PATH = "/etc/apex/admissions/exp004_admission.json"
RESEARCH_ROOT, RUNNER_ROOT, RESEARCH_USER = "/apex-data/research-exp004", "/opt/apex-runner-exp004", "apexresearch4"
EXISTING_DECISIONS = ("exp001b_admission.json", "exp001b_admission_rev2.json", "exp002_admission.json")


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_request(checkout: Path) -> dict:
    ident = boundary.source_identity(checkout)
    if ident["commit"] != PIN:
        raise SystemExit("NOT_AT_PIN: %s != %s" % (ident["commit"], PIN))
    if ident["dirty"]:
        raise SystemExit("DIRTY_CHECKOUT: %s" % ident["dirty"][:5])
    man = json.loads(MANIFEST.read_text())
    files = man["files"]
    dates = sorted(v["session_date"] for v in files.values() if v["symbol"] == INSTRUMENT)
    per_role = {r: sorted(d for d in dates if PERIODS[r][0] <= d <= PERIODS[r][1]) for r in ("fit", "development")}
    return {
        "contract": boundary.REAL_DATA_CONTRACT,
        "decision": "REQUESTED_NOT_GRANTED",
        "NOTE": ("THIS IS A REQUEST, NOT A DECISION. Unsigned; the decision field is not ADMIT and provenance names "
                 "no principal. The identity string is not the boundary: it selects which public key in "
                 "allowed_signers must have signed. The boundary is possession of the private key, held off-host and "
                 "never on the research host, together with protection of allowed_signers."),
        "EXPERIMENT_BINDING": {
            "experiment_id": EXPERIMENT_ID,
            "registration_hash": registration_hash(),
            "registration_frozen": True,
            "executable_entry_point": "scripts/alpha_exp_real_execute.py --experiment ALPHA-EXP-004 --decision <path> --execute",
            "adapter": "apex.world_model.exp004.historical.run -> apex.world_model.exp004.run.tournament",
            "inference_parameters": "NONE accepted: the entry point takes no inference parameters; B=10000 seed=20260909 come from the registration",
            "why_another_admission_cannot_authorise_this": (
                "the boundary checks purpose.experiment_id and purpose.registration_hash against the values the "
                "executing experiment supplies; a mismatch is refused (EXPERIMENT_MISMATCH / REGISTRATION_MISMATCH). "
                "Tested both directions in tests/test_exp004_activation_path.py")},
        "dataset": {"dataset_id": "history-b/etf_continuous", "root": str(DATASET_ROOT),
                    "manifest_path": str(MANIFEST), "manifest_sha256": sha(MANIFEST)},
        "scope": {
            "source_families": ["alpaca_sip_raw_1m"],
            "fields": ["open", "high", "low", "close", "volume", "event_time_utc"],
            "universe": [INSTRUMENT],
            "temporal_range": {
                "start": PERIODS["fit"][0], "end": PERIODS["development"][1],
                "sessions": sum(len(v) for v in per_role.values()),
                "roles": {"fit": list(PERIODS["fit"]), "development_EXPOSED": list(PERIODS["development"])},
                "sessions_by_role": {r: len(v) for r, v in per_role.items()},
                "evaluation_and_reserve": "SEALED; never requested by this experiment"}},
        "availability": man["availability"],
        "code": {"commit": PIN, "source_tree_sha256": ident["tree_sha256"],
                 "bound_files": ident["n_files"], "bound_paths": list(boundary.RELEVANT_SOURCE_PATHS),
                 "launcher_sha256_not_in_bound_tree": sha(checkout / "scripts/research_activation.py"),
                 "execute_script_sha256_bound": sha(checkout / "scripts/alpha_exp_real_execute.py"),
                 "note": ("the launcher is not a bound path; it is pinned by this hash and by invoking it from the "
                          "fresh checkout after checking that hash")},
        "output": {"root": RESEARCH_ROOT + "/out", "authority_classification": "RESEARCH_HISTORICAL"},
        "environment": {"research_root": RESEARCH_ROOT, "runner_root": RUNNER_ROOT,
                        "research_user": RESEARCH_USER,
                        "disjoint_from": ["/apex-data/research + apexresearch (EXP-001B rev1)",
                                          "/apex-data/research-rev2 + apexresearch2 (EXP-001B rev2)",
                                          "/apex-data/research-exp002 + apexresearch3 (EXP-002)"]},
        "DECISION_FILENAME": {"expected_path": DECISION_PATH, "signature_path": DECISION_PATH + ".sig",
                              "distinct_from": list(EXISTING_DECISIONS)},
        "WHAT_A_RESULT_WOULD_BE": (
            "an EXPOSED-DATA CANDIDATE SCREEN on 2019-2021 development data. It grants no sealed access, is not "
            "confirmation, and is not evidence of alpha, options profitability or tradability. Evaluation and "
            "reserve stay closed."),
        "MEMORY_QUALIFICATION": {
            "record": "docs/EXP004_MEMORY_QUALIFICATION.md; results/exp004_memory_adapter_registeredB.json",
            "measured": "737.2 MiB peak of a 1400 MiB cap, 662.8 MiB headroom, zero limit/OOM events, 12 min 4 s",
            "scope": ("synthetic bars, governed_path_exercised: false (ledger_dir None, on-demand loading). The "
                      "governed path at registered scale - admitted loader, import provenance and sealing over 1511 "
                      "sessions - has NEVER been run and its memory and runtime are NOT established")},
        "provenance": {"decided_by": "UNSIGNED_REQUEST_AWAITING_AUTHORITY", "decided_utc": None,
                       "review_reference": "EXP004-ACTIVATION-CANDIDATE"},
        "purpose": {"experiment_id": EXPERIMENT_ID, "registration_hash": registration_hash(),
                    "research_purpose": (
                        "EXP-004: does the clipped signed body-volume feature F~ improve the distributional score of a "
                        "15-minute-ahead SPY log-return forecast after the legacy price features, both ingredients and "
                        "their product are already in the location forecast, holding scale and tail shape fixed? Fit "
                        "once on 2016-2018; score the EXPOSED 2019-2021 development pool under two declared dispersion "
                        "specifications. Distributional only; no economics, no subgroup search, no refits.")},
    }


def dry_validate(req: dict, checkout: Path) -> dict:
    tmp = Path(tempfile.mkdtemp()); os.chmod(tmp, 0o755)
    result: dict = {}
    try:
        key = tmp / "key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key), "-C", "dry"], check=True)
        pub = (key.with_suffix(".pub")).read_text().split()
        signers = tmp / "allowed_signers"
        signers.write_text('dry-validation-throwaway namespaces="apex-admission" %s %s\n' % (pub[0], pub[1]))
        os.chmod(signers, 0o644)
        aroot = tmp / "adm"; aroot.mkdir(); os.chmod(aroot, 0o755)
        d = aroot / "exp004_admission.json"
        body = json.loads(json.dumps(req))
        body["decision"] = "ADMIT"
        body["provenance"] = {"decided_by": "dry-validation-throwaway",
                              "decided_utc": "2026-09-10T07:00:00Z", "review_reference": "DRY"}
        d.write_text(json.dumps(body, indent=1)); os.chmod(d, 0o644)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "apex-admission", str(d)],
                       check=True, capture_output=True)
        os.chmod(d.with_name(d.name + ".sig"), 0o644)
        trust = TrustConfig(admission_root=aroot, allowed_signers=signers, checkout_root=checkout,
                            permitted_roots=("/apex-data/history-b",), enforce_ownership=False)
        out = result
        g = boundary.verify_decision_with(d, trust, experiment_id=EXPERIMENT_ID,
                                          registration_hash=registration_hash())
        out["granted_as_exp004"] = {"experiment": g.experiment_id, "code_commit": g.code_commit,
                                    "manifest_sha256": g.manifest_sha256, "temporal_range": list(g.temporal_range),
                                    "manifest_files": len(g.manifest["files"])}
        for other, h in ((EXP002_ID, exp002_hash), (EXP001B_ID, exp001b_hash)):
            try:
                boundary.verify_decision_with(d, trust, experiment_id=other, registration_hash=h())
                out["refused_as_%s" % other] = "NOT REFUSED - INVESTIGATE"
            except RealDataRefused as e:
                out["refused_as_%s" % other] = str(e)[:90]
        try:
            boundary.verify_decision_with(d, trust, experiment_id=EXPERIMENT_ID, registration_hash=exp002_hash())
            out["wrong_registration"] = "NOT REFUSED - INVESTIGATE"
        except RealDataRefused as e:
            out["wrong_registration"] = str(e)[:90]
        return out
    finally:
        key_paths = [tmp / "key", tmp / "key.pub"]
        shutil.rmtree(tmp, ignore_errors=True)
        # report what is OBSERVED after cleanup, not that cleanup was attempted
        result.update({"temp_dir": str(tmp),
                       "temp_dir_removed_observed": not tmp.exists(),
                       "private_key_absent_observed": not key_paths[0].exists(),
                       "cleanup_note": ("shutil.rmtree(ignore_errors=True) can fail silently; these two fields are "
                                        "post-cleanup existence checks, not an assertion that removal succeeded. "
                                        "The key was generated in a temp directory on this host and never left it; "
                                        "the production signing key was never present.")})


def preservation() -> dict:
    def h(p):
        p = Path(p)
        return sha(p) if p.is_file() else "ABSENT"
    ids = {}
    for u in ("apexresearch", "apexresearch2", "apexresearch3", "apexresearch4"):
        r = subprocess.run(["id", "-u", u], capture_output=True, text=True)
        ids[u] = r.stdout.strip() if r.returncode == 0 else "DOES_NOT_EXIST"
    return {
        "signed_decisions_on_host": {n: h("/etc/apex/admissions/" + n)
                                     for n in (*EXISTING_DECISIONS, "exp004_admission.json")},
        "allowed_signers_sha256": h("/etc/apex/admissions/trust/allowed_signers"),
        "exp001b_rev2_sealed_result": h("/apex-data/research-rev2/out/ALPHA-EXP-001B/runs/"
                                        "20260909T003427Z-exp001b-914a30d3/_RESULT.json"),
        "exp002_sealed_result": h("/apex-data/research-exp002/out/ALPHA-EXP-002/runs/"
                                  "20260909T193814Z-exp002-ca450243/_RESULT.json"),
        "exp001b_aborted_forecasts": h("/apex-data/research/out/ALPHA-EXP-001B/runs/"
                                       "20260908T131351Z-exp001b-2054eaa4/forecasts_validation.jsonl"),
        "accounts": ids,
        "environments_present": sorted(str(p) for p in Path("/apex-data").glob("research*")),
        "runner_roots_present": sorted(str(p) for p in Path("/opt").glob("apex-runner*")),
    }


def main(req_path: str, checks_path: str) -> int:
    checkout = Path(__file__).resolve().parents[1]
    req = build_request(checkout)
    Path(req_path).write_text(json.dumps(req, indent=1, sort_keys=True) + "\n")
    checks = {"pin": PIN, "request_sha256": sha(req_path),
              "dry_validation": dry_validate(req, checkout), "preservation": preservation()}
    Path(checks_path).write_text(json.dumps(checks, indent=1, sort_keys=True) + "\n")
    print(json.dumps(checks, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
