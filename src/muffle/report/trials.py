"""Recruiting clinical trials that mention a patient's observed genes (ClinicalTrials.gov API v2,
no key; a U.S. government database: attribute it and show the date its data were processed).

For clinician review: a trial that mentions a gene is not a match, and eligibility is not
assessed here. Each query sends only "<GENE> mutation" with the condition "breast cancer" and the
statuses recruiting or not yet recruiting, never anything from a patient's record. Results are
cached on disk for a day (``CACHE``); when the registry can't be reached the stale cache, then
the bundled snapshot (``SNAPSHOT``, written by scripts/refresh_trials.py) answer, and the result
says which, with its date.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://clinicaltrials.gov/api/v2/studies"
VERSION_API = "https://clinicaltrials.gov/api/v2/version"
SNAPSHOT = Path(__file__).resolve().parents[3] / "app" / "trials_snapshot.json"
CACHE = Path("data/raw/trials")
CONDITION = "breast cancer"
STATUSES = "RECRUITING,NOT_YET_RECRUITING"
FIELDS = ("NCTId,BriefTitle,Phase,OverallStatus,InterventionName,LocationCountry,"
          "LastUpdatePostDate")
PAGE = 20  # trials kept per gene: the registry's first page, in its own relevance order
TTL = 24 * 3600


def term(gene: str) -> str:
    """The query term: the observed event, "<GENE> mutation" (a bare gene symbol also matches
    the registry's synonyms, e.g. ESR1 brings every estrogen-receptor trial)."""
    return f"{gene} mutation"


def params(gene: str, n: int = PAGE) -> dict:
    return {"query.cond": CONDITION, "query.term": term(gene), "filter.overallStatus": STATUSES,
            "fields": FIELDS, "pageSize": n, "countTotal": "true"}


def search_url(gene: str) -> str:
    """The same search on the registry's website."""
    return ("https://clinicaltrials.gov/search?" + urllib.parse.urlencode(
        {"cond": CONDITION, "term": term(gene), "aggFilters": "status:not rec"}))


def _get(url: str, timeout: float = 8) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _phase(code: str) -> str:
    return {"NA": "not applicable", "EARLY_PHASE1": "early phase 1"}.get(
        code, code.replace("PHASE", "phase "))


def _study(s: dict) -> dict:
    p = s.get("protocolSection", {})
    countries = [loc.get("country") for loc in p.get("contactsLocationsModule", {})
                 .get("locations", []) if loc.get("country")]
    return {"nct": p.get("identificationModule", {}).get("nctId", ""),
            "title": p.get("identificationModule", {}).get("briefTitle", ""),
            "phase": ", ".join(map(_phase, p.get("designModule", {}).get("phases", [])))
            or "not stated",
            "status": p.get("statusModule", {}).get("overallStatus", "").replace("_", " ")
            .lower(),
            "updated": p.get("statusModule", {}).get("lastUpdatePostDateStruct", {})
            .get("date", ""),
            "interventions": [i.get("name", "") for i in p.get("armsInterventionsModule", {})
                              .get("interventions", [])],
            "countries": list(dict.fromkeys(countries))}


_stamp = {"at": 0.0, "value": ""}


def data_timestamp() -> str:
    """When ClinicalTrials.gov last processed its data, asked at most once a day ("" if it has
    not been reached yet)."""
    if time.time() - _stamp["at"] > TTL:
        try:
            _stamp.update(value=_get(VERSION_API).get("dataTimestamp", ""), at=time.time())
        except Exception:  # unreachable: keep the last answer, ask again next time
            pass
    return _stamp["value"]


def fetch(gene: str, n: int = PAGE) -> dict:
    """One live query: {"gene", "term", "total", "studies", "fetched", "data_timestamp"}."""
    r = _get(API + "?" + urllib.parse.urlencode(params(gene, n)))
    return {"gene": gene, "term": term(gene), "total": r.get("totalCount"),
            "studies": [_study(s) for s in r.get("studies", [])],
            "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "data_timestamp": data_timestamp()}


def load_snapshot(path: Path = SNAPSHOT) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def studies(gene: str, live: bool = True) -> dict:
    """Trials for one gene, freshest source first: today's disk cache, the live registry, an
    older cache, the bundled snapshot. ``source`` says which ("cache", "live", "stale cache",
    "snapshot" or "none") and ``note`` how old it is."""
    path = CACHE / f"{gene}.json"
    cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if cached and time.time() - path.stat().st_mtime < TTL:
        return {**cached, "source": "cache", "note": f"registry query of {cached['fetched']}"}
    if live:
        try:
            r = fetch(gene)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(r), encoding="utf-8")
            except OSError:  # a read-only disk still gets the live answer
                pass
            return {**r, "source": "live", "note": f"registry query of {r['fetched']}"}
        except Exception:  # unreachable, slow or changed: fall back, never fail the page
            pass
    if cached:
        return {**cached, "source": "stale cache",
                "note": f"the registry could not be reached; last query {cached['fetched']}"}
    snap = load_snapshot()
    if gene in snap.get("genes", {}):
        return {**snap["genes"][gene], "source": "snapshot",
                "note": f"the registry could not be reached; bundled snapshot of "
                        f"{snap['snapshot']}"}
    return {"gene": gene, "term": term(gene), "total": None, "studies": [], "source": "none",
            "note": "the registry could not be reached and the snapshot has no query for this "
                    "gene"}
