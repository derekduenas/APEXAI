"""THE OPPORTUNITY BOARD — simultaneous candidates, one scarce unit of
risk.

Candidates arriving independently is how a retail bot behaves. A desk
maintains a BOARD and asks the professional question:

    "If one unit of risk is available, which opportunity deserves it?"

The board RANKS but never allocates — ranking is process (Captain),
allocation is money (Capital). It sorts on structured evidence, in a
declared lexicographic order rather than a blended score, so the reason
for an ordering is always legible:

  1. not compromised (assassin clean, disagreement not HIGH)
  2. quality tier (HIGH > MODERATE > LOW > UNASSESSABLE)
  3. entry quality (STRONG > MODERATE > UNKNOWN)
  4. fewer unknown conviction dimensions
  5. deterministic tiebreak on decision_id (never wall-clock luck)

Rejected candidates stay ON the board with their reasons: a board that
shows only survivors is a survivor gallery, not a record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

BOARD_VERSION = "apex_opportunity_board_v1"
_QUALITY = {"HIGH": 0, "MODERATE": 1, "LOW": 2, "COMPROMISED": 3,
            "UNASSESSABLE_INSUFFICIENT_EVIDENCE": 4}
_ENTRY = {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "UNKNOWN": 3}


@dataclass(frozen=True)
class BoardEntry:
    rank: int
    decision_id: str
    symbol: str
    quality: str
    directional_thesis: str
    entry_thesis: str
    primary_unresolved: str
    next_action: str
    capital_state: str | None
    why_ranked_here: str


@dataclass(frozen=True)
class OpportunityBoard:
    t_utc: str
    entries: tuple
    n_candidates: int
    allocation_note: str = (
        "RANKING IS PROCESS, ALLOCATION IS MONEY: the board orders "
        "opportunities; Capital alone decides whether any of them gets "
        "risk, and may refuse the top-ranked one entirely")
    version: str = field(default=BOARD_VERSION)

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "opportunity_board"
        return d


def build(states: list, capital_by_id: dict | None = None,
          t_utc: str = "") -> OpportunityBoard:
    """states: CaptainState objects for every live candidate."""
    caps = capital_by_id or {}

    def key(s):
        compromised = (s.conviction.get("assassin") == "WOUNDED"
                       or s.conviction.get("disagreement") == "HIGH")
        unknowns = len(s.conviction.get("classification", {})
                       .get("unknown_dimensions", []))
        return (1 if compromised else 0,
                _QUALITY.get(s.opportunity_quality, 9),
                _ENTRY.get(s.entry_thesis, 9),
                unknowns, s.decision_id)

    ordered = sorted(states, key=key)
    entries = []
    for i, s in enumerate(ordered, 1):
        compromised = (s.conviction.get("assassin") == "WOUNDED"
                       or s.conviction.get("disagreement") == "HIGH")
        why = ("compromised (assassin/disagreement)" if compromised
               else f"quality={s.opportunity_quality}, "
                    f"entry={s.entry_thesis}, "
                    f"unresolved={s.primary_unresolved}")
        entries.append(BoardEntry(
            rank=i, decision_id=s.decision_id, symbol=s.symbol,
            quality=s.opportunity_quality,
            directional_thesis=s.directional_thesis,
            entry_thesis=s.entry_thesis,
            primary_unresolved=s.primary_unresolved,
            next_action=s.next_action,
            capital_state=(caps.get(s.decision_id) or {}).get("final_state"),
            why_ranked_here=why))
    return OpportunityBoard(t_utc=t_utc, entries=tuple(entries),
                            n_candidates=len(entries))
