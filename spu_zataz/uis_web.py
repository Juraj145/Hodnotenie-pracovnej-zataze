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
import urllib.request
from dataclasses import dataclass
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
