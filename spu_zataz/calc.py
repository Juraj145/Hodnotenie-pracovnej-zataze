"""Výpočty podľa Metodického pokynu 1/2023 v znení Dodatku č. 2.

Modul neobsahuje nič z grafického rozhrania, aby sa dal samostatne testovať.
Odkazy v komentároch (čl., ods., tab.) smerujú na metodický pokyn.

Postup overený na výsledkoch ústavu UPTDB TF (hárok so stĺpcami Skóre vzdelávanie / publikácie / projekty,
Celkové skóre, pôvodné a prepočítané hodnoty):
  * pôvodná hodnota oblasti = priemer za rok (vzdelávanie v hodinách, publikácie v bodoch tab. 3,
    projekty = podiel na financiách v €),
  * prepočítaná hodnota = pôvodná + chýbajúca časť obdobia × priemer fakulty (čl. 3 ods. 1, čl. 4 ods. 2,
    čl. 5 ods. 1 B – chýbajúca časť sa nahradí priemerom príslušnej fakulty),
  * skóre oblasti = (x − x_min) / (x_max − x_min) × 100 z prepočítaných hodnôt (čl. 7 ods. 1.5),
  * celkové skóre = 0,4 · vzdelávanie + 0,4 · publikácie + 0,2 · projekty (váhy čl. 6 ods. 1).
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .config import OBLASTI
from .models import Data, Projekt, Publikacia, Ucitel


# ---------------------------------------------------------------- obdobia

@dataclass
class Obdobie:
    ak_roky: list[str]          # 2 posledné ukončené akademické roky (čl. 3 ods. 1) – alebo jeden zvolený
    roky_publikacie: list[int]  # 3 kalendárne roky (čl. 4 ods. 1)
    roky_projekty: list[int]    # 3 verifikované kalendárne roky (čl. 5 ods. 1)

    def popis(self) -> str:
        return (f"Vzdelávanie: {', '.join(self.ak_roky) or '–'} | "
                f"Publikácie: {', '.join(map(str, self.roky_publikacie)) or '–'} | "
                f"Projekty: {', '.join(map(str, self.roky_projekty)) or '–'}")

    def pocet(self, oblast: str) -> int:
        return max(len({"vzdelavanie": self.ak_roky, "publikacie": self.roky_publikacie,
                        "projekty": self.roky_projekty}[oblast]), 1)


def ak_rok_start(ak_rok: str) -> int:
    try:
        return int(str(ak_rok).replace("-", "/").split("/")[0])
    except ValueError:
        return 0


_ak_rok_start = ak_rok_start


def ak_rok_text(start: int) -> str:
    return f"{start}/{start + 1}"


def obdobie_podla_pokynu(params: dict, datum: Optional[dt.date] = None) -> Obdobie:
    """Sledované obdobie podľa čl. 2 ods. 2 k dátumu hodnotenia.

    vzdelávanie: dva posledné ukončené akademické roky,
    publikácie: tri kalendárne roky s uzávierkou v CREPČ najneskôr 31. 12. predchádzajúceho roka,
    projekty: tri posledné verifikované kalendárne roky (CVTI SR).
    """
    d = datum or dt.date.today()
    # akademický rok, ktorý práve prebieha, sa začal v roku d.year (od septembra) alebo d.year − 1
    prebieha = d.year if d.month >= params.get("zaciatok_ak_roka_mesiac", 9) else d.year - 1
    n_ak = params["pocet_akad_rokov"]
    ak = [ak_rok_text(s) for s in range(prebieha - n_ak, prebieha)]
    posl_pub = d.year - params.get("posun_rokov_publikacie", 2)
    posl_prj = d.year - params.get("posun_rokov_projekty", 2)
    return Obdobie(ak_roky=ak,
                   roky_publikacie=list(range(posl_pub - params["pocet_rokov_publikacie"] + 1, posl_pub + 1)),
                   roky_projekty=list(range(posl_prj - params["pocet_rokov_projekty"] + 1, posl_prj + 1)))


def roky_v_udajoch(data: Data) -> dict[str, list]:
    """Akademické a kalendárne roky, za ktoré sú v databáze údaje."""
    return {
        "ak_roky": sorted({v.ak_rok for v in data.vyucba if v.ak_rok} | {z.ak_rok for z in data.zaverecne_prace if z.ak_rok},
                          key=ak_rok_start),
        "publikacie": sorted({p.rok for p in data.publikacie if p.rok}),
        "projekty": sorted({p.rok for p in data.projekty if p.rok}),
    }


def navrhni_obdobie(data: Data, params: dict) -> Obdobie:
    """Navrhne sledované obdobie podľa najnovších údajov v databáze (posledné 2 ak. roky, 3 kalendárne roky)."""
    r = roky_v_udajoch(data)

    def posledne_roky(roky: list[int], n: int) -> list[int]:
        if not roky:
            return []
        last = roky[-1]
        return list(range(last - n + 1, last + 1))

    return Obdobie(
        ak_roky=r["ak_roky"][-params["pocet_akad_rokov"]:],
        roky_publikacie=posledne_roky(r["publikacie"], params["pocet_rokov_publikacie"]),
        roky_projekty=posledne_roky(r["projekty"], params["pocet_rokov_projekty"]),
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


# ---------------------------------------------------------------- výsledky učiteľov

@dataclass
class VysledokUcitela:
    ucitel: Ucitel
    zahrnuty: bool                    # prepočítaný úväzok ≥ 25 % vo všetkých oblastiach (čl. 1 ods. 3)
    fond_hodin: float
    # vzdelávanie – priemer za akademický rok
    h_vyucba: float = 0.0             # (2 resp. 6) × hodiny priamej výučby
    h_studenti: float = 0.0           # 0,25 h × študent
    h_zaverecne_prace: float = 0.0    # tab. 1
    h_vzdelavanie: float = 0.0
    hodiny_priamej_vyucby: float = 0.0
    pocet_studentov: float = 0.0
    studentohodiny: float = 0.0       # študentohodiny × koeficient odboru (pre ústav), priemer za ak. rok
    studentohodiny_prepocitane: float = 0.0
    vyucba_tyzden: float = 0.0        # hodiny priamej výučby / týždeň (pre porovnanie s pozn. 1)
    referencna_vyucba_tyzden: Optional[float] = None
    # projekty – priemer za kalendárny rok
    h_projekty: float = 0.0           # vykázané hodiny (čl. 5 ods. 3)
    financie_projekty: float = 0.0    # podiel na financiách (čl. 5 ods. 1 A)
    # publikácie – priemer za rok
    body_publikacie: float = 0.0
    pocet_publikacii: int = 0
    # percentá z fondu (za čas, keď bol učiteľ aktívny)
    pct_vzdelavanie: float = 0.0
    pct_spolu: float = 0.0
    status: str = ""
    dovod_vylucenia: str = ""
    upozornenia: list[str] = field(default_factory=list)
    # po oblastiach: aktivita (0–1), pôvodná a prepočítaná hodnota, skóre 0–100 (čl. 7 ods. 1.5)
    aktivita: dict = field(default_factory=dict)
    povodne: dict = field(default_factory=dict)
    prepocitane: dict = field(default_factory=dict)
    skore: dict = field(default_factory=dict)
    celkove_skore: Optional[float] = None
    poradie: Optional[int] = None     # poradie podľa celkového skóre v rámci skupiny štandardizácie

    # kompatibilita so staršími výstupmi (0–1)
    @property
    def std_vzdelavanie(self) -> Optional[float]:
        s = self.skore.get("vzdelavanie")
        return None if s is None else s / 100

    @property
    def std_publikacie(self) -> Optional[float]:
        s = self.skore.get("publikacie")
        return None if s is None else s / 100

    @property
    def std_projekty(self) -> Optional[float]:
        s = self.skore.get("projekty")
        return None if s is None else s / 100


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


def minmax_skore(values: list[float]) -> list[float]:
    """(x − x_min) / (x_max − x_min) × 100 (čl. 7 ods. 1.5)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.0 for _ in values]
    return [100 * (v - lo) / (hi - lo) for v in values]


def _minmax(values: list[float]) -> list[float]:
    return [v / 100 for v in minmax_skore(values)]


def skupina_standardizacie(u: Ucitel, params: dict) -> str:
    return u.fakulta or "" if params.get("standardizacia_skupina", "fakulta") == "fakulta" else "*"


def vypocitaj_ucitelov(data: Data, obd: Obdobie, params: dict) -> list[VysledokUcitela]:
    n_ak, n_pub, n_prj = obd.pocet("vzdelavanie"), obd.pocet("publikacie"), obd.pocet("projekty")
    ak_set, pub_set, prj_set = set(obd.ak_roky), set(obd.roky_publikacie), set(obd.roky_projekty)

    vyucba_h = defaultdict(float)
    vyucba_raw = defaultdict(float)
    studenti = defaultdict(float)
    sh = defaultdict(float)
    for v in data.vyucba:
        if v.ak_rok in ak_set:
            vyucba_h[v.ucitel_id] += hodiny_vyucby_zataz(v.hodiny, v.jazyk, params)
            vyucba_raw[v.ucitel_id] += v.hodiny
            studenti[v.ucitel_id] += v.pocet_studentov
            s = v.studentohodiny if v.studentohodiny and v.studentohodiny > 0 else v.hodiny * v.pocet_studentov
            sh[v.ucitel_id] += s * koeficient_odboru(v.odbor, params)

    zp_h = defaultdict(float)
    for z in data.zaverecne_prace:
        if z.ak_rok in ak_set:
            zp_h[z.ucitel_id] += params["hodiny_zaverecna_praca"].get(z.stupen, 0.0) * z.pocet

    pub_body = defaultdict(float)
    pub_pocet = defaultdict(int)
    for p in data.publikacie:
        if p.rok in pub_set:
            pub_body[p.ucitel_id] += body_publikacie(p, params)
            pub_pocet[p.ucitel_id] += 1

    prj_hod, prj_fin, prj_odhad = financie_projektov_ucitelov(data, prj_set, params)

    out: list[VysledokUcitela] = []
    for u in data.ucitelia:
        uv = u.uvazok or 0
        fond = params["fond_hodin_rok"] * uv
        r = VysledokUcitela(ucitel=u, zahrnuty=True, fond_hodin=fond)
        r.aktivita = {o: u.aktivita(o) for o in OBLASTI}
        nizke = [o for o in OBLASTI if uv * r.aktivita[o] < params["min_uvazok"] - 1e-9]
        if nizke:
            r.zahrnuty = False
            r.dovod_vylucenia = ("prepočítaný úväzok < 25 % (" + ", ".join(
                f"{o}: {uv * r.aktivita[o] * 100:.0f} %" for o in nizke) + ")")
        r.h_vyucba = vyucba_h[u.id] / n_ak
        r.h_studenti = params["hodiny_na_studenta"] * studenti[u.id] / n_ak
        r.h_zaverecne_prace = zp_h[u.id] / n_ak
        r.h_vzdelavanie = r.h_vyucba + r.h_studenti + r.h_zaverecne_prace
        r.hodiny_priamej_vyucby = vyucba_raw[u.id] / n_ak
        r.pocet_studentov = studenti[u.id] / n_ak
        r.studentohodiny = sh[u.id] / n_ak
        r.referencna_vyucba_tyzden = params["referencna_vyucba_tyzden"].get(u.funkcia)
        r.h_projekty = prj_hod[u.id] / n_prj
        r.financie_projekty = prj_fin[u.id] / n_prj
        r.body_publikacie = pub_body[u.id] / n_pub
        r.pocet_publikacii = pub_pocet[u.id]
        r.povodne = {"vzdelavanie": r.h_vzdelavanie, "publikacie": r.body_publikacie, "projekty": r.financie_projekty}

        # záťaž v % fondu za čas, keď bol učiteľ aktívny (priemer cez obdobie s materskou by ju podhodnotil)
        a_vzd, a_prj = r.aktivita["vzdelavanie"], r.aktivita["projekty"]
        if fond > 0:
            vzd_akt = r.h_vzdelavanie / a_vzd if a_vzd > 0 else 0.0
            prj_akt = r.h_projekty / a_prj if a_prj > 0 else 0.0
            r.pct_vzdelavanie = 100 * vzd_akt / fond
            r.pct_spolu = 100 * (vzd_akt + prj_akt) / fond
        akt_tyz = r.hodiny_priamej_vyucby / a_vzd if a_vzd > 0 else 0.0
        r.vyucba_tyzden = akt_tyz / params["tyzdne_vyucby"]
        r.status = (status_zataze(r.pct_vzdelavanie, r.pct_spolu, params) if r.zahrnuty
                    else f"Nezahrnutý – {r.dovod_vylucenia}")
        if r.zahrnuty and r.referencna_vyucba_tyzden and r.vyucba_tyzden > r.referencna_vyucba_tyzden * 1.0001:
            r.upozornenia.append(
                f"Priama výučba {r.vyucba_tyzden:.1f} h/týž. presahuje referenčných {r.referencna_vyucba_tyzden} h/týž. (pozn. 1).")
        if u.id in prj_odhad:
            r.upozornenia.append("Podiel na financiách projektov je odhadnutý rovným dielom – chýbajú vykázané hodiny "
                                 "(doplňte ich importom „Účasť na projektoch“ z UIS).")
        if r.zahrnuty and r.pct_spolu > params["hranica_pretazenia"] >= r.pct_vzdelavanie:
            r.upozornenia.append("Vzdelávanie + projekty prekračujú fond pracovného času (čl. 3 ods. 5, čl. 5 ods. 3).")
        if any(a < 1 for a in r.aktivita.values()):
            r.upozornenia.append("Učiteľ nebol aktívny celé obdobie (" + ", ".join(
                f"{o} {a * 100:.0f} %" for o, a in r.aktivita.items() if a < 1)
                + ") – chýbajúca časť je nahradená priemerom fakulty (prepočítané hodnoty).")
        out.append(r)

    _prepocitaj_chybajuce_obdobie(out, params)
    _standardizuj(out, params)
    return out


def priemery_fakult(vysledky: list[VysledokUcitela], hodnota) -> dict[tuple[str, str], float]:
    """Priemer fakulty pre každú oblasť: priemer pôvodných hodnôt zahrnutých učiteľov fakulty,
    ktorí boli aktívni celé obdobie oblasti (ak taký nie je, všetkých zahrnutých učiteľov fakulty)."""
    out = {}
    fakulty = {r.ucitel.fakulta or "" for r in vysledky}
    for f in fakulty:
        for o in OBLASTI:
            zakl = [r for r in vysledky if (r.ucitel.fakulta or "") == f and r.zahrnuty]
            plni = [r for r in zakl if r.aktivita.get(o, 1) >= 0.999] or zakl
            out[(f, o)] = sum(hodnota(r, o) for r in plni) / len(plni) if plni else 0.0
    return out


def _prepocitaj_chybajuce_obdobie(vysledky: list[VysledokUcitela], params: dict):
    prepocet = params.get("prepocet_chybajuceho_obdobia", True)
    priem = priemery_fakult(vysledky, lambda r, o: r.povodne[o])
    priem_sh = priemery_fakult(vysledky, lambda r, o: r.studentohodiny if o == "vzdelavanie" else 0.0)
    for r in vysledky:
        f = r.ucitel.fakulta or ""
        r.prepocitane = {}
        for o in OBLASTI:
            chyba = 1 - r.aktivita.get(o, 1) if prepocet else 0.0
            r.prepocitane[o] = r.povodne[o] + chyba * priem[(f, o)]
        chyba = 1 - r.aktivita.get("vzdelavanie", 1) if prepocet else 0.0
        r.studentohodiny_prepocitane = r.studentohodiny + chyba * priem_sh[(f, "vzdelavanie")]


def _standardizuj(vysledky: list[VysledokUcitela], params: dict):
    vahy = params.get("vahy_ucitelia") or params["vahy"]
    skupiny: dict[str, list[VysledokUcitela]] = defaultdict(list)
    for r in vysledky:
        if r.zahrnuty:
            skupiny[skupina_standardizacie(r.ucitel, params)].append(r)
    for clenovia in skupiny.values():
        for o in OBLASTI:
            for r, s in zip(clenovia, minmax_skore([r.prepocitane[o] for r in clenovia])):
                r.skore[o] = s
        for r in clenovia:
            r.celkove_skore = sum(vahy[o] * r.skore[o] for o in OBLASTI)
        for i, r in enumerate(sorted(clenovia, key=lambda x: -x.celkove_skore), start=1):
            r.poradie = i


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
    uvazky: float = 0.0               # prepočítaný počet učiteľov (vzdelávanie)
    uvazky_oblasti: dict = field(default_factory=dict)
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


def efektivne_uvazky(data: Data, oblast: str = "vzdelavanie") -> dict[int, float]:
    """Úväzok pre model ústavov (čl. 3 ods. 1, čl. 4 ods. 2, čl. 5 ods. 1 B).

    Chýbajúca časť obdobia oblasti (neskorší nástup, materská/rodičovská) sa nahradí
    priemerným úväzkom príslušnej fakulty.
    """
    podla_fakulty = defaultdict(list)
    for u in data.ucitelia:
        podla_fakulty[u.fakulta].append(u.uvazok or 0)
    priemer = {f: (sum(v) / len(v) if v else 0.0) for f, v in podla_fakulty.items()}
    out = {}
    for u in data.ucitelia:
        a = u.aktivita(oblast)
        out[u.id] = (u.uvazok or 0) * a + priemer[u.fakulta] * (1 - a)
    return out


def vypocitaj_ustavy(data: Data, obd: Obdobie, params: dict,
                     vysledky_ucitelov: Optional[list[VysledokUcitela]] = None) -> VysledokUstavov:
    if vysledky_ucitelov is None:
        vysledky_ucitelov = vypocitaj_ucitelov(data, obd, params)
    uvazky = {o: efektivne_uvazky(data, o) for o in OBLASTI}
    ucitel_ustav = {u.id: (u.fakulta, u.ustav) for u in data.ucitelia}
    ak_set = set(obd.ak_roky)
    upozornenia = []

    ustavy: dict[tuple[str, str], VysledokUstavu] = {}

    def get(key):
        if key not in ustavy:
            ustavy[key] = VysledokUstavu(fakulta=key[0], ustav=key[1], uvazky_oblasti={o: 0.0 for o in OBLASTI})
        return ustavy[key]

    for u in data.ucitelia:
        if not u.ustav:
            continue
        r = get((u.fakulta, u.ustav))
        for o in OBLASTI:
            r.uvazky_oblasti[o] += uvazky[o][u.id]
        r.uvazky = r.uvazky_oblasti["vzdelavanie"]
        r.pocet_ucitelov += 1

    nezname_odbory = {v.odbor for v in data.vyucba if v.ak_rok in ak_set and v.odbor and v.odbor not in params["koef_odbor"]}
    if nezname_odbory:
        upozornenia.append("Odbory bez koeficientu v tab. 2 (použitý najbližší alebo 1,0): " + ", ".join(sorted(nezname_odbory)))

    # výkony ústavu = súčet prepočítaných hodnôt jeho učiteľov (aj tých s úväzkom < 25 % – tie sa vylučujú
    # iba z výpočtov na úrovni pracovníkov, čl. 1 ods. 3)
    for r in vysledky_ucitelov:
        key = ucitel_ustav.get(r.ucitel.id)
        if key and key[1]:
            x = get(key)
            x.vykon_vzdelavanie += r.studentohodiny_prepocitane
            x.vykon_publikacie += r.prepocitane.get("publikacie", r.body_publikacie)
            x.vykon_projekty += r.prepocitane.get("projekty", r.financie_projekty)

    zoznam = sorted(ustavy.values(), key=lambda x: (x.fakulta, x.ustav))
    regresie = {
        "vzdelavanie": regresia_cez_pociatok([u.uvazky_oblasti["vzdelavanie"] for u in zoznam],
                                             [u.vykon_vzdelavanie for u in zoznam]),
        "publikacie": regresia_cez_pociatok([u.uvazky_oblasti["publikacie"] for u in zoznam],
                                            [u.vykon_publikacie for u in zoznam]),
        "projekty": regresia_cez_pociatok([u.uvazky_oblasti["projekty"] for u in zoznam],
                                          [u.vykon_projekty for u in zoznam]),
    }
    if len(zoznam) < 3:
        upozornenia.append("Regresný model potrebuje údaje z viacerých ústavov; pri menej ako 3 ústavoch sú výsledky orientačné.")

    vahy = params["vahy"]
    for u in zoznam:
        parts, opt_parts = [], []
        for oblast in OBLASTI:
            reg = regresie[oblast]
            y = getattr(u, f"vykon_{oblast}")
            if reg is None:
                continue
            z = reg.z(u.uvazky_oblasti[oblast], y)
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
