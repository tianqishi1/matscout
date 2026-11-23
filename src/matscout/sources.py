"""OpenAlex / Crossref adapters: search, DOI verification, normalization.

Only open metadata + abstracts are used. No paywall scraping.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from . import http

OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d or None


def title_hash(title: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def reconstruct_abstract(inv_index: dict | None) -> str | None:
    if not inv_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions) or None


def _mailto() -> str | None:
    return os.environ.get("MATSCOUT_CONTACT") or None


def _norm_openalex(w: dict) -> dict:
    authors = [a.get("author", {}).get("display_name", "") for a in (w.get("authorships") or [])][:12]
    venue = None
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    venue = src.get("display_name")
    doi = normalize_doi(w.get("doi"))
    return {
        "doi": doi,
        "title": w.get("display_name") or w.get("title") or "(untitled)",
        "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
        "year": w.get("publication_year"),
        "venue": venue,
        "authors": authors,
        "url": f"https://doi.org/{doi}" if doi else w.get("id"),
        "source": "openalex",
        "raw": w,
    }


def _norm_crossref(m: dict) -> dict:
    titles = m.get("title") or ["(untitled)"]
    authors = []
    for a in (m.get("author") or [])[:12]:
        name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if name:
            authors.append(name)
    year = None
    for key in ("issued", "published-print", "published-online", "created"):
        parts = (m.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = parts[0][0]
            break
    venues = m.get("container-title") or []
    doi = normalize_doi(m.get("DOI"))
    return {
        "doi": doi,
        "title": titles[0],
        "abstract": re.sub(r"<[^>]+>", " ", m.get("abstract") or "").strip() or None,
        "year": year,
        "venue": venues[0] if venues else None,
        "authors": authors,
        "url": f"https://doi.org/{doi}" if doi else m.get("URL"),
        "source": "crossref",
        "raw": m,
    }


def openalex_search(query: str, *, year_from=None, year_to=None, limit=10,
                    conn=None, fetch=None) -> list[dict]:
    filters = []
    if year_from:
        filters.append(f"from_publication_date:{int(year_from)}-01-01")
    if year_to:
        filters.append(f"to_publication_date:{int(year_to)}-12-31")
    params = {
        "search": query,
        "per-page": max(1, min(int(limit), 25)),
        "filter": ",".join(filters) if filters else None,
        "mailto": _mailto(),
    }
    data = http.get_json(OPENALEX, params, conn=conn, fetch=fetch)
    return [_norm_openalex(w) for w in (data.get("results") or [])]


def crossref_by_doi(doi: str, *, conn=None, fetch=None) -> dict | None:
    doi = normalize_doi(doi)
    if not doi:
        return None
    try:
        data = http.get_json(f"{CROSSREF}/{urllib_quote(doi)}", {"mailto": _mailto()}, conn=conn, fetch=fetch)
    except http.HttpError as e:
        if e.status == 404:
            return None
        raise
    m = data.get("message")
    return _norm_crossref(m) if m else None


def openalex_by_doi(doi: str, *, conn=None, fetch=None) -> dict | None:
    doi = normalize_doi(doi)
    if not doi:
        return None
    try:
        data = http.get_json(f"{OPENALEX}/doi:{doi}", {"mailto": _mailto()}, conn=conn, fetch=fetch)
    except http.HttpError as e:
        if e.status == 404:
            return None
        raise
    return _norm_openalex(data) if data.get("id") else None


def crossref_title_candidates(title: str, *, rows=3, conn=None, fetch=None) -> list[dict]:
    data = http.get_json(CROSSREF, {"query.bibliographic": title, "rows": rows, "mailto": _mailto()},
                         conn=conn, fetch=fetch)
    items = (data.get("message") or {}).get("items") or []
    return [_norm_crossref(m) for m in items]


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
