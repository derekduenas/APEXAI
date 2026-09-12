#!/usr/bin/env python
"""APEX DASHBOARD v0 -- read-only operating telemetry. CONSUMER ONLY.

    python scripts/apex_dashboard.py [--port 8790]      binds 127.0.0.1 only

Same law as the Flight Deck: reads canonical artifacts and serves them; no
decision authority, no state of its own, no controls, no credentials, no CDN.
Every metric carries its SOURCE and AS_OF; a row that cannot be measured says
NOT_READY or NOT_AVAILABLE rather than a number; a view whose refresh fails
shows STALE with its last successful update. Times are UTC. Simulated,
paper and actual results are never mixed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CORE = Path("/apex-data/core")
HB = CORE / "heartbeats"
OPS = CORE / "ops"
REPO = Path("/opt/apex-repo")
ALPHA = Path("/apex-data/tmp/alpha_wt")
UNITS = ("apex-orchestrator", "apex-options-paper", "apex-equity-fabric", "apex-btc-resolver",
         "apex-btc-derivatives", "apex-btc-ws", "apex-organism", "apex-catalyst",
         "apex-equity-shadow", "apex-equity-field", "apex-edgeforge-observatory",
         "apex-thetaterminal", "apex-gate2-opener")
STALE_AFTER_S = {"orchestrator": 180, "default": 1800}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def metric(value, source, as_of=None, quality="MEASURED", unit=None):
    return {"value": value, "source": source, "as_of": as_of or now_iso(),
            "quality": quality, "unit": unit}


def not_ready(source, why):
    return metric(None, source, quality="NOT_READY", unit=why)


def _sh(*a, timeout=8):
    try:
        r = subprocess.run(a, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except Exception as e:                                   # noqa: BLE001
        return -1, type(e).__name__


def _json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:                                        # noqa: BLE001
        return None


def _tail_json(p: Path, n=1):
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            fh.seek(max(0, size - 262144))
            lines = [l for l in fh.read().decode("utf-8", "replace").splitlines() if l.strip()]
        out = []
        for l in reversed(lines):
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                continue
            if len(out) >= n:
                break
        return out
    except Exception:                                        # noqa: BLE001
        return []


def _age_s(iso):
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:                                        # noqa: BLE001
        return None


# ------------------------------------------------------------- COMMAND CENTER
def units():
    out = {}
    for u in UNITS:
        rc, txt = _sh("systemctl", "show", u + ".service", "-p",
                      "ActiveState,SubState,Result,NRestarts,MemoryMax,ExecMainStartTimestamp,UnitFileState")
        d = dict(l.split("=", 1) for l in txt.splitlines() if "=" in l) if rc == 0 else {}
        cg = Path("/sys/fs/cgroup/apex.slice/apex-market.slice") / (u + ".service")
        peak = cur = None
        try:
            peak = round(int((cg / "memory.peak").read_text()) / 1048576, 1)
            cur = round(int((cg / "memory.current").read_text()) / 1048576, 1)
        except OSError:
            pass
        out[u] = {"active": d.get("ActiveState"), "sub": d.get("SubState"), "result": d.get("Result"),
                  "restarts": d.get("NRestarts"), "enabled": d.get("UnitFileState"),
                  "memory_max_mib": (round(int(d["MemoryMax"]) / 1048576) if d.get("MemoryMax", "").isdigit() else "unlimited"),
                  "memory_peak_mib": peak, "memory_current_mib": cur,
                  "started": d.get("ExecMainStartTimestamp") or None,
                  "source": "systemctl show + unit cgroup (peak only while running)"}
    return out


def holds():
    out = []
    for m in sorted(OPS.glob("MAINTENANCE_BLOCK_*")):
        txt = m.read_text(errors="replace")
        status = next((l.split("=", 1)[1].strip() for l in txt.splitlines() if "_STATUS" in l), "?")
        applied = next((l.split("=", 1)[1].strip() for l in txt.splitlines() if l.startswith("applied_utc")), "?")
        out.append({"marker": m.name, "status": status, "applied_utc": applied,
                    "source": str(m), "enforced_by": "systemd ConditionPathExists in the unit drop-in"})
    return out


def heartbeats():
    out = {}
    for p in sorted(HB.glob("*.json")):
        d = _json(p) or {}
        lw, bt = d.get("last_work_utc"), d.get("beat_utc")
        wage, bage = (_age_s(lw) if lw else None), (_age_s(bt) if bt else None)
        limit = STALE_AFTER_S.get(p.stem, STALE_AFTER_S["default"])
        # beat = the process is alive; work = it completed something. A quiet
        # session is ALIVE_IDLE, not STALE; STALE means the beat itself stopped.
        if bage is None and wage is None:
            q = "UNKNOWN"
        elif (bage if bage is not None else wage) > limit:
            q = "STALE"
        elif wage is not None and wage <= limit:
            q = "MEASURED"
        else:
            q = "ALIVE_IDLE"
        out[p.stem] = {"beat_utc": bt, "beat_age_s": round(bage) if bage is not None else None,
                       "last_work_utc": lw, "work_age_s": round(wage) if wage is not None else None,
                       "work_completed": d.get("work_completed"), "authority": d.get("authority"),
                       "last_error": d.get("last_error"), "quality": q, "stale_after_s": limit,
                       "source": str(p)}
    return out


def versions():
    dep = os.path.basename(os.path.realpath("/opt/apex/current"))
    rel = _json(Path("/opt/apex/current/RELEASE.json")) or {}
    heads = {}
    for b in ("milestone1-r2", "milestone1-recovery-candidate", "alpha-exp-001", "main"):
        rc, h = _sh("git", "-C", str(REPO), "rev-parse", b)
        heads[b] = h if rc == 0 else "NOT_AVAILABLE"
    return {"deployed_release": dep, "release_meta": rel, "branch_heads": heads,
            "source": "readlink /opt/apex/current; git rev-parse in /opt/apex-repo (read-only)"}


def orchestrator_ledger():
    recs = _tail_json(OPS / "orchestrator.jsonl", 1)
    if not recs:
        return not_ready(str(OPS / "orchestrator.jsonl"), "no readable record")
    r = recs[0]
    return {"at": r.get("at"), "phase": r.get("phase"), "missing": r["reconciliation"].get("missing"),
            "verdict": r["reconciliation"].get("verdict"), "incidents": len(r.get("incidents", [])),
            "maintenance": r.get("maintenance"), "actions": [(a.get("service"), a.get("outcome")) for a in r.get("actions", [])],
            "record_bytes": len(json.dumps(r, sort_keys=True)),
            "ledger_bytes": (OPS / "orchestrator.jsonl").stat().st_size,
            "source": str(OPS / "orchestrator.jsonl")}


def alerts(u, hb, led):
    a = []
    o = u.get("apex-orchestrator", {})
    if o.get("result") == "oom-kill":
        a.append({"level": "CRITICAL", "text": "orchestrator Result=oom-kill"})
    for k, v in hb.items():
        if v["quality"] == "STALE" and k in ("orchestrator", "equity-shadow", "equity-field", "organism", "edgeforge-observatory", "apex-catalyst"):
            a.append({"level": "WARN", "text": "%s heartbeat stale %ss" % (k, v["age_s"])})
    if u.get("apex-gate2-opener", {}).get("result") == "exit-code":
        a.append({"level": "WARN", "text": "apex-gate2-opener failed; untraced"})
    if isinstance(led, dict) and led.get("missing"):
        a.append({"level": "INFO", "text": "orchestrator reports missing: %s" % led["missing"]})
    a.append({"level": "INFO", "text": "journal OOM counts NOT_AVAILABLE here (no sudo in the dashboard); see systemctl Result/NRestarts"})
    return a


def command_center():
    u, hb, led = units(), heartbeats(), orchestrator_ledger()
    return {"view": "COMMAND_CENTER", "as_of": now_iso(), "timezone": "UTC",
            "operating_mode": {"value": "OPERATIONAL_RECOVERY_COMMISSIONED; RESEARCH_SHADOW_ONLY; LIVE_TRADING=SEALED",
                               "source": "docs/MILESTONE1_PACKAGE.md", "quality": "DECLARED"},
            "versions": versions(), "units": u, "maintenance_holds": holds(), "heartbeats": hb,
            "orchestrator_ledger": led, "alerts": alerts(u, hb, led),
            "blockers": [{"id": "D1", "text": "historical as-known availability NOT_PROVEN"},
                         {"id": "EXP-001", "text": "real-data admission PENDING REVIEW"},
                         {"id": "options-paper", "text": "launch held pending activation authorization"}],
            "not_ready": ["forecast view", "scenario view", "opportunity view", "expression view",
                          "risk view", "book view", "learning view"]}


# ------------------------------------------------------------- MARKET DATA
def market_data():
    v = {"view": "MARKET_DATA", "as_of": now_iso(), "timezone": "UTC", "sources": {}}
    # health artifacts
    for name, p in (("alpaca_fabric", CORE / "intraday/alpaca_fabric_health.json"),
                    ("equity_fabric", CORE / "intraday/equity_fabric_health.json"),
                    ("btc_ws", CORE / "btc/ws_health.json"), ("btc_derivatives", CORE / "btc/derivatives_health.json"),
                    ("crypto", CORE / "crypto/crypto_health.json")):
        d = _json(p)
        v["sources"][name] = ({"health": {k: d.get(k) for k in list(d)[:8]}, "source": str(p), "quality": "MEASURED"}
                              if d else not_ready(str(p), "absent or unreadable"))
    # corpora
    hb = Path("/apex-data/history-b")
    integ = _tail_json(hb / "etf_continuous/integrity.jsonl", 1)
    if integ:
        r = integ[0]
        v["sources"]["etf_continuous"] = {"corpus_version": r.get("corpus_version"), "adjustment": r.get("adjustment"),
                                          "missing_by_symbol": r.get("missing_by_symbol"), "duplicates": r.get("duplicates"),
                                          "event_time": "per bar (vendor)", "receipt_time": "bulk 2026-08-29 (not per bar)",
                                          "publication_time": "NOT_AVAILABLE", "revision_time": "NOT_AVAILABLE",
                                          "source": str(hb / "etf_continuous/integrity.jsonl"), "quality": "MEASURED"}
    # the file ends with a pit_membership_summary row; the card wants the last
    # MEMBERSHIP row, so scan the tail for kind == "pit_membership"
    tail = _tail_json(hb / "pit_singlename/membership_v1.jsonl", 8)
    mem = [r for r in tail if r.get("kind") == "pit_membership"]
    summ = [r for r in tail if r.get("kind") == "pit_membership_summary"]
    if mem:
        m = mem[0]
        v["sources"]["pit_singlename"] = {"latest_member_month": m.get("member_month"), "decided_asof": m.get("decided_asof"),
                                          "rule": m.get("rule"), "n_symbols": len(m.get("symbols", [])),
                                          "distinct_member_names": (summ[0].get("distinct_member_names") if summ else None),
                                          "calendar_sessions": (summ[0].get("calendar_sessions") if summ else None),
                                          "decision_power": (summ[0].get("decision_power") if summ else None),
                                          "source": str(hb / "pit_singlename/membership_v1.jsonl"), "quality": "MEASURED"}
    man = Path("/apex-data/history-a/options_history/manifest.jsonl")
    last = _tail_json(man, 1)
    if last:
        v["sources"]["options_history"] = {"rows": sum(1 for _ in man.open()), "last_acquired_at": last[0].get("acquired_at"),
                                           "last_date": last[0].get("date"), "receipt_time": "acquired_at per file",
                                           "publication_time": "per-row source timestamp (recorded law)",
                                           "source": str(man), "quality": "MEASURED"}
    live = Path("/apex-data/runtime/data/live/alpaca_fabric/bars")
    if live.exists():
        files = sorted(live.glob("*.json"))
        dates = sorted({f.stem.split("_")[-1] for f in files})
        v["sources"]["live_capture"] = {"files": len(files), "first": dates[0] if dates else None, "last": dates[-1] if dates else None,
                                        "receipt_time": "per file (own capture)", "source": str(live), "quality": "MEASURED"}
    ps = _json(REPO / "results/pulse010r_SUMMARY.json")
    v["pulse"] = ({"verdicts": ps.get("verdicts"), "source": "results/pulse010r_SUMMARY.json", "quality": "RECORDED"}
                  if ps else not_ready("results/pulse010r_SUMMARY.json", "absent on this checkout"))
    v["refused_or_missing"] = ["bid/ask/spread/trade_count: NOT in the bar corpora",
                               "option-implied 15m benchmark: NOT_ESTIMABLE", "NKLA mirror subject: reconstructs nothing (STALE_BEYOND_POLICY)"]
    return v


# ------------------------------------------------------------- RESEARCH
def research():
    reg = _json(ALPHA / "results/exp001_registration.json")
    ret = _json(REPO / "results/milestone1_RETURN.json")
    rc, ah = _sh("git", "-C", str(ALPHA), "rev-parse", "HEAD")
    return {"view": "RESEARCH", "as_of": now_iso(), "timezone": "UTC",
            "exp001": ({"experiment": reg["registration"].get("EXPERIMENT_ID"), "registration_hash": reg.get("registration_hash"),
                        "instrument": reg["registration"].get("INSTRUMENT"), "horizon": reg["registration"].get("HORIZON"),
                        "periods": reg["registration"].get("PERIODS"), "statistic": reg["registration"].get("STATISTIC"),
                        "search_budget": reg["registration"].get("SEARCH_BUDGET"), "branch_head": ah,
                        "source": str(ALPHA / "results/exp001_registration.json"), "quality": "RECORDED"}
                       if reg else not_ready("exp001_registration.json", "absent")),
            "execution_status": {"engineering_mode": "13 tests PASS (synthetic fixtures)",
                                 "real_data": "BLOCKED at WORLD_MODEL_SOURCE_BOUNDARY_V0 (REAL_EVIDENCE_PATH); admission PENDING REVIEW",
                                 "prospective": "NOT_ACTIVATED", "source": "docs/EXP001_ADMISSION_PACKAGE.md"},
            "evidence_classes": {"synthetic": "engineering integration only", "historical": "NONE (not admitted)",
                                 "prospective": "NONE (not activated)"},
            "recovery_milestone": ({"verdict": ret.get("verdict"), "source": "results/milestone1_RETURN.json", "quality": "RECORDED"}
                                   if ret else not_ready("results/milestone1_RETURN.json", "absent on this checkout")),
            "limitations": ["power figures are ILLUSTRATIVE", "eligibility is a SUBMITTED assessment",
                            "positive-control fixture was strengthened after failures (test development, recorded)"]}


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>APEX Dashboard v0</title>
<style>body{font:13px/1.4 -apple-system,Segoe UI,Helvetica,sans-serif;margin:0;background:#0f1216;color:#d8dee6}
header{padding:10px 16px;background:#161b22;border-bottom:1px solid #2a313a;display:flex;gap:18px;align-items:baseline}
h1{font-size:15px;margin:0}.tab{cursor:pointer;color:#8ea0b5}.tab.on{color:#fff;border-bottom:2px solid #4c9be8}
main{padding:14px 16px;display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.card{background:#161b22;border:1px solid #2a313a;border-radius:6px;padding:10px 12px}.card h2{font-size:12px;margin:0 0 8px;color:#8ea0b5;text-transform:uppercase;letter-spacing:.06em}
table{width:100%;border-collapse:collapse}td,th{padding:3px 6px;text-align:left;border-bottom:1px solid #222a33;vertical-align:top}th{color:#8ea0b5;font-weight:500}
.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}.dim{color:#6b7785}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
#status{margin-left:auto;font-size:12px}.stale{color:#f85149;font-weight:600}.nr{color:#6b7785;font-style:italic}
</style></head><body><header><h1>APEX Dashboard v0 &middot; read-only &middot; UTC</h1>
<span class="tab on" data-v="command">Command Center</span><span class="tab" data-v="market">Market Data</span><span class="tab" data-v="research">Research</span>
<span id="status" class="dim">connecting&hellip;</span></header><main id="main"></main>
<script>
const R=15000;let view='command',lastOk={};
function q(o){return JSON.stringify(o)}
function badge(v){if(v===null||v===undefined)return'<span class="nr">NOT_AVAILABLE</span>';return String(v)}
function cls(v){v=String(v||'');if(/^(active|success|MEASURED|PASS|READY|present)/.test(v))return'ok';if(/STALE|WARN|inactive|activating/.test(v))return'warn';if(/ALIVE_IDLE/.test(v))return'dim';if(/oom|FAIL|CRITICAL|BLOCKED/.test(v))return'bad';return''}
function card(t,body){return`<div class="card"><h2>${t}</h2>${body}</div>`}
function tbl(rows,hdr){return`<table>${hdr?'<tr>'+hdr.map(h=>'<th>'+h+'</th>').join('')+'</tr>':''}${rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')}</table>`}
function renderCommand(d){let h='';
 h+=card('Operating mode',`<div>${d.operating_mode.value}</div><div class="dim">source: ${d.operating_mode.source} (${d.operating_mode.quality})</div>`);
 const v=d.versions;h+=card('Versions',tbl([['deployed release',`<span class="mono">${v.deployed_release}</span>`],...Object.entries(v.branch_heads).map(([b,x])=>[b,`<span class="mono">${x.slice(0,12)}</span>`])])+`<div class="dim">${v.source}</div>`);
 h+=card('Services (systemctl, unit cgroup)',tbl(Object.entries(d.units).map(([u,x])=>[u.replace('apex-',''),`<span class="${cls(x.active)}">${badge(x.active)}/${badge(x.sub)}</span>`,`<span class="${cls(x.result)}">${badge(x.result)}</span>`,badge(x.restarts),badge(x.memory_max_mib),badge(x.memory_peak_mib)]),['unit','state','result','restarts','cap MiB','peak MiB']));
 h+=card('Maintenance holds (systemd-enforced)',d.maintenance_holds.length?tbl(d.maintenance_holds.map(m=>[m.marker.replace('MAINTENANCE_BLOCK_',''),m.status,m.applied_utc])):'<span class="nr">none</span>');
 h+=card('Liveness and last completed work (heartbeats)',tbl(Object.entries(d.heartbeats).map(([k,x])=>[k,badge(x.beat_age_s),badge(x.last_work_utc),badge(x.work_age_s),badge(x.work_completed),`<span class="${cls(x.quality)}">${x.quality}</span>`]),['service','beat age s','last_work_utc','work age s','work','quality']));
 const l=d.orchestrator_ledger;h+=card('Orchestrator ledger (newest record)',l.value===null?`<span class="nr">NOT_READY: ${l.unit}</span>`:tbl([['at',badge(l.at)],['phase',badge(l.phase)],['missing',q(l.missing)],['incidents',badge(l.incidents)],['maintenance',q(l.maintenance)],['actions',q(l.actions)],['record bytes',badge(l.record_bytes)],['ledger bytes',badge(l.ledger_bytes)]]));
 h+=card('Alerts',tbl(d.alerts.map(a=>[`<span class="${cls(a.level)}">${a.level}</span>`,a.text])));
 h+=card('Blockers',tbl(d.blockers.map(b=>[b.id,b.text])));
 h+=card('Not ready (no fabricated values)',d.not_ready.map(x=>`<span class="nr">${x}: NOT_READY</span>`).join('<br>'));
 return h}
function renderMarket(d){let h='';for(const [k,s] of Object.entries(d.sources)){h+=card(k,s.value===null?`<span class="nr">NOT_READY: ${s.unit}</span>`:tbl(Object.entries(s).filter(([a])=>!['source','quality'].includes(a)).map(([a,b])=>[a,typeof b==='object'?`<span class="mono">${q(b)}</span>`:badge(b)]))+`<div class="dim">source: ${s.source} (${s.quality})</div>`)}
 h+=card('PULSE verdicts',d.pulse.value===null?`<span class="nr">NOT_READY: ${d.pulse.unit}</span>`:tbl(Object.entries(d.pulse.verdicts).map(([a,b])=>[a,`<span class="${cls(b)}">${b}</span>`]))+`<div class="dim">${d.pulse.source}</div>`);
 h+=card('Refused / missing inputs',d.refused_or_missing.map(x=>'<div>'+x+'</div>').join(''));return h}
function renderResearch(d){let h='';const e=d.exp001;h+=card('EXP-001 registration',e.value===null?`<span class="nr">NOT_READY</span>`:tbl([['experiment',e.experiment],['registration hash',`<span class="mono">${e.registration_hash}</span>`],['instrument / horizon',e.instrument+' / '+e.horizon],['periods',`<span class="mono">${q(e.periods)}</span>`],['statistic',e.statistic],['search budget',q(e.search_budget)],['branch head',`<span class="mono">${e.branch_head}</span>`]])+`<div class="dim">${e.source} (${e.quality})</div>`);
 h+=card('Execution & admission status',tbl(Object.entries(d.execution_status).filter(([a])=>a!=='source').map(([a,b])=>[a,`<span class="${cls(b)}">${b}</span>`]))+`<div class="dim">${d.execution_status.source}</div>`);
 h+=card('Evidence classes',tbl(Object.entries(d.evidence_classes).map(([a,b])=>[a,b])));
 const r=d.recovery_milestone;h+=card('Recovery milestone',r.value===null?`<span class="nr">NOT_READY: ${r.unit}</span>`:`<span class="mono">${q(r.verdict)}</span><div class="dim">${r.source}</div>`);
 h+=card('Limitations',d.limitations.map(x=>'<div>'+x+'</div>').join(''));return h}
async function load(){const s=document.getElementById('status');try{const r=await fetch('/api/'+view,{cache:'no-store'});if(!r.ok)throw new Error(r.status);const d=await r.json();lastOk[view]=d.as_of;document.getElementById('main').innerHTML=(view==='command'?renderCommand:view==='market'?renderMarket:renderResearch)(d);s.className='dim';s.textContent='updated '+d.as_of+' (UTC) · refresh '+(R/1000)+'s · read-only'}catch(e){s.className='stale';s.textContent='STALE / DISCONNECTED · last successful update '+(lastOk[view]||'never')+' · '+e}}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));t.classList.add('on');view=t.dataset.v;load()});
load();setInterval(load,R);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            fn = {"/api/command": command_center, "/api/market": market_data, "/api/research": research}.get(self.path)
            if not fn:
                return self._send(404, b'{"error":"not found"}', "application/json")
            return self._send(200, json.dumps(fn(), default=str).encode(), "application/json")
        except Exception as e:                               # noqa: BLE001
            return self._send(500, json.dumps({"error": type(e).__name__, "detail": str(e)[:300]}).encode(), "application/json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8790); a = ap.parse_args()
    print("APEX Dashboard v0 on http://127.0.0.1:%d  (read-only; loopback only)" % a.port, flush=True)
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()
