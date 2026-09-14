"""PREMARKET_STAGES_V1 -- the ONE authoritative premarket stage operation.

R4's rule, and the reason this module exists: there must not be an audit-only absorb and a production absorb.
Everything that touches sources, normalization, dispositions, packet construction, the Captain and the seal lives
here once. `scripts/premarket_stage.py` (the production entry point) calls it. `scripts/premarket_run.py` (the
legacy long-sleeping runner, retained ONLY as a parity oracle) now delegates to the same functions, so the two
paths cannot drift in what they absorb -- the only thing that differs between them is WHEN they run, which is
precisely the defect under repair.

THE DEFECT BEING REPAIRED, stated exactly. The legacy runner computed `wait = target - now` and then slept
`min(wait, 3600)` WITHOUT rechecking the target. A process that started sufficiently early therefore returned
from the sleep an hour later and absorbed immediately, hours before the stage it was labelling. On a controlled
early-start fixture beginning at 02:00 ET, the `0815_ET_initial` absorption ran at 03:00 ET. Whether launchd
actually produces such an early start on this host is a SEPARATE question that only the disposable
operating-system test can answer; the 02:00 case here is a controlled early-start fixture, not an observation of
launchd.

The repair is not a better sleep. It is that a stage DECIDES: TOO_EARLY, ON_TIME, LATE_START or MISSED_WINDOW --
and an early invocation exits immediately instead of waiting.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCHEMA = "PREMARKET_STAGES_V1"

from apex.frontier.premarket import AS_OF_TIME_SEMANTICS_V2, PACKET_SCHEMA_V2  # noqa: E402

# ------------------------------------------------------------------ the schedule, in ONE place
# ET wall-clock targets. These were read out of scripts/premarket_run.py's own schedule list and its seal target;
# they are authoritative here now, and the legacy runner imports them rather than restating them.
ABSORB_STAGES = (("0815_ET_initial", 8, 15), ("0832_ET_post_macro", 8, 32),
                 ("0905_ET_refresh", 9, 5), ("0920_ET_final", 9, 20))
SEAL_STAGE = ("seal", 9, 25)
STAGE_SCHEDULE = ABSORB_STAGES + (SEAL_STAGE,)
STAGES = {name: (h, m) for name, h, m in STAGE_SCHEDULE}

WINDOW_S = 600.0        # a stage may start up to 10 minutes late; beyond that it is MISSED_WINDOW
ON_TIME_S = 60.0

PREMARKET_LAB_BUDGET = 6_000

FORBIDDEN_IN_BRIEF = ("buy ", "sell ", "position size", "probability",
                      "expected return", "place ", "authorize")

REQUIRED_BRIEF_SECTIONS = ("WHAT CHANGED OVERNIGHT",)

BRIEF_PROMPT = """You are the APEX premarket desk: five seats, one pass.
Read ONLY the sealed facts below (JSON). Roles: TAPE READER (what does
price/volume/sector behavior say), CATALYST ANALYST (which moves have
identified events; UNKNOWN_CATALYST_DISLOCATION names are flagged),
MACRO/CROSS-ASSET (note that MACRO_CALENDAR and CROSS_ASSET are
NOT_CONNECTED — treat that as a stated blind spot, never fill it from
memory), ADVERSARIAL TRADER (what obvious narrative may be misleading;
who may be crowded/trapped), CAPTAIN (synthesis).

Produce a CAPTAIN MORNING BRIEF in EXACTLY these sections:
WHAT CHANGED OVERNIGHT / MARKET WORLD / LEADING AREAS / WEAK AREAS /
IMPORTANT GAP NAMES / KNOWN CATALYSTS / NO CATALYST WITHIN ACTIVE
SOURCES / TODAY'S KNOWN SCHEDULED RISKS (state NOT_CONNECTED if the
calendar source is) / BIGGEST DATA BLIND SPOTS / WHAT COULD FOOL US AT
THE OPEN / SCENARIO A / SCENARIO B / SCENARIO C (each scenario: WOULD
EXPECT + INVALIDATED BY; qualitative, NO probabilities) / NAMES WORTH
WATCHING.

ELITE LENS (mandatory where catalysts exist): expectation vs reaction —
WHAT HAPPENED vs HOW PRICE REACTED. Good news + weak/negative reaction
IS information; bad news + refusal to fall IS information. Distinguish
gap QUALITY from gap size; sector sympathy from idiosyncratic moves;
note extension of overnight moves and possibly-trapped overnight
participants; end with WHAT WOULD MAKE THE CAPTAIN ABANDON THIS THESIS.

Rules: every factual claim must cite a field from the JSON (cite as
[field]). Anything not in the JSON is UNKNOWN. Never use the words: buy,
sell, position size, probability, expected return. These are PRIORS, not
truth — the tape gets the final vote.

SEALED FACTS:
{facts}
"""


BRIEF_TIMEOUT_S = 420


class StageRefused(RuntimeError):
    """A stage that cannot proceed honestly. Named, never silent."""


# ------------------------------------------------------------------ timing
def target_for(stage: str, now_et):
    """The stage's target as a WALL-CLOCK market instant.

    R5 DEFECT, found by the daylight-transition test. This was `now_et.normalize() + Timedelta(hours=h,
    minutes=m)`, which adds ELAPSED time to local midnight -- not the same thing as a wall-clock time on a day
    that has 23 or 25 hours. On the spring-forward date, midnight plus 8h15m of elapsed time is 09:15 local, so
    the 08:15 target was computed an hour late and an ON-TIME arrival was judged TOO_EARLY; on the fall-back
    date it was computed an hour early and an on-time arrival was judged MISSED_WINDOW.

    DORMANT, NOT LIVE, and the distinction matters: US daylight transitions fall on a SUNDAY in
    America/New_York and this job runs Monday to Friday, so no scheduled stage has ever hit it. It is fixed
    because a correctness property that holds only by a calendar coincidence is not a property. The legacy
    runner keeps the old construction deliberately -- it is the parity oracle, and this is a SECOND latent
    defect it carries, now on the record."""
    from apex.frontier import market_time as MT
    h, m = STAGES[stage]
    return MT.market_instant(str(now_et.date()), h, m)


def disposition(stage: str, now_et):
    """Decided, never slept through."""
    t = target_for(stage, now_et)
    delta = (now_et - t).total_seconds()
    if delta < -ON_TIME_S:
        return "TOO_EARLY", delta
    if delta <= WINDOW_S:
        return ("ON_TIME" if abs(delta) <= ON_TIME_S else "LATE_START"), delta
    return "MISSED_WINDOW", delta


# ------------------------------------------------------------------ symbols (unchanged selection, moved once)
def stage_symbols() -> list:
    """Indices + the bounded liquidity-top names from the frozen scan universe. This is verbatim the selection the
    legacy runner performed; it is a consumer read and introduces no new selection logic."""
    from apex.frontier.premarket import INDICES
    symbols = list(INDICES)
    uni = sorted(Path("results/hunter").glob("scan_universe_*.json"))
    if uni:
        try:
            u = json.loads(uni[-1].read_text())
            symbols += list(u.get("symbols", {}))[:25]
        except json.JSONDecodeError:
            pass
    return symbols


# ------------------------------------------------------------------ the transport seam
class RecordingTransport:
    """Wraps the EODHD chunk fetch so every raw response becomes a content-addressed blob BEFORE anything
    normalizes it, AND so the request and receipt instants are recorded as a source observation. Production
    writes both -- this is not audit scaffolding.

    It is also the boundary where a PROVIDER-DECLARED FUTURE availability is refused: a payload that says it
    became available after the instant this stage is reasoning about is dropped here, so its data never reaches
    the normalizer, the packet or the Captain prompt. Refusing it later would be too late -- the numbers would
    already be in the packet with a note attached."""

    def __init__(self, journal, inner=None, *, as_of_epoch=None):
        # `journal=None` records observations and refusals but writes no blobs. That is the form the LEGACY
        # oracle gets, so both producers build the same observation table from the same code and the new time
        # fields can be compared semantically between them.
        self.journal, self._inner, self.manifest = journal, inner, []
        self.observations, self.as_of_epoch = [], as_of_epoch

    def _real(self):
        if self._inner is not None:
            return self._inner
        from apex.frontier import premarket_runtime as RT
        sub = RT.transport()
        if sub is not None:
            return sub
        from apex.intraday.eodhd import fetch_intraday_chunk
        return fetch_intraday_chunk

    def __call__(self, symbol, lo, hi, gov, *a, **k):
        from apex.frontier import premarket_runtime as RT
        from apex.frontier import premarket_time as T
        req = RT.now_utc().timestamp()
        rows, src = self._real()(symbol, lo, hi, gov, *a, **k)
        rec = RT.now_utc().timestamp()
        available_at = _declared_availability(rows)
        obs = T.source_observation(
            source_id=symbol, source_kind="EODHD_PREMARKET",
            event_time=_latest_event_time(rows), request_time=req, receipt_time=rec,
            known_from=available_at, availability_basis=(T.BASIS_EXPLICIT if available_at is not None else None),
            source_timezone="UTC", carries_content=bool(rows),
            normalization=(T.NORM_ACCEPTED if rows else T.NORM_UNAVAILABLE))
        refused = T.provider_declared_future(obs, self.as_of_epoch)
        if refused:
            obs["normalization"] = T.NORM_REFUSED_FUTURE
            obs["refusal_reason"] = (
                "PROVIDER_DECLARED_AVAILABILITY_AFTER_STAGE_INSTANT: the payload claims it became available at "
                "%r, after the %r this stage reasons as of; its data was dropped at the transport boundary and "
                "never reached the normalizer, the packet or the Captain prompt" % (available_at, self.as_of_epoch))
            rows = []
        if self.journal is not None:
            sha = self.journal.put_blob({"symbol": symbol, "lo": lo, "hi": hi, "rows": rows, "source": src,
                                         "observation": obs})
            self.manifest.append({"key": "%s|%s|%s" % (symbol, lo, hi), "blob": sha, "source": src})
        self.observations.append(obs)
        return rows, src


def _latest_event_time(rows):
    """The newest instant the PROVIDER says its data is about. Absent rows give UNAVAILABLE, never `now`."""
    ts = [r.get("timestamp") for r in (rows or []) if isinstance(r, dict) and isinstance(r.get("timestamp"),
                                                                                        (int, float))]
    return float(max(ts)) if ts else None


def _declared_availability(rows):
    """A provider may state when a payload became available to us. EODHD does not, so this is normally None and
    known_from falls back to the receipt instant with its basis recorded as RECEIPT_INSTANT."""
    if isinstance(rows, dict):
        v = rows.get("available_at")
        return float(v) if isinstance(v, (int, float)) else None
    for r in (rows or []):
        if isinstance(r, dict) and isinstance(r.get("available_at"), (int, float)):
            return float(r["available_at"])
    return None


class ReplayTransport:
    """Serves the ORIGINAL captured bytes back. This is how a stage that crashed after capture resumes without
    refetching and without losing what it already saw."""

    def __init__(self, journal, manifest):
        self.journal = journal
        self.by_key = {m["key"]: m for m in manifest}
        self.served, self.observations = [], []

    def __call__(self, symbol, lo, hi, gov, *a, **k):
        key = "%s|%s|%s" % (symbol, lo, hi)
        m = self.by_key.get(key)
        if m is None:
            raise StageRefused("CAPTURE_MISSING_FOR_REPLAY: %s -- a resumed stage refuses to refetch a source it "
                               "has no record of capturing" % key)
        blob = self.journal.get_blob(m["blob"])     # re-hashed; an altered blob raises here
        self.served.append(key)
        if blob.get("observation"):
            self.observations.append(blob["observation"])
        return blob["rows"], blob["source"]


# ------------------------------------------------------------------ THE authoritative absorb
def absorb(label: str, *, as_of=None, fetch=None, symbols=None) -> dict:
    """One absorption: the legacy runner's selection and assembly, plus the production time model.

    R4 moved this here so there is exactly one absorb. R5 added the time model to it -- the observation table,
    the declared cutoff and the packet's instants -- so that a packet cannot be produced by ANY caller without
    carrying the instants that say how fresh it is.

    Note preserved deliberately, not fixed here: a fresh QuotaGovernor is constructed per absorption, so the
    'daily' LAB budget is in truth a per-stage budget. That was true of the legacy runner too. Changing it would
    change behaviour, and this brick's objective is to move the producer without moving its behaviour."""
    from apex.events.catalyst import catalyst_state
    from apex.events.cik_bridge import cik_of
    from apex.frontier import premarket_runtime as RT
    from apex.frontier import premarket_time as T
    from apex.frontier.premarket import assemble
    from apex.intraday.eodhd import QuotaGovernor

    collection_started_at = RT.now_utc().timestamp()
    as_of_epoch = (pd_ts(as_of).timestamp() if as_of is not None else collection_started_at)

    # The declared transport seam is resolved HERE, so the legacy oracle and the staged producer reach the same
    # transport. Resolving it in only one of them was the first thing the R4 parity run caught.
    fetch = fetch if fetch is not None else RT.transport()
    if not isinstance(fetch, (RecordingTransport, ReplayTransport)):
        # Always observed, even on the legacy path: a transport that is not observed produces a packet whose
        # freshness is once again unreconstructible, which is the defect this brick exists to close.
        fetch = RecordingTransport(None, inner=fetch, as_of_epoch=as_of_epoch)
    syms = list(symbols) if symbols is not None else stage_symbols()
    gov = QuotaGovernor(daily_budget=PREMARKET_LAB_BUDGET, purpose="LAB")

    catalyst_obs = []

    def cat(sym, now):
        req = RT.now_utc().timestamp()
        st = catalyst_state(sym, now, cik=cik_of(sym))
        rec = RT.now_utc().timestamp()
        for e in (st.events or ()):
            kf = _epoch(e.get("known_from"))
            catalyst_obs.append(T.source_observation(
                source_id="%s:%s" % (sym, e.get("accession")), source_kind="SEC_EDGAR",
                event_time=_epoch(e.get("event_time")), request_time=req, receipt_time=rec,
                known_from=kf, availability_basis=T.BASIS_EXPLICIT, source_timezone="UTC",
                normalization=T.NORM_ACCEPTED))
        if not st.events:
            # A MEASURED ABSENCE is itself an observation known at the query instant. Recording it is what lets a
            # reader distinguish "we asked and nothing matched" from "we never asked".
            catalyst_obs.append(T.source_observation(
                source_id=sym, source_kind="SEC_EDGAR", request_time=req, receipt_time=rec,
                source_timezone="UTC", carries_content=False,
                normalization=(T.NORM_ACCEPTED if st.status.startswith("NO_KNOWN_CATALYST")
                               else T.NORM_UNAVAILABLE)))
        return st

    pkt = assemble(symbols=syms, gov=gov, as_of=as_of, catalyst_lookup=cat, fetch=fetch)
    pkt["absorption_label"] = label

    # ---------------------------------------------------------------- the production time model
    absorption_finished_at = RT.now_utc().timestamp()
    observations = list(getattr(fetch, "observations", [])) + catalyst_obs
    receipts = [o["source_receipt_time"] for o in observations
                if isinstance(o.get("source_receipt_time"), (int, float))]
    # The DECLARED CUTOFF is the instant this packet stopped accepting input: never earlier than any receipt,
    # never taken from the seal clock.
    declared_cutoff = max([as_of_epoch, absorption_finished_at] + receipts)
    pkt["schema"] = PACKET_SCHEMA_V2
    pkt["source_observations"] = observations
    pkt["time"] = T.collection_times(collection_started_at=collection_started_at, observations=observations,
                                     declared_cutoff=declared_cutoff, created_at=absorption_finished_at)
    pkt["as_of_time_semantics"] = dict(AS_OF_TIME_SEMANTICS_V2)
    return pkt


def pd_ts(v):
    import pandas as pd
    t = pd.Timestamp(v)
    return t.tz_localize("UTC") if t.tz is None else t


def _epoch(v):
    if v is None or v == "UNAVAILABLE":
        return None
    try:
        return pd_ts(v).timestamp()
    except Exception:                                               # noqa: BLE001
        return None


def absorb_summary(pkt: dict) -> dict:
    return {"indices_ok": sum(1 for v in pkt["indices"].values() if v.get("status") == "OK"),
            "movers": len(pkt["gap_map"]),
            "unknown_catalyst": len(pkt["watch_map"]["UNKNOWN_CATALYST_MOVERS"])}


def observations(pkt: dict) -> dict:
    """The NORMALIZED layer, extracted from the packet the real builder produced: one typed state per symbol,
    plus the source-coverage matrix that says what was not looked at."""
    names = {a["symbol"]: a for a in pkt.get("gap_map", [])}
    return {"indices": pkt["indices"], "gap_map": pkt["gap_map"], "watch_map": pkt["watch_map"],
            "source_coverage": pkt["source_coverage"], "blind_spots": pkt["blind_spots"],
            "named_movers": sorted(names)}


def source_dispositions(pkt: dict) -> dict:
    """Per-source disposition as the REAL builder decides it. Nothing is asserted here that the builder does not
    actually do: statuses come from the builder's own status field, and NOT_CONNECTED sources are reported as
    unavailable because that is literally what `source_coverage` says."""
    per_symbol = {}
    for scope in ("indices",):
        for sym, st in pkt[scope].items():
            s = st.get("status")
            if s == "OK":
                per_symbol[sym] = "ACCEPTED" if "gap_frac" in st else "ACCEPTED_NO_PREMARKET_PRINTS"
            else:
                per_symbol[sym] = "UNAVAILABLE_%s" % s
    per_source = {k: ("MARKED_UNAVAILABLE" if v == "NOT_CONNECTED" else v)
                  for k, v in pkt["source_coverage"].items()}
    return {"per_symbol": per_symbol, "per_source": per_source}


# ------------------------------------------------------------------ the Captain seam
def _default_captain(prompt: str) -> str:
    r = subprocess.run(["claude", "-p", "--output-format", "text"], input=prompt,
                       capture_output=True, text=True, timeout=BRIEF_TIMEOUT_S)
    return r.stdout.strip()


def captain_call(prompt: str) -> str:
    from apex.frontier import premarket_runtime as RT
    fn = RT.captain()
    return (fn or _default_captain)(prompt)


def brief_verdict(text: str) -> dict:
    """The firewall and the schema check, separated. The firewall is the legacy rule, byte for byte. The schema
    check is NEW and is deliberately confined to the brief artifact: it can refuse a brief, it can never change,
    delay or block a packet. The sealed packet stands alone, exactly as the legacy runner intended."""
    low = (text or "").lower()
    hits = [w for w in FORBIDDEN_IN_BRIEF if w in low]
    missing = [s for s in REQUIRED_BRIEF_SECTIONS if s not in (text or "")]
    if hits:
        return {"verdict": "REFUSED_BY_FIREWALL", "firewall_hits": hits, "missing_sections": missing}
    if missing:
        return {"verdict": "CAPTAIN_SCHEMA_INVALID", "firewall_hits": [], "missing_sections": missing}
    return {"verdict": "ACCEPTED", "firewall_hits": [], "missing_sections": []}


def write_brief(sealed: dict, text: str, verdict: dict) -> str:
    from apex.frontier.premarket import packets_dir
    if verdict["verdict"] == "REFUSED_BY_FIREWALL":
        text = ("BRIEF REFUSED BY FIREWALL (contained %r); the sealed packet stands alone this morning."
                % verdict["firewall_hits"][0])
    elif verdict["verdict"] == "CAPTAIN_SCHEMA_INVALID":
        text = ("BRIEF REFUSED: CAPTAIN_SCHEMA_INVALID (missing %s); the sealed packet stands alone this morning."
                % ", ".join(verdict["missing_sections"]))
    out = packets_dir() / ("%s_morning_brief.md" % sealed["market_date"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "# CAPTAIN MORNING BRIEF — %s\npacket sha256: %s\n"
        "PRIORS, NOT TRUTH — the tape gets the final vote; if the open contradicts this brief, THE BRIEF LOSES.\n"
        "decision_power: NONE_FRONTIER_SHADOW\n\n%s\n" % (sealed["market_date"], sealed["packet_sha256"], text))
    return str(out)


def brief_facts(sealed: dict) -> str:
    """REPAIRED BY THE R4 PARITY RUN. This was `json.dumps(..., indent=1)` with no key ordering, so the Captain
    received a DIFFERENT PROMPT depending on which producer serialized the packet -- the staged path round-trips
    it through a canonical sorted-key blob, the legacy path did not. Same facts, different bytes, and a model is
    entitled to answer differently to different bytes. Sorting makes the Captain's input a function of the facts
    alone. The facts themselves are unchanged; only their order is now fixed."""
    return json.dumps({k: sealed[k] for k in
                       ("market_date", "indices", "gap_map", "watch_map", "source_coverage", "blind_spots")},
                      indent=1, sort_keys=True, default=str)[:14000]


def crash_point() -> str | None:
    return os.environ.get("APEX_PREMARKET_CRASH_AFTER") or None


def _maybe_crash(point: str):
    """A declared crash INJECTOR. It can only kill this process at a real phase boundary in the real code; it can
    never alter an output. It is listed in premarket_runtime.ENV_NAMES so it appears in `substitutions()` on every
    event it touches, and the prepared production shell is asserted to export it nowhere."""
    if crash_point() == point:
        os._exit(70)


# ------------------------------------------------------------------ predecessor verification
def predecessor_report(journal, stage: str) -> dict:
    """What the earlier stages of this morning did -- verified, not assumed.

    THE POLICY, DECLARED. The chain and every referenced blob are re-hashed first; a broken predecessor is a hard
    refusal, never a shrug. A predecessor that is merely ABSENT is recorded as MISSING and this stage proceeds,
    because each stage is an independent full re-assembly (the legacy runner behaved the same way: a DEGRADED
    absorption left `last` untouched and the next one carried on). Absence is therefore survivable; corruption is
    not, and the difference is now written down instead of being a property of whichever code path ran."""
    order = [n for n, _h, _m in STAGE_SCHEDULE]
    earlier = order[:order.index(stage)]
    chain = journal.verify()
    states, missing = {}, []
    for s in earlier:
        st = journal.stage_outcome(s)
        states[s] = st
        if st == "PENDING":
            missing.append(s)
    return {"chain": chain, "earlier_states": states, "missing": missing,
            "out_of_order": bool(missing) and stage != order[0]}


# ------------------------------------------------------------------ THE production stage operation
def config_identity() -> dict:
    """What CONFIGURATION produced this morning: the schedule, the window policy and the source-coverage matrix.
    Digested, so a packet can be tied to the configuration as well as to the code."""
    import hashlib

    from apex.frontier.premarket import SOURCES
    body = {"stage_schedule": [list(x) for x in STAGE_SCHEDULE], "window_s": WINDOW_S, "on_time_s": ON_TIME_S,
            "market_tz": "America/New_York", "sources": dict(SOURCES),
            "lab_budget": PREMARKET_LAB_BUDGET, "required_brief_sections": list(REQUIRED_BRIEF_SECTIONS)}
    return {"config_digest": hashlib.sha256(canonical_json(body).encode()).hexdigest(), "config": body}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def stage_time_block(*, stage, now_et, disposition_, delta, process_started_at, capture_started_at,
                     capture_finished_at, normalization_finished_at, absorption_finished_at,
                     code_identity=None) -> dict:
    """Every instant in a stage's own life, in market time and in epochs. `lateness_s` is the ACTUAL start minus
    the target and is never rounded toward the target -- a stage that started at 08:22 records 08:22."""
    from apex.frontier import market_time as MT
    t = target_for(stage, now_et)
    return {"schema": "PREMARKET_STAGE_TIME_V1", "market_tz": MT.MARKET_TZ,
            "market_date": str(now_et.date()), "stage": stage,
            "target_instant": t.isoformat(), "target_epoch": t.timestamp(),
            "window_opens": (t - __import__("pandas").Timedelta(seconds=ON_TIME_S)).isoformat(),
            "window_closes": (t + __import__("pandas").Timedelta(seconds=WINDOW_S)).isoformat(),
            "window_s": WINDOW_S,
            "process_started_at": process_started_at, "process_started_market": now_et.isoformat(),
            "capture_started_at": capture_started_at, "capture_finished_at": capture_finished_at,
            "normalization_finished_at": normalization_finished_at,
            "absorption_finished_at": absorption_finished_at,
            "disposition": disposition_, "lateness_s": round(delta, 3),
            "code_identity": code_identity, "config_identity": config_identity()}


def run_stage(stage: str, *, journal, now_et, symbols=None, emit=print, code_identity=None) -> dict:
    """One bounded invocation of one stage, start to terminal state, entirely through durable evidence.

    PENDING -> STARTED -> CAPTURED -> NORMALIZED -> ABSORBED -> COMPLETED, with the terminal alternatives named in
    premarket_journal.TERMINAL. Nothing here sleeps."""
    from apex.frontier import premarket_journal as PJ

    result = {"stage": stage, "trading_date": journal.trading_date}

    # --- a stage after the seal is a contradiction, not a late arrival
    sealed = journal.sealed_event()
    if sealed is not None and stage != "seal":
        journal.append(stage=stage, state="REFUSED_INPUT", reason="POST_SEAL",
                       sealed_seq=sealed["seq"],
                       note="the morning is sealed; a later absorption cannot be added to a sealed packet")
        emit("REFUSED_INPUT stage=%s reason=POST_SEAL" % stage)
        return {**result, "state": "REFUSED_INPUT", "reason": "POST_SEAL"}

    # --- duplicate delivery
    prior = journal.stage_outcome(stage)
    if prior in PJ.DECISIVE:
        journal.append(stage=stage, state="RECONCILED_DUPLICATE", prior_state=prior,
                       note="this stage already reached a decisive outcome; nothing was absorbed again")
        emit("RECONCILED_DUPLICATE stage=%s prior=%s" % (stage, prior))
        return {**result, "state": "RECONCILED_DUPLICATE", "prior_state": prior}

    # --- predecessors: verified, never assumed
    try:
        pred = predecessor_report(journal, stage)
    except PJ.ChainBroken as e:
        journal_append_safe(journal, stage, "FAILED", reason="JOURNAL_CHAIN_BROKEN", detail=str(e)[:400])
        emit("FAILED stage=%s reason=JOURNAL_CHAIN_BROKEN: %s" % (stage, e))
        return {**result, "state": "FAILED", "reason": "JOURNAL_CHAIN_BROKEN", "detail": str(e)}

    disp, delta = disposition(stage, now_et)
    journal.append(stage=stage, state="STARTED", disposition=disp, delta_s=round(delta, 1),
                   target_et=str(target_for(stage, now_et)), actual_et=str(now_et),
                   predecessors=pred["earlier_states"], missing_predecessors=pred["missing"],
                   out_of_order=pred["out_of_order"], chain=pred["chain"])
    emit("stage=%s disposition=%s delta=%.0fs missing_predecessors=%s"
         % (stage, disp, delta, pred["missing"] or "none"))

    if disp in ("TOO_EARLY", "MISSED_WINDOW"):
        # THE REPAIRED BEHAVIOUR. The legacy runner slept toward the target and absorbed when it woke. This exits.
        journal.append(stage=stage, state=disp, delta_s=round(delta, 1),
                       note="exited without sleeping and without fetching; no data was absorbed under this label")
        return {**result, "state": disp, "delta_s": delta}

    c = journal.claim(stage, holder="run_stage")
    if c["status"] == "HELD":
        journal.append(stage=stage, state="RECONCILED_DUPLICATE", prior_state=prior, claim_holder=c["holder"],
                       note="another live invocation holds this stage's exactly-once claim")
        emit("RECONCILED_DUPLICATE stage=%s (claim held by live pid %s)" % (stage, (c["holder"] or {}).get("pid")))
        return {**result, "state": "RECONCILED_DUPLICATE", "claim_holder": c["holder"]}
    if c["status"] == "TAKEOVER":
        journal.append(stage=stage, state="STARTED", claim_takeover=c["holder"], disposition=disp,
                       note="the previous holder's process is gone and this stage never reached a terminal "
                            "state; recovering it. The dead holder is named here rather than erased.")
        emit("CLAIM_TAKEOVER stage=%s from dead pid %s" % (stage, (c["holder"] or {}).get("pid")))

    resume = journal.resume_point(stage)
    as_of = resume["payload"].get("as_of") or str(now_et.tz_convert("UTC"))
    as_of_epoch = pd_ts(as_of).timestamp()
    process_started_at = now_et.tz_convert("UTC").timestamp()

    # ---------------- ABSORBED already reached: reuse it, never re-absorb
    if resume["state"] == "ABSORBED":
        packet_blob = resume["payload"]["packet_blob"]
        journal.get_blob(packet_blob)
        journal.append(stage=stage, state="COMPLETED", packet_blob=packet_blob, resumed_from="ABSORBED",
                       capture_blobs=resume["payload"].get("capture_blobs", []),
                       normalized_blob=resume["payload"].get("normalized_blob"), as_of=as_of)
        emit("COMPLETED stage=%s (resumed from ABSORBED; no source was fetched again)" % stage)
        return {**result, "state": "COMPLETED", "resumed_from": "ABSORBED", "packet_blob": packet_blob}

    # ---------------- capture (or replay the original capture)
    replayed = False
    if resume["state"] in ("CAPTURED", "NORMALIZED"):
        manifest = journal.get_blob(resume["payload"]["capture_manifest_blob"])
        transport = ReplayTransport(journal, manifest)
        replayed = True
    else:
        transport = RecordingTransport(journal, as_of_epoch=as_of_epoch)

    from apex.frontier import premarket_runtime as _RT
    capture_started_at = _RT.now_utc().timestamp()
    try:
        pkt = absorb(stage, as_of=as_of, fetch=transport, symbols=symbols)
    except Exception as e:                                          # noqa: BLE001
        kind = "SOURCE_UNAVAILABLE" if _is_source_error(e) else "FAILED"
        journal_append_safe(journal, stage, kind, reason="%s: %s" % (type(e).__name__, e),
                            captured=len(getattr(transport, "manifest", []) or []), as_of=as_of,
                            note="the legacy runner logged this as DEGRADED and left its packet untouched; "
                                 "this leaves a record instead of silence")
        emit("%s stage=%s: %s: %s" % (kind, stage, type(e).__name__, e))
        return {**result, "state": kind, "reason": "%s: %s" % (type(e).__name__, e)}

    capture_finished_at = _RT.now_utc().timestamp()
    manifest = (transport.manifest if not replayed else
                journal.get_blob(resume["payload"]["capture_manifest_blob"]))
    manifest_blob = journal.put_blob(manifest)
    journal.append(stage=stage, state="CAPTURED", capture_manifest_blob=manifest_blob,
                   capture_blobs=[m["blob"] for m in manifest], responses=len(manifest),
                   replayed_from_capture=replayed, as_of=as_of)
    emit("CAPTURED stage=%s responses=%d%s" % (stage, len(manifest), " (replayed)" if replayed else ""))
    _maybe_crash("capture")

    # ---------------- normalize
    obs = observations(pkt)
    normalization_finished_at = _RT.now_utc().timestamp()
    obs_blob = journal.put_blob(obs)
    disp_map = source_dispositions(pkt)
    journal.append(stage=stage, state="NORMALIZED", normalized_blob=obs_blob,
                   capture_manifest_blob=manifest_blob, capture_blobs=[m["blob"] for m in manifest],
                   dispositions=disp_map, as_of=as_of)
    emit("NORMALIZED stage=%s symbols=%d" % (stage, len(obs["indices"]) + len(obs["named_movers"])))
    _maybe_crash("normalize")

    # ---------------- absorb
    absorption_finished_at = _RT.now_utc().timestamp()
    pkt["stage_time"] = stage_time_block(
        stage=stage, now_et=now_et, disposition_=disp, delta=delta, process_started_at=process_started_at,
        capture_started_at=capture_started_at, capture_finished_at=capture_finished_at,
        normalization_finished_at=normalization_finished_at, absorption_finished_at=absorption_finished_at,
        code_identity=code_identity)
    packet_blob = journal.put_blob(pkt)
    summary = absorb_summary(pkt)
    journal.append(stage=stage, state="ABSORBED", packet_blob=packet_blob, normalized_blob=obs_blob,
                   capture_manifest_blob=manifest_blob, capture_blobs=[m["blob"] for m in manifest],
                   summary=summary, as_of=as_of)
    emit("ABSORBED stage=%s indices_ok=%d/4 movers=%d unknown_catalyst=%d"
         % (stage, summary["indices_ok"], summary["movers"], summary["unknown_catalyst"]))
    _maybe_crash("absorb")

    journal.append(stage=stage, state="COMPLETED", packet_blob=packet_blob, normalized_blob=obs_blob,
                   capture_manifest_blob=manifest_blob, capture_blobs=[m["blob"] for m in manifest],
                   summary=summary, disposition=disp, as_of=as_of, stage_time=pkt["stage_time"],
                   time=pkt["time"], source_observation_count=len(pkt["source_observations"]))
    emit("COMPLETED stage=%s packet=%s" % (stage, packet_blob[:12]))
    return {**result, "state": "COMPLETED", "packet_blob": packet_blob, "summary": summary,
            "dispositions": disp_map}


def _is_source_error(e) -> bool:
    try:
        from apex.intraday.eodhd import IntradayDataError
        if isinstance(e, IntradayDataError):
            return True
    except Exception:                                               # noqa: BLE001
        pass
    return type(e).__name__ in ("IntradayDataError", "SourceUnavailable", "URLError", "TimeoutError")


def journal_append_safe(journal, stage, state, **payload):
    try:
        journal.append(stage=stage, state=state, **payload)
    except Exception as e:                                          # noqa: BLE001
        # A journal that cannot record a failure must say so loudly rather than convert it into silence.
        print("JOURNAL_APPEND_FAILED stage=%s state=%s: %s: %s" % (stage, state, type(e).__name__, e))


# ------------------------------------------------------------------ the finalizer
def finalize(*, journal, now_et, emit=print) -> dict:
    """Rebuild from persisted evidence, run the real Captain path, validate it, call the real seal().

    PARTIAL-PACKET POLICY, DECLARED BEFORE IT IS NEEDED:
      - zero COMPLETED absorptions -> NOTHING_TO_SEAL, non-zero exit, no packet written. This is exactly what the
        legacy runner did ("nothing to seal -- every absorption failed").
      - one or more -> seal the NEWEST completed absorption, which is what the legacy runner's `last` held.
        Every missing stage is named in the finalization record. It is NOT stamped into the packet, because that
        would change the packet and this brick's parity claim would become untestable; making stage coverage a
        packet field is a behaviour change and belongs to a checkpoint that authorises one."""
    from apex.frontier import premarket_journal as PJ
    from apex.frontier.premarket import seal

    stage = "seal"
    prior = journal.stage_outcome(stage)
    if prior in PJ.DECISIVE:
        ev = journal.sealed_event()
        journal.append(stage=stage, state="RECONCILED_DUPLICATE", prior_state=prior,
                       note="the morning is already finalised; the sealed packet was not rewritten")
        emit("RECONCILED_DUPLICATE stage=seal prior=%s" % prior)
        return {"state": "RECONCILED_DUPLICATE", "prior_state": prior,
                "packet_sha256": ((ev or {}).get("payload") or {}).get("packet_sha256")}

    disp, delta = disposition(stage, now_et)
    try:
        pred = predecessor_report(journal, stage)
    except PJ.ChainBroken as e:
        journal_append_safe(journal, stage, "FAILED", reason="JOURNAL_CHAIN_BROKEN", detail=str(e)[:400])
        emit("FAILED stage=seal reason=JOURNAL_CHAIN_BROKEN: %s" % e)
        return {"state": "FAILED", "reason": "JOURNAL_CHAIN_BROKEN", "detail": str(e)}

    journal.append(stage=stage, state="STARTED", disposition=disp, delta_s=round(delta, 1),
                   target_et=str(target_for(stage, now_et)), actual_et=str(now_et),
                   predecessors=pred["earlier_states"], missing_predecessors=pred["missing"], chain=pred["chain"])
    emit("stage=seal disposition=%s delta=%.0fs missing=%s" % (disp, delta, pred["missing"] or "none"))
    if disp == "TOO_EARLY":
        journal.append(stage=stage, state="TOO_EARLY", delta_s=round(delta, 1),
                       note="exited without sleeping; nothing was sealed")
        return {"state": "TOO_EARLY", "delta_s": delta}

    c = journal.claim(stage, holder="finalize")
    if c["status"] == "HELD":
        journal.append(stage=stage, state="RECONCILED_DUPLICATE", claim_holder=c["holder"],
                       note="another live finalizer holds the seal claim")
        emit("RECONCILED_DUPLICATE stage=seal (claim held by live pid %s)" % (c["holder"] or {}).get("pid"))
        return {"state": "RECONCILED_DUPLICATE", "claim_holder": c["holder"]}
    if c["status"] == "TAKEOVER":
        journal.append(stage=stage, state="STARTED", claim_takeover=c["holder"],
                       note="recovering a seal whose holder is gone; the dead holder is named, not erased")
        emit("CLAIM_TAKEOVER stage=seal from dead pid %s" % (c["holder"] or {}).get("pid"))

    rec = journal.reconstruct()
    if rec["status"] != "RECONSTRUCTED":
        journal.append(stage=stage, state="FAILED", reason="NOTHING_TO_SEAL",
                       missing_predecessors=pred["missing"],
                       note="every absorption failed; there is no evidence to seal and none was invented")
        emit("NOTHING_TO_SEAL -- every absorption failed (DEGRADED)")
        return {"state": "FAILED", "reason": "NOTHING_TO_SEAL", "missing": pred["missing"]}

    packet = dict(rec["packet"])
    from apex.frontier import premarket_runtime as RT
    from apex.frontier import premarket_time as T

    # THE CAPTAIN RUNS BEFORE THE SEAL, which is a deliberate ORDER CHANGE from the legacy runner.
    # The brick requires the Captain's request and response instants to be IN the packet, and the seal to bind the
    # complete time block. Sealing first and briefing afterwards cannot do both: the ai_* instants would exist
    # only outside the digest. The brief ARTIFACT is still written after the seal, because its header cites the
    # sealed digest. The packet itself is unaffected by the Captain in either order -- a Captain failure still
    # leaves the sealed packet standing alone, exactly as before.
    captain_rec = {"status": "NOT_ATTEMPTED"}
    ai_req = ai_resp = T.UNAVAILABLE
    text = None
    try:
        ai_req = RT.now_utc().timestamp()
        text = captain_call(brief_prompt(packet))
        ai_resp = RT.now_utc().timestamp()
        verdict = brief_verdict(text)
        captain_rec = {"status": verdict["verdict"], "firewall_hits": verdict["firewall_hits"],
                       "missing_sections": verdict["missing_sections"],
                       "response_blob": journal.put_blob({"text": text}),
                       "ai_request_time": ai_req, "ai_response_time": ai_resp,
                       "transport": RT.substitutions().get(RT.ENV_CAPTAIN, "REAL_CLAUDE_CLI")}
    except subprocess.TimeoutExpired as e:                          # noqa: PERF203
        captain_rec = {"status": "CAPTAIN_TIMEOUT", "detail": str(e)[:200], "ai_request_time": ai_req,
                       "ai_response_time": T.UNAVAILABLE}
    except Exception as e:                                          # noqa: BLE001
        captain_rec = {"status": "CAPTAIN_DEGRADED_%s" % type(e).__name__, "detail": str(e)[:200],
                       "ai_request_time": ai_req, "ai_response_time": T.UNAVAILABLE}

    packet["as_of_time"] = str(RT.now_utc())
    if packet.get("schema") == PACKET_SCHEMA_V2:
        t = dict(packet.get("time") or {})
        # TWO DIFFERENT "STARTS", named apart. `packet_collection_started_at` is when the stage whose packet this
        # IS began collecting; `morning_started_at` is when the trading date's first process opened the session.
        # They differ by over an hour and a reader that conflates them will misjudge every freshness number.
        sess = next((e for e in journal.events() if e["stage"] == "session"), None)
        t["morning_started_at"] = (sess or {}).get("at", T.UNAVAILABLE)
        t["ai_request_time"] = ai_req
        t["ai_response_time"] = ai_resp if captain_rec["status"] == "ACCEPTED" or text is not None else T.UNAVAILABLE
        packet["time"] = t
    sealed = seal(packet)
    journal.put_blob(sealed)
    emit("PACKET SEALED %s (rebuilt from %s, blob %s, schema %s)"
         % (sealed["packet_sha256"][:12], rec["from_stage"], rec["packet_blob"][:12],
            sealed.get("schema", "V1")))

    if text is not None:
        captain_rec["brief_path"] = write_brief(sealed, text, brief_verdict(text))
    if captain_rec["status"] not in ("ACCEPTED",):
        emit("morning brief %s — the sealed packet stands alone" % captain_rec["status"])
    else:
        emit("brief -> %s" % captain_rec["brief_path"])

    journal.append(stage=stage, state="COMPLETED", packet_sha256=sealed["packet_sha256"],
                   sealed_blob=journal.put_blob(sealed), rebuilt_from=rec["from_stage"],
                   source_packet_blob=rec["packet_blob"],
                   provenance=[p["stage"] for p in rec["provenance"]],
                   missing_stages=pred["missing"], captain=captain_rec, disposition=disp,
                   packet_schema=sealed.get("schema"), time=sealed.get("time"))
    return {"state": "COMPLETED", "packet_sha256": sealed["packet_sha256"], "sealed": sealed,
            "rebuilt_from": rec["from_stage"], "missing_stages": pred["missing"], "captain": captain_rec}


def brief_prompt(sealed: dict) -> str:
    return BRIEF_PROMPT.format(facts=brief_facts(sealed))
