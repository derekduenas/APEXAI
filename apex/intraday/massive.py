"""MassiveIntradayProvider — adapter V1, NOT WIRED until credentials exist.

Two-tier design per the P1A directive: Tier 1 = whole-market 1-minute
aggregates (the replay substrate); Tier 2 = on-demand quote/trade slices for
serious candidates only (never bulk history). The raw lake stores vendor-
UNADJUSTED bars with symbols as they existed at the time; APEX applies its
own corporate-action interpretation downstream.

Until the operator subscribes and provides MASSIVE_API_KEY via the
environment (the Sharadar key discipline applies identically: never in
files, logs, or URLs at rest), every data method raises NotWired with the
remediation -- it does not return empty frames, which would be a fabricated
'no market'.
"""

from __future__ import annotations

import os

from apex.intraday.contract import IntradayProvider

ENV_VAR = "MASSIVE_API_KEY"
ADAPTER_VERSION = "massive-adapter-0.1-unwired"


class NotWired(RuntimeError):
    """The Massive subscription/credentials do not exist yet."""


def _refuse(what: str):
    raise NotWired(
        f"MassiveIntradayProvider.{what}: no {ENV_VAR} in the environment. "
        f"This is an OPERATOR act: subscribe (checking the individual/"
        f"non-professional licensing terms), then export {ENV_VAR}. The "
        f"adapter fails closed rather than fabricating an empty market.")


class MassiveIntradayProvider(IntradayProvider):
    def __init__(self):
        self.wired = bool(os.environ.get(ENV_VAR, "").strip())

    def availability(self) -> dict:
        return {"provider": "massive", "adapter_version": ADAPTER_VERSION,
                "wired": self.wired,
                "tier1": "whole-market 1m aggregates (history to 2003-09)",
                "tier2": "on-demand quote/trade slices only",
                "status": "READY" if self.wired else "BLOCKED_EXTERNAL"}

    def get_bars(self, security_ids, start, end, resolution, session_filter):
        if not self.wired:
            _refuse("get_bars")
        raise NotWired("wired path lands with the certification sample")

    def get_reference_state(self, as_of):
        if not self.wired:
            _refuse("get_reference_state")
        raise NotWired("wired path lands with the certification sample")

    def get_corporate_actions(self, start, end):
        if not self.wired:
            _refuse("get_corporate_actions")
        raise NotWired("wired path lands with the certification sample")

    def get_quotes(self, security_ids, start, end):
        if not self.wired:
            _refuse("get_quotes")
        raise NotWired("Tier 2 slices are on-demand only, post-certification")

    def get_trades(self, security_ids, start, end):
        if not self.wired:
            _refuse("get_trades")
        raise NotWired("Tier 2 slices are on-demand only, post-certification")
