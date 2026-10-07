"""Vymyslené ukážkové údaje na vyskúšanie programu (nie sú to reálne osoby)."""

from __future__ import annotations

import random

from .db import Databaza
from .models import (Projekt, ProjektUcast, Publikacia, Ucitel, Vyucba,
                     ZaverecnaPraca)

USTAVY = [
    ("FEM", "Ústav ekonomiky", "ekonómia a manažment"),
    ("FEM", "Ústav manažmentu", "ekonómia a manažment"),
    ("FAPZ", "Ústav agronómie", "poľnohospodárstvo a krajinárstvo"),
    ("FAPZ", "Ústav chovu zvierat", "poľnohospodárstvo a krajinárstvo"),
    ("FBP", "Ústav potravinárstva", "potravinárstvo"),
    ("FBP", "Ústav biotechnológií", "biotechnológie"),
    ("TF", "Ústav strojárstva", "strojárstvo"),
]
FUNKCIE = [("profesor", 6), ("docent", 8), ("odborný asistent", 12), ("odborný asistent", 12), ("lektor", 18)]
MENA = ["Novák", "Kováč", "Horváth", "Varga", "Tóth", "Nagy", "Baláž", "Szabó", "Molnár", "Lukáč", "Kollár",
        "Polák", "Benko", "Urban", "Hudák", "Král", "Gajdoš", "Oravec", "Kráľ", "Rusnák"]


def napln_ukazkove_data(db: Databaza, seed: int = 7):
    rnd = random.Random(seed)
    oc = 1000
    ucitelia = []
    for fak, ustav, odbor in USTAVY:
        for _ in range(rnd.randint(4, 9)):
            oc += 1
            funkcia, ref = rnd.choice(FUNKCIE)
            u = Ucitel(osobne_cislo=str(oc), titul_pred=rnd.choice(["Ing.", "doc. Ing.", "prof. Ing.", "Mgr."]),
                       meno=f"{rnd.choice('ABCDEFGHJKLMPRSTVZ')}. {rnd.choice(MENA)}",
                       titul_za="PhD.", fakulta=fak, ustav=ustav, funkcia=funkcia,
                       uvazok=rnd.choice([1, 1, 1, 1, 0.5, 0.2]),
                       podiel_aktivny=rnd.choice([1, 1, 1, 1, 1, 0.5]))
            db.uloz(u, commit=False)
            ucitelia.append((u, odbor, ref))
    for u, odbor, ref in ucitelia:
        for ak in ("2023/2024", "2024/2025"):
            for k in range(rnd.randint(1, 4)):
                db.uloz(Vyucba(ucitel_id=u.id, ak_rok=ak, predmet=f"Predmet {k + 1}",
                               jazyk=rnd.choice(["SK", "SK", "SK", "EN", "MOB"]), odbor=odbor,
                               hodiny=rnd.choice([26, 39, 52, 78]) * u.uvazok,
                               pocet_studentov=rnd.randint(10, 120)), commit=False)
            for st in ("Bc", "Ing"):
                n = rnd.randint(0, 5)
                if n:
                    db.uloz(ZaverecnaPraca(ucitel_id=u.id, ak_rok=ak, stupen=st, pocet=n), commit=False)
            if u.funkcia in ("profesor", "docent") and rnd.random() < 0.4:
                db.uloz(ZaverecnaPraca(ucitel_id=u.id, ak_rok=ak, stupen="PhD", pocet=1), commit=False)
        for rok in (2022, 2023, 2024):
            for _ in range(rnd.randint(0, 4)):
                kat = rnd.choice(["V2/V3 indexované vo WoS/Scopus", "V2/V3 indexované vo WoS/Scopus",
                                  "V2/V3 ostatné", "V1: monografia"])
                kv = "Bez Q" if kat == "V2/V3 ostatné" else rnd.choice(["Q1", "Q2", "Q3", "Q4", "Bez Q"])
                db.uloz(Publikacia(ucitel_id=u.id, rok=rok, kategoria=kat, kvartil=kv,
                                   podiel=rnd.choice([1, 0.5, 0.33, 0.25, 0.2]),
                                   nazov="Ukážková publikácia", zdroj="ukážka"), commit=False)
    typy = ["VEGA", "KEGA", "APVV", "Erasmus+ KA2", "Verejná správa"]
    for i in range(18):
        typ = rnd.choice(typy)
        riesitelia = rnd.sample(ucitelia, rnd.randint(2, 5))
        for rok in (2022, 2023, 2024):
            p = Projekt(kod=f"{typ}-{i:03d}", nazov=f"Ukážkový projekt {i + 1}", typ=typ, rok=rok,
                        suma=rnd.choice([5000, 12000, 30000, 80000]))
            db.uloz(p, commit=False)
            for j, (u, _, _) in enumerate(riesitelia):
                db.uloz(ProjektUcast(projekt_id=p.id, ucitel_id=u.id, hodiny=rnd.choice([50, 100, 150, 200]),
                                     zodpovedny=(j == 0)), commit=False)
    db.commit()
