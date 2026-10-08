"""Výpočty podľa Metodického pokynu 1/2023 v znení Dodatku č. 2.

Modul neobsahuje nič z grafického rozhrania, aby sa dal samostatne testovať.
Odkazy v komentároch (čl., ods., tab.) smerujú na metodický pokyn.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .models import Data, Projekt, Publikacia, Ucitel


# ---------------------------------------------------------------- obdobia

@dataclass
class Obdobie:
    ak_roky: list[str]          # 2 posledné ukončené akademické roky (čl. 3 ods. 1)
    roky_publikacie: list[int]  # 3 kalendárne roky (čl. 4 ods. 1)
    roky_projekty: list[int]    # 3 verifikované kalendárne roky (čl. 5 ods. 1)

    def popis(self) -> str:
        return (f"Vzdelávanie: {', '.join(self.ak_roky) or '–'} | "
                f"Publikácie: {', '.join(map(str, self.roky_publikacie)) or '–'} | "
                f"Projekty: {', '.join(map(str, self.roky_projekty)) or '–'}")


def _ak_rok_start(ak_rok: str) -> int:
    try:
        return int(str(ak_rok).replace("-", "/").split("/")[0])
    except ValueError:
        return 0


def navrhni_obdobie(data: Data, params: dict) -> Obdobie:
    """Navrhne sledované obdobie podľa najnovších údajov v databáze."""
    ak = sorted({v.ak_rok for v in data.vyucba} | {z.ak_rok for z in data.zaverecne_prace}, key=_ak_rok_start)
    pub = sorted({p.rok for p in data.publikacie if p.rok})
    prj = sorted({p.rok for p in data.projekty if p.rok})

    def posledne_roky(roky: list[int], n: int) -> list[int]:
        if not roky:
            return []
        last = roky[-1]
        return list(range(last - n + 1, last + 1))

    return Obdobie(
        ak_roky=ak[-params["pocet_akad_rokov"]:],
        roky_publikacie=posledne_roky(pub, params["pocet_rokov_publikacie"]),
        roky_projekty=posledne_roky(prj, params["pocet_rokov_projekty"]),
    )


# ---------------------------------------------------------------- jednotlivé zložky

def body_publikacie(pub: Publikacia, params: dict) -> float:
    """Bonifikovaný podiel zamestnanca na publikácii (tab. 3 × podiel)."""
    tab = params["body_publikacie"].get(pub.kategoria)
    if tab is None:
        raise ValueError(f"Neznáma kategória publikácie: {pub.kategoria}")
    body = tab.get(pub.kvartil)
    if body is None:
        # V2/V3 ostatné majú iba hodnotu „Bez Q“
        body = tab.get("Bez Q") or 0.0
    return float(body) * float(pub.podiel)


def hodiny_vyucby_zataz(hodiny: float, jazyk: str, params: dict) -> float:
    """Záťaž z priamej výučby: dvojnásobok hodín, v EN / mobilitní študenti bonifikácia koef. 3 (čl. 3 ods. 4)."""
    k = params["koef_priprava"]
    if jazyk in ("EN", "MOB"):
        k = k * params["koef_anglictina"] if params["en_koef_nasobi_pripravu"] else params["koef_anglictina"]
    return hodiny * k


def kapacita_projektu(projekt: Projekt, ucasti_hodiny: list[float]) -> float:
    if projekt.kapacita_hodin and projekt.kapacita_hodin > 0:
        return projekt.kapacita_hodin
    return sum(ucasti_hodiny)


# ---------------------------------------------------------------- výsledky učiteľov

@dataclass
class VysledokUcitela:
    ucitel: Ucitel
    zahrnuty: bool                    # úväzok ≥ 25 % (čl. 1 ods. 3)
    fond_hodin: float
    # vzdelávanie – priemer za akademický rok
    h_vyucba: float = 0.0             # (2 resp. 6) × hodiny priamej výučby
    h_studenti: float = 0.0           # 0,25 h × študent
    h_zaverecne_prace: float = 0.0    # tab. 1
    h_vzdelavanie: float = 0.0
    vyucba_tyzden: float = 0.0        # hodiny priamej výučby / týždeň (pre porovnanie s pozn. 1)
    referencna_vyucba_tyzden: Optional[float] = None
    # projekty – priemer za kalendárny rok
    h_projekty: float = 0.0           # vykázané hodiny (čl. 5 ods. 3)
    financie_projekty: float = 0.0    # podiel na financiách (čl. 5 ods. 1 A)
    # publikácie – priemer za rok
    body_publikacie: float = 0.0
    # percentá z fondu
    pct_vzdelavanie: float = 0.0
    pct_spolu: float = 0.0
    status: str = ""
    upozornenia: list[str] = field(default_factory=list)
    # min-max štandardizácia (čl. 7 ods. 1.5)
    std_vzdelavanie: Optional[float] = None
    std_publikacie: Optional[float] = None
    std_projekty: Optional[float] = None


def status_zataze(pct_vzd: float, pct_spolu: float, params: dict) -> str:
    """Slovné vyhodnotenie podľa čl. 7 ods. 1.2 a 1.3."""
    if pct_vzd > params["hranica_pretazenia"] or pct_spolu > params["hranica_pretazenia"]:
        return "Preťaženie (nad 100 % fondu)"
    if pct_vzd >= params["hranica_posudenia"]:
        return "Nutné kvalitatívne posúdenie (≥ 80 %)"
    if params["ideal_od"] <= pct_vzd <= params["ideal_do"]:
        return "Ideálny stav (40–60 %)"
    if pct_vzd < params["ideal_od"]:
        return "Pod ideálnym intervalom (< 40 %)"
    return "Nad ideálnym intervalom (60–80 %)"


def _minmax(values: list[float]) -> list[Optional[float]]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def vypocitaj_ucitelov(data: Data, obd: Obdobie, params: dict) -> list[VysledokUcitela]:
    n_ak = max(len(obd.ak_roky), 1)
    n_pub = max(len(obd.roky_publikacie), 1)
    n_prj = max(len(obd.roky_projekty), 1)
    ak_set, pub_set, prj_set = set(obd.ak_roky), set(obd.roky_publikacie), set(obd.roky_projekty)

    vyucba_h = defaultdict(float)
    vyucba_raw = defaultdict(float)
    studenti = defaultdict(float)
    for v in data.vyucba:
        if v.ak_rok in ak_set:
            vyucba_h[v.ucitel_id] += hodiny_vyucby_zataz(v.hodiny, v.jazyk, params)
            vyucba_raw[v.ucitel_id] += v.hodiny
            studenti[v.ucitel_id] += v.pocet_studentov

    zp_h = defaultdict(float)
    for z in data.zaverecne_prace:
        if z.ak_rok in ak_set:
            zp_h[z.ucitel_id] += params["hodiny_zaverecna_praca"].get(z.stupen, 0.0) * z.pocet

    pub_body = defaultdict(float)
    for p in data.publikacie:
        if p.rok in pub_set:
            pub_body[p.ucitel_id] += body_publikacie(p, params)

    prj_hod, prj_fin, prj_odhad = financie_projektov_ucitelov(data, prj_set, params)

    out: list[VysledokUcitela] = []
    for u in data.ucitelia:
        fond = params["fond_hodin_rok"] * (u.uvazok or 0)
        r = VysledokUcitela(ucitel=u, zahrnuty=(u.uvazok or 0) >= params["min_uvazok"], fond_hodin=fond)
        r.h_vyucba = vyucba_h[u.id] / n_ak
        r.h_studenti = params["hodiny_na_studenta"] * studenti[u.id] / n_ak
        r.h_zaverecne_prace = zp_h[u.id] / n_ak
        r.h_vzdelavanie = r.h_vyucba + r.h_studenti + r.h_zaverecne_prace
        r.vyucba_tyzden = vyucba_raw[u.id] / n_ak / params["tyzdne_vyucby"]
        r.referencna_vyucba_tyzden = params["referencna_vyucba_tyzden"].get(u.funkcia)
        r.h_projekty = prj_hod[u.id] / n_prj
        r.financie_projekty = prj_fin[u.id] / n_prj
        r.body_publikacie = pub_body[u.id] / n_pub
        if fond > 0:
            r.pct_vzdelavanie = 100 * r.h_vzdelavanie / fond
            r.pct_spolu = 100 * (r.h_vzdelavanie + r.h_projekty) / fond
        r.status = status_zataze(r.pct_vzdelavanie, r.pct_spolu, params) if r.zahrnuty else "Nezahrnutý (úväzok < 25 %)"
        if r.zahrnuty and r.referencna_vyucba_tyzden and r.vyucba_tyzden > r.referencna_vyucba_tyzden * 1.0001:
            r.upozornenia.append(
                f"Priama výučba {r.vyucba_tyzden:.1f} h/týž. presahuje referenčných {r.referencna_vyucba_tyzden} h/týž.")
        if r.zahrnuty and u.id in prj_odhad:
            r.upozornenia.append("Podiel na financiách projektov je odhadnutý rovným dielom – chýbajú vykázané hodiny "
                                 "(doplňte ich importom „Účasť na projektoch“ z UIS).")
        if r.zahrnuty and r.pct_spolu > params["hranica_pretazenia"] >= r.pct_vzdelavanie:
            r.upozornenia.append("Vzdelávanie + projekty prekračujú fond pracovného času (čl. 3 ods. 5, čl. 5 ods. 3).")
        out.append(r)

    zahrnuti = [r for r in out if r.zahrnuty]
    for attr, src in (("std_vzdelavanie", "h_vzdelavanie"), ("std_publikacie", "body_publikacie"),
                      ("std_projekty", "financie_projekty")):
        for r, s in zip(zahrnuti, _minmax([getattr(r, src) for r in zahrnuti])):
            setattr(r, attr, s)
    return out


def financie_projektov_ucitelov(data: Data, roky: set[int], params: dict):
    """Vráti (súčet hodín, súčet podielov na financiách, učitelia s odhadnutým podielom) v zadaných rokoch.

    Podiel = suma pripísaná SPU × hodiny učiteľa / celková riešiteľská kapacita.
    Zodpovedný riešiteľ výskumného projektu má hodiny vynásobené (čl. 5 ods. 1 A).
    Do záťaže v hodinách (čl. 5 ods. 3) idú skutočne vykázané hodiny bez bonifikácie.
    """
    projekty = {p.id: p for p in data.projekty if p.rok in roky}
    ucasti_podla_projektu = defaultdict(list)
    for uc in data.ucasti:
        if uc.projekt_id in projekty:
            ucasti_podla_projektu[uc.projekt_id].append(uc)

    hodiny = defaultdict(float)
    financie = defaultdict(float)
    odhad: set[int] = set()
    vyskumne = set(params["vyskumne_typy_projektov"])
    nasobok = params["nasobok_zodpovedny_riesitel"]
    for pid, ucasti in ucasti_podla_projektu.items():
        p = projekty[pid]
        kap = kapacita_projektu(p, [u.hodiny for u in ucasti])
        for uc in ucasti:
            hodiny[uc.ucitel_id] += uc.hodiny
            k = nasobok if uc.zodpovedny and p.typ in vyskumne else 1.0
            if kap > 0:
                financie[uc.ucitel_id] += p.suma * uc.hodiny * k / kap
            elif p.suma > 0:
                # Hodiny nie sú zadané (verejná časť UIS ich neuvádza): suma sa rozdelí rovným dielom
                # medzi všetkých riešiteľov projektu v UIS, zodpovedný riešiteľ výskumného projektu 2×.
                n = max(p.pocet_riesitelov or 0, len(ucasti))
                financie[uc.ucitel_id] += p.suma * k / n
                odhad.add(uc.ucitel_id)
    return hodiny, financie, odhad


# ---------------------------------------------------------------- ústavy

@dataclass
class Regresia:
    """Lineárny model bez absolútneho člena y = b·x (čl. 1 ods. 4)."""
    b: float
    s: float  # smerodajná odchýlka rezíduí

    def predikcia(self, x: float) -> float:
        return self.b * x

    def z(self, x: float, y: float) -> Optional[float]:
        if self.s <= 0:
            return 0.0
        return (y - self.b * x) / self.s

    def optimalny_pocet(self, y: float) -> Optional[float]:
        return y / self.b if self.b > 0 else None


def regresia_cez_pociatok(xs: list[float], ys: list[float]) -> Optional[Regresia]:
    pary = [(x, y) for x, y in zip(xs, ys) if x > 0]
    if len(pary) < 2:
        return None
    sxx = sum(x * x for x, _ in pary)
    b = sum(x * y for x, y in pary) / sxx
    rez = [y - b * x for x, y in pary]
    s = math.sqrt(sum(e * e for e in rez) / (len(pary) - 1))
    return Regresia(b=b, s=s)


@dataclass
class VysledokUstavu:
    fakulta: str
    ustav: str
    uvazky: float = 0.0               # prepočítaný počet učiteľov
    pocet_ucitelov: int = 0
    vykon_vzdelavanie: float = 0.0    # študentohodiny × koef. odboru (priemer za ak. rok)
    vykon_publikacie: float = 0.0     # body za publikácie (priemer za rok)
    vykon_projekty: float = 0.0       # podiely na financiách (priemer za rok)
    z_vzdelavanie: Optional[float] = None
    z_publikacie: Optional[float] = None
    z_projekty: Optional[float] = None
    sumarne_skore: Optional[float] = None
    opt_vzdelavanie: Optional[float] = None
    opt_publikacie: Optional[float] = None
    opt_projekty: Optional[float] = None
    opt_pedagogovia: Optional[float] = None

    @property
    def rozdiel_pedagogov(self) -> Optional[float]:
        return None if self.opt_pedagogovia is None else self.opt_pedagogovia - self.uvazky


@dataclass
class VysledokUstavov:
    ustavy: list[VysledokUstavu]
    regresie: dict[str, Optional[Regresia]]
    upozornenia: list[str] = field(default_factory=list)


def efektivne_uvazky(data: Data) -> dict[int, float]:
    """Úväzok pre model ústavov (čl. 3 ods. 1, čl. 4 ods. 2, čl. 5 ods. 1 B).

    Chýbajúca časť obdobia (neskorší nástup, materská/rodičovská) sa nahradí
    priemerným úväzkom príslušnej fakulty.
    """
    podla_fakulty = defaultdict(list)
    for u in data.ucitelia:
        podla_fakulty[u.fakulta].append(u.uvazok or 0)
    priemer = {f: (sum(v) / len(v) if v else 0.0) for f, v in podla_fakulty.items()}
    out = {}
    for u in data.ucitelia:
        a = min(max(u.podiel_aktivny if u.podiel_aktivny is not None else 1.0, 0.0), 1.0)
        out[u.id] = (u.uvazok or 0) * a + priemer[u.fakulta] * (1 - a)
    return out


def koeficient_odboru(odbor: str, params: dict) -> float:
    if not odbor:
        return 1.0
    tab = params["koef_odbor"]
    if odbor in tab:
        return float(tab[odbor])
    low = odbor.strip().lower()
    for k, v in tab.items():
        if k.lower() == low or k.lower() in low:
            return float(v)
    return 1.0


def vypocitaj_ustavy(data: Data, obd: Obdobie, params: dict,
                     vysledky_ucitelov: Optional[list[VysledokUcitela]] = None) -> VysledokUstavov:
    if vysledky_ucitelov is None:
        vysledky_ucitelov = vypocitaj_ucitelov(data, obd, params)
    uvazky = efektivne_uvazky(data)
    ucitel_ustav = {u.id: (u.fakulta, u.ustav) for u in data.ucitelia}
    n_ak = max(len(obd.ak_roky), 1)
    ak_set = set(obd.ak_roky)
    upozornenia = []

    ustavy: dict[tuple[str, str], VysledokUstavu] = {}

    def get(key):
        if key not in ustavy:
            ustavy[key] = VysledokUstavu(fakulta=key[0], ustav=key[1])
        return ustavy[key]

    for u in data.ucitelia:
        if not u.ustav:
            continue
        r = get((u.fakulta, u.ustav))
        r.uvazky += uvazky[u.id]
        r.pocet_ucitelov += 1

    nezname_odbory = set()
    for v in data.vyucba:
        if v.ak_rok in ak_set and v.ucitel_id in ucitel_ustav and ucitel_ustav[v.ucitel_id][1]:
            if v.odbor and v.odbor not in params["koef_odbor"]:
                nezname_odbory.add(v.odbor)
            sh = v.studentohodiny if v.studentohodiny and v.studentohodiny > 0 else v.hodiny * v.pocet_studentov
            get(ucitel_ustav[v.ucitel_id]).vykon_vzdelavanie += sh * koeficient_odboru(v.odbor, params) / n_ak
    if nezname_odbory:
        upozornenia.append("Odbory bez koeficientu v tab. 2 (použitý najbližší alebo 1,0): " + ", ".join(sorted(nezname_odbory)))

    for r in vysledky_ucitelov:
        key = ucitel_ustav.get(r.ucitel.id)
        if key and key[1]:
            get(key).vykon_publikacie += r.body_publikacie
            get(key).vykon_projekty += r.financie_projekty

    zoznam = sorted(ustavy.values(), key=lambda x: (x.fakulta, x.ustav))
    x = [u.uvazky for u in zoznam]
    regresie = {
        "vzdelavanie": regresia_cez_pociatok(x, [u.vykon_vzdelavanie for u in zoznam]),
        "publikacie": regresia_cez_pociatok(x, [u.vykon_publikacie for u in zoznam]),
        "projekty": regresia_cez_pociatok(x, [u.vykon_projekty for u in zoznam]),
    }
    if len(zoznam) < 3:
        upozornenia.append("Regresný model potrebuje údaje z viacerých ústavov; pri menej ako 3 ústavoch sú výsledky orientačné.")

    vahy = params["vahy"]
    for u in zoznam:
        parts, opt_parts = [], []
        for oblast, attr in (("vzdelavanie", "vykon_vzdelavanie"), ("publikacie", "vykon_publikacie"),
                             ("projekty", "vykon_projekty")):
            reg = regresie[oblast]
            y = getattr(u, attr)
            if reg is None:
                continue
            z = reg.z(u.uvazky, y)
            opt = reg.optimalny_pocet(y)
            setattr(u, f"z_{oblast}", z)
            setattr(u, f"opt_{oblast}", opt)
            parts.append(vahy[oblast] * z)
            if opt is not None:
                opt_parts.append(vahy[oblast] * opt)
        if len(parts) == 3:
            u.sumarne_skore = sum(parts)
        if len(opt_parts) == 3:
            u.opt_pedagogovia = sum(opt_parts)
    return VysledokUstavov(ustavy=zoznam, regresie=regresie, upozornenia=upozornenia)
