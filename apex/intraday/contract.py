"""The provider-neutral IntradayProvider contract, and DataQuality.

FAIL CLOSED: unknown identity, stale data, hash mismatch, impossible
ordering, unreconcilable duplicates -- each raises. UNKNOWN is a valid
DataQuality state; silently-safe is not.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class DataQuality(Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"
    MISSING_REFERENCE = "MISSING_REFERENCE"
    MISSING_BAR = "MISSING_BAR"
    CORPORATE_ACTION_UNRESOLVED = "CORPORATE_ACTION_UNRESOLVED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    UNKNOWN = "UNKNOWN"


CRITICAL_QUALITY = {DataQuality.AMBIGUOUS_IDENTITY, DataQuality.STALE,
                    DataQuality.CORPORATE_ACTION_UNRESOLVED,
                    DataQuality.PROVIDER_ERROR}


class IntradayDataError(RuntimeError):
    """A fail-closed condition in the intraday substrate."""


def require_quality(quality: DataQuality, context: str) -> None:
    if quality in CRITICAL_QUALITY:
        raise IntradayDataError(
            f"{context}: {quality.value} is a critical data-quality failure "
            f"and fails closed. Unknown never becomes safe.")


@dataclass(frozen=True)
class IntradayBarRaw:
    """Vendor-unadjusted, immutable. Adjustments live downstream."""
    provider: str
    provider_symbol: str
    event_time_utc: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    transactions: int
    source_file: str
    source_hash: str
    ingestion_time: str


@dataclass(frozen=True)
class PartitionManifest:
    provider: str
    dataset: str
    date: str
    schema_version: str
    row_count: int
    min_timestamp: str
    max_timestamp: str
    symbol_count: int
    file_size: int
    content_hash: str
    download_timestamp: str
    provider_metadata: dict
    validation_status: str = field(default="UNVALIDATED")

    def replay_eligible(self) -> bool:
        return self.validation_status == "VALIDATED"


def manifest_hash(m: PartitionManifest) -> str:
    body = {k: getattr(m, k) for k in m.__dataclass_fields__}
    return hashlib.sha256(json.dumps(body, sort_keys=True,
                                     default=str).encode()).hexdigest()


class IntradayProvider(ABC):
    """Provider-neutral. Adapters translate; they never leak vendor shapes."""

    @abstractmethod
    def get_bars(self, security_ids, start, end, resolution,
                 session_filter): ...

    @abstractmethod
    def get_reference_state(self, as_of): ...

    @abstractmethod
    def get_corporate_actions(self, start, end): ...

    @abstractmethod
    def get_quotes(self, security_ids, start, end): ...

    @abstractmethod
    def get_trades(self, security_ids, start, end): ...

    @abstractmethod
    def availability(self) -> dict:
        """Provenance + coverage; consumers must check before trusting."""
