"""DECISION_CONTEXT_IDENTITY_V1 — what a decision was ACTUALLY made on.

THE DEFECT THIS ADDRESSES. `snapshot_id` is `state_hash[:32]`, and `TwinSources.snapshot()` never passes
`chain_meta` to `compose()`, so the option chain and the selected quote contribute nothing to it. Two scans on
completely different chains -- a 650 CALL at 2.45 and a 900 PUT at 88.00 -- produce the SAME `snapshot_id`, while
the decision record uses that id to name the market state the decision was made on.

`snapshot_id`'s own declared scope is ACCURATE and is PRESERVED here: it identifies the underlying state. This
module is ADDITIVE and versioned. It binds the things a decision is actually made on, each as its own component,
so a reviewer can tell WHICH part differed rather than only that something did.

WHAT IS DELIBERATELY NOT BOUND INTO IT: a later execution re-quote. A fill happens after the decision, on a later
clock, from a possibly different source; folding it back into the decision's context would backdate information
the decision never had -- the same hindsight the availability contract exists to prevent. Execution quotes bind
separately, per fill attempt, via `execution_quote_binding`.

ORDERING. Chain rows are canonicalised and SORTED, because the set of contracts offered is what the decision saw;
the order a provider happened to deliver them in has no declared meaning. If an ordering ever acquires meaning it
must be declared and bound explicitly, not inherited by accident."""
from __future__ import annotations

from apex.options_pilot.records import canonical_hash

SCHEMA = "DECISION_CONTEXT_IDENTITY_V1"

CONTRACT_KEYS = ("expiration", "strike", "right")
QUOTE_KEYS = ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch", "observation_id")


def normalize_contract(row: dict) -> dict:
    """The contract as the candidate builder sees it, plus the quote fields that were actually attached."""
    out = {k: row.get(k) for k in CONTRACT_KEYS}
    out.update({k: row.get(k) for k in QUOTE_KEYS if k in row})
    return out


def normalize_chain(chain_rows) -> list:
    """Canonical and order-insensitive. Duplicates are RETAINED, not collapsed: a provider delivering the same
    contract twice is a fact about the input, and the existing duplicate policy decides what it means."""
    rows = [normalize_contract(r) for r in (chain_rows or []) if isinstance(r, dict)]
    return sorted(rows, key=lambda r: canonical_hash(r))


def decision_context_identity(*, snapshot: dict, chain_rows, reference_quote: dict | None = None,
                              config: dict | None = None) -> dict:
    """Bind the underlying state, the chain actually used, and the decision-time reference quote.

    Every component is derived from the object that was CONSUMED -- the caller passes what it used, not a
    separately fetched copy, which would identify a different read of the world."""
    if not isinstance(snapshot, dict) or not snapshot.get("snapshot_id"):
        raise ValueError("DECISION_CONTEXT_REQUIRES_A_SNAPSHOT_WITH_AN_ID")
    chain = normalize_chain(chain_rows)
    components = {
        "snapshot_id": snapshot["snapshot_id"],
        "underlying_state_digest": snapshot["state_hash"],
        "as_of_epoch": snapshot["as_of_epoch"],
        "symbol": snapshot["symbol"],
        "n_bars_available": snapshot.get("n_bars_available"),
        "chain_digest": canonical_hash(chain),
        "n_chain_rows": len(chain),
        "reference_quote_digest": (canonical_hash({k: reference_quote.get(k) for k in QUOTE_KEYS})
                                   if isinstance(reference_quote, dict) else None),
        "config_digest": (canonical_hash(config) if config is not None else None),
    }
    return {
        "schema": SCHEMA,
        "components": components,
        "context_id": "ctx:" + canonical_hash(components)[:32],
        "covers": ("the underlying snapshot, the normalized option chain used for candidate construction, the "
                   "decision-time reference quote, and the configuration identity"),
        "does_not_cover": ("execution re-quotes, which happen after the decision on a later clock and bind to "
                           "their own fill attempt via execution_quote_binding()"),
        "snapshot_id_scope_preserved": ("snapshot_id continues to identify the UNDERLYING state only; this "
                                        "identity is additive and does not redefine it"),
    }


def execution_quote_binding(*, context_id: str, quote: dict, attempt: int, at_epoch: float,
                            source: str | None = None) -> dict:
    """One execution quote, bound to its own attempt and its own clock -- never folded backwards into the
    decision context it post-dates."""
    body = {"context_id": context_id, "attempt": int(attempt), "at_epoch": float(at_epoch), "source": source,
            "quote": {k: (quote or {}).get(k) for k in QUOTE_KEYS}}
    return {"schema": "EXECUTION_QUOTE_BINDING_V1", **body,
            "binding_id": "exq:" + canonical_hash(body)[:32],
            "law": ("bound to THIS attempt at THIS instant. A later re-quote is a new binding, never a revision "
                    "of the decision's context.")}
