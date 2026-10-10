"""Podmienky hodnotenia: dokument metodiky (metodický pokyn a jeho dodatky) a parametre výpočtu z neho.

Používateľ nahrá dokument (PDF, DOCX alebo TXT). Program z textu vyčíta číselné parametre pokynu
(fond pracovného času, koeficienty, tabuľky 1–3, váhy, hranice záťaže, dĺžky období …), porovná ich
s parametrami, podľa ktorých práve počíta, a po potvrdení ich použije. Pri novom dodatku teda stačí
nahrať aktualizovaný dokument – zmenené hodnoty sa prejavia vo výpočte automaticky.

Automaticky sa preberajú hodnoty, nie nové postupy: ak by dodatok zmenil samotný spôsob výpočtu
(napr. nová oblasť hodnotenia), program to v dokumente nerozpozná – v prehľade sa zobrazí, ktoré
parametre sa v dokumente nenašli.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import shutil
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import config

# ------------------------------------------------------------------ čítanie dokumentu


class MetodikaChyba(Exception):
    pass


def nacitaj_text(path: str | Path) -> str:
    path = Path(path)
    pripona = path.suffix.lower()
    if pripona == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover
            raise MetodikaChyba("Na čítanie PDF chýba knižnica pypdf (príkaz: python -m pip install pypdf).") from e
        try:
            r = PdfReader(str(path))
            return "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception as e:  # noqa: BLE001
            raise MetodikaChyba(f"PDF sa nedá prečítať: {e}") from e
    if pripona == ".docx":
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        except (KeyError, zipfile.BadZipFile) as e:
            raise MetodikaChyba(f"Dokument Word sa nedá prečítať: {e}") from e
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:tab/>|</w:tc>", " ", xml)
        xml = re.sub(r"<[^>]+>", "", xml)
        return (xml.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                .replace("&quot;", '"').replace("&apos;", "'"))
    if pripona in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    raise MetodikaChyba("Podporované sú dokumenty PDF, DOCX a TXT.")


def _cislo(t: str) -> float:
    return float(t.replace(" ", "").replace(",", "."))


_SLOVA_NASOBOK = {"jedno": 1, "dvoj": 2, "troj": 3, "štvor": 4, "stvor": 4, "päť": 5, "pat": 5}
_SLOVA_POCET = {"jeden": 1, "jedného": 1, "dva": 2, "dvoch": 2, "dvoma": 2, "tri": 3, "troch": 3, "štyri": 4,
                "štyroch": 4, "päť": 5, "piatich": 5}


def _nasobok(slovo: str) -> Optional[float]:
    s = slovo.lower()
    m = re.match(r"(\d+(?:[,.]\d+)?)", s)
    if m:
        return _cislo(m.group(1))
    for k, v in _SLOVA_NASOBOK.items():
        if s.startswith(k):
            return float(v)
    return None


def _pocet(slovo: str) -> Optional[int]:
    s = slovo.lower()
    if s.isdigit():
        return int(s)
    return _SLOVA_POCET.get(s)


def _ascii(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


# ------------------------------------------------------------------ vyhľadanie parametrov

@dataclass
class Nalez:
    kluc: str            # cesta v parametroch, napr. "body_publikacie|V1: monografia|Q1"
    nazov: str           # popis pre používateľa
    hodnota: Any
    citat: str = ""      # úryvok z dokumentu


NAZVY_PARAMETROV = {
    "fond_hodin_rok": "Fond pracovného času pri plnom úväzku (h/rok)",
    "min_uvazok": "Minimálny prepočítaný úväzok pre hodnotenie učiteľa",
    "koef_priprava": "Násobok hodín priamej výučby (príprava)",
    "koef_anglictina": "Bonifikácia výučby v angličtine / mobilitných študentov (koeficient)",
    "hodiny_na_studenta": "Hodiny na jedného študenta",
    "nasobok_zodpovedny_riesitel": "Bonifikácia zodpovedného riešiteľa výskumného projektu (násobok hodín)",
    "ideal_od": "Ideálny interval záťaže vzdelávaním – od (%)",
    "ideal_do": "Ideálny interval záťaže vzdelávaním – do (%)",
    "hranica_posudenia": "Hranica kvalitatívneho posúdenia (%)",
    "hranica_pretazenia": "Hranica preťaženia (%)",
    "pocet_akad_rokov": "Počet sledovaných akademických rokov (vzdelávanie)",
    "pocet_rokov_publikacie": "Počet sledovaných kalendárnych rokov (publikácie)",
    "pocet_rokov_projekty": "Počet sledovaných kalendárnych rokov (projekty)",
}


def nazov_parametra(kluc: str) -> str:
    if kluc in NAZVY_PARAMETROV:
        return NAZVY_PARAMETROV[kluc]
    casti = kluc.split("|")
    if casti[0] == "hodiny_zaverecna_praca":
        return f"Tab. 1 – hodiny za záverečnú prácu {casti[1]}"
    if casti[0] == "koef_odbor":
        return f"Tab. 2 – koeficient odboru {casti[1]}"
    if casti[0] == "body_publikacie":
        return f"Tab. 3 – {casti[1]}, {casti[2]}"
    if casti[0] == "vahy":
        return f"Váha sumárneho skóre – {config.NAZVY_OBLASTI.get(casti[1], casti[1])}"
    if casti[0] == "vahy_ucitelia":
        return f"Váha celkového skóre učiteľa – {config.NAZVY_OBLASTI.get(casti[1], casti[1])}"
    if casti[0] == "referencna_vyucba_tyzden":
        return f"Pozn. 1 – referenčná priama výučba ({casti[1]}) h/týždeň"
    return kluc


def _ploche(text: str) -> str:
    t = text.replace(" ", " ").replace("‐", "-").replace("–", "–")
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)          # rozdelené slová na konci riadka
    return re.sub(r"\s+", " ", t)


def _riadky(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", r).strip() for r in text.replace(" ", " ").splitlines()]


def _citat(text: str, m: re.Match, okolie: int = 70) -> str:
    a, b = max(0, m.start() - okolie), min(len(text), m.end() + okolie)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def _sekcia(riadky: list[str], zaciatok: str, koniec: str = r"^Zdroj|^Tabuľka|^Tabulka|^Článok|^Clanok") -> list[str]:
    for i, r in enumerate(riadky):
        if re.match(zaciatok, r, re.I):
            out = []
            for r2 in riadky[i + 1:i + 40]:
                if re.match(koniec, r2, re.I):
                    break
                out.append(r2)
            return out
    return []


def extrahuj_parametre(text: str) -> list[Nalez]:
    """Vyhľadá parametre metodiky v texte dokumentu."""
    p = _ploche(text)
    riadky = _riadky(text)
    out: list[Nalez] = []

    def pridaj(kluc, hodnota, m=None, citat=""):
        if hodnota is None:
            return
        if any(n.kluc == kluc for n in out):
            return
        out.append(Nalez(kluc, nazov_parametra(kluc), hodnota, _citat(p, m) if m else citat))

    m = re.search(r"(\d[\d ]{2,4}(?:[,.]\d+)?)\s*h\s*/\s*(?:1\s*)?rok", p)
    if m:
        pridaj("fond_hodin_rok", _cislo(m.group(1)), m)
    m = re.search(r"interval\w*\s*[<〈(\[]\s*(\d+(?:[,.]\d+)?)\s*%\s*[,;]\s*(\d+(?:[,.]\d+)?)\s*%", p, re.I)
    if m:
        pridaj("ideal_od", _cislo(m.group(1)), m)
        pridaj("ideal_do", _cislo(m.group(2)), m)
    m = re.search(r"dosahuje\s+(\d+(?:[,.]\d+)?)\s*%\s+celkov", p, re.I)
    if m:
        pridaj("hranica_posudenia", _cislo(m.group(1)), m)
    m = re.search(r"(?:viac|nad)\s+ako\s+(\d+(?:[,.]\d+)?)\s*%\s+ročn", p, re.I)
    if m:
        pridaj("hranica_pretazenia", _cislo(m.group(1)), m)
    m = re.search(r"stav\w*\s+úväzku\s+je\s+men\w+\s+ako\s+(\d+(?:[,.]\d+)?)\s*%", p, re.I)
    if m:
        pridaj("min_uvazok", _cislo(m.group(1)) / 100, m)
    m = re.search(r"\(\s*(\d+(?:[,.]\d+)?)\s*hodin\w*\s*/\s*1\s*študent", p, re.I)
    if not m:
        m = re.search(r"v podobe\s+(\d+(?:[,.]\d+)?)\s+za\s+každého", p, re.I)
    if m:
        pridaj("hodiny_na_studenta", _cislo(m.group(1)), m)
    m = re.search(r"bonifikuje\s+koeficientom\s+(\d+(?:[,.]\d+)?)", p, re.I)
    if m:
        pridaj("koef_anglictina", _cislo(m.group(1)), m)
    m = re.search(r"súčtom\s+(\w+násobku|\d+(?:[,.]\d+)?\s*-?\s*násobku)\s+hodín\s+priamej", p, re.I) or \
        re.search(r"ako\s+(\w+násobok|\d+(?:[,.]\d+)?\s*-?\s*násobok)\s+danej\s+hodnoty", p, re.I)
    if m:
        pridaj("koef_priprava", _nasobok(m.group(1)), m)
    m = re.search(r"bonifikovan\w*\s+(\w+násobkom|\d+(?:[,.]\d+)?\s*-?\s*násobkom)\s+hodín", p, re.I)
    if m:
        pridaj("nasobok_zodpovedny_riesitel", _nasobok(m.group(1)), m)

    # dĺžky období (čl. 2 ods. 2)
    m = re.search(r"posledných\s+(\w+)\s+(?:dvoch\s+)?ukončených\s+akademických", p, re.I) or \
        re.search(r"(\w+)\s+posledn\w+\s+ukončen\w+\s+(?:\w+\s+)?akademick", p, re.I)
    if m and _pocet(m.group(1)):
        pridaj("pocet_akad_rokov", _pocet(m.group(1)), m)
    m = re.search(r"publikačnej\s+činnosti\s+v\s+posledných\s+(\w+)\s+kalendárnych", p, re.I)
    if m and _pocet(m.group(1)):
        pridaj("pocet_rokov_publikacie", _pocet(m.group(1)), m)
    m = re.search(r"projektovej\s+činnosti\s+v\s+(\w+)\s+posledných\s+kalendárnych", p, re.I) or \
        re.search(r"projektovej\s+činnosti\s+v\s+posledných\s+(\w+)\s+kalendárnych", p, re.I)
    if m and _pocet(m.group(1)):
        pridaj("pocet_rokov_projekty", _pocet(m.group(1)), m)

    # pozn. 1 – referenčná výučba
    m = re.search(r"Referenčn\w+\s+počet\s+priamej\s+výučby[^:]*:\s*([^()]{5,160})", p, re.I)
    if m:
        for funkcia in ("profesor", "docent", "odborný asistent", "lektor"):
            m2 = re.search(rf"(?<![\w]){funkcia}\s+(\d+(?:[,.]\d+)?)", m.group(1), re.I)
            if m2:
                pridaj(f"referencna_vyucba_tyzden|{funkcia}", _cislo(m2.group(1)), m)

    # váhy sumárneho skóre (čl. 6 ods. 1)
    for oblast, vzor in (("vzdelavanie", r"vzdelávac\w+\s+činnos\w+"), ("publikacie", r"publikačn\w+\s+činnos\w+"),
                         ("projekty", r"projektov\w+\s+činnos\w+")):
        m = re.search(vzor + r"\s+(\d+(?:[,.]\d+)?)\s*%", p, re.I)
        if m:
            pridaj(f"vahy|{oblast}", _cislo(m.group(1)) / 100, m)

    # tab. 1 – záverečné práce
    stupne = {"I": "Bc", "II": "Ing", "III": "PhD"}
    for r in _sekcia(riadky, r"^Tabu[lľ]ka\s*1\b"):
        m = re.search(r"(\d+(?:[,.]\d+)?)\s*/\s*\d+(?:[,.]\d+)?\s+(I{1,3})\.\s*stup", r)
        if m:
            pridaj(f"hodiny_zaverecna_praca|{stupne[m.group(2)]}", _cislo(m.group(1)), citat=r)

    # tab. 2 – koeficienty študijných odborov (odbor môže pokračovať na ďalšom riadku)
    zaznamy: list[list] = []
    for r in _sekcia(riadky, r"^Tabu[lľ]ka\s*2\b"):
        m = re.match(r"^(\d+(?:[,.]\d+)?)\s+(.+)$", r)
        if m:
            zaznamy.append([_cislo(m.group(1)), m.group(2)])
        elif zaznamy and r and not re.match(r"^Koeficient", r, re.I):
            zaznamy[-1][1] += " " + r
    for koef, odbory in zaznamy:
        for odbor in odbory.split(","):
            odbor = odbor.strip(" .;")
            if odbor and len(odbor) > 3:
                pridaj(f"koef_odbor|{odbor}", koef, citat=f"{koef:g} {odbory}")

    # tab. 3 – body za publikácie
    stlpce = ["Bez Q", "Q1", "Q2", "Q3", "Q4"]
    for r in _sekcia(riadky, r"^Tabu[lľ]ka\s*3\b"):
        if re.search(r"Bez\s*Q.*Q1", r):
            stlpce = re.findall(r"Bez\s*Q|Q\d", r)
            stlpce = ["Bez Q" if s.lower().startswith("bez") else s for s in stlpce]
            continue
        m = re.match(r"^(V\d.*?)\s+((?:\d+(?:[,.]\d+)?|x)(?:\s+(?:\d+(?:[,.]\d+)?|x))*)\s*$", r)
        if not m:
            continue
        kat = _kategoria(m.group(1))
        hodnoty = m.group(2).split()
        for i, s in enumerate(stlpce):
            v = hodnoty[i] if i < len(hodnoty) else "x"
            kluc = f"body_publikacie|{kat}|{s}"
            if not any(n.kluc == kluc for n in out):       # „x“ = kvartil sa pri kategórii nepoužíva
                out.append(Nalez(kluc, nazov_parametra(kluc), None if v == "x" else _cislo(v), r))
    return out


def _kategoria(nazov: str) -> str:
    """Názov kategórie z dokumentu → kľúč tab. 3 (zachová existujúci názov, ak sa zhoduje)."""
    a = _ascii(nazov).replace(" ", "")
    for k in config.KATEGORIE_PUBLIKACII:
        if _ascii(k).replace(" ", "") == a:
            return k
    return nazov.strip()


def ucinnost(text: str) -> str:
    p = _ploche(text)
    datumy = re.findall(r"účinnosťou\s+od\s+(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", p, re.I)
    return datumy[-1].replace(" ", "") if datumy else ""


def nazov_dokumentu(text: str, subor: str = "") -> str:
    p = _ploche(text[:3000])
    m = re.search(r"METODICK\w+\s+POKYN\s+(\d+\s*/\s*\d{4})", p, re.I)
    nazov = f"Metodický pokyn {m.group(1).replace(' ', '')}" if m else (Path(subor).stem if subor else "Metodika")
    dodatky = re.findall(r"Dodatk\w*\s+č\.\s*(\d+)", _ploche(text))
    if dodatky:
        nazov += f" v znení Dodatku č. {max(int(d) for d in dodatky)}"
    return nazov


# ------------------------------------------------------------------ porovnanie a použitie

def _ziskaj(params: dict, kluc: str):
    v: Any = params
    for k in kluc.split("|"):
        if not isinstance(v, dict) or k not in v:
            return None
        v = v[k]
    return v


def _nastav(params: dict, kluc: str, hodnota):
    casti = kluc.split("|")
    v = params
    for k in casti[:-1]:
        v = v.setdefault(k, {})
    v[casti[-1]] = hodnota


@dataclass
class Zmena:
    kluc: str
    nazov: str
    stara: Any
    nova: Any
    citat: str = ""


def _rovnake(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def porovnaj(params: dict, nalezy: list[Nalez]) -> list[Zmena]:
    out = []
    for n in nalezy:
        stara = _ziskaj(params, n.kluc)
        if not _rovnake(stara, n.hodnota):
            out.append(Zmena(n.kluc, n.nazov, stara, n.hodnota, n.citat))
    return out


# parametre, ktoré by mal dokument metodiky obsahovať (pre prehľad „nenašlo sa“)
OCAKAVANE = (["fond_hodin_rok", "min_uvazok", "koef_priprava", "koef_anglictina", "hodiny_na_studenta",
              "nasobok_zodpovedny_riesitel", "ideal_od", "ideal_do", "hranica_posudenia", "hranica_pretazenia",
              "pocet_akad_rokov", "pocet_rokov_publikacie", "pocet_rokov_projekty"]
             + [f"hodiny_zaverecna_praca|{s}" for s in config.STUPNE_STUDIA]
             + [f"vahy|{o}" for o in config.OBLASTI]
             + [f"body_publikacie|{k}|Bez Q" for k in config.KATEGORIE_PUBLIKACII])


def nenajdene(nalezy: list[Nalez]) -> list[str]:
    kluce = {n.kluc for n in nalezy}
    return [k for k in OCAKAVANE if k not in kluce]


def pouzi(params: dict, nalezy: list[Nalez], nahradit_tabulku_odborov: bool = True) -> dict:
    """Nové parametre = doterajšie + hodnoty z dokumentu. Tab. 2 sa nahradí celá (zrušené odbory zmiznú)."""
    nove = copy.deepcopy(params)
    odbory = {n.kluc.split("|", 1)[1]: n.hodnota for n in nalezy if n.kluc.startswith("koef_odbor|")}
    if odbory and nahradit_tabulku_odborov:
        nove["koef_odbor"] = odbory
    for n in nalezy:
        if n.kluc.startswith("koef_odbor|"):
            continue
        _nastav(nove, n.kluc, n.hodnota)
        if n.kluc.startswith("vahy|"):
            _nastav(nove, "vahy_ucitelia|" + n.kluc.split("|", 1)[1], n.hodnota)
    # nová kategória v tab. 3 musí mať všetky stĺpce
    for kat, tab in nove["body_publikacie"].items():
        for q in config.KVARTILY:
            tab.setdefault(q, None)
    return nove


# ------------------------------------------------------------------ uložené dokumenty

@dataclass
class Dokument:
    subor: str                     # názov súboru v priečinku podmienok
    nazov: str
    nahrate: str                   # ISO dátum a čas
    ucinnost: str = ""
    aktivny: bool = False
    nalezy: list[dict] = field(default_factory=list)

    def nalezy_obj(self) -> list[Nalez]:
        return [Nalez(**n) for n in self.nalezy]


def priecinok() -> Path:
    p = config.app_data_dir() / "Podmienky hodnotenia"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _index_path() -> Path:
    return priecinok() / "dokumenty.json"


def zoznam() -> list[Dokument]:
    p = _index_path()
    if not p.exists():
        return []
    try:
        return [Dokument(**d) for d in json.loads(p.read_text(encoding="utf-8"))]
    except (ValueError, TypeError):
        return []


def uloz_zoznam(docs: list[Dokument]):
    _index_path().write_text(json.dumps([asdict(d) for d in docs], ensure_ascii=False, indent=1), encoding="utf-8")


def aktivny() -> Optional[Dokument]:
    return next((d for d in zoznam() if d.aktivny), None)


def pridaj_dokument(cesta: str | Path) -> tuple[Dokument, str]:
    """Skopíruje dokument do priečinka podmienok a vyčíta z neho parametre. Vráti (dokument, text)."""
    cesta = Path(cesta)
    text = nacitaj_text(cesta)
    if len(text.strip()) < 200:
        raise MetodikaChyba("Z dokumentu sa nepodarilo prečítať text (je to sken bez textovej vrstvy?).")
    ciel = priecinok() / cesta.name
    if ciel.resolve() != cesta.resolve():
        i = 2
        while ciel.exists():
            ciel = priecinok() / f"{cesta.stem} ({i}){cesta.suffix}"
            i += 1
        shutil.copy2(cesta, ciel)
    doc = Dokument(subor=ciel.name, nazov=nazov_dokumentu(text, cesta.name),
                   nahrate=dt.datetime.now().isoformat(timespec="seconds"), ucinnost=ucinnost(text),
                   nalezy=[asdict(n) for n in extrahuj_parametre(text)])
    docs = [d for d in zoznam() if d.subor != doc.subor] + [doc]
    uloz_zoznam(docs)
    return doc, text


def aktivuj(subor: str):
    docs = zoznam()
    for d in docs:
        d.aktivny = d.subor == subor
    uloz_zoznam(docs)


def odstran(subor: str):
    docs = [d for d in zoznam() if d.subor != subor]
    uloz_zoznam(docs)
    try:
        (priecinok() / subor).unlink()
    except OSError:
        pass


def popis_aktivnej_metodiky() -> str:
    d = aktivny()
    if d:
        return d.nazov + (f" (účinnosť od {d.ucinnost})" if d.ucinnost else "")
    return "Metodický pokyn 1/2023 v znení Dodatku č. 2 (parametre zabudované v programe)"
