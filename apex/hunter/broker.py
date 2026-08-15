"""Abstract BrokerAdapter -- the seam that keeps Hunter broker-independent.

Robinhood may become adapter V1 SOMEDAY; nothing in Hunter may import a
broker by name. In this project phase every LIVE-side method is
STRUCTURALLY DISABLED: calling one raises, always, in every subclass,
because the base class seals them -- a subclass cannot re-enable live
execution by overriding, only a future dated governance change to THIS
file can. Paper/shadow methods are abstract and implementable now.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LiveExecutionDisabled(RuntimeError):
    """Live execution is disabled in this project phase, structurally."""


class BrokerAdapter(ABC):
    """Read + paper/shadow only. The live methods are FINAL and disabled."""

    # -- read-side (implementable) -------------------------------------------
    @abstractmethod
    def market_data_status(self) -> dict: ...

    @abstractmethod
    def portfolio(self) -> dict: ...

    @abstractmethod
    def positions(self) -> list: ...

    # -- paper / shadow (implementable) --------------------------------------
    @abstractmethod
    def paper_execute(self, thesis_hash: str, side: str, qty: float,
                      limit: float) -> dict: ...

    @abstractmethod
    def shadow_record(self, thesis_hash: str, intended: dict) -> dict: ...

    # -- live-side: sealed. NOT abstract, NOT overridable-to-enable ----------
    def place_order(self, *a, **k):
        raise LiveExecutionDisabled(
            "place_order is disabled in this project phase. Enabling it is a "
            "dated governance change to apex/hunter/broker.py, not a subclass.")

    def cancel_order(self, *a, **k):
        raise LiveExecutionDisabled("cancel_order is disabled in this phase.")

    def modify_order(self, *a, **k):
        raise LiveExecutionDisabled("modify_order is disabled in this phase.")

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        for sealed in ("place_order", "cancel_order", "modify_order"):
            if sealed in cls.__dict__:
                raise TypeError(
                    f"{cls.__name__} attempts to override {sealed}: live "
                    f"execution cannot be re-enabled by subclassing.")
