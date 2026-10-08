"""Parametre modelu podľa Metodického pokynu 1/2023 v znení Dodatku č. 2.

Všetky číselné hodnoty z pokynu sú na jednom mieste. Používateľ ich môže
prepísať v súbore parametre.json v priečinku s dátami (Nastavenia → Parametre),
takže pri ďalšom dodatku netreba meniť program, stačí upraviť parametre.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

# Kategórie publikácií a kvartily (tab. 3)
KATEGORIE_PUBLIKACII = [
    "V1: monografia",
    "V1: editovaná kniha, kritická edícia, kritický preklad",
    "V2/V3 indexované vo WoS/Scopus",
    "V2/V3 ostatné",
]
KVARTILY = ["Bez Q", "Q1", "Q2", "Q3", "Q4"]

JAZYKY_VYUCBY = {
    "SK": "slovenský jazyk",
    "EN": "anglický jazyk (aj SK/EN program vyučovaný v angličtine)",
    "MOB": "mobilitní študenti evidovaní v UIS",
}

STUPNE_STUDIA = ["Bc", "Ing", "PhD"]

FUNKCIE = ["profesor", "docent", "odborný asistent", "lektor", "iné"]

TYPY_PROJEKTOV = [
    "VEGA", "KEGA", "APVV", "Medzinárodný výskumný (Horizont a pod.)",
    "Iný výskumný zo štátneho rozpočtu (súťažný)",
    "Štrukturálne fondy", "Erasmus+ KA2", "Verejná správa", "Iný subjekt",
]
# Druhy projektov z UIS, ktoré pokyn nezapočítava (pozn. 8 – iba externé projekty)
NEZAPOCITAT = "— nezapočítať —"

DEFAULT_PARAMETRE: dict = {
    # čl. 7 ods. 1.2 – ročný fond pracovného času pri plnom úväzku
    "fond_hodin_rok": 1537.5,
    # čl. 1 ods. 3 – pedagógovia s úväzkom pod touto hranicou nevstupujú do výpočtov na úrovni pracovníkov
    "min_uvazok": 0.25,
    # čl. 3 ods. 1 – dvojnásobok hodín priamej výučby (príprava)
    "koef_priprava": 2.0,
    # čl. 3 ods. 4 – bonifikácia výučby v angličtine a mobilitných študentov
    "koef_anglictina": 3.0,
    # Ak True: hodina v EN = koef_priprava × koef_anglictina (2 × 3 = 6 h).
    # Ak False: hodina v EN = koef_anglictina (3 h namiesto 2 h).
    "en_koef_nasobi_pripravu": True,
    # čl. 3 ods. 1 a čl. 7 ods. 1.1 b) – hodiny na jedného študenta
    "hodiny_na_studenta": 0.25,
    # tab. 1 – hodiny za úspešne ukončenú záverečnú prácu
    "hodiny_zaverecna_praca": {"Bc": 26.0, "Ing": 26.0, "PhD": 312.0},
    # tab. 2 – koeficient študijného odboru pre študentohodiny ústavu
    "koef_odbor": {
        "biotechnológie": 1.5,
        "biológia": 1.5,
        "potravinárstvo": 1.5,
        "strojárstvo": 1.5,
        "poľnohospodárstvo a krajinárstvo": 1.6,
        "ekonómia a manažment": 1.0,
    },
    # tab. 3 – body za publikácie podľa kategórie a kvartilu (None = nepoužíva sa)
    "body_publikacie": {
        "V1: monografia": {"Bez Q": 15, "Q1": 180, "Q2": 120, "Q3": 60, "Q4": 15},
        "V1: editovaná kniha, kritická edícia, kritický preklad": {"Bez Q": 5, "Q1": 60, "Q2": 40, "Q3": 20, "Q4": 5},
        "V2/V3 indexované vo WoS/Scopus": {"Bez Q": 42.5, "Q1": 510, "Q2": 340, "Q3": 170, "Q4": 42.5},
        "V2/V3 ostatné": {"Bez Q": 5, "Q1": None, "Q2": None, "Q3": None, "Q4": None},
    },
    # čl. 5 ods. 1 A – zodpovedný riešiteľ výskumného projektu
    "nasobok_zodpovedny_riesitel": 2.0,
    # pozn. 9 – výskumné projekty (bonifikácia zodpovedného riešiteľa)
    "vyskumne_typy_projektov": ["VEGA", "KEGA", "APVV", "Medzinárodný výskumný (Horizont a pod.)",
                                "Iný výskumný zo štátneho rozpočtu (súťažný)"],
    # čl. 6 ods. 1 – váhy sumárneho skóre
    "vahy": {"vzdelavanie": 0.4, "publikacie": 0.4, "projekty": 0.2},
    # čl. 7 ods. 1.2 a 1.3 – hranice záťaže vzdelávaním v % fondu
    "ideal_od": 40.0,
    "ideal_do": 60.0,
    "hranica_posudenia": 80.0,
    "hranica_pretazenia": 100.0,
    # poznámka 1 – referenčný počet hodín priamej výučby za týždeň
    "referencna_vyucba_tyzden": {"profesor": 6, "docent": 8, "odborný asistent": 12, "lektor": 18},
    # 2 semestre × 13 týždňov (tab. 1: 1 hodina týždenne počas dvoch semestrov = 26 h)
    "tyzdne_vyucby": 26,
    # dĺžky sledovaných období (čl. 2 ods. 2)
    "pocet_akad_rokov": 2,
    "pocet_rokov_publikacie": 3,
    "pocet_rokov_projekty": 3,
}


def app_data_dir() -> Path:
    """Priečinok s dátami používateľa (každý používateľ má vlastnú databázu)."""
    override = os.environ.get("SPU_ZATAZ_DATA")
    if override:
        p = Path(override)
    elif sys.platform.startswith("win"):
        p = Path(os.environ.get("APPDATA", Path.home())) / "SPU-Zataz"
    else:
        p = Path.home() / ".spu-zataz"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def parametre_path() -> Path:
    return app_data_dir() / "parametre.json"


def load_parametre() -> dict:
    path = parametre_path()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return _merge(DEFAULT_PARAMETRE, json.load(f))
        except (OSError, ValueError):
            pass
    return copy.deepcopy(DEFAULT_PARAMETRE)


def save_parametre(params: dict) -> None:
    with open(parametre_path(), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ nastavenia používateľa

DEFAULT_NASTAVENIA = {
    "scopus_api_key": "",
    "scopus_insttoken": "",
    "wos_api_key": "",
    "kontrolovat_aktualizacie": True,
    "preskocena_verzia": "",
}


def nastavenia_path() -> Path:
    return app_data_dir() / "nastavenia.json"


def load_nastavenia() -> dict:
    out = dict(DEFAULT_NASTAVENIA)
    p = nastavenia_path()
    if p.exists():
        try:
            out.update(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return out


def save_nastavenia(n: dict) -> None:
    nastavenia_path().write_text(json.dumps(n, ensure_ascii=False, indent=2), encoding="utf-8")
