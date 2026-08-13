"""Cross-experiment research governance -- directive sections 4 and 5.

APEX has finite statistical credibility. It may generate unlimited ideas during
exploration; it has a fixed budget for confirmation. This module is the accountant.

WHAT IT ENFORCES

  BUDGET          Five lifetime evaluations against the locked holdout (user
                  ruling, 2026-08-09, superseding protocol section 7's
                  one-evaluation-ever). The sixth is refused.

  NO RE-LOOKS     The same experiment cannot evaluate the same period twice. A
                  modified specification is a NEW experiment with a NEW id and
                  costs another credit -- protocol section 10, the rule most
                  likely to be violated.

  TAMPER EVIDENCE Every entry chains to its predecessor by SHA-256. Editing or
                  deleting a line -- most temptingly, a failed experiment --
                  breaks the chain and is detected. Directive section 34.12: no
                  hiding failed experiments.

  WRITE-ONCE      A recorded result cannot be overwritten. Directive section
                  34.14.

MULTIPLICITY, AND WHY THERE ARE TWO CORRECTIONS

  `sequential_alpha` is Bonferroni over the WHOLE committed budget: family_alpha
  divided by the budget, not by the credits spent so far. It is valid before any
  later p-value exists, which is the only moment at which an authorisation can
  actually be made. It never loosens as credits are spent -- a budget that got
  easier to clear the more of it you used would be no budget at all.

  `holm` is the step-down Holm procedure over the completed family. It is
  uniformly more powerful than Bonferroni, but it needs every p-value, so it can
  only ever be a retrospective review. It never authorises anything.

THE COLLISION WITH THE HAC FINDING

  Protocol section 10 pre-registers t >= 2.5. Its MEASURED one-sided size under
  the pre-registered Bartlett-25 estimator is ~1.9% (see apex/evaluate/reference),
  not the 0.621% a nominal reading implies. Bonferroni over five credits at
  family-wise 5% demands 1.0% per test. Since 1.9% > 1.0%, a result landing
  exactly on the pre-registered hurdle would satisfy section 10 and still fail
  family-wise control.

  `required_tstat` computes the threshold that WOULD control the family. It is
  REPORTED alongside every holdout result. It is deliberately not enforced:
  section 10 is pre-registered, and retightening a promotion criterion after the
  fact is the same category of error as loosening one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.dev.namespace import require_confirmatory

GENESIS = "0" * 64
SPEND = "spend"
RESULT = "result"
# INCIDENT-001, 2026-08-12. An execution that failed BEFORE recording a result
# produced no experimental observation, but it left a spend behind, and the
# no-second-look guard keys on the spend. Deleting that spend was considered
# and rejected: it is precisely the operation the hash chain and the external
# anchor exist to detect, and it would have erased the incident from the only
# tamper-evident record of it. An annulment is APPENDED instead. Nothing is
# removed, the chain is unbroken, and the failure stays permanently visible.
ANNULMENT = "annulment"

# Only these periods draw on the research budget. In-sample exists to verify the
# pipeline; charging it would make pipeline debugging cost statistical credibility.
BUDGETED_PERIODS = ("validation", "holdout")


class LedgerError(RuntimeError):
    """The ledger refused an operation."""


class BudgetExhausted(LedgerError):
    """No research credits remain."""


class LedgerTampered(LedgerError):
    """The hash chain does not verify: an entry was edited or removed."""


class AlreadyEvaluated(LedgerError):
    """This experiment has already been evaluated against this period."""


class ValidationNotPassed(LedgerError):
    """The holdout was addressed before this experiment passed validation."""


class MissingDatasetFingerprint(LedgerError):
    """An evaluation was recorded without identifying the data it ran on."""


def _require_dataset_hash(dataset_hash: str, experiment_id: str, period: str) -> None:
    """Ruling 1, 2026-08-09: "A result without a dataset fingerprint is not a result."

    A p-value that cannot be tied to an exact, hashed snapshot is unreproducible
    and therefore is not evidence. Enforced at the ledger boundary so it cannot
    be forgotten by a caller.
    """
    # ORDER MATTERS. The missing-fingerprint case is the ledger's own error and
    # callers distinguish it by type, so it is checked FIRST. Running the
    # development guard ahead of it silently changed the exception type for an
    # empty fingerprint -- caught by test_research_ledger.
    if not dataset_hash or not str(dataset_hash).strip():
        raise MissingDatasetFingerprint(
            f"'{experiment_id}' addressed period '{period}' with no dataset "
            f"fingerprint.\n"
            f"  Ruling 1 (2026-08-09): a result without a dataset fingerprint is "
            f"not a result. Pass the snapshot manifest digest -- section 31 "
            f"requires every result to trace to a data snapshot."
        )

    # A development dataset is refused outright: the ledger is the record of
    # confirmatory evidence, and dev data is definitionally not that.
    require_confirmatory(dataset_hash, context=f"ledger entry for '{experiment_id}' ({period})")


# Protocol section 7: "The holdout is not opened until validation has passed."
# Only this verdict opens it. INCONCLUSIVE does not -- section 10 routes that to
# "no further capital or effort".
PASSING_VERDICT = "PASS"
HOLDOUT = "holdout"
VALIDATION = "validation"


# ---------------------------------------------------------------------------
# entries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    kind: str
    experiment_id: str
    period: str
    timestamp: str
    hypothesis: str = ""
    config_hash: str = ""
    protocol_hash: str = ""
    conventions_hash: str = ""
    git_sha: str = ""
    dataset_hash: str = ""
    reason: str = ""
    p_value: float | None = None
    t_stat: float | None = None
    verdict: str = ""
    prev_hash: str = GENESIS
    entry_hash: str = ""

    def payload(self) -> dict:
        """Everything the hash covers -- i.e. everything except the hash itself."""
        data = asdict(self)
        data.pop("entry_hash")
        return data

    def compute_hash(self) -> str:
        canonical = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# multiplicity
# ---------------------------------------------------------------------------


def holm_rejections(p_values: dict[str, float], alpha: float) -> dict[str, bool]:
    """Holm-Bonferroni step-down over a completed family.

    Sort ascending; reject p(i) while p(i) <= alpha / (m - i + 1); stop at the
    first failure and accept everything from there on -- including any small
    p-value that happens to sit below it in the ordering.
    """
    if not p_values:
        return {}
    if not 0.0 < alpha < 1.0:
        raise LedgerError(f"alpha must lie in (0, 1); got {alpha}")

    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    out: dict[str, bool] = {}
    still_rejecting = True

    for i, (key, p) in enumerate(ordered):
        if still_rejecting and p <= alpha / (m - i):
            out[key] = True
        else:
            still_rejecting = False
            out[key] = False
    return out


def required_tstat(reference, alpha: float) -> float:
    """The t-statistic that would achieve a true one-sided size of `alpha`.

    Read off the SIMULATED null distribution of the pre-registered estimator, not
    from a normal table -- the whole point is that the estimator is not normal.
    """
    if not 0.0 < alpha < 1.0:
        raise LedgerError(f"alpha must lie in (0, 1); got {alpha}")
    return float(reference.quantile(1.0 - alpha))


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------


class ResearchLedger:
    """Append-only, hash-chained record of every evaluation that spent a credit."""

    def __init__(self, path: Path | str, budget: int = 5) -> None:
        if budget < 1:
            raise LedgerError(f"budget must be at least 1; got {budget}")
        self.path = Path(path)
        self.budget = int(budget)
        self._entries: list[LedgerEntry] = self._load()

    # -- persistence ---------------------------------------------------------

    @property
    def head_path(self) -> Path:
        """External anchor recording how long the chain is meant to be.

        A backward hash chain cannot detect its own TRUNCATION: lop the last
        entry off and the remainder still verifies perfectly, because nothing
        points forward to what was removed. Deleting the most recent failed
        experiment is precisely the attack that matters, so the length and head
        hash are anchored outside the file.

        This raises the cost of tampering; it does not make it impossible. The
        real anchor is git -- the ledger and this file are both committed, so
        rewriting them is a visible change to a tracked file with a history.
        """
        return self.path.with_name(self.path.name + ".head")

    def _load(self) -> list[LedgerEntry]:
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(LedgerEntry(**json.loads(line)))
        return entries

    def _write_head(self) -> None:
        head = self._entries[-1].entry_hash if self._entries else GENESIS
        self.head_path.write_text(
            json.dumps({"count": len(self._entries), "head_hash": head}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _append(self, entry: LedgerEntry) -> LedgerEntry:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
        self._entries.append(entry)
        self._write_head()
        return entry

    def _next(self, **fields) -> LedgerEntry:
        prev = self._entries[-1].entry_hash if self._entries else GENESIS
        draft = LedgerEntry(
            sequence=len(self._entries),
            timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
            prev_hash=prev,
            **fields,
        )
        return LedgerEntry(**{**asdict(draft), "entry_hash": draft.compute_hash()})

    # -- reading -------------------------------------------------------------

    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def verify_chain(self) -> None:
        """Raise if any entry was edited, removed, or truncated off the end."""
        if self.head_path.exists():
            anchor = json.loads(self.head_path.read_text(encoding="utf-8"))
            actual_head = self._entries[-1].entry_hash if self._entries else GENESIS
            if anchor["count"] != len(self._entries):
                raise LedgerTampered(
                    f"the ledger holds {len(self._entries)} entries but its head "
                    f"anchor records {anchor['count']}; "
                    f"{anchor['count'] - len(self._entries)} entrie(s) were removed. "
                    f"Directive section 34.12: no hiding failed experiments."
                )
            if anchor["head_hash"] != actual_head:
                raise LedgerTampered(
                    f"head anchor expects {anchor['head_hash'][:12]} but the final "
                    f"entry hashes to {actual_head[:12]}; the ledger was rewritten"
                )
        elif self._entries:
            raise LedgerTampered(
                f"the ledger has {len(self._entries)} entries but its head anchor "
                f"({self.head_path.name}) is missing; truncation cannot be ruled out"
            )

        expected_prev = GENESIS
        for i, entry in enumerate(self._entries):
            if entry.sequence != i:
                raise LedgerTampered(
                    f"entry {i} carries sequence {entry.sequence}; an entry was removed"
                )
            if entry.prev_hash != expected_prev:
                raise LedgerTampered(
                    f"entry {i} ({entry.experiment_id}) chains to {entry.prev_hash[:12]} "
                    f"but its predecessor hashes to {expected_prev[:12]}; "
                    f"an entry was edited or removed"
                )
            if entry.compute_hash() != entry.entry_hash:
                raise LedgerTampered(
                    f"entry {i} ({entry.experiment_id}) does not match its own hash; "
                    f"its contents were edited after it was written"
                )
            expected_prev = entry.entry_hash

    def _spends(self) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self._entries if e.kind == SPEND)

    def credits_spent(self) -> int:
        """Credits count EXPERIMENTS, not evaluations (CONVENTIONS A-003).

        The budget is "five separate pre-registered experiments", and each
        experiment gets its own validation pass plus one holdout evaluation.
        Charging validation and holdout separately would halve the programme for
        no statistical reason: it is the number of distinct hypotheses put to
        out-of-sample data that inflates family-wise error, not the number of
        times a single one is measured along its own pre-registered path.
        """
        return len({e.experiment_id for e in self._spends() if e.period in BUDGETED_PERIODS})

    def credits_remaining(self) -> int:
        return max(0, self.budget - self.credits_spent())

    def _active_spend(self, experiment_id: str, period: str) -> LedgerEntry | None:
        """The unmatched spend for this (experiment, period), or None.

        Entries are read IN ORDER. A spend becomes active; a later annulment
        voids the most recent active spend. Excess annulments void nothing --
        they cannot bank capacity for a future run, so two annulments never
        buy two replacements.
        """
        active: list[LedgerEntry] = []
        for entry in self._entries:
            if entry.experiment_id != experiment_id or entry.period != period:
                continue
            if entry.kind == SPEND:
                active.append(entry)
            elif entry.kind == ANNULMENT and active:
                active.pop()
        return active[-1] if active else None

    def already_evaluated(self, experiment_id: str, period: str) -> LedgerEntry | None:
        """The spend that blocks a re-look, or None if there is none.

        An ANNULLED spend does not block: it records an execution that produced
        no observation. An un-annulled one still does, and a result recorded
        against a spend makes it un-annullable (see `annul`).
        """
        return self._active_spend(experiment_id, period)

    def annul(
        self,
        *,
        experiment_id: str,
        period: str,
        reason: str,
    ) -> LedgerEntry:
        """Void an unmatched spend that never produced a result. APPEND-ONLY.

        Refuses when there is no unmatched spend to void, and refuses when a
        result was recorded against it -- otherwise this would be a way to
        erase a real experimental observation, which is the thing the ledger
        exists to prevent.
        """
        self.verify_chain()

        spend = self._active_spend(experiment_id, period)
        if spend is None:
            raise LedgerError(
                f"nothing to annul: no unmatched spend for '{experiment_id}' "
                f"on period '{period}'. An annulment cannot be banked against "
                f"a future execution."
            )
        recorded = [
            e for e in self._entries
            if e.kind == RESULT and e.experiment_id == experiment_id
            and e.period == period
        ]
        if recorded:
            raise LedgerError(
                f"refusing to annul '{experiment_id}' on '{period}': a result "
                f"was recorded ({recorded[-1].verdict}). An evaluation that "
                f"produced an observation stands. Annulment is only for an "
                f"execution that failed before recording one."
            )
        if not reason.strip():
            raise LedgerError("an annulment requires a written reason")

        return self._append(
            self._next(
                kind=ANNULMENT,
                experiment_id=experiment_id,
                period=period,
                reason=reason,
            )
        )

    def results(self) -> dict:
        """Keyed by (experiment_id, period).

        An experiment now carries BOTH a validation and a holdout result, so a
        key of experiment_id alone would let the second silently overwrite the
        first -- and the validation verdict is exactly what gates the holdout.
        """
        out: dict = {}
        for entry in self._entries:
            if entry.kind == RESULT:
                out[(entry.experiment_id, entry.period)] = {
                    "period": entry.period,
                    "p_value": entry.p_value,
                    "t_stat": entry.t_stat,
                    "verdict": entry.verdict,
                    "dataset_hash": entry.dataset_hash,
                    "timestamp": entry.timestamp,
                }
        return out

    def result_for(self, experiment_id: str, period: str) -> dict | None:
        return self.results().get((experiment_id, period))

    def holdout_results(self) -> dict:
        """Holdout results by experiment id -- the family programme-level
        inference is drawn over. Validation is a screen, not a finding."""
        return {
            eid: value
            for (eid, period), value in self.results().items()
            if period == HOLDOUT
        }

    # -- writing -------------------------------------------------------------

    def spend(
        self,
        *,
        experiment_id: str,
        hypothesis: str,
        period: str,
        config_hash: str,
        protocol_hash: str,
        conventions_hash: str,
        git_sha: str,
        dataset_hash: str,
        reason: str,
    ) -> LedgerEntry:
        """Consume a research credit. Called BEFORE the evaluation runs."""
        self.verify_chain()
        _require_dataset_hash(dataset_hash, experiment_id, period)

        # The no-second-look rule binds only on BUDGETED periods. In-sample
        # exists to debug the pipeline and is run many times; blocking a repeat
        # there would make ordinary development impossible while protecting
        # nothing -- section 7 grants in-sample no statistical standing at all.
        if period in BUDGETED_PERIODS:
            prior = self.already_evaluated(experiment_id, period)
            if prior is not None:
                raise AlreadyEvaluated(
                    f"experiment '{experiment_id}' has already been evaluated against "
                    f"period '{period}' on {prior.timestamp}.\n"
                    f"  A second look is not available. Protocol section 10: a modified "
                    f"specification is a NEW hypothesis requiring a new experiment id "
                    f"and consuming another credit."
                )

        # Protocol section 7 / CONVENTIONS A-003: each experiment gets its own
        # validation pass and then ONE holdout evaluation. Checked BEFORE the
        # budget so a refused holdout never consumes a credit.
        if period == HOLDOUT:
            self._require_validation_passed(experiment_id)

        if period in BUDGETED_PERIODS and self.credits_remaining() == 0:
            spent = [e.experiment_id for e in self._spends() if e.period in BUDGETED_PERIODS]
            raise BudgetExhausted(
                f"the research budget of {self.budget} confirmatory evaluations is "
                f"exhausted; already spent by {spent}.\n"
                f"  Directive section 4: every holdout evaluation permanently "
                f"consumes one research credit. There are no more."
            )

        return self._append(
            self._next(
                kind=SPEND,
                experiment_id=experiment_id,
                hypothesis=hypothesis,
                period=period,
                config_hash=config_hash,
                protocol_hash=protocol_hash,
                conventions_hash=conventions_hash,
                git_sha=git_sha,
                dataset_hash=dataset_hash,
                reason=reason,
            )
        )

    def _require_validation_passed(self, experiment_id: str) -> None:
        """Refuse the holdout unless THIS experiment has a recorded validation PASS.

        Three distinct refusals, because the remedy differs for each:
        never ran validation, ran it but recorded no result, or recorded a
        result that was not a pass.
        """
        if self.already_evaluated(experiment_id, VALIDATION) is None:
            raise ValidationNotPassed(
                f"experiment '{experiment_id}' has never run a validation pass, so "
                f"the holdout may not be opened.\n"
                f"  Protocol section 7: 'The holdout is not opened until validation "
                f"has passed.' Each experiment gets its own validation pass and then "
                f"one -- and only one -- holdout evaluation. Skipping validation "
                f"would spend that single irreplaceable look on an unscreened "
                f"hypothesis."
            )

        result = self.result_for(experiment_id, VALIDATION)
        if result is None:
            raise ValidationNotPassed(
                f"experiment '{experiment_id}' spent a validation credit but "
                f"recorded no result, so the holdout may not be opened.\n"
                f"  Spending the credit is not the same as passing. Record the "
                f"validation verdict first."
            )
        if str(result["verdict"]).upper() != PASSING_VERDICT:
            raise ValidationNotPassed(
                f"experiment '{experiment_id}' recorded validation verdict "
                f"'{result['verdict']}', not {PASSING_VERDICT}, so the holdout "
                f"remains untouched.\n"
                f"  Protocol section 7: 'If validation fails, the holdout remains "
                f"untouched and available for a future experiment.' Section 10 "
                f"routes INCONCLUSIVE the same way -- no further capital or effort. "
                f"A modified specification is a NEW experiment id."
            )

    def record_result(
        self,
        experiment_id: str,
        period: str,
        *,
        p_value: float,
        t_stat: float,
        verdict: str,
        dataset_hash: str,
    ) -> LedgerEntry:
        """Close out an evaluation. Write-once."""
        self.verify_chain()
        _require_dataset_hash(dataset_hash, experiment_id, period)

        if self.already_evaluated(experiment_id, period) is None:
            raise LedgerError(
                f"no credit was spent for experiment '{experiment_id}' against "
                f"period '{period}'; a result cannot exist without an evaluation"
            )
        if self.result_for(experiment_id, period) is not None:
            raise LedgerError(
                f"a result for '{experiment_id}' against period '{period}' is "
                f"already recorded and cannot be overwritten (directive 34.14)"
            )

        return self._append(
            self._next(
                kind=RESULT,
                experiment_id=experiment_id,
                period=period,
                p_value=float(p_value),
                t_stat=float(t_stat),
                verdict=verdict,
                dataset_hash=dataset_hash,
            )
        )

    # -- multiplicity --------------------------------------------------------

    def sequential_alpha(self, family_alpha: float) -> float:
        """Bonferroni over the COMMITTED budget, not over credits spent so far."""
        if not 0.0 < family_alpha < 1.0:
            raise LedgerError(f"family_alpha must lie in (0, 1); got {family_alpha}")
        return family_alpha / self.budget

    def holm(self, alpha: float) -> dict[str, bool]:
        """Retrospective Holm over the recorded family. Never an authorisation."""
        p_values = {
            eid: r["p_value"]
            for eid, r in self.holdout_results().items()
            if r["p_value"] is not None
        }
        return holm_rejections(p_values, alpha)

    def report(self, family_alpha: float = 0.05) -> dict:
        """Everything a reviewer needs to judge the family, in one object."""
        try:
            self.verify_chain()
            verified = True
        except LedgerTampered:
            verified = False

        results = self.results()
        holm = self.holm(family_alpha) if results else {}
        sequential = self.sequential_alpha(family_alpha)

        experiments = []
        for entry in self._spends():
            result = results.get((entry.experiment_id, entry.period), {})
            p = result.get("p_value")
            experiments.append(
                {
                    "experiment_id": entry.experiment_id,
                    "hypothesis": entry.hypothesis,
                    "period": entry.period,
                    "evaluated": entry.timestamp,
                    "budgeted": entry.period in BUDGETED_PERIODS,
                    "p_value": p,
                    "t_stat": result.get("t_stat"),
                    "verdict": result.get("verdict"),
                    "dataset_hash": entry.dataset_hash,
                    "passes_sequential_bonferroni": (p is not None and p <= sequential),
                    "passes_holm_retrospective": holm.get(entry.experiment_id),
                }
            )

        return {
            "budget": self.budget,
            "credits_spent": self.credits_spent(),
            "credits_remaining": self.credits_remaining(),
            "family_alpha": family_alpha,
            "sequential_alpha": sequential,
            "chain_verified": verified,
            "experiments": experiments,
        }
