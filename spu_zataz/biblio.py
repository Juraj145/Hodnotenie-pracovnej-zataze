"""Načítanie publikácií z databáz Scopus (Elsevier) a Web of Science (Clarivate).

Obe služby vyžadujú vlastný API kľúč:
  * Scopus:  https://dev.elsevier.com  (Scopus Search API; prístup cez sieť / licenciu SPU,
             mimo siete univerzity aj „Institutional token“)
  * WoS:     https://developer.clarivate.com  (Web of Science Starter API)

Dôležité: metodický pokyn určuje kvartil V2/V3 podľa AIS (Article Influence Score, JCR)
a podiel autora podľa CREPČ. Tieto údaje API neposkytujú v požadovanej podobe, preto
sa načítané publikácie zobrazia na kontrolu, kde používateľ doplní kvartil a podiel.
Kvartil podľa CiteScore percentilu zo Scopusu sa dá zapnúť len ako orientačný návrh.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from .config import KATEGORIE_PUBLIKACII

TIMEOUT = 30


class BiblioChyba(Exception):
    pass


@dataclass
class NajdenaPublikacia:
    rok: int
    nazov: str
    casopis: str
    typ: str
    identifikator: str      # EID / UT
    doi: str
    issn: str
    pocet_autorov: int      # 0 = neznámy
    zdroj: str              # Scopus / WoS
    kategoria: str = KATEGORIE_PUBLIKACII[2]
    kvartil: str = "Bez Q"
    podiel: float = 1.0


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SPU-Zataz", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        if e.code in (401, 403):
            raise BiblioChyba(f"Prístup zamietnutý ({e.code}). Skontrolujte API kľúč a či ste v sieti univerzity. {detail}")
        if e.code == 429:
            raise BiblioChyba("Prekročený limit požiadaviek API. Skúste to neskôr.")
        raise BiblioChyba(f"Chyba servera {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise BiblioChyba(f"Nepodarilo sa pripojiť: {e.reason}")


def _kategoria_z_typu(typ: str) -> str:
    t = (typ or "").lower()
    if "book" in t and "chapter" not in t:
        return KATEGORIE_PUBLIKACII[0]
    if "edited" in t:
        return KATEGORIE_PUBLIKACII[1]
    return KATEGORIE_PUBLIKACII[2]   # indexované vo WoS/Scopus


# ------------------------------------------------------------------ Scopus

SCOPUS_SEARCH = "https://api.elsevier.com/content/search/scopus"
SCOPUS_SERIAL = "https://api.elsevier.com/content/serial/title/issn/"


def scopus_publikacie(author_id: str, rok_od: int, rok_do: int, api_key: str, insttoken: str = "",
                      navrh_kvartilu: bool = False, progress: Optional[Callable[[str], None]] = None) -> list[NajdenaPublikacia]:
    if not api_key:
        raise BiblioChyba("Chýba Scopus API kľúč (Nastavenia → API kľúče).")
    headers = {"X-ELS-APIKey": api_key}
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    query = f"AU-ID({author_id.strip()}) AND PUBYEAR > {rok_od - 1} AND PUBYEAR < {rok_do + 1}"
    out, start = [], 0
    while True:
        url = SCOPUS_SEARCH + "?" + urllib.parse.urlencode({"query": query, "start": start, "count": 25})
        data = _get_json(url, headers)["search-results"]
        entries = data.get("entry", [])
        if entries and "error" in entries[0]:
            break
        for e in entries:
            rok = int(str(e.get("prism:coverDate", "0"))[:4] or 0)
            typ = e.get("subtypeDescription", "") or e.get("prism:aggregationType", "")
            p = NajdenaPublikacia(
                rok=rok, nazov=e.get("dc:title", ""), casopis=e.get("prism:publicationName", ""), typ=typ,
                identifikator=e.get("eid", ""), doi=e.get("prism:doi", ""),
                issn=e.get("prism:issn", "") or e.get("prism:eIssn", ""),
                pocet_autorov=int(e.get("author-count", {}).get("$", 0) or 0) if isinstance(e.get("author-count"), dict) else 0,
                zdroj="Scopus", kategoria=_kategoria_z_typu(typ))
            if p.pocet_autorov:
                p.podiel = round(1 / p.pocet_autorov, 4)
            out.append(p)
        total = int(data.get("opensearch:totalResults", 0))
        start += len(entries)
        if progress:
            progress(f"Scopus: načítaných {start} z {total}")
        if not entries or start >= total:
            break
    if navrh_kvartilu:
        cache: dict[str, str] = {}
        for p in out:
            if p.issn and p.kategoria == KATEGORIE_PUBLIKACII[2]:
                if p.issn not in cache:
                    cache[p.issn] = _scopus_kvartil(p.issn, p.rok, headers)
                p.kvartil = cache[p.issn]
    return out


def _scopus_kvartil(issn: str, rok: int, headers: dict) -> str:
    """Orientačný kvartil podľa najlepšieho CiteScore percentilu (nie AIS!)."""
    try:
        d = _get_json(SCOPUS_SERIAL + urllib.parse.quote(issn.replace("-", "")) + "?view=CITESCORE", headers)
        entry = d["serial-metadata-response"]["entry"][0]
        roky = entry["citeScoreYearInfoList"]["citeScoreYearInfo"]
        vyber = [y for y in roky if str(y.get("@year")) == str(rok)] or roky
        best = 0.0
        for info in vyber[0]["citeScoreInformationList"]:
            for ci in info.get("citeScoreInfo", []):
                for rank in ci.get("citeScoreSubjectRank", []):
                    best = max(best, float(rank.get("percentile", 0)))
        if best >= 75:
            return "Q1"
        if best >= 50:
            return "Q2"
        if best >= 25:
            return "Q3"
        return "Q4" if best > 0 else "Bez Q"
    except (BiblioChyba, KeyError, IndexError, ValueError, TypeError):
        return "Bez Q"


# ------------------------------------------------------------------ Web of Science

WOS_STARTER = "https://api.clarivate.com/apis/wos-starter/v1/documents"


def wos_publikacie(researcher_id: str, rok_od: int, rok_do: int, api_key: str,
                   progress: Optional[Callable[[str], None]] = None) -> list[NajdenaPublikacia]:
    if not api_key:
        raise BiblioChyba("Chýba Web of Science API kľúč (Nastavenia → API kľúče).")
    headers = {"X-ApiKey": api_key}
    q = f"AI=({researcher_id.strip()}) AND PY=({rok_od}-{rok_do})"
    out, page = [], 1
    while True:
        url = WOS_STARTER + "?" + urllib.parse.urlencode({"db": "WOS", "q": q, "limit": 50, "page": page})
        data = _get_json(url, headers)
        hits = data.get("hits", [])
        for h in hits:
            src = h.get("source", {}) or {}
            ids = h.get("identifiers", {}) or {}
            autori = (h.get("names", {}) or {}).get("authors", []) or []
            typ = ", ".join(h.get("types", []) or [])
            p = NajdenaPublikacia(
                rok=int(src.get("publishYear") or 0), nazov=h.get("title", ""), casopis=src.get("sourceTitle", ""),
                typ=typ, identifikator=h.get("uid", ""), doi=ids.get("doi", ""),
                issn=ids.get("issn", "") or ids.get("eissn", ""), pocet_autorov=len(autori), zdroj="WoS",
                kategoria=_kategoria_z_typu(typ))
            if p.pocet_autorov:
                p.podiel = round(1 / p.pocet_autorov, 4)
            out.append(p)
        total = int((data.get("metadata", {}) or {}).get("total", 0))
        if progress:
            progress(f"WoS: načítaných {len(out)} z {total}")
        if not hits or len(out) >= total:
            break
        page += 1
    return out


def odstran_duplicity(pubs: list[NajdenaPublikacia]) -> list[NajdenaPublikacia]:
    """Spojí výsledky zo Scopusu a WoS – rovnaké DOI sa započíta iba raz."""
    seen, out = set(), []
    for p in pubs:
        key = (p.doi or "").lower() or (p.nazov.lower().strip(), p.rok)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out
