#!/usr/bin/env python
"""PATTERN OBSERVATORY SHADOW RUNTIME.

    python scripts/pattern_observatory_shadow_runtime.py [--minutes 420]
                                                         [--cadence 60]

THE THURSDAY FIREWALL. Tomorrow's official objective is validating the
repaired Alpaca sensor. This process runs in parallel as a pure
SHADOW_OBSERVER and must not be able to affect that:

  * it never imports apex.hunter / captain / execution / frontier /
    frontier2 -- enforced by an AST import-closure test, not by this
    docstring
  * it writes ONLY under results/pattern_observatory/
  * if it crashes, every official service continues untouched
  * it reads production artifacts as FILES, which crosses no import
    boundary (the same pattern daily_forensics_v2.py already uses)

WHAT SUCCESS LOOKS LIKE TOMORROW -- and it is deliberately not "all
modules populated":

    real sector/breadth input -> real PatternWorldState -> real
    PatternState -> real PatternAssassin review -> persisted prospective
    observation -> resolvable by the outcome resolver later

with probability NOT_ESTIMABLE, decision_power NONE_PATTERN_OBSERVATORY
and capital authority NONE throughout. If that chain traverses naturally
even once, V1 has done its job.

DEGRADED INPUT IS RECORDED, NEVER DROPPED -- but a degraded observation
is never equivalent to a clean one, and the quality vector travels with
it so a future reader can tell the difference.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

import pandas as pd  # noqa: E402

from apex.intraday.alpaca_fabric import load_live_bars  # noqa: E402
from apex.pattern_observatory import OBSERVATORY_POWER, WRITE_ROOT  # noqa: E402
from apex.pattern_observatory import abnormality as abn  # noqa: E402
from apex.pattern_observatory import birth as birthmod  # noqa: E402
from apex.pattern_observatory import breadth as brmod  # noqa: E402
from apex.pattern_observatory import cftc_positioning as cftcmod  # noqa: E402
from apex.pattern_observatory import finra_short_pressure as finmod  # noqa: E402
from apex.pattern_observatory import conjunction as cjmod  # noqa: E402
from apex.pattern_observatory import contradiction as cdmod  # noqa: E402
from apex.pattern_observatory import crypto_sensor as crymod  # noqa: E402
from apex.pattern_observatory import families as fammod  # noqa: E402
from apex.pattern_observatory import memory as mem  # noqa: E402
from apex.pattern_observatory import obs_features as obf  # noqa: E402
from apex.pattern_observatory import options_surface as osmod  # noqa: E402
from apex.pattern_observatory import pattern_assassin as pamod  # noqa: E402
from apex.pattern_observatory import pattern_state as psmod  # noqa: E402
from apex.pattern_observatory import positioning as posmod  # noqa: E402
from apex.pattern_observatory import information_lead as ilmod  # noqa: E402
from apex.pattern_observatory import probability as pbmod  # noqa: E402
from apex.pattern_observatory import resolution as resmod  # noqa: E402
from apex.pattern_observatory import quality as qmod  # noqa: E402
from apex.pattern_observatory import registry as regmod  # noqa: E402
from apex.pattern_observatory import sector_rotation as srmod  # noqa: E402
from apex.pattern_observatory import sequence as sqmod  # noqa: E402
from apex.pattern_observatory import summary as summod  # noqa: E402
from apex.pattern_observatory import support as supmod  # noqa: E402
from apex.pattern_observatory import world_state as wsmod  # noqa: E402

SERVICE_NAME = "pattern_observatory_shadow_runtime"
ROOT = Path(WRITE_ROOT)
HEALTH_PATH = ROOT / "runtime" / "health.json"
ERRORS = ROOT / "errors" / "error_ledger.jsonl"

MARKET_PROXY = "SPY"
INDEX_SUBJECTS = ("SPY", "QQQ", "IWM")
OPTION_STATES = Path("results/option_analytics/live/states.jsonl")
FRONTIER2_CURVE = Path("results/frontier2/curve_ledger.jsonl")
FRONTIER2_SYSCOG = Path("results/frontier2/system_cognition_ledger.jsonl")

# HEALTH IS NOT PID LIVENESS. Four separate axes, because a process can
# be alive while making no progress, and can make input progress while
# producing no patterns -- the 2026-08-19 lesson stated as a contract.
PROCESS_ALIVE = "PROCESS_ALIVE"
INPUT_PROGRESS = "INPUT_PROGRESS"
PATTERN_PROGRESS = "PATTERN_PROGRESS"
DEGRADED_INPUT = "DEGRADED_INPUT"
STALLED = "STALLED"
FAILED = "FAILED"


def _err(cycle: int, stage: str, exc: BaseException) -> None:
    rec = {"kind": "observatory_runtime_error", "cycle": cycle,
           "stage": stage, "exception": f"{type(exc).__name__}: {exc}",
           "traceback": traceback.format_exc()[-2000:],
           "as_of": str(pd.Timestamp.now(tz="UTC")),
           "recovery_action": "cycle continues; this stage is skipped",
           "decision_power": OBSERVATORY_POWER}
    try:
        ERRORS.parent.mkdir(parents=True, exist_ok=True)
        with ERRORS.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:                                       # noqa: BLE001
        pass


def _session_bars(symbol: str, day: str, now):
    b = load_live_bars(symbol, day)
    if b is None or not len(b):
        return None
    open_utc = pd.Timestamp(f"{day} 13:30:00+00:00")
    reg = b[(b["event_time_utc"] >= open_utc) & (b["event_time_utc"] <= now)]
    return reg if len(reg) else None


def _bar_quality(bars, *, symbol, now):
    if bars is None or not len(bars):
        return qmod.assess_bar_input(
            source="ALPACA_WEBSOCKET_SIP_V1", event_time=None,
            known_from=now, now=now, gap_fraction=None, bars_observed=0)
    gap_ms = float(bars["gap_duration_ms"].fillna(0).sum())
    gap_fraction = gap_ms / 1000.0 / max(len(bars) * 60.0, 1.0)
    return qmod.assess_bar_input(
        source="ALPACA_WEBSOCKET_SIP_V1",
        event_time=bars["event_time_utc"].max(), known_from=now, now=now,
        gap_fraction=gap_fraction, bars_observed=len(bars),
        coverage_fraction=1.0 - min(gap_fraction, 1.0))


def _read_recent(path: Path, day: str, limit: int = 4000) -> list:
    if not path.exists():
        return []
    out = []
    try:
        lines = path.read_text().splitlines()[-limit:]
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(r.get("as_of", "")).startswith(day):
            out.append(r)
    return out


class State:
    def __init__(self):
        self.conj = cjmod.ConjunctionEngine()
        self.seq = sqmod.SequenceEngine()
        self.prior_sector_fraction = None
        self.prior_velocity = None
        self.prior_surface = {}
        self.prior_ranks = {}
        self.leadership_history = {}
        self.history = {}          # metric -> [values]
        self.history_sessions = {}  # metric -> [session dates]
        self.positioning_facts = ()
        self.positioning_fetched_on = None
        self.short_pressure = None
        self.cycles = 0
        self.patterns_seen = 0
        self.last_input_at = None
        self.last_pattern_at = None


def run_cycle(state: State, cycle: int, now, day: str, birth: dict | None
              ) -> dict:
    out = {"cycle": cycle, "as_of": str(now), "patterns": 0, "errors": 0,
           "facets_live": 0}

    # ---------------------------------------------------- market + sectors
    spy = _session_bars(MARKET_PROXY, day, now)
    spy_q = _bar_quality(spy, symbol=MARKET_PROXY, now=now)
    mkt_ret = obf.obs_return_from_open(spy, symbol=MARKET_PROXY,
                                       known_from=now).value if spy is not None else None
    if spy is not None:
        state.last_input_at = str(now)

    sector_obs, sector_rows = [], []
    for sym in srmod.SECTOR_ETFS:
        try:
            b = _session_bars(sym, day, now)
            sector_obs.append(srmod.observe_sector(
                sym, b, market_return=mkt_ret, known_from=now,
                quality=_bar_quality(b, symbol=sym, now=now).quality))
            if b is not None and len(b):
                vw = obf.obs_vwap(b, symbol=sym, known_from=now).value
                orr = obf.obs_opening_range(b, symbol=sym, known_from=now)
                last = float(b["close"].iloc[-1])
                sector_rows.append({
                    "return_from_open": obf.obs_return_from_open(
                        b, symbol=sym, known_from=now).value,
                    "above_obs_vwap": (last > vw) if vw else None,
                    "above_opening_range": orr["state"] == "ABOVE_OR_HIGH"})
        except Exception as e:                              # noqa: BLE001
            _err(cycle, f"sector:{sym}", e)
            out["errors"] += 1

    sector_state = None
    try:
        sector_state = srmod.classify(
            sector_obs, market_return=mkt_ret, prior_ranks=state.prior_ranks,
            leadership_history=state.leadership_history, as_of=now,
            known_from=now, quality=spy_q.quality)
        state.prior_ranks = {o.symbol: o.rank for o in sector_state.sectors
                             if o.rank}
        state.leadership_history = dict(sector_state.leadership_persistence)
    except Exception as e:                                  # noqa: BLE001
        _err(cycle, "sector_rotation", e)
        out["errors"] += 1

    breadth_state = None
    try:
        breadth_state = brmod.compute(
            sector_rows=sector_rows, universe_rows=[], index_return=mkt_ret,
            prior_fraction=state.prior_sector_fraction,
            prior_velocity=state.prior_velocity, as_of=now, known_from=now,
            quality=spy_q.quality)
        state.prior_velocity = breadth_state.velocity
        if breadth_state.sector.advancing_fraction is not None:
            state.prior_sector_fraction = breadth_state.sector.advancing_fraction
    except Exception as e:                                  # noqa: BLE001
        _err(cycle, "breadth", e)
        out["errors"] += 1

    # ------------------------------------------------- options + positioning
    options_state = None
    try:
        opt = _read_recent(OPTION_STATES, day)
        spy_opts = [r for r in opt if str(r.get("symbol", "")).startswith("SPY")]
        if spy_opts:
            options_state = osmod.observe(
                "SPY", spy_opts[-120:], prior=state.prior_surface.get("SPY"),
                as_of=now, known_from=now)
            state.prior_surface["SPY"] = options_state
    except Exception as e:                                  # noqa: BLE001
        _err(cycle, "options_surface", e)
        out["errors"] += 1

    # POSITIONING: fetched ONCE PER SESSION, not per cycle. CFTC is a
    # weekly report and FINRA is a daily file -- re-fetching every minute
    # would hammer two free public sources for data that cannot have
    # changed, which is both rude and a good way to get rate-limited off
    # the only positioning APEX has.
    if state.positioning_fetched_on != day:
        try:
            ing = cftcmod.ingest(now=now)
            state.positioning_facts = tuple(
                f for f in ing["facts"] if f.value is not None)
            print(f"  CFTC: {len(state.positioning_facts)} facts, "
                  f"report {ing['most_recent_report']}, "
                  f"lag {ing['max_freshness_days']}d", flush=True)
        except Exception as e:                              # noqa: BLE001
            _err(cycle, "cftc_ingest", e)
            out["errors"] += 1
        # FINRA: EXPECTED PUBLICATION LATENCY IS NOT AN ERROR.
        # Today's off-exchange file does not exist until after the close.
        # Writing that to the error ledger would put noise in tomorrow's
        # forensics that reads as operationally meaningful. So the policy
        # decides, the latest LEGITIMATELY PUBLISHED file is used, and
        # only a real transport or parse fault reaches _err().
        try:
            got = finmod.latest_published(as_of=now)
            state.short_pressure = (
                finmod.market_wide(got["rows"], session_date=got["market_date"],
                                   known_from=got["known_from"])
                if got["rows"] else None)
            if state.short_pressure is not None:
                state.short_pressure["source_state"] = got["source_state"]
                state.short_pressure["staleness_days"] = got.get("staleness_days")
                print(f"  FINRA: {got['symbols']} symbols for "
                      f"{got['market_date']} ({got['source_state']}, "
                      f"{got.get('staleness_days')}d), ratio "
                      f"{state.short_pressure['short_ratio']:.4f}", flush=True)
            if got["is_error"]:
                _err(cycle, "finra_ingest",
                     RuntimeError(f"{got['source_state']}: {got['failures']}"))
                out["errors"] += 1
            else:
                print(f"  FINRA state {got['source_state']} "
                      f"(expected, not an error)", flush=True)
        except Exception as e:                              # noqa: BLE001
            _err(cycle, "finra_ingest", e)
            out["errors"] += 1
        state.positioning_fetched_on = day

    positioning_state = posmod.observe(as_of=now, known_from=now,
                                       facts=state.positioning_facts)

    f2 = None
    try:
        sc = _read_recent(FRONTIER2_SYSCOG, day, limit=200)
        if sc:
            f2 = {"system_cognition": sc[-1].get("overall_quality"),
                  "source": "results/frontier2/system_cognition_ledger.jsonl",
                  "note": "READ-ONLY; the Observatory is the first consumer "
                          "of this ledger"}
    except Exception as e:                                  # noqa: BLE001
        _err(cycle, "frontier2_read", e)
        out["errors"] += 1

    # ------------------------------------------------------------- world
    birth_class = birthmod.classify(now, birth=birth)

    # CRYPTO SLEEVE (2026-08-21): a live healthy capture daemon existed
    # while this facet sat declared DARK -- the adapter lights it with
    # honest sleeve observability (sensor/book/arena state, market
    # features explicitly NOT_DERIVED yet).
    crypto_snap = None
    try:
        cr = crymod.observe(now=now)
        crypto_snap = cr.get("state") if cr.get("status") == "LIVE" else None
        if crypto_snap is None:
            out.setdefault("facets_dark_reasons", {})["crypto"] = \
                cr.get("reason")
    except Exception as e:                          # noqa: BLE001
        _err(cycle, "crypto_sensor", e)
        out["errors"] += 1

    world = wsmod.compose(
        as_of=now, known_from=now, session_date=day,
        market={"proxy": MARKET_PROXY, "return_from_open": mkt_ret,
                "quality": spy_q.quality},
        sector_state=sector_state, breadth_state=breadth_state,
        options_state=options_state, positioning_state=positioning_state,
        frontier2_snapshot=f2, crypto_snapshot=crypto_snap,
        quality=spy_q.as_dict(),
        birth_classification=birth_class)
    out["facets_live"] = len(world.facets_live)
    mem.append(mem.WORLD_LEDGER, world.as_dict())

    # ------------------------------------------------------- abnormality
    if breadth_state is not None and breadth_state.sector.advancing_fraction is not None:
        key = "sector_advancing_fraction"
        hist = state.history.setdefault(key, [])
        sess = state.history_sessions.setdefault(key, [])
        a = abn.assess(key, "MARKET", breadth_state.sector.advancing_fraction,
                       list(hist), session_dates=list(sess), as_of=now,
                       known_from=now)
        hist.append(breadth_state.sector.advancing_fraction)
        sess.append(day)
        out["breadth_abnormality"] = a.state

    # ------------------------------------- components -> conjunction -> pattern
    active = {}
    if sector_state is not None and sector_state.state not in ("UNKNOWN", "MIXED"):
        active["sector_rotation"] = sector_state.state
        if sector_state.rank_changes:
            active["sector_leadership_change"] = True
        if sector_state.dispersion.get("value"):
            active["sector_dispersion"] = sector_state.dispersion["value"]
    if breadth_state is not None:
        if breadth_state.state in ("DETERIORATING", "COLLAPSING", "NARROWING"):
            active["breadth_deteriorating"] = breadth_state.state
        elif breadth_state.state in ("IMPROVING", "BROAD_PARTICIPATION"):
            active["breadth_improving"] = breadth_state.state
        if breadth_state.divergence != "NONE":
            active["breadth_divergence"] = breadth_state.divergence
    if mkt_ret is not None:
        active["curve_negative" if mkt_ret < 0 else "curve_positive"] = mkt_ret
    if options_state is not None and options_state.state not in ("UNKNOWN",
                                                                 "STABLE"):
        active["options_surface_state"] = options_state.state
        if "VOL_REPRICING" in options_state.state:
            active["vol_repricing"] = options_state.state

    states, reviews = [], []
    if len(active) >= 2:
        # The sector/breadth quality that bar quality alone cannot supply.
        sq = qmod.PatternInputQuality(
            source="OBSERVATORY_SECTOR_BREADTH", event_time=str(now),
            known_from=str(now), freshness_s=0.0,
            coverage_fraction=(sector_state.sectors_observed / 11
                               if sector_state else 0.0),
            gap_fraction=None, missing_observations=None, staleness="FRESH",
            integrity="OK",
            quality=(sector_state.quality if sector_state else "UNKNOWN"),
            feature_sufficiency={
                "sector_leadership": (sector_state.quality
                                      if sector_state else "UNKNOWN"),
                "breadth": (breadth_state.quality
                            if breadth_state else "UNKNOWN")})
        osq = qmod.assess_generic_input(
            source="OPTION_ANALYTICS_SURFACE", event_time=now, known_from=now,
            now=now, features=("options_surface",),
            available=options_state is not None and options_state.estimable,
            unavailable_reason="surface suppressed or insufficient")

        # THE SUPPORT FIX. Loaded ONCE per cycle (not once per matching
        # family) and reused -- the ledger only grows during this cycle
        # via mem.append() calls below, which happen AFTER every family's
        # support was already computed, so no family can see its own
        # not-yet-written row.
        ledger_rows = supmod.load_ledger()

        for fam in fammod.matching(set(active)):
            try:
                c = state.conj.observe(
                    subject=MARKET_PROXY, market="EQUITIES_INTRADAY",
                    active_components=active,
                    quality_vector={"bars": spy_q.quality},
                    regime="UNKNOWN", now=now, known_from=now,
                    family_id=fam.family_id)
                if c is None:
                    continue
                v = qmod.combine([spy_q, sq, osq],
                                 required_features=fam.required_features)
                seq = state.seq.observe(
                    sequence_id=f"{fam.family_id}:{MARKET_PROXY}:{day}",
                    family_id=fam.family_id, subject=MARKET_PROXY,
                    market="EQUITIES_INTRADAY",
                    declared_steps=fam.sequence_steps,
                    active_steps=set(active), now=now, known_from=now)
                # family-scoped id (schema v2) so contradiction rows carry
                # the same identity the PatternState will persist
                fid = cjmod.family_pattern_id(
                    family_id=fam.family_id, subject=c.subject,
                    conjunction_id=c.pattern_id, first_seen=c.first_seen)
                con = cdmod.search(
                    pattern_id=fid, family_id=fam.family_id,
                    active_components=set(active),
                    independence=c.independence, quality_verdict=v, as_of=now)
                sup = supmod.aggregate(ledger_rows, family_id=fam.family_id,
                                       as_of=now)
                st = psmod.build(
                    conjunction=c, family=fam, quality_verdict=v,
                    sequence_state=seq, contradiction=con, support=sup,
                    now=now, known_from=now)
                rv = pamod.review(
                    st, clock_violation=(spy_q.integrity != "OK"),
                    sequence_state=seq, as_of=now, known_from=now)

                rec = st.as_dict()
                rec["birth_classification"] = birth_class
                mem.append(mem.PATTERN_LEDGER, rec)
                mem.append(mem.SEQUENCE_LEDGER, seq.as_dict())
                mem.append(mem.ASSASSIN_LEDGER, rv.as_dict())
                states.append(st)
                reviews.append(rv)
                state.patterns_seen += 1
                state.last_pattern_at = str(now)
            except Exception as e:                          # noqa: BLE001
                _err(cycle, f"pattern:{fam.family_id}", e)
                out["errors"] += 1

    # OUTCOME RESOLUTION LOOP (living-organism diagnostic, 2026-08-21:
    # outcomes.resolve() had ZERO live callers -- the learning cycle was
    # severed; episodes could be minted but never learn what happened
    # next). One sweep per cycle: resolve every unresolved episode x
    # horizon whose window has genuinely elapsed IN THE BARS.
    try:
        res_counters = resmod.run_cycle(
            bars_by_subject={MARKET_PROXY: spy}, now=now)
        out["outcomes"] = {k: v for k, v in res_counters.items()
                           if v and k != "newly_terminal"}

        # INFORMATION LEAD, finally CALLED -- once per episode, on the
        # cycle its LEAD_HORIZON outcome resolves. Under its n-floor
        # summarize() refuses a verdict; each measurement is still
        # honest, durable evidence.
        for ep in res_counters.get("newly_terminal", []):
            try:
                lead = ilmod.measure(
                    organ="PATTERN_OBSERVATORY",
                    subject=ep["subject"],
                    observation=str(ep["family_id"]),
                    first_known_at=ep["first_seen"], bars=spy,
                    known_from=now)
                rec = (lead.as_dict() if hasattr(lead, "as_dict")
                       else dict(lead.__dict__))
                rec["kind"] = "pattern_information_lead"
                rec["pattern_id"] = ep["pattern_id"]
                rec["episode_first_seen"] = ep["first_seen"]
                rec["birth_classification"] = birth_class
                rec["decision_power"] = OBSERVATORY_POWER
                mem.append(mem.WORLD_LEDGER, rec)
            except Exception as e:                  # noqa: BLE001
                _err(cycle, "information_lead", e)
                out["errors"] += 1

        # PROBABILITY + INFORMATION LEAD, finally CALLED (both organs
        # were imported/built and never invoked). estimate() refuses via
        # its own gates until support is earned -- the point tonight is
        # that its refusal is now COMPUTED and PERSISTED each cycle, not
        # implied by an unwired module. Lead measurement runs on the
        # resolved corpus; below its n-floor it reports honestly.
        if states:
            oc_rows = mem.read(mem.OUTCOME_LEDGER)
            for st in states:
                try:
                    corpus = resmod.outcome_corpus(
                        oc_rows, family_id=st.family_id,
                        horizon_minutes=30, as_of=now)
                    prof = pbmod.SupportProfile(
                        prospective_n=st.prospective_n,
                        distinct_sessions=st.distinct_sessions,
                        distinct_regimes=st.distinct_regimes,
                        distinct_subjects=st.distinct_symbols)
                    est = pbmod.estimate(
                        pattern_id=st.pattern_id,
                        family_id=st.family_id, subject=st.subject,
                        support=prof, regime=st.regime,
                        current_state={}, history=[],
                        prior_outcomes=corpus["returns"],
                        as_of=now, known_from=now)
                    mem.append(mem.WORLD_LEDGER, {
                        "kind": "pattern_probability_check",
                        "pattern_id": st.pattern_id,
                        "family_id": st.family_id,
                        "corpus_n": corpus["n"],
                        "estimate": est.as_dict()
                        if hasattr(est, "as_dict") else est,
                        "as_of": str(now), "known_from": str(now),
                        "birth_classification": birth_class,
                        "decision_power": OBSERVATORY_POWER})
                except Exception as e:              # noqa: BLE001
                    _err(cycle, f"probability:{st.family_id}", e)
                    out["errors"] += 1
    except Exception as e:                          # noqa: BLE001
        _err(cycle, "outcome_resolution", e)
        out["errors"] += 1

    # TERMINAL TRANSITIONS (2026-08-20 finding: expire() existed, tested,
    # NEVER CALLED -- an entire prospective session produced zero
    # BROKEN/EXPIRED rows and episodes just silently stopped updating.
    # That was a PERSISTENCE_DEFECT, not market behavior). An episode's
    # END is evidence: the outcome resolver needs to know when the
    # configuration stopped holding, not merely when its last row
    # happened to be written.
    try:
        for gone in state.conj.expire(now=now):
            for fam in fammod.matching(set(gone.components)):
                mem.append(mem.PATTERN_LEDGER, {
                    "kind": "pattern_episode_end",
                    "pattern_id": cjmod.family_pattern_id(
                        family_id=fam.family_id, subject=gone.subject,
                        conjunction_id=gone.pattern_id,
                        first_seen=gone.first_seen),
                    "conjunction_id": gone.pattern_id,
                    "pattern_id_schema_version":
                        cjmod.PATTERN_ID_SCHEMA_VERSION,
                    "family_id": fam.family_id, "subject": gone.subject,
                    "market": gone.market,
                    "first_seen": gone.first_seen,
                    "last_seen": gone.last_seen,
                    "duration_s": gone.duration_s,
                    "regime": gone.regime,
                    "current_status": "EXPIRED",
                    # BROKEN (a required component visibly failing while
                    # tracked) vs EXPIRED (idle timeout) is NOT yet
                    # discriminated -- recorded honestly rather than
                    # guessed. All terminal rows are EXPIRED for now.
                    "terminal_discrimination": "EXPIRED_ONLY_V1",
                    "known_from": str(now),
                    "birth_classification": birth_class,
                    "decision_power": OBSERVATORY_POWER})
    except Exception as e:                                  # noqa: BLE001
        _err(cycle, "expire", e)
        out["errors"] += 1

    out["patterns"] = len(states)
    if states:
        s = summod.build(as_of=now, known_from=now, world=world,
                         pattern_states=states, assassin_reviews=reviews,
                         session_date=day)
        (ROOT / "summary").mkdir(parents=True, exist_ok=True)
        (ROOT / "summary" / f"{day}.json").write_text(
            json.dumps(s, indent=2, default=str))
    return out


def write_health(state: State, status: str, extra: dict | None = None) -> None:
    rec = {"kind": "pattern_observatory_health", "service": SERVICE_NAME,
           "status": status, "cycles": state.cycles,
           "patterns_observed": state.patterns_seen,
           "last_input_at": state.last_input_at,
           "last_pattern_at": state.last_pattern_at,
           "as_of": str(pd.Timestamp.now(tz="UTC")),
           "health_axes": {
               "process_alive": True,
               "input_progress": state.last_input_at is not None,
               "pattern_progress": state.last_pattern_at is not None},
           "pid_liveness_is_not_health": True,
           "decision_power": OBSERVATORY_POWER}
    rec.update(extra or {})
    try:
        HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_PATH.write_text(json.dumps(rec, indent=2, default=str))
    except Exception:                                       # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=420.0)
    ap.add_argument("--cadence", type=float, default=60.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    birth = birthmod.load()
    if birth is None:
        birth = birthmod.mint(
            now=pd.Timestamp.now(tz="UTC"),
            code_lineage="pattern_observatory V1 built 2026-08-19 post-market",
            families=len(fammod.FAMILIES))
        for f in fammod.FAMILIES:
            mem.append(mem.FAMILY_REGISTRY, f.as_dict())
        print(f"BIRTH MINTED {birth['birth_timestamp']} "
              f"hash={birth['birth_hash']}", flush=True)
    else:
        print(f"birth already minted {birth['birth_timestamp']}", flush=True)

    v = regmod.violations()
    if v:
        print(f"REGISTRY VIOLATIONS -- refusing to start: {v}", flush=True)
        write_health(State(), FAILED, {"registry_violations": v})
        return 2

    st = State()
    t_end = time.time() + a.minutes * 60
    print(f"PATTERN_OBSERVATORY_SHADOW_RUNTIME start "
          f"decision_power={OBSERVATORY_POWER}", flush=True)

    while True:
        st.cycles += 1
        now = pd.Timestamp.now(tz="UTC")
        day = str(now.tz_convert("America/New_York").date())
        try:
            r = run_cycle(st, st.cycles, now, day, birth)
            status = (PATTERN_PROGRESS if r["patterns"]
                      else INPUT_PROGRESS if st.last_input_at
                      else PROCESS_ALIVE)
            print(f"{now:%H:%M:%S} cycle={st.cycles} facets={r['facets_live']}/11 "
                  f"patterns={r['patterns']} errors={r['errors']}", flush=True)
            write_health(st, status, {"last_cycle": r})
        except Exception as e:                              # noqa: BLE001
            _err(st.cycles, "run_cycle", e)
            write_health(st, FAILED, {"error": f"{type(e).__name__}: {e}"})
            print(f"{now:%H:%M:%S} cycle={st.cycles} FAILED "
                  f"{type(e).__name__}: {e}", flush=True)
        if a.once or time.time() >= t_end:
            break
        time.sleep(max(1.0, min(a.cadence, t_end - time.time())))

    write_health(st, "COMPLETE")
    print("PATTERN_OBSERVATORY_SHADOW_RUNTIME stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
