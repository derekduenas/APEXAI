"""PIT-safe security identity: ticker != identity, ambiguity fails closed.

A ticker resolves THROUGH TIME to an apex_security_id via validity windows.
A recycled ticker (same string, different issuer) resolves differently on
either side of the boundary; a timestamp falling in zero or two windows is
AMBIGUOUS and refuses -- it never guesses.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from apex.intraday.contract import IntradayDataError


@dataclass(frozen=True)
class SecurityIdentityMap:
    apex_security_id: str
    provider: str
    provider_symbol: str
    valid_from: str
    valid_to: str                 # exclusive; "9999-12-31" = open
    external_ids: dict            # cik / figi_composite / figi_share_class / permaticker
    mapping_method: str
    mapping_confidence: float
    evidence: str


class IdentityBridge:
    def __init__(self, mappings):
        self.mappings = list(mappings)

    def resolve(self, provider_symbol: str, at) -> str:
        t = pd.Timestamp(at)
        hits = [m for m in self.mappings
                if m.provider_symbol == provider_symbol
                and pd.Timestamp(m.valid_from) <= t < pd.Timestamp(m.valid_to)]
        if len(hits) == 1:
            return hits[0].apex_security_id
        if not hits:
            raise IntradayDataError(
                f"identity: {provider_symbol!r} at {t} maps to NOTHING. "
                f"An unmapped symbol fails closed; it is never passed through "
                f"as its own identity.")
        raise IntradayDataError(
            f"identity: {provider_symbol!r} at {t} maps to "
            f"{[m.apex_security_id for m in hits]} -- AMBIGUOUS, refused.")

    def reconcile_against_permatickers(self, permaticker_by_id: dict) -> list:
        """Cross-check external ids against the existing Sharadar identity
        layer; disagreements are FINDINGS, returned, never auto-resolved."""
        findings = []
        for m in self.mappings:
            pt = m.external_ids.get("permaticker")
            if pt is not None and permaticker_by_id.get(m.apex_security_id) not in (None, pt):
                findings.append(
                    f"{m.apex_security_id}: provider says permaticker {pt}, "
                    f"APEX says {permaticker_by_id[m.apex_security_id]}")
        return findings
