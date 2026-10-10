"""Kontrola úplnosti údajov potrebných na výpočet a analýzu."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from . import config
from .calc import Obdobie
from .models import Data

CHYBA = "chyba"            # výsledok bude nesprávny alebo sa nedá vypočítať
UPOZORNENIE = "upozornenie"  # výsledok môže byť skreslený
INFO = "info"


@dataclass
class Problem:
    zavaznost: str
    oblast: str             # Učitelia / Výučba / Záverečné práce / Projekty / Publikácie / Obdobie / Podmienky
    popis: str
    tabulka: str = ""       # kľúč tabuľky v databáze (pre prechod na záznam)
    id: Optional[int] = None
    ucitel_id: Optional[int] = None


def skontroluj(data: Data, obd: Obdobie, params: dict, metodika_nahrata: bool = True) -> list[Problem]:
    out: list[Problem] = []
    ak, pub, prj = set(obd.ak_roky), set(obd.roky_publikacie), set(obd.roky_projekty)
    mena = {u.id: u.cele_meno for u in data.ucitelia}

    if not metodika_nahrata:
        out.append(Problem(INFO, "Podmienky", "Nie je nahratý dokument metodiky – počíta sa s parametrami zabudovanými "
                                               "v programe (Metodický pokyn 1/2023 v znení Dodatku č. 2)."))
    if not data.ucitelia:
        out.append(Problem(CHYBA, "Učitelia", "Zoznam učiteľov je prázdny."))
    for nazov, roky in (("akademické roky (vzdelávanie)", obd.ak_roky), ("roky publikácií", obd.roky_publikacie),
                        ("roky projektov", obd.roky_projekty)):
        if not roky:
            out.append(Problem(CHYBA, "Obdobie", f"Nie sú zvolené {nazov}."))

    # ---------------------------------------------------------------- učitelia
    vyucba_uc = defaultdict(float)
    for v in data.vyucba:
        if v.ak_rok in ak:
            vyucba_uc[v.ucitel_id] += v.hodiny
    pub_uc = {p.ucitel_id for p in data.publikacie if p.rok in pub}
    for u in data.ucitelia:
        def p(zav, text, u=u):
            out.append(Problem(zav, "Učitelia", f"{u.cele_meno or '(bez mena)'}: {text}", "ucitelia", u.id, u.id))
        if not (u.meno or "").strip():
            p(CHYBA, "chýba meno")
        if not u.fakulta:
            p(CHYBA, "chýba fakulta (potrebná pre priemer fakulty a štandardizáciu)")
        if not u.ustav:
            p(CHYBA, "chýba ústav (učiteľ sa nezapočíta do hodnotenia ústavov)")
        if not u.uvazok:
            p(CHYBA, "chýba úväzok")
        if u.funkcia not in params["referencna_vyucba_tyzden"]:
            p(UPOZORNENIE, "chýba funkcia (profesor / docent / odborný asistent / lektor) – bez porovnania s pozn. 1")
        chyb = [n for n, v in (("ORCID", u.orcid), ("Scopus Author ID", u.scopus_id), ("WoS ResearcherID", u.wos_id))
                if not v]
        if chyb:
            p(UPOZORNENIE, "chýba " + ", ".join(chyb))
        if (u.uvazok or 0) >= params["min_uvazok"] and ak:
            if u.id not in vyucba_uc:
                p(UPOZORNENIE, "žiadna výučba v sledovaných akademických rokoch – chýbajú údaje?")
        if (u.uvazok or 0) >= params["min_uvazok"] and pub and u.id not in pub_uc:
            p(INFO, "žiadna publikácia v sledovaných rokoch")
        neaktivne = [f"{config.NAZVY_OBLASTI[o].lower()} {u.aktivita(o) * 100:.0f} %" for o in config.OBLASTI
                     if u.aktivita(o) < 1]
        if neaktivne:
            p(INFO, "neaktívny časť obdobia (" + ", ".join(neaktivne) + ") – dopočíta sa priemer fakulty")

    # ---------------------------------------------------------------- výučba
    ak_s_vyucbou = {v.ak_rok for v in data.vyucba}
    for r in obd.ak_roky:
        if r not in ak_s_vyucbou:
            out.append(Problem(CHYBA, "Výučba", f"Za akademický rok {r} nie je načítaná výučba."))
    bez_odboru, bez_studentov, nulove = defaultdict(int), defaultdict(int), defaultdict(int)
    for v in data.vyucba:
        if v.ak_rok not in ak:
            continue
        if not v.odbor or v.odbor not in params["koef_odbor"]:
            bez_odboru[v.ucitel_id] += 1
        if not v.pocet_studentov:
            bez_studentov[v.ucitel_id] += 1
        if not v.hodiny:
            nulove[v.ucitel_id] += 1
    for uid, n in bez_odboru.items():
        out.append(Problem(UPOZORNENIE, "Výučba", f"{mena.get(uid, '?')}: {n} predmetov bez študijného odboru z tab. 2 "
                                                   "(pre ústav sa použije koeficient 1,0)", "vyucba", None, uid))
    for uid, n in bez_studentov.items():
        out.append(Problem(INFO, "Výučba", f"{mena.get(uid, '?')}: {n} predmetov bez počtu študentov "
                                            "(doktorandské predmety ho v UIS nemajú)", "vyucba", None, uid))
    for uid, n in nulove.items():
        out.append(Problem(UPOZORNENIE, "Výučba", f"{mena.get(uid, '?')}: {n} záznamov s 0 hodinami", "vyucba", None, uid))

    # ---------------------------------------------------------------- záverečné práce
    ak_so_zp = {z.ak_rok for z in data.zaverecne_prace}
    for r in obd.ak_roky:
        if r not in ak_so_zp:
            out.append(Problem(UPOZORNENIE, "Záverečné práce", f"Za akademický rok {r} nie sú načítané záverečné práce."))
    for z in data.zaverecne_prace:
        if z.ak_rok in ak and z.stupen not in params["hodiny_zaverecna_praca"]:
            out.append(Problem(CHYBA, "Záverečné práce", f"{mena.get(z.ucitel_id, '?')}: neznámy stupeň „{z.stupen}“",
                               "zaverecne_prace", z.id, z.ucitel_id))

    # ---------------------------------------------------------------- publikácie
    roky_pub = {p.rok for p in data.publikacie}
    for r in obd.roky_publikacie:
        if r not in roky_pub:
            out.append(Problem(CHYBA, "Publikácie", f"Za rok {r} nie sú načítané publikácie."))
    for p in data.publikacie:
        if p.rok not in pub:
            continue
        kto = mena.get(p.ucitel_id, "?")
        if p.kategoria not in params["body_publikacie"]:
            out.append(Problem(CHYBA, "Publikácie", f"{kto}: neznáma kategória „{p.kategoria}“ – {p.nazov[:60]}",
                               "publikacie", p.id, p.ucitel_id))
        if not (0 < (p.podiel or 0) <= 1):
            out.append(Problem(CHYBA, "Publikácie", f"{kto}: podiel {p.podiel} mimo 0–1 – {p.nazov[:60]}",
                               "publikacie", p.id, p.ucitel_id))
        if p.kvartil not in config.KVARTILY:
            out.append(Problem(UPOZORNENIE, "Publikácie", f"{kto}: neznámy kvartil „{p.kvartil}“ – {p.nazov[:60]}",
                               "publikacie", p.id, p.ucitel_id))

    # ---------------------------------------------------------------- projekty
    roky_prj = {p.rok for p in data.projekty}
    for r in obd.roky_projekty:
        if r not in roky_prj:
            out.append(Problem(CHYBA, "Projekty", f"Za rok {r} nie sú načítané projekty."))
    ucasti = defaultdict(list)
    for uc in data.ucasti:
        ucasti[uc.projekt_id].append(uc)
    for p in data.projekty:
        if p.rok not in prj:
            continue
        nazov = f"{p.kod} ({p.rok})"
        if not p.suma:
            out.append(Problem(CHYBA, "Projekty", f"{nazov}: chýba suma pripísaná na účet SPU (Sofia/SAP)", "projekty", p.id))
        if p.typ not in config.TYPY_PROJEKTOV:
            out.append(Problem(UPOZORNENIE, "Projekty", f"{nazov}: typ „{p.typ}“ nie je v zozname pozn. 8 "
                                                         "(nevie sa, či ide o výskumný projekt)", "projekty", p.id))
        if not ucasti[p.id]:
            out.append(Problem(CHYBA, "Projekty", f"{nazov}: žiadny riešiteľ z databázy", "projekty", p.id))
        elif not any(uc.hodiny for uc in ucasti[p.id]) and not p.kapacita_hodin:
            out.append(Problem(UPOZORNENIE, "Projekty", f"{nazov}: chýbajú vykázané hodiny riešiteľov – podiel na "
                                                         "financiách sa odhadne rovným dielom", "projekty", p.id))
    return out


def podla_ucitela(problemy: list[Problem]) -> dict[int, list[Problem]]:
    out: dict[int, list[Problem]] = defaultdict(list)
    for p in problemy:
        if p.ucitel_id is not None:
            out[p.ucitel_id].append(p)
    return out


def suhrn(problemy: list[Problem]) -> dict[str, dict[str, int]]:
    """{oblasť: {závažnosť: počet}}"""
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in problemy:
        out[p.oblast][p.zavaznost] += 1
    return out
