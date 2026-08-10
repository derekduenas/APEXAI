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

GENESIS = "0" * 64
SPEND = "spend"
RESULT = "result"

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
        return sum(1 for e in self._spends() if e.period in BUDGETED_PERIODS)

    def credits_remaining(self) -> int:
        return max(0, self.budget - self.credits_spent())

    def already_evaluated(self, experiment_id: str, period: str) -> LedgerEntry | None:
        for entry in self._spends():
            if entry.experiment_id == experiment_id and entry.period == period:
                return entry
        return None

    def results(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for entry in self._entries:
            if entry.kind == RESULT:
                out[entry.experiment_id] = {
                    "period": entry.period,
                    "p_value": entry.p_value,
                    "t_stat": entry.t_stat,
                    "verdict": entry.verdict,
                    "timestamp": entry.timestamp,
                }
        return out

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
        reason: str,
    ) -> LedgerEntry:
        """Consume a research credit. Called BEFORE the evaluation runs."""
        self.verify_chain()

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
                reason=reason,
            )
        )

    def record_result(
        self,
        experiment_id: str,
        period: str,
        *,
        p_value: float,
        t_stat: float,
        verdict: str,
    ) -> LedgerEntry:
        """Close out an evaluation. Write-once."""
        self.verify_chain()

        if self.already_evaluated(experiment_id, period) is None:
            raise LedgerError(
                f"no credit was spent for experiment '{experiment_id}' against "
                f"period '{period}'; a result cannot exist without an evaluation"
            )
        if experiment_id in self.results():
            raise LedgerError(
                f"a result for '{experiment_id}' is already recorded and cannot be "
                f"overwritten (directive section 34.14)"
            )

        return self._append(
            self._next(
                kind=RESULT,
                experiment_id=experiment_id,
                period=period,
                p_value=float(p_value),
                t_stat=float(t_stat),
                verdict=verdict,
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
            eid: r["p_value"] for eid, r in self.results().items() if r["p_value"] is not None
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
            result = results.get(entry.experiment_id, {})
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
