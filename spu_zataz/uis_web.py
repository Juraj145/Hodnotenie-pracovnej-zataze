"""Načítanie zamestnancov pracovísk z verejnej časti UIS (is.uniag.sk).

Používa iba verejné stránky „Pracoviská“ a „Zoznam zamestnancov“, ktoré si môže pozrieť
ktokoľvek v prehliadači. Program ich načíta až na pokyn používateľa, po jednej stránke,
a neukladá kontakty (telefón, e-mail, kanceláriu) – iba meno, tituly, zaradenie a ID osoby v UIS.

Ak by priame načítanie nefungovalo (napr. bez siete univerzity), dá sa stránka uložiť
v prehliadači (Ctrl+S) a načítať zo súboru – parser je rovnaký.
"""

from __future__ import annotations

import html as htmllib
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from .version import __version__

UIS_BASE = "https://is.uniag.sk"
TIMEOUT = 25


class UISChyba(Exception):
    pass


@dataclass
class Pracovisko:
    id: int
    nazov: str
    skratka: str = ""


@dataclass
class Zamestnanec:
    uis_id: str
    priezvisko_meno: str     # tvar z UIS: „Priezvisko Meno“
    titul_pred: str
    titul_za: str
    zaradenie: str
    externy: bool
    funkcia: str             # profesor / docent / odborný asistent / lektor / iné

    @property
    def meno(self) -> str:
        """Meno ponechané v tvare z UIS („Priezvisko Meno“) – pri viacslovných menách
        sa nedá spoľahlivo určiť, ktoré slovo je krstné meno."""
        return self.priezvisko_meno

    @property
    def je_pedagog(self) -> bool:
        return self.funkcia in ("profesor", "docent", "odborný asistent", "lektor", "asistent")


# ------------------------------------------------------------------ sťahovanie

def stiahni(cesta_alebo_url: str) -> str:
    url = cesta_alebo_url if cesta_alebo_url.startswith("http") else UIS_BASE + cesta_alebo_url
    if not url.startswith(UIS_BASE):
        raise UISChyba("Podporované sú iba stránky is.uniag.sk.")
    req = urllib.request.Request(url, headers={
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) SPU-Zataz/{__version__}",
        "Accept-Language": "sk",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
            data = r.read()
    except Exception as e:  # noqa: BLE001
        raise UISChyba(f"Stránku {url} sa nepodarilo načítať: {e}") from e
    return data.decode("utf-8", errors="replace")


def id_z_odkazu(text: str) -> Optional[int]:
    """Z odkazu na pracovisko alebo zoznam zamestnancov vytiahne ID pracoviska."""
    text = text.strip()
    if text.isdigit():
        return int(text)
    ids = re.findall(r"[?;&]id=(\d+)", text)
    return int(ids[-1]) if ids else None   # pri zpet=…?id=30;id=222 platí posledné


# ------------------------------------------------------------------ parsovanie

def _text(fragment: str) -> str:
    t = re.sub(r"<[^>]+>", "", fragment)
    return " ".join(htmllib.unescape(t).replace("\xa0", " ").split())


_SEKCIA = re.compile(r'<a name="(\d+)"></a>(?:(?!<a name=)[\s\S]){0,600}?<b><font size="\+1">([\s\S]*?)</font></b>')
_DROBCEK = re.compile(r'<li class="breadcrumb-item[^"]*"[^>]*>([\s\S]*?)</li>')


def podpracoviska(html: str) -> list[Pracovisko]:
    """Zoznam pracovísk na stránke fakulty (alebo fakúlt na hlavnej stránke Pracoviská)."""
    out, videne = [], set()
    for m in _SEKCIA.finditer(html):
        pid = int(m.group(1))
        if pid not in videne:
            videne.add(pid)
            out.append(Pracovisko(id=pid, nazov=_text(m.group(2))))
    return out


def drobcekova_navigacia(html: str) -> list[tuple[str, Optional[int]]]:
    """Položky navigácie „Pracoviská › TF › UEAIF“ ako (text, id pracoviska alebo None)."""
    out = []
    for m in _DROBCEK.finditer(html):
        frag = m.group(1)
        href = re.search(r'href="([^"]*pracoviste\.pl[^"]*)"', frag)
        out.append((_text(frag), id_z_odkazu(href.group(1)) if href else None))
    return [x for x in out if x[0]]


_PRED = {"prof.", "doc.", "ing.", "mgr.", "bc.", "rndr.", "phdr.", "paeddr.", "judr.", "mudr.", "mvdr.", "pharmdr.",
         "thdr.", "dr.", "akad.", "arch.", "ing. arch.", "mga.", "doc", "prof", "h.", "c.", "dr. h. c."}
_ZA = ("phd", "csc", "drsc", "mba", "artd", "llm", "dis", "msc", "bsc", "dba", "mpa", "thd")


def rozdel_meno(text: str) -> tuple[str, str, str]:
    """„Božiková Monika, prof. RNDr., PhD.“ → („Božiková Monika“, „prof. RNDr.“, „PhD.“)."""
    casti = [c.strip() for c in text.split(",") if c.strip()]
    if not casti:
        return "", "", ""
    meno, pred, za = casti[0], [], []
    for c in casti[1:]:
        nizke = c.lower().replace(" ", "")
        if any(nizke.startswith(z) for z in _ZA):
            za.append(c)
        elif not za:
            pred.append(c)
        else:
            za.append(c)
    return meno, " ".join(pred), ", ".join(za)


def funkcia_zo_zaradenia(zaradenie: str) -> str:
    z = zaradenie.lower()
    if z.startswith("profesor"):
        return "profesor"
    if z.startswith("docent"):
        return "docent"
    if "odborn" in z and "asistent" in z:
        return "odborný asistent"
    if z.startswith("lektor"):
        return "lektor"
    if z.startswith("asistent"):
        return "asistent"
    return "iné"


_RIADOK = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>")
_BUNKA = re.compile(r"<td[^>]*>([\s\S]*?)</td>")


def zamestnanci(html: str) -> list[Zamestnanec]:
    """Spracuje stránku „Zoznam zamestnancov“ (zamestnanci.pl)."""
    out: list[Zamestnanec] = []
    # stránka má sekcie <big><b>Zamestnanci</b></big> a <big><b>Externí pracovníci</b></big>
    sekcie = re.split(r"<big><b>([\s\S]*?)</b></big>", html)
    # sekcie = [pred, nadpis1, obsah1, nadpis2, obsah2, ...]
    dvojice = list(zip(sekcie[1::2], sekcie[2::2])) or [("Zamestnanci", html)]
    for nadpis, obsah in dvojice:
        ext_sekcia = "extern" in _text(nadpis).lower()
        for riadok in _RIADOK.finditer(obsah):
            bunky = _BUNKA.findall(riadok.group(1))
            if len(bunky) < 2:
                continue
            odkaz = re.search(r"clovek\.pl\?id=(\d+)", bunky[0])
            if not odkaz:
                continue
            priezvisko_meno, pred, za = rozdel_meno(_text(bunky[0]))
            zaradenie = _text(bunky[1])
            out.append(Zamestnanec(
                uis_id=odkaz.group(1), priezvisko_meno=priezvisko_meno, titul_pred=pred, titul_za=za,
                zaradenie=zaradenie, externy=ext_sekcia or zaradenie.lower().startswith("extern"),
                funkcia=funkcia_zo_zaradenia(zaradenie)))
    return out


# ------------------------------------------------------------------ vyššia úroveň

def fakulty() -> list[Pracovisko]:
    return podpracoviska(stiahni("/pracoviste/pracoviste.pl"))


def fakulta_a_pracoviska(fakulta_id: int) -> tuple[str, list[Pracovisko]]:
    """Vráti skratku fakulty (napr. TF) a jej pracoviská."""
    html = stiahni(f"/pracoviste/pracoviste.pl?id={fakulta_id}")
    nav = drobcekova_navigacia(html)
    skratka = nav[-1][0] if nav else ""
    prac = podpracoviska(html)
    # skratky pracovísk z odkazov „#220“ v hornej časti stránky
    for m in re.finditer(r'href="pracoviste\.pl\?id=\d+#(\d+)"[^>]*>([^<]+)</a>', html):
        for p in prac:
            if str(p.id) == m.group(1):
                p.skratka = _text(m.group(2))
    return skratka, prac


def info_o_pracovisku(pracovisko_id: int) -> tuple[Optional[int], str, str]:
    """Pre ID ústavu vráti (ID fakulty, skratka fakulty, skratka ústavu)."""
    nav = drobcekova_navigacia(stiahni(f"/pracoviste/pracoviste.pl?id={pracovisko_id}"))
    # [Pracoviská, TF(id=30), UEAIF]
    fak = nav[-2] if len(nav) >= 3 else ("", None)
    return fak[1], fak[0], nav[-1][0] if nav else ""


def zamestnanci_pracoviska(pracovisko_id: int) -> list[Zamestnanec]:
    return zamestnanci(stiahni(f"/pracoviste/zamestnanci.pl?id={pracovisko_id}"))


# ------------------------------------------------------------------ zápis do databázy

@dataclass
class VysledokNacitania:
    novi: list[str]
    aktualizovani: list[str]
    presunuti: list[str]          # učitelia, ktorým sa zmenil ústav
    chybajuci: list[str]          # v databáze pri ústave, ale v UIS už nie sú

    def sprava(self) -> str:
        t = f"Noví učitelia: {len(self.novi)}, aktualizovaní: {len(self.aktualizovani)}."
        if self.presunuti:
            t += "\n\nZmena ústavu: " + ", ".join(self.presunuti)
        if self.chybajuci:
            t += ("\n\nV databáze sú pri týchto ústavoch učitelia, ktorí v UIS už nie sú (neodstránil som ich, "
                  "skontrolujte ich na karte Učitelia): " + ", ".join(self.chybajuci))
        if self.novi:
            t += "\n\nNovým učiteľom doplňte prepočítaný úväzok (predvolene 1,0)."
        return t


def zluc_do_databazy(db, polozky: list[tuple[Zamestnanec, str, str]]) -> VysledokNacitania:
    """polozky: (zamestnanec, fakulta, ústav). Učiteľa páruje podľa ID z UIS (osobné číslo),
    potom podľa mena, ak ešte osobné číslo nemá. Úväzok a ďalšie údaje existujúcich učiteľov nemení."""
    from .models import Ucitel
    res = VysledokNacitania([], [], [], [])
    ustavy = set()
    nacitane_id = set()
    for z, fakulta, ustav in polozky:
        ustavy.add((fakulta, ustav))
        nacitane_id.add(z.uis_id)
        u = db.najdi_ucitela(z.uis_id, "")
        if u is None:
            u = db.najdi_ucitela("", z.meno)
            if u is not None and u.osobne_cislo:
                u = None
        if u is None:
            u = Ucitel(osobne_cislo=z.uis_id, titul_pred=z.titul_pred, meno=z.meno, titul_za=z.titul_za,
                       fakulta=fakulta, ustav=ustav, funkcia=z.funkcia if z.funkcia != "asistent" else "iné",
                       uvazok=1.0)
            db.uloz(u, commit=False)
            res.novi.append(z.meno)
            continue
        if u.ustav and u.ustav != ustav:
            res.presunuti.append(f"{z.meno} ({u.ustav} → {ustav})")
        u.osobne_cislo = z.uis_id
        u.titul_pred, u.meno, u.titul_za = z.titul_pred, z.meno, z.titul_za
        u.fakulta, u.ustav = fakulta, ustav
        if z.funkcia not in ("iné", "asistent"):
            u.funkcia = z.funkcia
        db.uloz(u, commit=False)
        res.aktualizovani.append(z.meno)
    db.commit()
    for u in db.nacitaj("ucitelia"):
        if (u.fakulta, u.ustav) in ustavy and u.osobne_cislo not in nacitane_id:
            res.chybajuci.append(u.cele_meno)
    return res


# ------------------------------------------------------------------ záverečné práce (is.uniag.sk/zp/)

TYP_ZP = {"BP": "Bc", "DP": "Ing", "DizP": "PhD"}
ZP_ZNACKA = "[UIS ZP "


@dataclass
class ZaverecnaPracaUIS:
    zp_id: str
    stav: str
    typ: str                 # BP / DP / DizP
    nazov: str
    rok: int                 # rok obhajoby = koniec akademického roka
    veduci_id: str
    veduci_meno: str
    pracovisko: str

    @property
    def ak_rok(self) -> str:
        return f"{self.rok - 1}/{self.rok}"

    @property
    def stupen(self) -> Optional[str]:
        return TYP_ZP.get(self.typ)

    @property
    def obhajena(self) -> bool:
        return self.stav.lower().startswith("obháj")


def obdobie_zo_ak_roku(ak_rok: str) -> Optional[int]:
    """„2023/2024“ → 2024 (UIS označuje obdobie rokom, v ktorom končí)."""
    m = re.match(r"\s*(\d{4})\s*[/-]\s*(\d{2,4})", ak_rok or "")
    if not m:
        return None
    return int(m.group(1)) + 1


def parsuj_zaverecne_prace(html: str) -> list[ZaverecnaPracaUIS]:
    out = []
    # tabuľka výsledkov začína hlavičkou s „Vedúci práce“ (môže byť vnorená v rozložení stránky)
    for m in re.finditer(r"<th[^>]*>\s*(?:<a[^>]*razeni=vedouci[^>]*>)?\s*Vedúci", html):
        koniec = html.find("</table>", m.end())
        tab = html[m.start(): koniec if koniec > 0 else len(html)]
        for riadok in _RIADOK.finditer(tab):
            b = _BUNKA.findall(riadok.group(1))
            if len(b) < 8:
                continue
            ved = re.search(r"clovek\.pl\?id=(\d+)", b[6])
            zp = re.search(r"[?;]zp=(\d+)", riadok.group(1))
            rok = re.search(r"\d{4}", _text(b[5]))
            if not ved or not rok:
                continue
            out.append(ZaverecnaPracaUIS(
                zp_id=zp.group(1) if zp else "", stav=_text(b[1]), typ=_text(b[2]), nazov=_text(b[4]),
                rok=int(rok.group(0)), veduci_id=ved.group(1), veduci_meno=_text(b[6]), pracovisko=_text(b[7])))
    return out


def zaverecne_prace(pracovisko_id: int, ak_roky: list[str]) -> list[ZaverecnaPracaUIS]:
    """Bakalárske, diplomové a dizertačné práce pracoviska (fakulta zahŕňa všetky jej ústavy)."""
    obdobia = sorted({o for o in (obdobie_zo_ak_roku(a) for a in ak_roky) if o})
    if not obdobia:
        raise UISChyba("Zadajte akademické roky v tvare 2023/2024.")
    params = [("prehled", "pracoviste"), ("pracoviste", str(pracovisko_id)), ("typ", "1"), ("typ", "2"),
              ("typ", "3"), *[("obdobi", str(o)) for o in obdobia], ("filtr_odklad", "0"), ("zobrazit", "Zobraziť")]
    url = UIS_BASE + "/zp/portal_zp.pl"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode("utf-8"), headers={
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) SPU-Zataz/{__version__}",
        "Accept-Language": "sk", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise UISChyba(f"Záverečné práce sa nepodarilo načítať: {e}") from e
    return [p for p in parsuj_zaverecne_prace(html) if p.rok in obdobia]


_TITULY = re.compile(r"\b(prof|doc|ing|mgr|bc|rndr|phdr|paeddr|judr|mudr|mvdr|pharmdr|thdr|dr|arch|phd|csc|drsc|mba|artd|"
                     r"h|c|dr\.h\.c)\.?(?=\s|,|$)", re.I)


def kluc_mena(meno: str) -> str:
    """Meno bez titulov ako množina slov – „doc. Ing. Ján Novák, PhD.“ aj „Novák Ján“ → „jan novak“."""
    import unicodedata
    t = _TITULY.sub(" ", meno.replace(",", " "))
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(w for w in re.split(r"[\s.]+", t) if len(w) > 1))


@dataclass
class PriradenieZP:
    ucitel_id: Optional[int]
    ucitel: str
    ak_rok: str
    stupen: str
    prace: list[ZaverecnaPracaUIS]


def prirad_ucitelom(prace: list[ZaverecnaPracaUIS], ucitelia) -> tuple[list[PriradenieZP], dict[str, int]]:
    """Obhájené práce priradí učiteľom (podľa ID v UIS, inak podľa mena).
    Vráti (priradenia po učiteľ × ak. rok × stupeň, {vedúci mimo databázy: počet prác})."""
    podla_id = {u.osobne_cislo: u for u in ucitelia if u.osobne_cislo}
    podla_mena = {kluc_mena(u.meno): u for u in ucitelia}
    skupiny: dict[tuple, PriradenieZP] = {}
    mimo: dict[str, int] = {}
    for p in prace:
        if not p.obhajena or not p.stupen:
            continue
        u = podla_id.get(p.veduci_id) or podla_mena.get(kluc_mena(p.veduci_meno))
        if u is None:
            mimo[p.veduci_meno] = mimo.get(p.veduci_meno, 0) + 1
            continue
        k = (u.id, p.ak_rok, p.stupen)
        if k not in skupiny:
            skupiny[k] = PriradenieZP(u.id, u.cele_meno, p.ak_rok, p.stupen, [])
        skupiny[k].prace.append(p)
    return sorted(skupiny.values(), key=lambda s: (s.ucitel, s.ak_rok, s.stupen)), mimo


def uloz_zaverecne_prace(db, priradenia: list[PriradenieZP]) -> int:
    """Uloží práce ako záznamy učiteľov. Predtým zmaže práce načítané z UIS skôr pre tých istých
    učiteľov a akademické roky (ručne zadané záznamy zostanú)."""
    from .models import ZaverecnaPraca
    for uid, ak in {(s.ucitel_id, s.ak_rok) for s in priradenia}:
        db.conn.execute("DELETE FROM zaverecne_prace WHERE ucitel_id = ? AND ak_rok = ? AND nazov LIKE ?",
                        (uid, ak, f"%{ZP_ZNACKA}%"))
    n = 0
    for s in priradenia:
        for p in s.prace:
            db.uloz(ZaverecnaPraca(ucitel_id=s.ucitel_id, ak_rok=s.ak_rok, stupen=s.stupen, pocet=1,
                                   nazov=f"{p.nazov} {ZP_ZNACKA}{p.zp_id}]"), commit=False)
            n += 1
    db.commit()
    return n


# ------------------------------------------------------------------ projekty (is.uniag.sk/vv/projekty.pl)

ZAPOCITANE_STAVY = ("riešený", "ukončený")
ULOHY_RIESITELA = ("riešiteľ", "metodický riešiteľ")


@dataclass
class ProjektUIS:
    uis_id: str
    nazov: str
    stav: str
    od: int
    do: int
    druh: str
    garant_id: str
    garant_meno: str
    kod: str = ""
    riesitelia: list = field(default_factory=list)    # (uis_id, meno, úlohy)

    @property
    def zapocitany_stav(self) -> bool:
        return self.stav.lower() in ZAPOCITANE_STAVY

    def roky(self, sledovane: list[int]) -> list[int]:
        return [r for r in sledovane if self.od <= r <= self.do]


def _ascii(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def je_interny_grant(kod: str) -> bool:
    """Interné granty SPU (napr. „10-GA SPU-16“, „GA FEM“) – nie sú externé zdroje podľa pozn. 8."""
    return bool(re.search(r"\bGA\s*(SPU|FAPZ|FBP|FEM|FE[SŠ]RR|FZKI|TF)\b", kod or "", re.I))


def kategoria_projektu(druh: str, kod: str = "") -> str:
    """Zaradí druh projektu z UIS do kategórie podľa pozn. 8 a 9 metodického pokynu.
    Interné granty univerzity a mobilitné / štipendijné programy sa nezapočítavajú."""
    from .config import NEZAPOCITAT
    if je_interny_grant(kod):
        return NEZAPOCITAT
    d = _ascii(druh)
    if not d or "duplicit" in d:
        return NEZAPOCITAT
    if re.match(r"ga\b|ga (spu|fapz|fbp|fem|fesrr|fzki|tf)", d) or "grantova agentura spu" in d:
        return NEZAPOCITAT                     # interné granty SPU – nie sú externé zdroje
    if any(x in d for x in ("stipend", "ceepus", "mobilit", "akcia rakusko", "academic exchange")):
        return NEZAPOCITAT
    if "vega" in d:
        return "VEGA"
    if "kega" in d:
        return "KEGA"
    if any(x in d for x in ("apvv", "apvt", "vseobecne vyzvy", "bilateraln", "multilateral", "mvts",
                            "medzinarodna vedecko", "pripravne projekty")):
        return "APVV"
    if "erasmus" in d:
        return "Erasmus+ KA2" if "ka2" in d else NEZAPOCITAT
    if re.search(r"horizont|horizon|european research council|\berc\b|\bcost\b|biodiversa|eureka|era-net|"
                 r"ramcov|\beits?\b", d):
        return "Medzinárodný výskumný (Horizont a pod.)"
    # akcie programu Erasmus+ KA2 evidované v UIS pod vlastným názvom
    if "kooperacne partnerstv" in d or "capacity building" in d or ("budovani" in d and "kapacit" in d):
        return "Erasmus+ KA2"
    if "statne programy vyskumu" in d:
        return "Iný výskumný zo štátneho rozpočtu (súťažný)"
    if re.search(r"\bop\b|operacny program|\birop\b|interreg|plan obnovy|program slovensko|"
                 r"program rozvoja vidieka|struktur|kohezn", d):
        return "Štrukturálne fondy"
    if any(x in d for x in ("dotaci", "mprv", "ministerst", "msvvas", "statnej sprav", "samosprav", "verejn")):
        return "Verejná správa"
    return "Iný subjekt"


def _post(cesta: str, params: list[tuple[str, str]], timeout: int = 90) -> str:
    req = urllib.request.Request(UIS_BASE + cesta, data=urllib.parse.urlencode(params).encode("utf-8"), headers={
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) SPU-Zataz/{__version__}",
        "Accept-Language": "sk", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise UISChyba(f"Stránku {cesta} sa nepodarilo načítať: {e}") from e


def pracoviska_projektov(html: Optional[str] = None) -> list[tuple[int, str, int]]:
    """Pracoviská z výberu na stránke „Projekty podľa pracoviska“: (id, názov, úroveň 0=SPU, 1=fakulta, 2=ústav)."""
    html = html if html is not None else stiahni("/vv/projekty.pl?zalozka=5;lang=sk")
    sel = re.search(r'<select[^>]*name="pracoviste"[^>]*>([\s\S]*?)</select>', html)
    out = []
    if not sel:
        return out
    for m in re.finditer(r'<option[^>]*value="(\d+)"[^>]*>([\s\S]*?)</option>', sel.group(1)):
        surovy = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).replace("\xa0", " ")
        odsadenie = len(surovy) - len(surovy.lstrip(" "))
        out.append((int(m.group(1)), " ".join(surovy.split()), odsadenie))
    urovne = sorted({o for _, _, o in out})
    return [(i, n, urovne.index(o)) for i, n, o in out]


def parsuj_zoznam_projektov(html: str) -> list[ProjektUIS]:
    out = []
    for m in re.finditer(r"<th[^>]*>\s*Názov projektu", html):
        koniec = html.find("</table>", m.end())
        tab = html[m.start(): koniec if koniec > 0 else len(html)]
        for riadok in _RIADOK.finditer(tab):
            b = _BUNKA.findall(riadok.group(1))
            if len(b) < 5:
                continue
            proj = re.search(r"projekt=(\d+)", b[1])
            if not proj:
                continue
            stav = re.search(r'aria-label="([^"]+)"', b[0])
            nazov = re.search(r"<a[^>]*projekt=\d+[^>]*>([\s\S]*?)</a>", b[1])
            gar = re.search(r'clovek\.pl\?id=(\d+)[^>]*>([\s\S]*?)</a>', b[1])
            try:
                od, do = int(_text(b[2])), int(_text(b[3]) or _text(b[2]))
            except ValueError:
                continue
            kod = re.search(r"</a>\s*\(([^()<]+)\)", b[1])
            out.append(ProjektUIS(uis_id=proj.group(1), nazov=_text(nazov.group(1)) if nazov else "",
                                  stav=stav.group(1) if stav else "", od=od, do=do, druh=_text(b[4]),
                                  garant_id=gar.group(1) if gar else "", garant_meno=_text(gar.group(2)) if gar else "",
                                  kod=_text(kod.group(1)) if kod else ""))
        break
    return out


def zoznam_projektov(pracovisko_id: int) -> list[ProjektUIS]:
    """Projekty, na ktorých je evidovaný aspoň jeden pracovník pracoviska (vrátane podpracovísk)."""
    html = _post("/vv/projekty.pl", [("lang", "sk"), ("pracoviste", str(pracovisko_id)), ("podpracoviste", "1"),
                                     ("stav", "-3"), ("pouzit_pracovnika", "1"),
                                     ("dohledat_pracoviste", "Vyhľadať"), ("zalozka", "5")])
    return parsuj_zoznam_projektov(html)


def parsuj_detail_projektu(html_info: str, html_pracovnici: str, p: ProjektUIS) -> ProjektUIS:
    for riadok in _RIADOK.finditer(html_info):
        b = _BUNKA.findall(riadok.group(1))
        if len(b) >= 2 and _text(b[0]).startswith("Identifikácia projektu"):
            p.kod = _text(b[1])
        if len(b) >= 2 and _text(b[0]).startswith("Druh projektu") and not p.druh:
            p.druh = _text(b[1])
    gar = re.search(r"Garant:\s*<a[^>]*clovek\.pl\?id=(\d+)[^>]*>([\s\S]*?)</a>", html_info)
    if gar:
        p.garant_id, p.garant_meno = gar.group(1), _text(gar.group(2))
    p.riesitelia = []
    for m in re.finditer(r"<th[^>]*>\s*Pracovník", html_pracovnici):
        koniec = html_pracovnici.find("</table>", m.end())
        tab = html_pracovnici[m.start(): koniec if koniec > 0 else len(html_pracovnici)]
        for riadok in _RIADOK.finditer(tab):
            b = _BUNKA.findall(riadok.group(1))
            if len(b) < 2:
                continue
            osoba = re.search(r'clovek\.pl\?id=(\d+)[^>]*>([\s\S]*?)</a>', b[0])
            if not osoba:
                continue
            ulohy = [u for u in re.findall(r'aria-label="([^"]+)"', b[1]) if u]
            p.riesitelia.append((osoba.group(1), _text(osoba.group(2)), ulohy))
        break
    return p


def detail_projektu(p: ProjektUIS) -> ProjektUIS:
    zaklad = f"/vv/projekty.pl?zalozka=5;projekt={p.uis_id};podrobnosti=1;lang=sk"
    return parsuj_detail_projektu(stiahni(zaklad + ";zobrazit=1"), stiahni(zaklad + ";zobrazit=2"), p)


@dataclass
class VysledokProjektov:
    projekty_roky: int = 0          # počet uložených dvojíc projekt × rok
    ucasti_nove: int = 0
    ucitelia: set = field(default_factory=set)

    def sprava(self) -> str:
        return (f"Uložené: {self.projekty_roky} záznamov projekt × kalendárny rok, {self.ucasti_nove} nových účastí "
                f"pre {len(self.ucitelia)} učiteľov.\n\nVerejná časť UIS neuvádza vykázané hodiny ani financie. "
                "Doplňte na karte Projekty sumu pripísanú SPU v jednotlivých rokoch (Sofia/SAP) a hodiny riešiteľov "
                "(import „Účasť na projektoch“ z UIS). Kým hodiny chýbajú, suma sa rozdelí rovným dielom medzi "
                "riešiteľov a výsledok je označený ako odhad.")


def je_riesitel(p: ProjektUIS, osoba_id: str, ulohy: list[str]) -> bool:
    return osoba_id == p.garant_id or any(u.lower() in ULOHY_RIESITELA for u in ulohy)


def uloz_projekty(db, projekty: list[ProjektUIS], kategorie: dict[str, str], roky: list[int]) -> VysledokProjektov:
    """Uloží projekty po kalendárnych rokoch a priradí ich učiteľom v databáze (podľa ID v UIS alebo mena).

    * zodpovedný riešiteľ = garant projektu v UIS,
    * riešiteľ = úloha „Riešiteľ“ alebo „Metodický riešiteľ“ (administratíva, pomocník, pozorovateľ sa nezapočítajú),
    * existujúce sumy, kapacity a hodiny sa nemenia – doplnia sa iba chýbajúce záznamy.
    """
    from .config import NEZAPOCITAT
    from .models import Projekt, ProjektUcast
    ucitelia = db.nacitaj("ucitelia")
    podla_id = {u.osobne_cislo: u for u in ucitelia if u.osobne_cislo}
    podla_mena = {kluc_mena(u.meno): u for u in ucitelia}
    res = VysledokProjektov()
    for p in projekty:
        typ = kategorie.get(p.druh, kategoria_projektu(p.druh))
        if je_interny_grant(p.kod) or typ == NEZAPOCITAT or not p.zapocitany_stav:
            continue
        clenovia = [(oid, meno, ul) for oid, meno, ul in p.riesitelia if je_riesitel(p, oid, ul)]
        if p.garant_id and all(oid != p.garant_id for oid, _, _ in clenovia):
            clenovia.append((p.garant_id, p.garant_meno, []))
        nasi = []
        for oid, meno, _ in clenovia:
            u = podla_id.get(oid) or podla_mena.get(kluc_mena(meno))
            if u is not None:
                nasi.append((u, oid == p.garant_id))
        if not nasi:
            continue
        kod = p.kod or f"UIS-{p.uis_id}"
        for rok in p.roky(roky):
            proj = db.najdi_projekt(kod, rok)
            if proj is None:
                proj = Projekt(kod=kod, rok=rok)
            proj.nazov, proj.typ, proj.uis_id, proj.pocet_riesitelov = p.nazov, typ, p.uis_id, len(clenovia)
            db.uloz(proj, commit=False)
            res.projekty_roky += 1
            existujuce = {uc.ucitel_id: uc for uc in db.nacitaj_where("ucasti", "projekt_id = ?", (proj.id,))}
            for u, zodp in nasi:
                uc = existujuce.get(u.id)
                if uc is None:
                    db.uloz(ProjektUcast(projekt_id=proj.id, ucitel_id=u.id, hodiny=0.0, zodpovedny=zodp), commit=False)
                    res.ucasti_nove += 1
                elif uc.zodpovedny != zodp:
                    uc.zodpovedny = zodp
                    db.uloz(uc, commit=False)
                res.ucitelia.add(u.id)
    db.commit()
    return res
