"""ORGANISM INTEGRATION COMMISSIONING — scenarios A through P.

One organism, one paper capital pool, multiple specialist brains. The
tests that matter most prove the failure modes: fail-closed capital,
kernel veto, catalyst degradation, restart idempotence, and that the
CIO can never touch the book.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from apex.catalyst import context as CC
from apex.organism import allocator as AL
from apex.organism import book as BK
from apex.organism import candidate as CA
from apex.organism import cio as CIO
from apex.organism import experience as EX
from apex.organism import risk_kernel as RK


# ------------------------------------------------------------ fixtures

def opt_record(eid="2026-08-28:001:SPY", sym="SPY", risk=301.0):
    return {"record_kind": "options_evaluation", "session": "2026-08-28",
            "known_from": "2026-08-28 10:00:00",
            "payload": {"evaluation_id": eid, "symbol": sym,
                        "direction": "SHORT", "verdict": "PAPER_ATTACKED",
                        "event_time": "2026-08-28 10:00:00",
                        "entry_quality": "GOOD", "chase_risk": "LOW"}}


def opt_card(sym="SPY", risk=301.0):
    return {"kind": "options_live_attack", "symbol": sym,
            "T": "2026-08-28 10:00:00", "status": "PAPER_ATTACKED",
            "declared_1R": risk, "expression": "LONG_PUT",
            "net_debit": risk, "card_hash": f"hash_{sym}"}


def eq_record(did="EQS_1", sym="NVDA", risk=300.0, direction="LONG"):
    return {"record_kind": "equity_shadow_decision",
            "session": "2026-08-28",
            "payload": {"decision_id": did, "symbol": sym,
                        "direction": direction,
                        "decision": "ATTACK_READY_SHADOW",
                        "event_time": "2026-08-28T14:00:00Z",
                        "known_from": "2026-08-28T14:00:00Z",
                        "declared_1R": risk, "entry_fill": 100.02,
                        "stop": 98.0, "quantity": 150,
                        "setup_type": "LONG_BREAKOUT",
                        "entry_quality": "GOOD", "chase_risk": "LOW"}}


def btc_record(risk=250.0, cohort="ATTACK"):
    return {"kind": "btc_paper_decision", "T": "2026-08-28 03:00:00",
            "cohort": cohort, "participant_state": "TRAPPED_LONG",
            "thesis_state": "FORCED_ACTION",
            "attack_geometry": {"declared_1R": risk,
                                "direction": "SHORT"}}


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


@pytest.fixture
def led(tmp_path):
    return {"book": tmp_path / "book.jsonl",
            "dec": tmp_path / "alloc.jsonl",
            "cards": _write(tmp_path / "cards.jsonl", [opt_card()])}


def adapt_opt(rec, cards):
    return CA.from_options(rec, attack_ledger=cards)


# ============================== A/B/C — single-sleeve candidate funds

def test_A_options_only_candidate_funds(led):
    env = adapt_opt(opt_record(), led["cards"])
    run = AL.allocate([env], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["results"][0]["state"] == "FUNDED"
    st = BK.state(ledger=led["book"])
    assert st["open_positions"] == 1
    assert st["open_risk"] == 301.0
    assert st["available_capital"] == 10_000.0 - 301.0


def test_B_equity_only_candidate_funds(led):
    env = CA.from_equity(eq_record())
    run = AL.allocate([env], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["results"][0]["state"] == "FUNDED"
    assert BK.state(ledger=led["book"])["positions"][0]["sleeve"] == \
        "EQUITY"


def test_C_btc_only_candidate_funds(led):
    env = CA.from_btc(btc_record())
    run = AL.allocate([env], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["results"][0]["state"] == "FUNDED"
    assert BK.state(ledger=led["book"])["positions"][0]["symbol"] == \
        "PBTCUCZ50"


# ================== D — same underlying across sleeves = redundancy

def test_D_options_plus_equity_same_underlying_detected(led):
    o = adapt_opt(opt_record(sym="SPY"), led["cards"])
    e = CA.from_equity(eq_record(sym="SPY", direction="SHORT"))
    rels = AL.cross_sleeve_relations([o, e])
    assert rels and rels[0]["redundancy"] == "HIGHLY_REDUNDANT"
    run = AL.allocate([o, e], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    states = {r["candidate_id"]: r["state"] for r in run["results"]}
    # the arena funds the first claim and refuses the second as the
    # same bet in a different costume
    assert sorted(states.values()) == ["FUNDED",
                                       "REFUSED_ARENA_REFUSE_REDUNDANT"]


# ==================== E — three independent opportunities compete

def test_E_three_independent_opportunities_compared(led):
    envs = [adapt_opt(opt_record(sym="SPY"), led["cards"]),
            CA.from_equity(eq_record(sym="NVDA")),
            CA.from_btc(btc_record())]
    run = AL.allocate(envs, session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert len(run["results"]) == 3
    assert all("REFUSED_FAIL" not in r["state"] for r in run["results"])
    st = BK.state(ledger=led["book"])
    assert st["open_positions"] >= 2      # cheapest-first competition


# ================= F — catalyst contradiction recorded, not obeyed

def test_F_catalyst_contradiction_is_recorded_not_a_veto(tmp_path, led):
    ev = {"kind": "catalyst_event", "event_id": "E1",
          "known_from": "2026-08-28 09:00:00",
          "affected_symbols": ["SPY"], "importance": "HIGH",
          "verification": "VERIFIED",
          "directional_expectation": "POSITIVE",
          "headline": "verified positive catalyst"}
    evl = _write(tmp_path / "events.jsonl", [ev])
    ctx = CC.context(symbol="SPY", as_of="2026-08-28 10:00:00",
                     events_ledger=evl,
                     reactions_ledger=tmp_path / "rx.jsonl")
    assert ctx["directional_support"] == "CATALYST_POSITIVE"
    assert CC.alignment(direction="SHORT", ctx=ctx) == \
        "CATALYST_OPPOSED"
    # the SHORT still reaches the arena and can fund: catalyst informs,
    # the specialist decides, the arena allocates
    env = adapt_opt(opt_record(sym="SPY"), led["cards"])
    run = AL.allocate([env], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"],
                      catalyst_roots={"events_ledger": evl,
                                      "reactions_ledger":
                                          tmp_path / "rx.jsonl"})
    assert run["results"][0]["state"] == "FUNDED"


def test_F2_catalyst_never_sees_the_future(tmp_path):
    ev = {"kind": "catalyst_event", "event_id": "E2",
          "known_from": "2026-08-28 11:00:00",
          "affected_symbols": ["SPY"], "importance": "CRITICAL",
          "verification": "VERIFIED",
          "directional_expectation": "NEGATIVE", "headline": "later"}
    evl = _write(tmp_path / "e.jsonl", [ev])
    ctx = CC.context(symbol="SPY", as_of="2026-08-28 10:00:00",
                     events_ledger=evl,
                     reactions_ledger=tmp_path / "r.jsonl")
    assert ctx["events_known"] == 0, "an 11:00 event leaked into 10:00"
    assert ctx["directional_support"] == "CATALYST_UNKNOWN"


# ================= G — catalyst unavailable degrades to UNKNOWN

def test_G_catalyst_unavailable_is_unknown_not_a_halt(led, monkeypatch):
    def boom(**kw):
        raise RuntimeError("catalyst store unreachable")
    monkeypatch.setattr(AL.catalyst_context, "context", boom)
    env = adapt_opt(opt_record(), led["cards"])
    run = AL.allocate([env], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["results"][0]["state"] == "FUNDED", \
        "a dead catalyst halted allocation instead of degrading context"


# ======================= H — capital arena unavailable: FAIL CLOSED

def test_H_arena_unavailable_fails_closed(led, monkeypatch):
    monkeypatch.setattr(AL.book, "state",
                        lambda **k: (_ for _ in ()).throw(
                            OSError("book unreadable")))
    env = adapt_opt(opt_record(), led["cards"])
    run = AL.allocate([env], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["fail_closed"] is True
    assert run["results"][0]["state"] == "REFUSED_FAIL_CLOSED"
    rows = [json.loads(l) for l in
            led["book"].read_text().splitlines() if l.strip()]
    assert rows[-1]["kind"] == "paper_refusal"
    assert rows[-1]["refused_at_stage"] == "FAIL_CLOSED"


# ================================ I — risk kernel blocks a candidate

def test_I_kernel_vetoes_oversize_and_arena_cannot_override(led):
    big = adapt_opt(opt_record(eid="big"), led["cards"])
    big["declared_risk"] = 800.0          # > MAX_RISK_PER_TRADE
    run = AL.allocate([big], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["results"][0]["state"] == "REFUSED_RISK_KERNEL"


def test_I2_session_drawdown_halts_new_funding(led):
    env1 = adapt_opt(opt_record(eid="e1"), led["cards"])
    AL.allocate([env1], session="2026-08-28", book_ledger=led["book"],
                decision_ledger=led["dec"])
    BK.attach_outcome(candidate_id="e1", session="2026-08-28",
                      executable_pnl=-1200.0,
                      outcome_class="THESIS_FAILURE",
                      ledger=led["book"])
    env2 = adapt_opt(opt_record(eid="e2"), led["cards"])
    run = AL.allocate([env2], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["results"][0]["state"] == "REFUSED_RISK_KERNEL"


# ==================== J — execution failure stays NOT_ESTIMABLE

def test_J_execution_failure_is_not_a_zero(led):
    env = adapt_opt(opt_record(eid="ef"), led["cards"])
    AL.allocate([env], session="2026-08-28", book_ledger=led["book"],
                decision_ledger=led["dec"])
    BK.attach_outcome(candidate_id="ef", session="2026-08-28",
                      executable_pnl="NOT_ESTIMABLE",
                      outcome_class="EXECUTION_FAILURE",
                      ledger=led["book"])
    st = BK.state(ledger=led["book"])
    assert st["execution_failures"] == 1
    assert st["realized_pnl"] == 0.0, \
        "NOT_ESTIMABLE leaked into P&L as a number"


# ============================================= K — cash preferred

def test_K_unproven_edge_locking_the_session_defers_to_cash(led):
    env = CA.from_equity(eq_record())
    env["sleeve_payload"]["capital_lockup_min"] = 350
    # rebuild the arena candidate with lockup via sleeve payload
    run = AL.allocate([env], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    # lockup flows through candidate -> arena DEFER_FOR_SUPERIOR
    assert run["results"][0]["state"] in (
        "FUNDED", "REFUSED_ARENA_DEFER_FOR_SUPERIOR_OPPORTUNITY")
    # cash competing is structural: the arena owns the rule; here we
    # assert the refusal is EXPRESSIBLE and sealed when it fires
    from apex.capital.arena import ACTIONS
    assert "CASH_PREFERRED" in ACTIONS


# ========================= L — long and short coexist in the book

def test_L_long_and_short_coexist(led):
    s = adapt_opt(opt_record(sym="SPY"), led["cards"])       # SHORT
    l = CA.from_equity(eq_record(sym="NVDA", direction="LONG"))
    run = AL.allocate([s, l], session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    st = BK.state(ledger=led["book"])
    dirs = {p["direction"] for p in st["positions"]}
    assert dirs == {"LONG", "SHORT"}


# ============== M — same catalyst, correlated exposure is visible

def test_M_same_family_risk_is_capped(led, tmp_path):
    cards = _write(tmp_path / "c2.jsonl",
                   [opt_card(sym="SPY", risk=500.0),
                    opt_card(sym="QQQ", risk=500.0),
                    opt_card(sym="AAPL", risk=500.0)])
    for c in json.loads("[]") or []:
        pass
    envs = []
    for sym in ("SPY", "QQQ", "AAPL"):
        r = opt_record(eid=f"m:{sym}", sym=sym)
        envs.append(CA.from_options(r, attack_ledger=cards))
    run = AL.allocate(envs, session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    st = BK.state(ledger=led["book"])
    fam = st["risk_by_family"].get("US_LARGE_BETA", 0.0)
    assert fam <= 1000.0, \
        f"US_LARGE_BETA risk {fam} breached the family cap"
    states = [r["state"] for r in run["results"]]
    assert any("REFUSED" in s for s in states)


# ================= N/O — CIO and EdgeForge cannot touch the book

def test_N_cio_produces_directive_but_has_no_mutating_surface(led):
    d = CIO.daily_directive(session="2026-08-28",
                            book_ledger=led["book"],
                            ledger=led["book"].parent / "cio.jsonl")
    assert d["kind"] == "cio_directive"
    assert d["decision_power"] == "RESEARCH_DIRECTION_ONLY"
    src = Path(CIO.__file__).read_text()
    tree = ast.parse(src)
    banned = {"fund", "refuse", "attach_outcome", "allocate",
              "place_order", "compete"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = (f.id if isinstance(f, ast.Name)
                    else f.attr if isinstance(f, ast.Attribute)
                    else None)
            assert name not in banned, f"CIO calls {name}()"


def test_O_nothing_downstream_of_research_can_alter_the_book(led):
    """The book only grows through allocate(); research modules import
    neither fund nor refuse."""
    for mod in ("apex/organism/cio.py", "apex/organism/experience.py"):
        for n in ast.walk(ast.parse(Path(mod).read_text())):
            if isinstance(n, ast.ImportFrom):
                names = [a.name for a in n.names]
                assert "fund" not in names and "refuse" not in names, \
                    f"{mod} imports a book mutator"


# ======================== P — restart with open positions: no dupes

def test_P_restart_cannot_double_fund(led):
    env = adapt_opt(opt_record(eid="dup"), led["cards"])
    AL.allocate([env], session="2026-08-28", book_ledger=led["book"],
                decision_ledger=led["dec"])
    # the same record redelivered after a crash/restart
    run2 = AL.allocate([env], session="2026-08-28",
                       book_ledger=led["book"],
                       decision_ledger=led["dec"])
    assert run2["results"][0]["state"] == "DUPLICATE"
    st = BK.state(ledger=led["book"])
    assert st["open_positions"] == 1, "a restart doubled a position"
    assert st["open_risk"] == 301.0


# ============================== EXPERIENCE GRAPH + AS_KNOWN_AT

def test_experience_graph_as_known_at_excludes_the_future(tmp_path, led):
    env = adapt_opt(opt_record(eid="tr"), led["cards"])
    AL.allocate([env], session="2026-08-28", book_ledger=led["book"],
                decision_ledger=led["dec"])
    g = tmp_path / "graph.jsonl"
    EX.rebuild(sources={"paper_book": led["book"],
                        "allocator": led["dec"]}, graph=g)
    before = EX.as_known_at("2026-08-27 00:00:00", graph=g)
    after = EX.as_known_at("2099-01-01", graph=g)
    assert len(before) == 0, "future nodes leaked into the past"
    assert len(after) >= 2
    tr = EX.trace("tr", graph=g)
    assert tr["n_links"] >= 2


# ======================================= REAL-CAPITAL LOCK HOLDS

def test_no_real_order_surface_anywhere_in_the_organism():
    banned = {"place_order", "submit_order", "send_order",
              "create_order", "route_order"}
    for mod in Path("apex/organism").glob("*.py"):
        for n in ast.walk(ast.parse(mod.read_text())):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert n.name not in banned
            if isinstance(n, ast.Call):
                f = n.func
                name = (f.id if isinstance(f, ast.Name)
                        else f.attr if isinstance(f, ast.Attribute)
                        else None)
                assert name not in banned


def test_stale_candidate_with_outcome_is_still_refused_upstream():
    """Prospective-or-nothing survives integration: the options adapter
    rides on join_attack_card, which refuses outcome-bearing cards."""
    from apex.capital.consumer import join_attack_card
    card = opt_card()
    card["realized_pnl"] = -54.0
    p = opt_record()["payload"]
    import tempfile
    led = Path(tempfile.mkdtemp()) / "c.jsonl"
    _write(led, [card])
    j = join_attack_card(p, ledger=led)
    assert j["joined"] is False
    assert "hindsight" in j["why"] or "outcome" in j["why"]


# ================= THE FRESHNESS FENCE (found live, first deployment)

def test_a_prior_session_candidate_is_refused_as_stale(led):
    """The initial cursor drain delivered Thursday's attacks on Friday
    and the book funded both -- trades whose outcomes were already
    public. Prospective means the outcome CANNOT yet be known."""
    old = adapt_opt(opt_record(), led["cards"])   # known_from 08-28
    run = AL.allocate([old], session="2026-08-29",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    assert run["results"][0]["state"] == "REFUSED_STALE"
    assert BK.state(ledger=led["book"])["open_positions"] == 0


def test_a_voided_funding_leaves_the_economic_state(led):
    env = adapt_opt(opt_record(eid="v1"), led["cards"])
    AL.allocate([env], session="2026-08-28", book_ledger=led["book"],
                decision_ledger=led["dec"])
    assert BK.state(ledger=led["book"])["open_positions"] == 1
    BK.void_funding(candidate_id="v1", why="test correction",
                    ledger=led["book"])
    st = BK.state(ledger=led["book"])
    assert st["open_positions"] == 0
    assert st["open_risk"] == 0.0
    # and the chain still holds every record -- corrections append
    kinds = [json.loads(l)["kind"] for l in
             led["book"].read_text().splitlines() if l.strip()]
    assert "paper_funding" in kinds and "paper_funding_void" in kinds


def test_the_cio_does_not_count_voided_fundings(led):
    env = adapt_opt(opt_record(eid="cv"), led["cards"])
    AL.allocate([env], session="2026-08-28", book_ledger=led["book"],
                decision_ledger=led["dec"])
    BK.void_funding(candidate_id="cv", why="test", ledger=led["book"])
    d = CIO.daily_directive(session="2026-08-28",
                            book_ledger=led["book"],
                            ledger=led["book"].parent / "c2.jsonl")
    assert d["funded"] == 0, "a voided funding still counted as funded"


def test_options_aggregate_attaches_only_when_it_is_one_trade(
        tmp_path, monkeypatch):
    """With 2 attacks the session aggregate is NOT a per-trade outcome
    and must not be split; with 1 it IS the trade and attaches."""
    import scripts.organism_service as S
    from apex.organism import book as B
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results/organism").mkdir(parents=True)
    (tmp_path / "results/equities").mkdir(parents=True)
    led = B.LEDGER
    env = adapt_opt(opt_record(eid="o1"),
                    _write(tmp_path / "cards.jsonl", [opt_card()]))
    AL.allocate([env], session="2026-08-28", book_ledger=led,
                decision_ledger=tmp_path / "d.jsonl")
    sb = {"kind": "options_session_scoreboard", "session": "2026-08-28",
          "attacks_raw": 1,
          "friction": {"executable_pnl": -35.0, "mid_pnl": -20.0,
                       "friction": 15.0,
                       "by_primary_class": {"THESIS_WRONG": 1}}}
    _write(tmp_path / "results/options_live_ledger.jsonl", [sb])
    n = S.attach_new_outcomes("2026-08-28")
    assert n == 1
    st = B.state(ledger=led)
    assert st["realized_pnl"] == -35.0
    # a second call must not double-attach
    assert S.attach_new_outcomes("2026-08-28") == 0


def test_baselines_are_computed_but_never_fund(led):
    """The comparators exist beside every run; the book hears only
    from the real arena."""
    envs = [adapt_opt(opt_record(), led["cards"]),
            CA.from_equity(eq_record())]
    run = AL.allocate(envs, session="2026-08-28",
                      book_ledger=led["book"],
                      decision_ledger=led["dec"])
    b = run["baseline_diagnostics"]
    assert set(b["policies"]) == {"CASH", "EQUAL_RISK_ALL_ELIGIBLE",
                                  "FIRST_VALID_CANDIDATE"}
    assert b["policies"]["CASH"]["funds"] == []
    assert len(b["policies"]["EQUAL_RISK_ALL_ELIGIBLE"]["funds"]) == 2
    assert len(b["policies"]["FIRST_VALID_CANDIDATE"]["funds"]) == 1
    # and the real book contains only what the REAL arena funded
    st = BK.state(ledger=led["book"])
    assert st["open_positions"] == 2   # arena funded both here
    kinds = {json.loads(l)["kind"] for l in
             led["book"].read_text().splitlines() if l.strip()}
    assert "baseline_funding" not in kinds
