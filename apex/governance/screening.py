"""The Phase 2 cheap screen. APEX Screening Protocol v1.0, rules S1-S13.

A filter that can reject an idea and is structurally incapable of improving
one. Every rule the protocol states is enforced by a type or a refusal here,
because a rule that lives only in prose is a rule that erodes.

WHY THIS IS A SEPARATE CHAIN
----------------------------
`LedgerEntry.payload()` covers every field, and `verify_chain` recomputes
`entry.compute_hash()` for each entry. Adding one field to carry a dossier hash
would therefore change the hash of every entry already written and break the
live six-entry research ledger. `tests/test_screening.py` demonstrates this
rather than asserting it. Screening gets its own append-only chained log, and
the research ledger is not touched at all (S10, S12).

S13 -- A SCREENING OUTCOME IS NOT EVIDENCE
------------------------------------------
A verdict here is an ELIGIBILITY decision. It carries no evidentiary weight
toward the eventual experiment and may never enter its statistics, verdict,
multiplicity accounting or interpretation. Enforced structurally in the only
way available: nothing in the evaluation path imports this module, and a test
asserts that. "It already looked good in screening" has nowhere to enter from.

WHY THE RETURN TYPE IS SO NARROW
--------------------------------
`ScreenOutcome` carries a verdict and prose reasons. It has no field that can
hold a score, a ranking, a per-variant result, or a suggested parameter, so S7
is not a policy anyone has to remember -- there is nowhere to put the
information. A screen that could say "0.62, try a 9-month window" would be a
tuning loop with a governance label on it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

GENESIS = "0" * 64

REJECT = "REJECT"
SURVIVE = "SURVIVE"
VERDICTS = (REJECT, SURVIVE)

# S1. These are TRANSCRIBED from the protocol's "What a dossier must contain",
# not chosen here. The earlier version of this module enforced a ten-field list
# the protocol never specified, which made the definition of a valid hypothesis
# an undocumented implementation choice -- a hidden selection criterion inside
# a system built to eliminate hidden selection criteria. `prior_literature` and
# `why_it_might_fail` were inventions and have been removed.
#
# The two groups are kept apart on purpose. Only the first is a statement about
# the science; the second is bookkeeping, and a reader must be able to see at a
# glance that a missing `title` is an administrative defect and not a
# scientific one.
SCIENTIFIC_FIELDS = (
    "hypothesis",
    "economic_rationale",
    "signal_definition",
    "directional_prediction",
    "timing",
    "data_requirements",
    "universe",
    "horizon",
    "falsification_criterion",
)

# Provenance and a readable log. NOT scientific criteria: their absence makes a
# dossier unadministrable, never unscientific.
GOVERNANCE_FIELDS = ("title", "author", "date")

REQUIRED_FIELDS = SCIENTIFIC_FIELDS + GOVERNANCE_FIELDS


class ScreeningError(RuntimeError):
    """A screening rule was violated."""


class DossierIncomplete(ScreeningError):
    """S1: the dossier is missing a required field."""


class AlreadyRejected(ScreeningError):
    """S5: rejection is terminal for that exact dossier."""


class NondeterministicScreen(ScreeningError):
    """S9: the same frozen dossier produced a different verdict."""


class HoldoutRequested(ScreeningError):
    """S11: a screen tried to reach the sealed holdout."""


class OptimisationLeak(ScreeningError):
    """S7: a screen tried to return information usable for tuning."""


class ScreenLogTampered(ScreeningError):
    """The screen log chain does not verify."""


# ---------------------------------------------------------------------------
# S1, S2 -- the dossier and its identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dossier:
    """A frozen hypothesis. Identity is the content hash, never the filename."""

    content: dict

    def __post_init__(self) -> None:
        def absent(fields):
            return [f for f in fields if not str(self.content.get(f, "")).strip()]

        science, admin = absent(SCIENTIFIC_FIELDS), absent(GOVERNANCE_FIELDS)
        if science or admin:
            parts = []
            if science:
                parts.append(f"scientific requirements missing: {science}")
            if admin:
                parts.append(f"governance metadata missing: {admin}")
            raise DossierIncomplete(
                f"dossier is incomplete -- {'; '.join(parts)}. S1: the required "
                f"content is stated in APEX-SCREENING-PROTOCOL-v1.0.md, not "
                f"here; this module transcribes it and may not add to it."
            )

    def canonical(self) -> str:
        """Deterministic serialisation. Key order and whitespace cannot drift."""
        return json.dumps(self.content, sort_keys=True, separators=(",", ":"))

    @property
    def hash(self) -> str:
        """S2. The identity of this exact hypothesis."""
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    @classmethod
    def from_file(cls, path: Path) -> "Dossier":
        return cls(content=json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# S4, S7 -- what a screen is allowed to say
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScreenOutcome:
    """REJECT or SURVIVE, plus prose. Deliberately nothing else.

    There is no `score`, no `rank`, no `by_variant`, no `suggested_*`. S7 is
    enforced by the shape of this object: the information simply has nowhere
    to live.
    """

    verdict: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ScreeningError(
                f"a screen returns {REJECT} or {SURVIVE}; got {self.verdict!r}. "
                f"S4: there is no score, rank, or degree of promise."
            )
        if not self.reasons:
            raise ScreeningError("a screen outcome requires at least one reason")


def _reject_optimisation_information(outcome: object) -> ScreenOutcome:
    """S7. The screen function is caller-supplied, so its return is checked.

    The type above prevents a screen from DECLARING a tuning field. This
    catches a screen that returns some other object entirely.
    """
    if not isinstance(outcome, ScreenOutcome):
        raise OptimisationLeak(
            f"a screen must return ScreenOutcome; got {type(outcome).__name__}. "
            f"S7: any richer return type can carry tuning information."
        )
    return outcome


# ---------------------------------------------------------------------------
# S11 -- the window a screen may look at
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScreenWindow:
    """The dates a screen may examine. Bounded by the in-sample period."""

    start: str
    end: str

    @classmethod
    def in_sample(cls, config) -> "ScreenWindow":
        spec = config.period("in_sample")
        if spec.get("locked", True):
            raise HoldoutRequested(
                "the in-sample period is marked locked; refusing to screen"
            )
        return cls(start=str(spec["start"]), end=str(spec["end"]))

    def assert_excludes_locked_periods(self, config) -> None:
        """S11. Any overlap with a budgeted period is refused."""
        for name in ("validation", "holdout"):
            spec = config.period(name)
            if str(self.start) <= str(spec["end"]) and str(spec["start"]) <= str(self.end):
                raise HoldoutRequested(
                    f"screen window {self.start}..{self.end} overlaps the "
                    f"{name} period ({spec['start']}..{spec['end']}). S11: a "
                    f"screen may not read a budgeted period, and the holdout "
                    f"is sealed."
                )


# ---------------------------------------------------------------------------
# S3 -- the permanent, tamper-evident log
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScreenEntry:
    sequence: int
    timestamp: str
    dossier_hash: str
    title: str
    verdict: str
    reasons: tuple[str, ...]
    window_start: str
    window_end: str
    prev_hash: str = GENESIS
    entry_hash: str = ""

    def payload(self) -> dict:
        data = asdict(self)
        data.pop("entry_hash")
        data["reasons"] = list(self.reasons)
        return data

    def compute_hash(self) -> str:
        canonical = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ScreenLog:
    """Append-only, hash-chained, externally anchored. Rejections included.

    S3's file-drawer rule is the reason this exists at all: if only survivors
    were recorded, the survivors would look stronger than they are, because
    the denominator would be missing.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._entries: list[ScreenEntry] = self._load()

    @property
    def head_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".head")

    def _load(self) -> list[ScreenEntry]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                raw = json.loads(line)
                raw["reasons"] = tuple(raw.get("reasons", ()))
                out.append(ScreenEntry(**raw))
        return out

    def _write_head(self) -> None:
        head = self._entries[-1].entry_hash if self._entries else GENESIS
        self.head_path.write_text(
            json.dumps({"count": len(self._entries), "head_hash": head},
                       sort_keys=True),
            encoding="utf-8",
        )

    def entries(self) -> tuple[ScreenEntry, ...]:
        return tuple(self._entries)

    def verify_chain(self) -> None:
        if self.head_path.exists():
            anchor = json.loads(self.head_path.read_text(encoding="utf-8"))
            actual = self._entries[-1].entry_hash if self._entries else GENESIS
            if anchor["count"] != len(self._entries):
                raise ScreenLogTampered(
                    f"the screen log holds {len(self._entries)} entries but its "
                    f"anchor records {anchor['count']}; a screening event was "
                    f"removed. S3: rejections are logged as permanently as "
                    f"survivals."
                )
            if anchor["head_hash"] != actual:
                raise ScreenLogTampered("the screen log was rewritten")
        elif self._entries:
            raise ScreenLogTampered(
                "the screen log has entries but no head anchor; truncation "
                "cannot be ruled out"
            )

        expected_prev = GENESIS
        for i, entry in enumerate(self._entries):
            if entry.sequence != i or entry.prev_hash != expected_prev:
                raise ScreenLogTampered(f"screen entry {i} does not chain")
            if entry.compute_hash() != entry.entry_hash:
                raise ScreenLogTampered(f"screen entry {i} was edited after writing")
            expected_prev = entry.entry_hash

    def _append(self, **fields) -> ScreenEntry:
        prev = self._entries[-1].entry_hash if self._entries else GENESIS
        draft = ScreenEntry(
            sequence=len(self._entries),
            timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
            prev_hash=prev,
            **fields,
        )
        entry = ScreenEntry(**{**asdict(draft), "reasons": draft.reasons,
                               "entry_hash": draft.compute_hash()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.payload() | {"entry_hash": entry.entry_hash},
                                sort_keys=True) + "\n")
        self._entries.append(entry)
        self._write_head()
        return entry

    # -- reading -----------------------------------------------------------

    def history(self, dossier_hash: str) -> tuple[ScreenEntry, ...]:
        return tuple(e for e in self._entries if e.dossier_hash == dossier_hash)

    def verdict_for(self, dossier_hash: str) -> str | None:
        seen = self.history(dossier_hash)
        return seen[-1].verdict if seen else None

    def is_rejected(self, dossier_hash: str) -> bool:
        """S5: rejection is terminal."""
        return any(e.verdict == REJECT for e in self.history(dossier_hash))

    def is_eligible_for_registration(self, dossier_hash: str) -> bool:
        """S6: SURVIVE grants eligibility only. Never authorisation."""
        return (
            not self.is_rejected(dossier_hash)
            and any(e.verdict == SURVIVE for e in self.history(dossier_hash))
        )

    def counts(self) -> dict:
        """S3's denominator, available to any later reader."""
        return {
            "screens": len(self._entries),
            "rejected": sum(1 for e in self._entries if e.verdict == REJECT),
            "survived": sum(1 for e in self._entries if e.verdict == SURVIVE),
            "distinct_dossiers": len({e.dossier_hash for e in self._entries}),
        }


# ---------------------------------------------------------------------------
# the screening act
# ---------------------------------------------------------------------------


def run_screen(
    dossier: Dossier,
    screen_fn: Callable[[Dossier, ScreenWindow], ScreenOutcome],
    log: ScreenLog,
    window: ScreenWindow,
    config,
) -> ScreenOutcome:
    """Screen one frozen dossier once, and log it. Consumes no credit.

    Enforces S5 (rejection terminal), S9 (determinism), S11 (no locked
    period), S7 (return type), and S3 (everything logged, including
    rejections).
    """
    log.verify_chain()
    window.assert_excludes_locked_periods(config)

    digest = dossier.hash
    if log.is_rejected(digest):
        raise AlreadyRejected(
            f"dossier {digest[:12]} was already REJECTED. S5: rejection is "
            f"terminal for that exact hypothesis. A materially changed "
            f"hypothesis has a different hash and is a new screening event."
        )

    frozen_before = dossier.canonical()
    outcome = _reject_optimisation_information(screen_fn(dossier, window))

    if dossier.canonical() != frozen_before:
        raise ScreeningError(
            "the screen mutated the dossier it was given. A screen reads a "
            "frozen hypothesis; it does not edit one."
        )

    prior = log.verdict_for(digest)
    if prior is not None and prior != outcome.verdict:
        raise NondeterministicScreen(
            f"dossier {digest[:12]} previously screened {prior} and now "
            f"{outcome.verdict}. S9: re-screening a frozen dossier must be "
            f"deterministic."
        )

    log._append(                                            # noqa: SLF001
        dossier_hash=digest,
        title=str(dossier.content["title"]),
        verdict=outcome.verdict,
        reasons=tuple(outcome.reasons),
        window_start=window.start,
        window_end=window.end,
    )
    return outcome
