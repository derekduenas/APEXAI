"""ResearchDocument — the atomic unit of the library. Immutable,
versioned, hash-identified, never silently overwritten.

VERSIONING LAW: `ingest()` computes a content hash. Ingesting identical
content a second time returns the EXISTING document (a DUPLICATE
verdict, no new row). Ingesting DIFFERENT content under the same
(collection, title) mints a NEW version that `supersedes` the prior
one -- v1 is never rewritten, never deleted; it just stops being the
latest.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.research_library import RESEARCH_LIBRARY_POWER

LEDGER = Path("results/research_library/documents.jsonl")

# Named, documented collections -- NOT a closed enum. New collections
# may be used without a schema change; this tuple exists for discovery
# and for the initial-index report, not as a validation gate.
COLLECTIONS = (
    "ELITE_TRADING", "OPTIONS", "BTC_PERPS", "EQUITIES_INTRADAY",
    "MARKET_MICROSTRUCTURE", "RISK_AND_RUIN", "EXECUTION", "VOLATILITY",
    "EVENTS_MACRO", "PARTICIPANT_BEHAVIOR", "PROPAGATION",
    "RESEARCH_METHODS", "APEX_INTERNAL_LESSONS",
)

DOCUMENT_TYPES = (
    "RESEARCH_REPORT", "ACADEMIC_PAPER", "INSTITUTIONAL_RESEARCH",
    "EXCHANGE_DOCUMENTATION", "PRACTITIONER_RESEARCH", "APEX_INTERNAL_REPORT",
    "EXPERIMENT_RESULT", "FAILURE_ANALYSIS", "DOCTRINE",
)

RESEARCH_STATUSES = ("RAW", "REVIEWED", "SYNTHESIZED", "HYPOTHESIS_SOURCE",
                     "SUPERSEDED", "RETRACTED")

INGEST_VERDICTS = ("INGESTED", "DUPLICATE", "NEW_VERSION")


class ResearchLibraryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchDocument:
    document_id: str
    title: str
    collection: str
    version: int
    created_at: str
    ingested_at: str
    document_type: str
    source_type: str
    source_name: str
    source_reference: str
    authors: tuple
    publication_date: str | None
    content_hash: str
    source_hash: str
    research_status: str
    evidence_class: str
    known_limitations: tuple
    known_from: str
    as_of: str
    supersedes: str | None = None
    decision_power: str = RESEARCH_LIBRARY_POWER

    def __post_init__(self):
        if self.document_type not in DOCUMENT_TYPES:
            raise ResearchLibraryError(f"unknown document_type {self.document_type!r}")
        if self.research_status not in RESEARCH_STATUSES:
            raise ResearchLibraryError(f"unknown research_status {self.research_status!r}")
        if self.version < 1:
            raise ResearchLibraryError("version must be >= 1")

    def as_record(self) -> dict:
        return {"kind": "research_document", **asdict(self)}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_all() -> list:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(__import__("json").loads(line))
        except Exception:  # noqa: BLE001
            continue
    return out


def _latest_by_title(collection: str, title: str) -> dict | None:
    matches = [d for d in _read_all()
              if d.get("collection") == collection and d.get("title") == title]
    if not matches:
        return None
    return max(matches, key=lambda d: d.get("version", 0))


def ingest(*, title: str, collection: str, document_type: str, source_type: str,
          source_name: str, source_reference: str, content: str,
          authors: tuple = (), publication_date: str | None = None,
          research_status: str = "RAW", evidence_class: str = "UNASSESSED",
          known_limitations: tuple = (), known_from, now) -> tuple:
    """Returns (ResearchDocument, verdict) where verdict is one of
    INGEST_VERDICTS. `content`: the FULL text used to compute the
    content hash -- the original artifact is never altered; this
    function only ever reads it."""
    import pandas as pd
    now = pd.Timestamp(now)
    chash = _content_hash(content)
    shash = hashlib.sha256(source_reference.encode("utf-8")).hexdigest()[:16]

    prior = _latest_by_title(collection, title)
    if prior is not None and prior.get("content_hash") == chash:
        return _from_record(prior), "DUPLICATE"

    version = (prior.get("version", 0) + 1) if prior else 1
    doc_id = f"{collection}:{title}:v{version}:{chash[:12]}"
    doc = ResearchDocument(
        document_id=doc_id, title=title, collection=collection, version=version,
        created_at=str(now), ingested_at=str(now), document_type=document_type,
        source_type=source_type, source_name=source_name,
        source_reference=source_reference, authors=tuple(authors),
        publication_date=publication_date, content_hash=chash, source_hash=shash,
        research_status=research_status, evidence_class=evidence_class,
        known_limitations=tuple(known_limitations), known_from=str(pd.Timestamp(known_from)),
        as_of=str(now), supersedes=(prior.get("document_id") if prior else None))

    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, doc.as_record())
    return doc, ("NEW_VERSION" if prior is not None else "INGESTED")


def _from_record(rec: dict) -> ResearchDocument:
    fields = {f: rec.get(f) for f in ResearchDocument.__dataclass_fields__}
    for tf in ("authors", "known_limitations"):
        if fields.get(tf) is not None:
            fields[tf] = tuple(fields[tf])
    return ResearchDocument(**fields)
