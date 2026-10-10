"""Identifikátory autorov: ORCID, Scopus Author ID, Web of Science ResearcherID.

Zdroje (verejné, bez prihlásenia):
  1. menné autority Slovenskej poľnohospodárskej knižnice (arl4.library.sk, databáza SpuUsAuth) – pole 024
     s ORCID, pole C48 s pracoviskom na SPU,
  2. register ORCID (pub.orcid.org) – vyhľadanie podľa mena a pracoviska SPU, ak knižnica ORCID nemá,
  3. profil ORCID – externé identifikátory „Scopus Author ID“ a „ResearcherID“, ktoré si autor prepojil.

Doplnia sa iba prázdne polia; existujúce hodnoty sa neprepisujú. Pri nejednoznačnej zhode (viac osôb
s rovnakým menom) sa nič nedoplní a učiteľ zostane označený na ručné doplnenie.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from . import epca
from .version import __version__

ORCID_API = "https://pub.orcid.org/v3.0"
SPU_ORCID = "Slovak University of Agriculture"
DB_AUTORITY = "SpuUsAuth"
RE_ORCID = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b")


class IdChyba(Exception):
    pass


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": f"SPU-Zataz/{__version__} (hodnotenie pracovnej zataze)"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise IdChyba(f"{urllib.parse.urlparse(url).netloc}: {e}") from e


# ------------------------------------------------------------------ autority knižnice

@dataclass
class Autorita:
    id: str
    meno: str               # „Priezvisko, Meno“
    orcid: str = ""
    crepc: str = ""
    spu: bool = False       # pracovisko na SPU (pole C48)
    pracovisko: str = ""


def parsuj_autoritu(rec: dict) -> Autorita:
    p = epca.polia(rec.get("data", []))

    def sf(pole, kod):
        return [v for k, v in pole if k == kod]

    a = Autorita(id=rec.get("t001", ""), meno=(sf(p["100"][0], "a") or [""])[0].rstrip(",. ") if "100" in p else "")
    for pole in p.get("024", []):
        if "orcid" in " ".join(sf(pole, "2")).lower():
            m = RE_ORCID.search(" ".join(sf(pole, "a") + sf(pole, "1")))
            if m:
                a.orcid = m.group(1)
    for pole in p.get("035", []):
        if "CREPC" in " ".join(sf(pole, "2")).upper():
            a.crepc = (sf(pole, "a") or [""])[0]
    for pole in p.get("C48", []):
        text = " ".join(sf(pole, "X") + sf(pole, "a"))
        if "poľnohospodárska univerzita" in text.lower() or re.search(r"\bSPU", text):
            a.spu = True
            a.pracovisko = (sf(pole, "X") or [a.pracovisko])[0]
    return a


def autority(priezvisko: str, limit: int = 300) -> list[Autorita]:
    out, od, spolu = [], 1, 1
    while od <= spolu and od <= limit:
        d = epca.hladaj(f"@attr 1=1 {epca._pqf(priezvisko)}", od, od + 99, db=DB_AUTORITY)
        spolu = int(d.get("hits") or 0)
        out.extend(parsuj_autoritu(r) for r in d.get("records") or [])
        od += 100
    return out


def zhoda_mena(meno_ucitela: str, meno_autority: str) -> bool:
    a, b = set(epca.kluc_mena(meno_ucitela).split()), set(epca.kluc_mena(meno_autority).split())
    return len(b) >= 2 and b <= a


# ------------------------------------------------------------------ ORCID

def orcid_hladaj(priezvisko: str, krstne: str = "", pracovisko: str = SPU_ORCID) -> list[dict]:
    q = f'family-name:"{priezvisko}"'
    if krstne:
        q += f' AND given-names:"{krstne}"'
    if pracovisko:
        q += f' AND affiliation-org-name:"{pracovisko}"'
    d = _get_json(f"{ORCID_API}/expanded-search/?rows=20&q=" + urllib.parse.quote(q))
    return d.get("expanded-result") or []


def orcid_externe(orcid: str) -> dict[str, str]:
    """{'scopus': …, 'wos': …} z externých identifikátorov profilu ORCID."""
    d = _get_json(f"{ORCID_API}/{orcid}/external-identifiers")
    return externe_z_odpovede(d)


def externe_z_odpovede(d: dict) -> dict[str, str]:
    out = {}
    for e in d.get("external-identifier") or []:
        typ = (e.get("external-id-type") or "").lower()
        hodnota = (e.get("external-id-value") or "").strip()
        if not hodnota:
            continue
        if "scopus" in typ and "scopus" not in out:
            out["scopus"] = hodnota
        elif ("researcherid" in typ or "web of science" in typ) and "wos" not in out:
            out["wos"] = hodnota
    return out


# ------------------------------------------------------------------ učiteľ

@dataclass
class NajdeneId:
    ucitel_id: int
    meno: str
    orcid: str = ""
    scopus: str = ""
    wos: str = ""
    zdroje: list[str] = field(default_factory=list)
    poznamka: str = ""

    @property
    def nieco(self) -> bool:
        return bool(self.orcid or self.scopus or self.wos)


def slova_mena(meno: str) -> list[str]:
    t = re.sub(r"\b(prof|doc|ing|mgr|bc|rndr|phdr|paeddr|phd|csc|drsc|mba)\.", " ", meno or "", flags=re.I)
    return [w for w in re.split(r"[\s,]+", t) if len(w) > 1 and not w.endswith(".")]


def najdi(ucitel, cache: Optional[dict] = None) -> NajdeneId:
    """Nájde ORCID, Scopus Author ID a ResearcherID učiteľa (doplní iba chýbajúce)."""
    cache = cache if cache is not None else {}
    res = NajdeneId(ucitel_id=ucitel.id, meno=ucitel.cele_meno, orcid=ucitel.orcid or "")
    slova = slova_mena(ucitel.meno)
    if not slova:
        res.poznamka = "chýba meno"
        return res

    # 1. menné autority knižnice SPU
    if not res.orcid:
        kandidati = []
        for slovo in slova[:2]:
            kluc = ("aut", slovo.lower())
            if kluc not in cache:
                try:
                    cache[kluc] = autority(slovo)
                except epca.EpcaChyba as e:
                    cache[kluc] = []
                    res.poznamka = str(e)
            kandidati += [a for a in cache[kluc] if zhoda_mena(ucitel.meno, a.meno)]
        s_orcid = {a.orcid for a in kandidati if a.orcid}
        if len(s_orcid) == 1:
            res.orcid = s_orcid.pop()
            res.zdroje.append("knižnica SPU")
        elif len(s_orcid) > 1:
            spu = {a.orcid for a in kandidati if a.orcid and a.spu}
            if len(spu) == 1:
                res.orcid = spu.pop()
                res.zdroje.append("knižnica SPU")
            else:
                res.poznamka = "v knižnici viac osôb s rovnakým menom"

    # 2. register ORCID podľa mena a pracoviska
    if not res.orcid and len(slova) >= 2:
        najdene = {}
        for i in range(len(slova)):
            priezvisko = slova[i]
            krstne = " ".join(slova[:i] + slova[i + 1:])
            try:
                for r in orcid_hladaj(priezvisko, krstne):
                    if r.get("orcid-id"):
                        najdene[r["orcid-id"]] = r
            except IdChyba as e:
                res.poznamka = str(e)
                break
            if najdene:
                break
        if len(najdene) == 1:
            res.orcid = next(iter(najdene))
            res.zdroje.append("register ORCID")
        elif len(najdene) > 1:
            res.poznamka = f"v registri ORCID {len(najdene)} osoby s týmto menom na SPU"

    # 3. Scopus a ResearcherID z profilu ORCID
    if res.orcid and (not ucitel.scopus_id or not ucitel.wos_id):
        try:
            ext = orcid_externe(res.orcid)
            if not ucitel.scopus_id and ext.get("scopus"):
                res.scopus = ext["scopus"]
            if not ucitel.wos_id and ext.get("wos"):
                res.wos = ext["wos"]
            if ext:
                res.zdroje.append("profil ORCID")
        except IdChyba as e:
            res.poznamka = str(e)
    if res.orcid == (ucitel.orcid or ""):
        res.orcid = "" if ucitel.orcid else res.orcid
    return res


def chybajuce_id(ucitel) -> list[str]:
    out = []
    if not ucitel.orcid:
        out.append("ORCID")
    if not ucitel.scopus_id:
        out.append("Scopus ID")
    if not ucitel.wos_id:
        out.append("ResearcherID")
    return out
