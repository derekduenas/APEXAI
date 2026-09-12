"""R4 dataset-and-role permissions (contract §1.3). NOTHING is inherited from a prior experiment's admission.

Every read of a dataset goes through `require_read`, which refuses unless (a) the dataset is registered, (b) the
role permits the use, and (c) an explicit R4 authorization artefact for that use has been presented. Role approval
is NOT run authorization: a fitting RUN additionally needs its own artefact naming the session range, the fit
cutoff and the evaluation population."""
from __future__ import annotations

from dataclasses import dataclass, field

CONTRACT_PIN = "a0228fac4a2dab4c455c9fc8a41d1378522a27de"        # docs/R4_JOINT_MARKET_STATE_SPEC.md blob


class PermissionRefused(PermissionError):
    pass


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    path: str
    role: str
    permitted_uses: tuple
    authorization_required: str | None          # None = no artefact can authorize it in this brick


REGISTRY = {d.dataset_id: d for d in (
    Dataset("HIST-A-OPTIONS/2016-2019", "/apex-data/history-a/options_history", "TRAIN", ("FIT", "REPLAY"), "R4-FIT-001"),
    Dataset("HIST-A-OPTIONS/2020-2021", "/apex-data/history-a/options_history", "VALIDATION", ("REPLAY", "FIT"), "R4-FIT-001"),
    Dataset("HIST-A-OPTIONS/2022-2024", "/apex-data/history-a/options_history", "EVALUATION_SEALED", (), None),
    Dataset("HIST-A-OPTIONS/2025-2026-08-28", "/apex-data/history-a/options_history", "RESERVE_SEALED", (), None),
    Dataset("PILOT-COLLECTION", "/apex-data/pilot_collection/", "PROSPECTIVE_OBSERVATION", ("FIT", "CALIBRATION_REPORT"), "R4-FIT-002"),
    Dataset("PILOT-LEDGER", "/apex-data/core", "PROSPECTIVE_DECISION", ("OUTCOME_EVIDENCE",), None),
    Dataset("SYNTHETIC-FIXTURE", "<in-process>", "SYNTHETIC", ("FIT", "REPLAY", "CALIBRATION_REPORT", "OUTCOME_EVIDENCE"), None),
)}


@dataclass(frozen=True)
class Authorization:
    """An R4 authorization artefact. A FIT use also requires the run fields (§1.3 item 1)."""
    artefact_id: str
    dataset_id: str
    use: str
    session_range: tuple | None = None
    fit_cutoff: float | None = None
    evaluation_population: str | None = None
    granted_by: str = "OPERATOR"
    notes: str = ""

    def problem(self, *, dataset_id: str, use: str) -> str | None:
        if self.dataset_id != dataset_id:
            return "AUTHORIZATION_DATASET_MISMATCH: artefact names %r, read is %r" % (self.dataset_id, dataset_id)
        if self.use != use:
            return "AUTHORIZATION_USE_MISMATCH: artefact permits %r, read is %r" % (self.use, use)
        if use == "FIT" and not (self.session_range and self.fit_cutoff is not None and self.evaluation_population):
            return "AUTHORIZATION_RUN_FIELDS_MISSING: a FIT run needs session_range, fit_cutoff and evaluation_population"
        return None


def require_read(dataset_id: str, use: str, *, authorization: Authorization | None = None) -> dict:
    """Returns the permission record to persist, or raises PermissionRefused. SYNTHETIC needs no artefact."""
    ds = REGISTRY.get(dataset_id)
    if ds is None:
        raise PermissionRefused("DATASET_NOT_REGISTERED: %r" % (dataset_id,))
    if use not in ds.permitted_uses:
        raise PermissionRefused("ROLE_FORBIDS_USE: dataset %s role %s permits %s, requested %r"
                                % (ds.dataset_id, ds.role, list(ds.permitted_uses) or "nothing", use))
    if ds.role == "SYNTHETIC":
        return {"dataset_id": ds.dataset_id, "role": ds.role, "use": use, "authorization": "NOT_REQUIRED_FOR_SYNTHETIC",
                "contract_pin": CONTRACT_PIN}
    if ds.authorization_required is None:
        raise PermissionRefused("NO_AUTHORIZATION_OBTAINABLE: dataset %s role %s" % (ds.dataset_id, ds.role))
    if authorization is None:
        raise PermissionRefused("AUTHORIZATION_REQUIRED: %s for %s/%s (role approval is not run authorization)"
                                % (ds.authorization_required, ds.dataset_id, use))
    if authorization.artefact_id != ds.authorization_required:
        raise PermissionRefused("AUTHORIZATION_ARTEFACT_MISMATCH: need %s, got %s"
                                % (ds.authorization_required, authorization.artefact_id))
    problem = authorization.problem(dataset_id=dataset_id, use=use)
    if problem:
        raise PermissionRefused(problem)
    return {"dataset_id": ds.dataset_id, "role": ds.role, "use": use, "authorization": authorization.artefact_id,
            "session_range": authorization.session_range, "fit_cutoff": authorization.fit_cutoff,
            "evaluation_population": authorization.evaluation_population, "contract_pin": CONTRACT_PIN,
            "inheritance": "NONE: no prior experiment's admission authorizes an R4 read"}


def walk_forward_problem(*, decision_epoch: float, fit_cutoff: float, session_start_epoch: float,
                         training_row_ids: set, evaluation_row_ids: set) -> str | None:
    """Contract §1.6. Returns the refusal reason or None."""
    if not fit_cutoff < session_start_epoch:
        return "FIT_CUTOFF_NOT_BEFORE_SESSION: cutoff %.3f, session start %.3f" % (fit_cutoff, session_start_epoch)
    if decision_epoch < session_start_epoch:
        return "DECISION_BEFORE_SESSION_START"
    overlap = sorted(set(training_row_ids) & set(evaluation_row_ids))
    if overlap:
        return "FIT_EVAL_OVERLAP: %d row(s), first %r" % (len(overlap), overlap[:3])
    return None
