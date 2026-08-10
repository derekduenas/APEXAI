"""The vendor seam.

Every source of market data implements `PriceSource`. The pipeline is written
against this protocol and never against a vendor's schema, so the Sharadar
adapter (Stage 4) drops in behind the same interface the synthetic generator
already satisfies -- and the null rig keeps testing the same code path that will
later run on real prices.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from apex.contracts import Panel


@runtime_checkable
class PriceSource(Protocol):
    """Yields a validated `Panel` covering the full data lake.

    Implementations must return FULL history for every security they know about,
    including delisted ones, and must not filter to any universe. Universe
    construction is a separate, point-in-time stage; a source that pre-filters
    has already destroyed the survivorship property.
    """

    @property
    def name(self) -> str: ...

    @property
    def dataset_fingerprint(self) -> str:
        """Hash identifying EXACTLY the data this source yields.

        Ruling 1: a result without a dataset fingerprint is not a result. Every
        source must be able to name its own data, so the ledger can bind a
        p-value to a reproducible snapshot.
        """
        ...

    @property
    def requires_signed_registration(self) -> bool:
        """True for real vendor data, False for synthetic fixtures.

        Stages 1-3 verify the pipeline and touch no real prices, so they run
        against an unsigned pre-registration. Real data does not.
        """
        ...

    def load(self) -> Panel: ...
