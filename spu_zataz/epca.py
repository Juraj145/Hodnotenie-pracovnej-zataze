"""Publikácie z evidencie publikačnej činnosti Slovenskej poľnohospodárskej knižnice (ARL, EPCA).

Knižnica SPU spracúva publikačnú činnosť univerzity a záznamy odovzdáva do CREPČ – každý záznam obsahuje
identifikátor záznamu v CREPČ 2 (pole 035). Program číta verejnú webovú službu knižnice
(https://arl4.library.sk/i3/epcareports/i2.ws.cls, databáza SpuUsEpca), tú istú, ktorú používa aplikácia
„EPCA výstupy“. Prihlásenie nie je potrebné.

Použité polia záznamu (MARC 21 s miestnymi poľami ARL):
  001        číslo záznamu v knižnici
  008        rok vydania (pozície 7–10)
  024        DOI ($2 doi), WoS UT ($2 WoS), Scopus EID ($2 Scopus)
  035        CREPČ 2 ($2 CREPC2)
  100 / 700  autori: $a meno, $7 autorita, $9 podiel v %, $u pracovisko, $X ID osoby v UIS
  245        názov
  773        zdrojový dokument (časopis)
  970        kategória do 2021 ($a, napr. ADC)
  976        kategória od 2022 ($a V1/V2/V3/…, $b typ: MON monografia, EDK editovaná kniha, ZBR zborník, CLA článok…)
  978        indexovanie ($d WoS, SCOPUS, CCC…)
  985        rok vykázania ($r)
  T16        metriky časopisu v roku $a: $c JIF, $4 kvartil JIF, $j AIS, $D kvartil AIS, $M SJR, $N kvartil SJR
             ($D ako kvartil AIS bol overený na záznamoch knižnice: poradie AIS v kategórii WoS mu zodpovedá vo všetkých
             porovnaných dvojiciach časopisov)
"""

from __future__ import annotations

import json
import re
import ssl
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from .config import KATEGORIE_PUBLIKACII
from .version import __version__

WS_URL = "https://arl4.library.sk/i3/epcareports/i2.ws.cls"
DB = "SpuUsEpca"
ZDROJ = "Knižnica SPU / CREPČ"
SF = "\x1f"


class EpcaChyba(Exception):
    pass


# ------------------------------------------------------------------ webová služba

def hladaj(query: str, od: int = 1, do: int = 100) -> dict:
    data = urllib.parse.urlencode({"method": "search", "querytype": "PQF", "from": od, "to": do, "db": DB,
                                   "fmt": "LINEMARC", "pfmt": "json", "ictx": "spu", "language": "1",
                                   "query": query}).encode("utf-8")
    req = urllib.request.Request(WS_URL, data=data, headers={
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) SPU-Zataz/{__version__}",
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        raise EpcaChyba(f"Webová služba knižnice SPU nie je dostupná: {e}") from e
    if str(d.get("ret_code")) != "0":
        raise EpcaChyba(f"Knižnica vrátila chybu: {d.get('ret_msg', '')[:200]}")
    return d


def _pqf(text: str) -> str:
    return "'" + text.replace("'", " ") + "'"


def dotaz_autor(priezvisko: str, roky_vydania: list[int]) -> str:
    q = f"@attr 1=1003 @attr 4=1 {_pqf(priezvisko)}"
    roky = sorted(set(roky_vydania))
    if not roky:
        return q
    cast = f"@attr 1=31 '{roky[-1]}'"
    for r in reversed(roky[:-1]):
        cast = f"@or @attr 1=31 '{r}' {cast}"
    return f"@and {q} {cast}"


def vsetky_zaznamy(query: str, limit: int = 1000) -> Optional[list[dict]]:
    """Všetky záznamy dotazu; None, ak je ich viac ako limit (napr. hľadanie podľa krstného mena)."""
    out, od, spolu = [], 1, 1
    while od <= spolu:
        d = hladaj(query, od, od + 99)
        spolu = int(d.get("hits") or 0)
        if spolu > limit:
            return None
        out.extend(d.get("records") or [])
        od += 100
    return out


# ------------------------------------------------------------------ záznam

def polia(riadky: list[str]) -> dict[str, list[list[tuple[str, str]]]]:
    out: dict[str, list] = {}
    for r in riadky:
        tag = r[:3]
        telo = r[7:] if len(r) > 7 else ""
        if SF in telo:
            sub = [(s[0], s[1:].strip()) for s in telo.split(SF)[1:] if s]
        else:
            sub = [("", telo.strip())]
        out.setdefault(tag, []).append(sub)
    return out


def _sf(pole: list[tuple[str, str]], kod: str) -> list[str]:
    return [v for k, v in pole if k == kod]


@dataclass
class Autor:
    meno: str
    uis_id: str
    podiel: Optional[float]      # 0–1, None ak v zázname chýba
    pracovisko: str
    autorita: str


@dataclass
class Zaznam:
    id: str
    nazov: str
    rok: int                     # rok vykázania (985), inak rok vydania
    rok_vydania: int
    kategoria: str               # V1 / V2 / V3 / O3 …
    typ: str                     # MON / EDK / ZBR / CLA …
    stara_kategoria: str
    zdroj_dok: str
    indexovane: set
    ids: dict
    autori: list[Autor]
    metriky: list[dict] = field(default_factory=list)

    @property
    def vedecky(self) -> bool:
        return self.kategoria in ("V1", "V2", "V3")

    def kategoria_tab3(self) -> Optional[str]:
        """Kategória podľa tab. 3 metodického pokynu (None = pokyn ju nehodnotí)."""
        if self.kategoria == "V1":
            if self.typ == "MON" or (not self.typ and self.stara_kategoria in ("AAA", "AAB")):
                return KATEGORIE_PUBLIKACII[0]
            return KATEGORIE_PUBLIKACII[1]
        if self.kategoria in ("V2", "V3"):
            if self.indexovane & {"WOS", "SCOPUS"}:
                return KATEGORIE_PUBLIKACII[2]
            return KATEGORIE_PUBLIKACII[3]
        return None

    def kvartil_ais(self) -> str:
        """Kvartil podľa AIS (T16 $D) za rok vydania; ak chýba, za najbližší predchádzajúci rok."""
        kand = [m for m in self.metriky if m.get("D")]
        if not kand:
            return "Bez Q"
        pred = [m for m in kand if m["rok"] and m["rok"] <= self.rok_vydania]
        m = max(pred, key=lambda x: x["rok"]) if pred else max(kand, key=lambda x: x["rok"])
        q = m["D"].upper().replace(" ", "")
        return q if q in ("Q1", "Q2", "Q3", "Q4") else "Bez Q"

    def podiel(self, uis_id: str = "", meno: str = "") -> tuple[Optional[float], bool]:
        """(podiel 0–1, odhadnutý) pre autora podľa ID v UIS alebo mena."""
        a = self.najdi_autora(uis_id, meno)
        if a is None:
            return None, False
        if a.podiel is not None:
            return a.podiel, False
        return (1 / len(self.autori) if self.autori else 1.0), True

    def najdi_autora(self, uis_id: str = "", meno: str = "") -> Optional[Autor]:
        if uis_id:
            for a in self.autori:
                if a.uis_id == uis_id:
                    return a
        if meno:
            k = kluc_mena(meno)
            for a in self.autori:
                if kluc_mena(a.meno) == k:
                    return a
        return None

    def identifikator(self) -> str:
        casti = [f"{k}:{v}" for k, v in self.ids.items() if v]
        return "|".join(casti + [f"epca:{self.id}"])


def _rok(text: str) -> int:
    m = re.search(r"(19|20)\d{2}", text or "")
    return int(m.group(0)) if m else 0


def parsuj(rec: dict) -> Zaznam:
    p = polia(rec.get("data", []))
    first = lambda tag, kod: (_sf(p[tag][0], kod) or [""])[0] if tag in p else ""  # noqa: E731
    ids = {"doi": "", "wos": "", "scopus": "", "crepc": ""}
    for pole in p.get("024", []):
        typ = (_sf(pole, "2") or [""])[0].lower()
        hodnota = (_sf(pole, "a") or [""])[0]
        if typ == "doi":
            ids["doi"] = hodnota.lower()
        elif typ == "wos":
            ids["wos"] = hodnota
        elif typ == "scopus":
            ids["scopus"] = hodnota
    for pole in p.get("035", []):
        if "CREPC" in " ".join(_sf(pole, "2")).upper():
            ids["crepc"] = (_sf(pole, "a") or [""])[0]
    autori = []
    for tag in ("100", "700"):
        for pole in p.get(tag, []):
            pod = (_sf(pole, "9") or [""])[0].replace(",", ".")
            try:
                podiel = float(pod) / 100 if pod else None
            except ValueError:
                podiel = None
            autori.append(Autor(meno=(_sf(pole, "a") or [""])[0].rstrip(",. "), uis_id=(_sf(pole, "X") or [""])[0],
                                podiel=podiel, pracovisko=(_sf(pole, "u") or [""])[0],
                                autorita=(_sf(pole, "7") or [""])[0]))
    indexy = set()
    for pole in p.get("978", []):
        indexy |= {v.upper() for v in _sf(pole, "d")}
    metriky = []
    for pole in p.get("T16", []):
        m = {k: v for k, v in pole if k}
        m["rok"] = _rok(m.get("a", "") or m.get("r", ""))
        metriky.append(m)
    rok_vyd = _rok(first("008", "")[7:11]) if "008" in p else 0
    rok_vyk = _rok(first("985", "r"))
    nazov = re.sub(r"\s*/\s*$", "", " ".join((_sf(p["245"][0], "a") + _sf(p["245"][0], "b")) if "245" in p else []))
    return Zaznam(id=rec.get("t001") or first("001", ""), nazov=nazov.strip(" /:"), rok=rok_vyk or rok_vyd,
                  rok_vydania=rok_vyd or rok_vyk, kategoria=first("976", "a").upper(), typ=first("976", "b").upper(),
                  stara_kategoria=first("970", "a").upper(), zdroj_dok=first("773", "t"), indexovane=indexy,
                  ids=ids, autori=autori, metriky=metriky)


def kluc_mena(meno: str) -> str:
    t = re.sub(r"\b(prof|doc|ing|mgr|bc|rndr|phdr|paeddr|phd|csc|drsc|mba)\.?", " ", meno or "", flags=re.I)
    t = re.sub(r"\b\d{4}-?(\d{4})?\b", " ", t)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(w for w in re.split(r"[\s.,]+", t) if len(w) > 1))


# ------------------------------------------------------------------ vyhľadanie publikácií učiteľov

@dataclass
class NajdenaPublikaciaEPCA:
    ucitel_id: int
    ucitel: str
    zaznam: Zaznam
    kategoria: str
    kvartil: str
    podiel: float
    podiel_odhad: bool


def priezviska(meno: str) -> list[str]:
    """Slová mena, ktoré môžu byť priezviskom (UIS: „Priezvisko Meno“, ručne aj „Meno Priezvisko“)."""
    if "," in (meno or ""):
        meno = meno.split(",", 1)[0]
    t = re.sub(r"\b(prof|doc|ing|mgr|bc|rndr|phdr|paeddr|phd|csc|drsc|mba)\.", " ", meno or "", flags=re.I)
    slova = [w for w in re.split(r"[\s]+", t) if len(w) > 2 and not w.endswith(".")]
    out = []
    for w in slova:
        if w not in out:
            out.append(w)
    return out


def publikacie_ucitela(ucitel, roky: list[int], zaznamy_cache: Optional[dict] = None) -> list[NajdenaPublikaciaEPCA]:
    """Vedecké publikácie (V1–V3) učiteľa vykázané v zadaných rokoch.

    Autor sa v zázname určí podľa ID osoby v UIS (pole $X = osobné číslo učiteľa z importu UIS),
    inak podľa mena, ak je autor z pracoviska SPU."""
    if not roky:
        return []
    roky_vyd = list(range(min(roky) - 1, max(roky) + 1))
    out, videne = [], set()
    for poradie, slovo in enumerate(priezviska(ucitel.meno)):
        kluc = (slovo.lower(), tuple(roky_vyd))
        if zaznamy_cache is not None and kluc in zaznamy_cache:
            recs = zaznamy_cache[kluc]
        else:
            recs = vsetky_zaznamy(dotaz_autor(slovo, roky_vyd), limit=3000 if poradie == 0 else 800)
            if zaznamy_cache is not None:
                zaznamy_cache[kluc] = recs
        for rec in recs or []:          # None = príliš veľa záznamov (krstné meno)
            z = parsuj(rec)
            if z.id in videne or z.rok not in roky or not z.vedecky:
                continue
            autor = z.najdi_autora(str(ucitel.osobne_cislo or ""), ucitel.meno)
            if autor is None:
                continue
            if autor.uis_id != str(ucitel.osobne_cislo or "") and not autor.pracovisko.upper().startswith("SPU"):
                continue
            videne.add(z.id)
            pod, odhad = z.podiel(autor.uis_id, autor.meno)
            kat = z.kategoria_tab3()
            out.append(NajdenaPublikaciaEPCA(ucitel_id=ucitel.id, ucitel=ucitel.cele_meno, zaznam=z, kategoria=kat,
                                             kvartil=z.kvartil_ais() if kat in KATEGORIE_PUBLIKACII[:3] else "Bez Q",
                                             podiel=round(pod or 0.0, 4), podiel_odhad=odhad))
    return out


# ------------------------------------------------------------------ porovnanie a uloženie

def tokeny_id(text: str) -> set[str]:
    out = set()
    for t in re.split(r"[|;\s]+", (text or "").lower()):
        t = re.sub(r"^(doi|wos|ut|scopus|eid|crepc|epca):", "", t.strip())
        t = t.replace("https://doi.org/", "").replace("http://dx.doi.org/", "")
        if not t:
            continue
        if re.fullmatch(r"\d{9,}", t):          # WoS UT bez predpony (vedúce nuly sa líšia)
            t = "ut" + t.lstrip("0")
        out.add(t)
    return out


def kluc_nazvu(nazov: str) -> str:
    t = unicodedata.normalize("NFKD", nazov or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)[:80]


def je_duplicita(pub, z: Zaznam) -> bool:
    """Publikácia v databáze (napr. zo Scopus/WoS) je tá istá ako záznam knižnice."""
    a = tokeny_id(pub.identifikator)
    b = tokeny_id(z.identifikator())
    if a & b:
        return True
    k1, k2 = kluc_nazvu(pub.nazov), kluc_nazvu(z.nazov)
    return bool(k1) and len(k1) >= 20 and k1 == k2 and abs((pub.rok or 0) - z.rok) <= 1


@dataclass
class VysledokEPCA:
    pridane: int = 0
    nahradene: dict = field(default_factory=dict)     # zdroj -> počet odstránených duplicít
    podiely_odhad: int = 0
    ucitelia: set = field(default_factory=set)

    def sprava(self) -> str:
        t = f"Uložených {self.pridane} publikácií z knižnice SPU / CREPČ pre {len(self.ucitelia)} učiteľov."
        if self.nahradene:
            t += ("\nOdstránené duplicity (nahradené záznamom knižnice so správnou kategóriou, kvartilom a podielom): "
                  + ", ".join(f"{k or 'ručne'}: {v}" for k, v in sorted(self.nahradene.items())))
        if self.podiely_odhad:
            t += f"\nPri {self.podiely_odhad} publikáciách knižnica neuvádza podiel – použitý rovnaký diel (1 / počet autorov)."
        return t


def uloz(db, najdene: list[NajdenaPublikaciaEPCA], roky: list[int]) -> VysledokEPCA:
    from .models import Publikacia
    res = VysledokEPCA()
    ucitelia = {n.ucitel_id for n in najdene}
    # skôr načítané z knižnice za tieto roky sa nahradia
    for uid in ucitelia:
        for r in roky:
            db.conn.execute("DELETE FROM publikacie WHERE ucitel_id = ? AND rok = ? AND zdroj = ?", (uid, r, ZDROJ))
    existujuce: dict[int, list] = {}
    for p in db.nacitaj("publikacie"):
        existujuce.setdefault(p.ucitel_id, []).append(p)
    for n in najdene:
        if not n.kategoria:
            continue
        for p in list(existujuce.get(n.ucitel_id, [])):
            if p.zdroj != ZDROJ and je_duplicita(p, n.zaznam):
                db.conn.execute("DELETE FROM publikacie WHERE id = ?", (p.id,))
                existujuce[n.ucitel_id].remove(p)
                res.nahradene[p.zdroj] = res.nahradene.get(p.zdroj, 0) + 1
        db.uloz(Publikacia(ucitel_id=n.ucitel_id, rok=n.zaznam.rok, kategoria=n.kategoria, kvartil=n.kvartil,
                           podiel=n.podiel, nazov=n.zaznam.nazov, zdroj=ZDROJ,
                           identifikator=n.zaznam.identifikator()), commit=False)
        res.pridane += 1
        res.podiely_odhad += int(n.podiel_odhad)
        res.ucitelia.add(n.ucitel_id)
    db.commit()
    return res


def je_v_kniznici(db_publikacie: list, ucitel_id: int, doi: str = "", identifikator: str = "", nazov: str = "",
                  rok: int = 0) -> bool:
    """Pre import zo Scopus/WoS: publikácia učiteľa už je v databáze zo záznamu knižnice."""
    t = tokeny_id(f"{doi}|{identifikator}")
    k = kluc_nazvu(nazov)
    for p in db_publikacie:
        if p.ucitel_id != ucitel_id:
            continue
        if t & tokeny_id(p.identifikator):
            return True
        if k and len(k) >= 20 and k == kluc_nazvu(p.nazov) and abs((p.rok or 0) - rok) <= 1:
            return True
    return False
