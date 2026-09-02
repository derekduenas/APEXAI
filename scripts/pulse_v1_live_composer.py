"""PULSE_V1 live-provider composer -- ENGINEERING REGIME ONLY.

Feeds PulseV1Runtime from the REAL providers via the REAL compose()
path, so this gate proves actual schemas, timestamps and degraded-state
handling rather than a reimplementation that could quietly diverge.

EVIDENCE CLASS
--------------
Every packet is stamped PULSE_V1_PREBIRTH_ENGINEERING, never
LIVE_PROSPECTIVE. Real market data does NOT make this a prospective
regime. These observations are permanently excluded from World Model
training/validation/calibration, PRIME evaluation, alpha claims, and
the future PULSE_V1 birth evidence.

RESOURCE DISCIPLINE
-------------------
The engineering run uses a bounded subject set by default. No
engineering run may recreate host-wide memory pressure.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/opt/apex-repo")
for p in (str(REPO), str(REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from apex.intraday.sessions import classify              # noqa: E402
from apex.pulse.compose import (TIER_1_DEEP,             # noqa: E402
                                TIER_2_BROAD, compose)
from apex.pulse.sources import (CatalystIndex,           # noqa: E402
                                cross_asset_state,
                                options_state)
from apex.pulse.universe import load_universe, universe_version  # noqa: E402

# the REAL provider fetch used by the frozen V0 cycle
from pulse_cycle import snapshots, TIER_1, UNIVERSE_FILE  # noqa: E402

PREBIRTH_EVIDENCE_CLASS = "PULSE_V1_PREBIRTH_ENGINEERING"
REGIME = "PULSE_V1_PREBIRTH_LIVE_COMMISSIONING"


def _now():
    return datetime.now(timezone.utc)


class LiveProviderComposer:
    """Callable for PulseV1Runtime(compose_packets=...)."""

    def __init__(self, *, max_subjects: int = 24,
                 enable_options: bool = True):
        uni = load_universe(UNIVERSE_FILE,
                            builder="daily_closes_cache.py")
        self.universe_version = universe_version(uni)
        allsyms = [s for s in uni["symbols"] if s.isalpha()]
        tier1 = [s for s in TIER_1 if s in allsyms]
        rest = [s for s in allsyms if s not in tier1]
        # Tier-1 always, then a deterministic slice -- bounded on
        # purpose so the engineering run cannot pressure the host.
        self.subjects = tier1 + rest[:max(0, max_subjects - len(tier1))]
        self.tier1 = set(tier1)
        self.enable_options = enable_options
        self.provider_report: dict = {}

    def __call__(self, scheduled_time, ck) -> list[dict]:
        t_start = _now()
        session = classify(t_start)
        rep: dict = {"session": session.value, "errors": {}}

        # ---- Alpaca (real) -----------------------------------------
        t0 = time.monotonic()
        snaps, errors = snapshots(self.subjects)
        rep["alpaca_fetch_s"] = round(time.monotonic() - t0, 3)
        rep["alpaca_returned"] = len(snaps)
        rep["alpaca_errors"] = len(errors)
        t_capture_end = _now()

        # ---- Catalyst (real, causally fenced) -----------------------
        try:
            cat = CatalystIndex(t_start.isoformat())
            rep["catalyst"] = {
                "status": cat.status,
                "events_causally_visible": getattr(cat, "total", None),
                "state_hash": cat.state_hash()}
        except Exception as e:                            # noqa: BLE001
            cat = None
            rep["catalyst"] = {"status": "PROVIDER_ERROR",
                               "error": type(e).__name__}

        # ---- BTC cross-asset (real) ---------------------------------
        try:
            xasset = cross_asset_state(session=session, now=t_start)
            rep["cross_asset"] = {
                k: xasset.get(k) for k in
                ("btc_status", "btc_book_age_s", "btc_book_quality",
                 "btc_symbol", "btc_venue", "as_of", "state_hash")
                if k in xasset}
        except Exception as e:                            # noqa: BLE001
            xasset = None
            rep["cross_asset"] = {"btc_status": "PROVIDER_ERROR",
                                  "error": type(e).__name__}

        packets = []
        opt_states: dict = {}
        for sym in self.subjects:
            snap = snaps.get(sym)
            if not snap:
                rep["errors"][sym] = errors.get(sym, "no snapshot")
                continue
            # feed V1's BOUNDED rolling state from the live tape.
            # Without this the checkpoint stays trivially small and
            # "bounded state under live load" would prove nothing.
            q = snap.get("latestQuote") or {}
            mid = ((q["bp"] + q["ap"]) / 2
                   if q.get("bp") and q.get("ap") else None)
            if mid:
                # Stamp the observation with the CYCLE SLOT, not the
                # wall clock. run_cycle prunes the window by
                # scheduled_time; if observations carry a different
                # clock the cutoff can never reach them and the window
                # silently stops pruning -- which is exactly the
                # unbounded-state defect PULSE_V1 exists to prevent.
                # An observation belongs to its cycle, not to the
                # instant the code happened to run.
                ck.rolling.observe(sym, scheduled_time, price=mid,
                                   volume=(snap.get("dailyBar") or {}
                                           ).get("v"))
            opts = None
            if self.enable_options and sym in self.tier1:
                try:
                    # options_state REQUIRES spot -- omitting it was
                    # the TypeError that blanked every Tier-1 option
                    # state in the first run.
                    opts = options_state(sym, spot=mid, session=session,
                                         now=t_start)
                    st_ = (opts or {}).get("status")
                    opt_states[st_ or "none"] = \
                        opt_states.get(st_ or "none", 0) + 1
                except Exception as e:                    # noqa: BLE001
                    rep.setdefault("options_errors", {})[sym] = \
                        type(e).__name__
            # compose() wants a PER-SUBJECT catalyst dict, not the
            # index object -- cat.for_subject(sym), exactly as the
            # frozen V0 cycle calls it. Getting this wrong is why the
            # gate reuses the real path instead of reimplementing it.
            cat_sub = cat.for_subject(sym) if cat is not None else None
            st = compose(
                subject=sym, snapshot=snap,
                scheduled_time=scheduled_time.isoformat(),
                capture_start=t_start.isoformat(),
                capture_end=t_capture_end.isoformat(),
                complete_time=_now().isoformat(),
                universe_version=self.universe_version,
                catalyst=cat_sub, options=opts, cross_asset=xasset,
                # rolling/premarket are deliberately absent here: V1
                # holds that state in its BOUNDED CHECKPOINT, not in
                # V0's journal-backed stores. Their features will be
                # correctly reported ABSENT rather than fabricated.
                rolling=None, premarket_path=None,
                tier=(TIER_1_DEEP if sym in self.tier1
                      else TIER_2_BROAD),
                # NEVER LIVE_PROSPECTIVE in this regime
                evidence_class=PREBIRTH_EVIDENCE_CLASS)
            sealed = st.seal()
            sealed["regime"] = REGIME
            packets.append(sealed)
        rep["options"] = opt_states
        rep["packets"] = len(packets)
        self.provider_report = rep
        return packets
