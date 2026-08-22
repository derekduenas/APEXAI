"""PATTERN WORLD STATE -- one canonical snapshot of the field.

Composes the Observatory's own sensors plus READ-ONLY reads of artifacts
other organs already persist. It duplicates no canonical signal: where
Frontier-2 or Hunter already wrote a state, this reads their file rather
than recomputing their meaning.

Every facet carries its own availability and quality, so a world state
with four dark facets is legible as exactly that rather than silently
thin -- the failure that let Curve run on 2 of 10 dimensions for a whole
session without anyone noticing.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

FACETS = ("market", "sectors", "breadth", "volatility", "liquidity",
          "options", "positioning", "cross_asset", "events", "crypto",
          "system_state")


@dataclass(frozen=True)
class PatternWorldState:
    as_of: str
    known_from: str
    session_date: str
    facets: dict
    facets_live: tuple
    facets_dark: tuple
    quality: dict
    birth_classification: str

    def as_dict(self) -> dict:
        return {"kind": "pattern_world_state", "as_of": self.as_of,
                "known_from": self.known_from,
                "session_date": self.session_date,
                "facets": dict(self.facets),
                "facets_live": list(self.facets_live),
                "facets_dark": list(self.facets_dark),
                "facet_coverage": f"{len(self.facets_live)}/{len(FACETS)}",
                "quality": dict(self.quality),
                "birth_classification": self.birth_classification,
                "decision_power": OBSERVATORY_POWER}


def _facet(status: str, payload=None, note: str | None = None) -> dict:
    d = {"status": status}
    if payload is not None:
        d["state"] = payload
    if note:
        d["note"] = note
    return d


def compose(*, as_of, known_from, session_date: str,
            market: dict | None = None,
            sector_state=None, breadth_state=None,
            options_state=None, positioning_state=None,
            frontier2_snapshot: dict | None = None,
            crypto_snapshot: dict | None = None,
            events_snapshot: dict | None = None,
            quality: dict | None = None,
            birth_classification: str = "HISTORICAL_CONTEXT"
            ) -> PatternWorldState:
    facets = {
        "market": _facet("LIVE", market) if market else _facet("DARK"),
        "sectors": (_facet("LIVE", sector_state.as_dict()) if sector_state
                    else _facet("DARK")),
        "breadth": (_facet("LIVE", breadth_state.as_dict()) if breadth_state
                    else _facet("DARK")),
        "volatility": _facet(
            "DARK", note="no realised-vol organ; options surface carries "
                         "implied only"),
        "liquidity": _facet(
            "DARK", note="no book/depth feed on the equities sleeve"),
        "options": (_facet("LIVE", options_state.as_dict()) if options_state
                    else _facet("DARK")),
        # LIVE once real facts exist, INTERFACE_ONLY while the contract
        # is defined but empty. The distinction matters: a reader must be
        # able to tell "we have lagged CFTC positioning" from "we have a
        # positioning-shaped hole".
        "positioning": (
            _facet("LIVE" if positioning_state.facts else "INTERFACE_ONLY",
                   positioning_state.as_dict(),
                   note=(None if positioning_state.facts else
                         "contract defined, no source acquired"))
            if positioning_state else _facet("DARK")),
        "cross_asset": _facet(
            "DARK", note="no cross-asset feed wired on this sleeve"),
        "events": (_facet("LIVE", events_snapshot) if events_snapshot
                   else _facet("DARK", note="EDGAR capture runs 24/7 but "
                                            "Catalyst is DORMANT by ruling")),
        "crypto": (_facet("LIVE", crypto_snapshot) if crypto_snapshot
                   else _facet("DARK", note="BTC perps sleeve NOT_AVAILABLE")),
        "system_state": (_facet("LIVE", frontier2_snapshot)
                         if frontier2_snapshot else _facet("DARK")),
    }
    live = tuple(f for f, v in facets.items() if v["status"] == "LIVE")
    dark = tuple(f for f, v in facets.items() if v["status"] != "LIVE")
    return PatternWorldState(
        as_of=str(as_of), known_from=str(known_from),
        session_date=session_date, facets=facets, facets_live=live,
        facets_dark=dark, quality=dict(quality or {}),
        birth_classification=birth_classification)
