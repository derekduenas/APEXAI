"""AUTONOMOUS EVENT-TIMING CERTIFICATION from SEC EDGAR.

The broker calendar's am/pm label is vendor data. EDGAR's 8-K
acceptance timestamp (Item 2.02, Results of Operations) is the
authoritative public record of WHEN the earnings information was
filed. For each watched event near its report date, this fetches the
issuer's recent 8-K filings and seals a timing certification:

  BEFORE_MARKET_OPEN   accepted before 09:30 ET on the report date
  DURING_RTH           accepted 09:30-16:00 ET
  AFTER_MARKET_CLOSE   accepted after 16:00 ET
  TIMING_UNCERTIFIED   no matching 2.02 8-K found (vendor label
                       stands, flagged uncertified)

Uses the SEC's own ticker->CIK map (cached). Rate-limited and
UA-identified per SEC policy. decision_power: SHADOW_PROSPECTIVE_ONLY.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apex.governance.chain_ledger import chain_append  # noqa: E402

LEDGER = Path("results/event_sprint/prospective_ledger.jsonl")
TICKERS = Path("data/reference/sec_company_tickers_raw.json")
NY = ZoneInfo("America/New_York")
UA = "APEX research derek@apex.local"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception:
            if a == 2:
                return None
            time.sleep(2)


def cik_map():
    if TICKERS.exists():
        age_ok = (time.time() - TICKERS.stat().st_mtime) < 7 * 86400
        if age_ok:
            raw = json.loads(TICKERS.read_text())
            return {v["ticker"].upper(): int(v["cik_str"])
                    for v in raw.values()}
    raw = _get("https://www.sec.gov/files/company_tickers.json")
    if raw is None:
        if TICKERS.exists():
            raw = json.loads(TICKERS.read_text())
        else:
            return {}
    else:
        TICKERS.parent.mkdir(parents=True, exist_ok=True)
        TICKERS.write_text(json.dumps(raw))
    return {v["ticker"].upper(): int(v["cik_str"])
            for v in raw.values()}


def classify(accepted_et):
    m = accepted_et.hour * 60 + accepted_et.minute
    if m < 570:
        return "BEFORE_MARKET_OPEN"
    if m < 960:
        return "DURING_RTH"
    return "AFTER_MARKET_CLOSE"


def main():
    rows = []
    for l in LEDGER.read_text().splitlines():
        try:
            rows.append(json.loads(l))
        except Exception:
            pass
    done = {(r["symbol"], r["report_date"]) for r in rows
            if r.get("kind") == "timing_certification"}
    today = datetime.now(NY).date()
    todo = []
    for r in rows:
        if r.get("kind") != "watch":
            continue
        k = (r["symbol"], r["report_date"])
        if k in done or k in {(t["symbol"], t["report_date"])
                              for t in todo}:
            continue
        rd = datetime.strptime(r["report_date"], "%Y-%m-%d").date()
        # certify once the filing had time to appear, within a window
        if timedelta(days=0) <= (today - rd) <= timedelta(days=6):
            todo.append(r)
    cm = cik_map()
    n_cert = n_uncert = 0
    for r in todo[:40]:                       # SEC-politeness cap
        cik = cm.get(r["symbol"].upper())
        rec = {"kind": "timing_certification", "symbol": r["symbol"],
               "report_date": r["report_date"],
               "vendor_timing": r["timing"],
               "source": "SEC_EDGAR_8K_ITEM_2.02_ACCEPTANCE"}
        cert = None
        if cik:
            sub = _get(f"https://data.sec.gov/submissions/"
                       f"CIK{cik:010d}.json")
            time.sleep(0.4)
            try:
                rec_forms = sub["filings"]["recent"]
                for i, form in enumerate(rec_forms["form"]):
                    if form != "8-K":
                        continue
                    items = (rec_forms.get("items") or [""] * 1)[i] \
                        if i < len(rec_forms.get("items", [])) else ""
                    fdate = rec_forms["filingDate"][i]
                    if "2.02" not in (items or ""):
                        continue
                    rd = r["report_date"]
                    if abs((datetime.strptime(fdate, "%Y-%m-%d")
                            - datetime.strptime(rd, "%Y-%m-%d")
                            ).days) > 1:
                        continue
                    acc = rec_forms["acceptanceDateTime"][i]
                    et = datetime.fromisoformat(
                        acc.replace("Z", "+00:00")).astimezone(NY)
                    cert = {"accepted_et": et.isoformat(),
                            "classification": classify(et),
                            "filing_date": fdate}
                    break
            except Exception:
                cert = None
        if cert:
            rec.update(cert)
            rec["agrees_with_vendor"] = (
                (cert["classification"] == "AFTER_MARKET_CLOSE"
                 and r["timing"] == "pm")
                or (cert["classification"] == "BEFORE_MARKET_OPEN"
                    and r["timing"] == "am"))
            n_cert += 1
        else:
            rec["classification"] = "TIMING_UNCERTIFIED"
            rec["why"] = ("no CIK" if not cik
                          else "no matching 2.02 8-K yet")
            n_uncert += 1
        chain_append(LEDGER, rec)
    print(json.dumps({"certified": n_cert,
                      "uncertified": n_uncert,
                      "examined": len(todo[:40])}))


if __name__ == "__main__":
    main()
