"""SELF-CRITIC — the function whose job is to doubt our own findings.

Phase 19. Not a chatty agent. A checklist with teeth: for every
apparently successful discovery it asks the questions a hostile
reviewer would ask, answers them from the evidence actually on record,
and DOWNGRADES research confidence when the evidence cannot answer.

It may downgrade. It may never promote. That asymmetry is deliberate --
a critic that can also bless is just another advocate.

THE DEFAULT IS SUSPICION. An unanswerable question counts against the
finding, not for it. A discovery that survives only because nobody
looked for leakage has not survived anything.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

CONFIDENCE = ("RESEARCH_PROMISING", "RESEARCH_UNCERTAIN",
              "RESEARCH_DOUBTFUL", "RESEARCH_REJECTED")

QUESTIONS = (
    "leakage", "multiple_testing", "regime_concentration",
    "execution_assumption", "simpler_baseline", "competing_mechanism",
    "out_of_sample", "abandonment_evidence", "sample_sufficiency",
    "world_class_dependence",
)


@dataclass(frozen=True)
class CriticFinding:
    question: str
    answered: bool
    answer: str
    counts_against: bool

    def as_record(self) -> dict:
        return asdict(self)


def critique(*, discovery: dict, analog_quality: dict | None = None,
             adversary: dict | None = None, arena: dict | None = None,
             world_class_split: dict | None = None,
             family: dict | None = None,
             prospective_n: int = 0) -> dict:
    """Interrogate a finding using only what is actually on record."""
    f = []

    # leakage
    boundary = discovery.get("dataset_boundary", "")
    leak_ok = bool(boundary) and "SUPERSEDED" not in boundary.upper()
    f.append(CriticFinding(
        "leakage", leak_ok,
        (f"dataset boundary {boundary!r}; analog membership fixed "
         f"pre-reveal by construction" if leak_ok
         else "no declared dataset boundary: leakage cannot be excluded"),
        not leak_ok))

    # multiple testing
    n_fam = (family or {}).get("n_experiments")
    fam_ok = isinstance(n_fam, int) and n_fam > 0
    f.append(CriticFinding(
        "multiple_testing", fam_ok,
        (f"family holds {n_fam} registered experiments, "
         f"{(family or {}).get('n_null_or_dead', 0)} null/dead -- that "
         f"is the denominator" if fam_ok
         else "no multiple-testing family on record: the denominator "
              "is unknown, so significance is uninterpretable"),
        not fam_ok))

    # regime concentration
    conc = (analog_quality or {}).get("regime_concentration")
    conc_ok = isinstance(conc, float) and conc < 0.5
    f.append(CriticFinding(
        "regime_concentration", isinstance(conc, float),
        (f"dominant regime holds {conc:.0%} of the neighbourhood"
         if isinstance(conc, float)
         else "regime distribution unavailable"),
        not conc_ok))

    # execution
    ex = (adversary or {}).get("execution_breakpoint")
    ex_ok = adversary is not None and (adversary.get("verdict")
                                       != "FRAGILE")
    f.append(CriticFinding(
        "execution_assumption", adversary is not None,
        (f"adversary verdict {adversary.get('verdict')}; execution "
         f"breakpoints {ex}" if adversary
         else "never stressed: 'worked when nothing went wrong'"),
        not ex_ok))

    # simpler baseline
    base_ok = arena is not None and \
        arena.get("verdict") == "BEATS_ALL_TESTED_BASELINES"
    f.append(CriticFinding(
        "simpler_baseline", arena is not None,
        (f"arena: {arena.get('verdict')}, lost to "
         f"{arena.get('lost_to')}" if arena
         else "never raced against a naive baseline"),
        not base_ok))

    # competing mechanism
    comps = discovery.get("competing_explanations") or []
    f.append(CriticFinding(
        "competing_mechanism", bool(comps),
        (f"{len(comps)} competing explanation(s) preserved" if comps
         else "no competing explanation offered: this is a story"),
        not comps))

    # out of sample / prospective
    f.append(CriticFinding(
        "out_of_sample", prospective_n > 0,
        (f"{prospective_n} prospective observation(s)" if prospective_n
         else "zero prospective evidence: historical survival only"),
        prospective_n == 0))

    # abandonment criteria
    fals = discovery.get("falsifiers") or discovery.get("falsifier")
    f.append(CriticFinding(
        "abandonment_evidence", bool(fals),
        (f"falsifier(s) declared: {fals}" if fals
         else "no declared falsifier: nothing could make us drop it"),
        not fals))

    # sample sufficiency
    n_eff = (analog_quality or {}).get("n_effective_lower_bound", 0)
    suff = isinstance(n_eff, int) and n_eff >= 20
    f.append(CriticFinding(
        "sample_sufficiency", isinstance(n_eff, int),
        f"n_effective_lower_bound = {n_eff}", not suff))

    # world-class dependence
    flag = (world_class_split or {}).get("flag")
    f.append(CriticFinding(
        "world_class_dependence", world_class_split is not None,
        (flag or "no generated-world dependence detected"
         if world_class_split else "not split by world class"),
        bool(flag)))

    against = [x for x in f if x.counts_against]
    unanswered = [x for x in f if not x.answered]
    n = len(against)
    conf = ("RESEARCH_PROMISING" if n == 0 else
            "RESEARCH_UNCERTAIN" if n <= 2 else
            "RESEARCH_DOUBTFUL" if n <= 5 else "RESEARCH_REJECTED")
    return {"kind": "self_critique",
            "findings": [x.as_record() for x in f],
            "n_counting_against": n,
            "n_unanswered": len(unanswered),
            "concerns": [x.question for x in against],
            "research_confidence": conf,
            "may_promote": False,
            "law": "the default is suspicion: an unanswerable question "
                   "counts AGAINST a finding. This function may "
                   "downgrade and may never promote -- a critic that "
                   "can also bless is just another advocate",
            "decision_power": "NONE_RESEARCH"}
