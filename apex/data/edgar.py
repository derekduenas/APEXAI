"""SEC EDGAR -- issuer identity, point-in-time shares outstanding, delistings.

DEVELOPMENT ONLY. See DATA_LIMITATIONS.md. Nothing here may feed a confirmatory
run; the fingerprint it contributes to is `dev-` namespaced and the verdict
layer, the ledger and the holdout gate all refuse it.

WHAT EDGAR IS GOOD FOR, AND IT IS MORE THAN EXPECTED

  CIK          A genuine permanent identifier. Never recycled, never deleted,
               stable across ticker changes, renames and delisting. This is
               exactly the property `contracts.py` demands of `security_id` and
               that no free price vendor provides.

  SHARES       The XBRL `companyconcept` endpoint returns each observation with
               a `filed` date alongside the period `end` date. Using `filed` as
               the knowledge date gives GENUINELY point-in-time shares
               outstanding -- the one place this free stack is architecturally
               correct rather than merely adequate.

  DELISTINGS   Form 25 / 25-NSE are the statutory delisting notifications --
               but they delist a SECURITY, not an ISSUER. Apple has filed one
               and is plainly still listed. Corroboration is therefore REQUIRED
               (see `issuer`), and even then EDGAR does not say WHY a security
               was delisted, so the performance-vs-M&A distinction that drives
               the Shumway haircut cannot be made from this source at all.

  SECTOR       SIC code. A PROXY, not the CONVENTIONS C3 taxonomy, and it is the
               issuer's CURRENT code -- not point-in-time. Documented as a
               limitation rather than presented as sector data.

FAIR ACCESS

SEC policy requires a descriptive User-Agent carrying contact details and asks
that requests stay under 10/second. This client sends the required header and
paces itself well below the limit. It is a public-domain government source, so
there is no licence restriction and no key.

NOTHING IS INVENTED

Where EDGAR has no shares-outstanding observation on or before a date, the
result is NaN and the security-date is excluded by the production
`pit_market_cap` filter. There is no forward fill beyond the last actual filing,
no back fill, and no interpolation.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

CA_BUNDLE = "/etc/ssl/cert.pem"
SEC_HOST = "https://www.sec.gov"
DATA_HOST = "https://data.sec.gov"

# SEC fair-access policy: identify yourself with a contact address.
DEFAULT_USER_AGENT = "apex-equities-research/0.1 (jrzcxph2dt@privaterelay.appleid.com)"

# SEC permits 10 requests/second. We stay well under it -- this is a courtesy
# to a free public service, and being throttled would corrupt a partial pull.
MIN_INTERVAL_SECONDS = 0.15

# The XBRL tag carrying the cover-page share count.
SHARES_TAG = "dei/EntityCommonStockSharesOutstanding"
# Fallback used by some filers.
SHARES_TAG_FALLBACK = "us-gaap/CommonStockSharesOutstanding"

# Statutory delisting notifications.
DELISTING_FORMS = {"25", "25-NSE"}


class EdgarError(RuntimeError):
    """EDGAR could not supply something that was asked for."""


@dataclass
class Issuer:
    """One issuer, as EDGAR knows it."""

    cik: str
    ticker: str
    name: str
    sic: str
    sic_description: str
    exchanges: tuple
    former_names: tuple = ()
    first_filing: str = ""
    last_filing: str = ""
    delist_date: str = ""
    delist_form: str = ""
    delist_evidence: str = ""
    still_listed: bool = True

    @property
    def security_id(self) -> str:
        """CIK, zero-padded. A permanent identifier -- never the ticker."""
        return f"CIK{int(self.cik):010d}"


@dataclass
class SharesObservation:
    """A single point-in-time share count.

    `filed` is the knowledge date -- when the number became public. `end` is the
    period it describes. Using `end` would be lookahead; the whole point of this
    record is that the two are kept apart.
    """

    cik: str
    filed: str
    end: str
    value: float
    form: str
    accession: str


@dataclass
class EdgarFetchLog:
    """Everything the manifest needs, and everything that went wrong."""

    requests: int = 0
    started_at: str = ""
    finished_at: str = ""
    endpoints: list = field(default_factory=list)
    failures: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source": "SEC EDGAR (public domain)",
            "requests": self.requests,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "endpoints": self.endpoints,
            "failures": self.failures,
        }


class EdgarClient:
    """Polite, rate-limited, no-key client for public SEC endpoints."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.user_agent = user_agent
        self._ctx = ssl.create_default_context(cafile=CA_BUNDLE)
        self._last_request = 0.0
        self.log = EdgarFetchLog(started_at=dt.datetime.now(dt.timezone.utc).isoformat())

    def _get(self, url: str) -> bytes:
        elapsed = time.monotonic() - self._last_request
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        self._last_request = time.monotonic()

        request = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip"}
        )
        self.log.requests += 1
        root = urllib.parse.urlsplit(url)._replace(query="", fragment="").geturl()
        base = root.rsplit("/", 1)[0]
        if base not in self.log.endpoints:
            self.log.endpoints.append(base)

        with urllib.request.urlopen(request, timeout=45, context=self._ctx) as response:
            payload = response.read()
            if "gzip" in (response.headers.get("Content-Encoding") or ""):
                payload = gzip.decompress(payload)
            return payload

    def _get_json(self, url: str) -> dict:
        return json.loads(self._get(url).decode("utf-8"))

    # -- identity ------------------------------------------------------------

    def ticker_map(self) -> dict:
        """Current ticker -> CIK. CURRENT ONLY; see DATA_LIMITATIONS.md section 5."""
        raw = self._get_json(f"{SEC_HOST}/files/company_tickers.json")
        out: dict = {}
        for entry in raw.values():
            out.setdefault(str(entry["ticker"]).upper(), str(entry["cik_str"]))
        if not out:
            raise EdgarError("company_tickers.json returned no entries")
        return out

    def issuer(self, cik: str, ticker: str = "") -> Issuer:
        """Identity, sector proxy, filing span and any delisting notification."""
        padded = f"{int(cik):010d}"
        data = self._get_json(f"{DATA_HOST}/submissions/CIK{padded}.json")

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", []) or []
        dates = recent.get("filingDate", []) or []

        # A Form 25 delists a SECURITY, not an ISSUER. Apple has filed one (to
        # delist a class of notes) and is plainly still listed. Treating the
        # filing alone as an issuer delisting date marks live mega-caps as dead
        # and silently poisons the universe -- measured on real data, 2026-08-10.
        #
        # We therefore require CORROBORATION: a Form 25 AND no current exchange
        # listing AND no current ticker. Anything less is reported as unverified
        # and the security is treated as still listed.
        form25_date, form25_form = "", ""
        for form, filed in zip(forms, dates):
            if str(form).upper() in DELISTING_FORMS:
                form25_date, form25_form = filed, str(form).upper()

        exchanges = tuple(data.get("exchanges") or [])
        current_tickers = data.get("tickers") or []
        listed_now = bool(exchanges) and bool(current_tickers)

        delist_date, delist_form, evidence = "", "", ""
        if form25_date and not listed_now:
            delist_date, delist_form = form25_date, form25_form
            evidence = "form25+no_current_listing"
        elif form25_date and listed_now:
            evidence = (
                "form25_present_but_issuer_STILL_LISTED -- the filing delisted "
                "some other security of this issuer, not its common stock"
            )

        former = tuple(
            (f.get("name", ""), (f.get("from") or "")[:10], (f.get("to") or "")[:10])
            for f in (data.get("formerNames") or [])
        )

        return Issuer(
            cik=str(int(cik)),
            ticker=(ticker or (current_tickers[0] if current_tickers else "")).upper(),
            name=data.get("name", ""),
            sic=str(data.get("sic") or ""),
            sic_description=data.get("sicDescription", ""),
            exchanges=exchanges,
            former_names=former,
            first_filing=min(dates) if dates else "",
            last_filing=max(dates) if dates else "",
            delist_date=delist_date,
            delist_form=delist_form,
            delist_evidence=evidence,
            still_listed=listed_now,
        )

    # -- point-in-time shares outstanding ------------------------------------

    def shares_outstanding(self, cik: str) -> list:
        """Every reported share count, each carrying its FILING date.

        Returns an empty list when the issuer has no XBRL share data -- which is
        normal before roughly 2009. That absence is propagated as NaN market cap
        and excluded by the production filter, never filled.
        """
        padded = f"{int(cik):010d}"
        for tag in (SHARES_TAG, SHARES_TAG_FALLBACK):
            url = f"{DATA_HOST}/api/xbrl/companyconcept/CIK{padded}/{tag}.json"
            try:
                data = self._get_json(url)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                raise

            observations = []
            for unit_values in (data.get("units") or {}).values():
                for row in unit_values:
                    if not row.get("filed") or row.get("val") is None:
                        continue
                    observations.append(
                        SharesObservation(
                            cik=str(int(cik)),
                            filed=row["filed"],
                            end=row.get("end", ""),
                            value=float(row["val"]),
                            form=row.get("form", ""),
                            accession=row.get("accn", ""),
                        )
                    )
            if observations:
                return sorted(observations, key=lambda o: (o.filed, o.end))
        return []

    # -- delisted issuers ----------------------------------------------------

    def delisting_filers(self, year: int, quarter: int, limit: int = 200) -> list:
        """CIKs that filed a Form 25 in a given quarter, from the full index.

        This is how real delisted issuers enter the development universe. Without
        it the dev set would be exactly the survivorship-biased sample the
        protocol forbids -- still unfit for confirmation, but unable to exercise
        the delisting code paths at all.
        """
        url = f"{SEC_HOST}/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"
        try:
            text = self._get(url).decode("latin-1")
        except urllib.error.HTTPError as exc:
            raise EdgarError(f"full-index {year} QTR{quarter} unavailable: HTTP {exc.code}")

        found = []
        for line in text.splitlines():
            form = line[:12].strip().upper()
            if form not in DELISTING_FORMS:
                continue
            # Fixed-width: form | company | CIK | date | filename
            parts = line.split()
            for token in parts:
                if token.isdigit() and 3 <= len(token) <= 10:
                    found.append(token)
                    break
            if len(found) >= limit:
                break
        return found

    def finish(self) -> EdgarFetchLog:
        self.log.finished_at = dt.datetime.now(dt.timezone.utc).isoformat()
        return self.log
