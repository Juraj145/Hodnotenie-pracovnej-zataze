"""Dátové záznamy, s ktorými pracuje model."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Optional


@dataclass
class Ucitel:
    id: Optional[int] = None
    osobne_cislo: str = ""          # identifikátor z UIS / personálnej evidencie (kľúč pri importe)
    titul_pred: str = ""
    meno: str = ""                  # meno a priezvisko
    titul_za: str = ""
    fakulta: str = ""
    ustav: str = ""
    funkcia: str = ""               # profesor / docent / odborný asistent / lektor
    uvazok: float = 1.0             # prepočítaný stav úväzku 0–1
    podiel_aktivny: float = 1.0     # podiel sledovaného obdobia v pracovnom pomere (bez materskej/rodičovskej) 0–1
    scopus_id: str = ""
    wos_id: str = ""                # ResearcherID
    orcid: str = ""

    @property
    def cele_meno(self) -> str:
        return " ".join(x for x in (self.titul_pred, self.meno) if x) + (f", {self.titul_za}" if self.titul_za else "")


@dataclass
class Vyucba:
    """Jeden predmet / rozvrhová akcia učiteľa v akademickom roku."""
    id: Optional[int] = None
    ucitel_id: int = 0
    ak_rok: str = ""                # napr. 2024/2025
    predmet: str = ""
    jazyk: str = "SK"               # SK / EN / MOB
    odbor: str = ""                 # kľúč z tab. 2
    hodiny: float = 0.0             # hodiny priamej výučby za akademický rok
    pocet_studentov: float = 0.0
    studentohodiny: float = 0.0     # z rozvrhu UIS: Σ hodiny akcie × študenti skupiny (0 = hodiny × študenti)


@dataclass
class ZaverecnaPraca:
    id: Optional[int] = None
    ucitel_id: int = 0
    ak_rok: str = ""
    stupen: str = "Bc"              # Bc / Ing / PhD
    pocet: float = 1.0              # počet úspešne ukončených študentov
    nazov: str = ""


@dataclass
class Publikacia:
    id: Optional[int] = None
    ucitel_id: int = 0
    rok: int = 0
    kategoria: str = "V2/V3 ostatné"
    kvartil: str = "Bez Q"
    podiel: float = 1.0             # podiel zamestnanca na publikácii 0–1
    nazov: str = ""
    zdroj: str = ""                 # ručne / Excel / UIS / Scopus / WoS / CREPČ
    identifikator: str = ""         # DOI, EID, UT, …


@dataclass
class Projekt:
    """Projekt v konkrétnom kalendárnom roku."""
    id: Optional[int] = None
    kod: str = ""
    nazov: str = ""
    typ: str = ""
    rok: int = 0
    suma: float = 0.0               # finančné prostriedky pripísané na účet SPU v danom roku
    kapacita_hodin: float = 0.0     # celková riešiteľská kapacita v UIS (0 = súčet hodín účastníkov)
    pocet_riesitelov: int = 0       # počet riešiteľov projektu v UIS (aj z iných pracovísk) – pre odhad bez hodín
    uis_id: str = ""                # ID projektu v UIS (is.uniag.sk/vv)


@dataclass
class ProjektUcast:
    id: Optional[int] = None
    projekt_id: int = 0
    ucitel_id: int = 0
    hodiny: float = 0.0             # vykázané hodiny v danom roku
    zodpovedny: bool = False


def field_names(cls) -> list[str]:
    return [f.name for f in fields(cls)]


@dataclass
class Data:
    """Kompletné vstupy modelu."""
    ucitelia: list[Ucitel] = field(default_factory=list)
    vyucba: list[Vyucba] = field(default_factory=list)
    zaverecne_prace: list[ZaverecnaPraca] = field(default_factory=list)
    publikacie: list[Publikacia] = field(default_factory=list)
    projekty: list[Projekt] = field(default_factory=list)
    ucasti: list[ProjektUcast] = field(default_factory=list)
