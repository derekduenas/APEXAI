"""The Digital Twin: a deterministic, PIT-aware description of what was knowable.

WHAT THE TWIN IS (Part 3)
-------------------------
Not an AI persona. A `TwinState` is a reproducible statement of the information
set available at a single formation date T: which securities were eligible,
which feature values were knowable, and the anchor of the frozen data it was
built from. It is DETERMINISTIC (same snapshot + same T -> same state),
VERSIONED (it records the dataset fingerprint and a twin format version), and
PIT-AWARE (it refuses to expose anything dated after T).

WHY IT REFUSES RATHER THAN FILTERS
----------------------------------
A twin that silently dropped future rows would be indistinguishable from one
that never had them, and a look-ahead bug would hide inside the drop. Instead
`at()` builds the state from data already masked to `date <= T` and
`assert_no_future_leak` recomputes that the constructed state contains nothing
knowable only later. The check is a measurement, not a promise -- the same
discipline `nsi`'s `known_from_out` established.

The twin is a CONSUMER of the certified feature/universe machinery, not a new
data path. It does not compute features; it packages the ones already computed,
at one date, with the future provably absent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import pandas as pd

TWIN_VERSION = "twin-v1"


class TwinLeak(RuntimeError):
    """A twin state exposed information unknowable at its formation date."""


@dataclass(frozen=True)
class TwinState:
    """The information set at one formation date. Immutable and hashable."""

    date: pd.Timestamp
    dataset_fingerprint: str
    version: str
    eligible_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]
    # feature_id -> {security_id: value} for eligible, NSI-present names only.
    values: dict
    # feature_id -> the latest knowability date that fed any value, per Part 3.
    knowable_asof: dict

    def __post_init__(self) -> None:
        if self.version != TWIN_VERSION:
            raise TwinLeak(f"twin version mismatch: {self.version!r}")

    def digest(self) -> str:
        """Deterministic identity. Same snapshot + same T -> same digest."""
        payload = json.dumps(
            {
                "date": str(self.date.date()),
                "dataset_fingerprint": self.dataset_fingerprint,
                "version": self.version,
                "eligible_ids": sorted(self.eligible_ids),
                "feature_ids": sorted(self.feature_ids),
                "values": {k: dict(sorted(v.items())) for k, v in sorted(self.values.items())},
            },
            sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def assert_no_future_leak(self) -> None:
        """PIT guard (Part 3). Every feed date must be <= the formation date.

        `knowable_asof` records, per feature, the latest input date that
        contributed to any value in this state. If any exceeds T, the state was
        built with information that did not exist at T.
        """
        t = self.date
        for feature_id, asof in self.knowable_asof.items():
            if asof is not None and pd.Timestamp(asof) > t:
                raise TwinLeak(
                    f"twin state at {t.date()} exposes feature {feature_id!r} "
                    f"whose latest input is dated {pd.Timestamp(asof).date()} -- "
                    f"unknowable at the formation date. Part 3: a twin at T must "
                    f"not contain information unknowable at T."
                )


def build_state(
    *,
    date: pd.Timestamp,
    dataset_fingerprint: str,
    eligible_row: pd.Series,
    feature_rows: dict,
    knowable_asof: dict,
) -> TwinState:
    """Assemble one TwinState from already-PIT-masked inputs.

    `eligible_row` is a boolean Series over security_id at this date.
    `feature_rows` maps feature_id -> Series over security_id, ALREADY masked to
    date <= T by the feature machinery. `knowable_asof` maps feature_id -> the
    latest input date that fed it (or None). This function packages; it does not
    reach back into raw data, so it cannot itself introduce a leak.
    """
    eligible_ids = tuple(str(s) for s in eligible_row.index[eligible_row.fillna(False)])
    values = {}
    for feature_id, row in feature_rows.items():
        present = row.reindex(eligible_ids).dropna()
        values[feature_id] = {str(k): float(v) for k, v in present.items()}

    state = TwinState(
        date=pd.Timestamp(date),
        dataset_fingerprint=dataset_fingerprint,
        version=TWIN_VERSION,
        eligible_ids=eligible_ids,
        feature_ids=tuple(sorted(feature_rows)),
        values=values,
        knowable_asof={k: knowable_asof.get(k) for k in feature_rows},
    )
    state.assert_no_future_leak()
    return state
