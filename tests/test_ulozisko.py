"""Uloženie údajov do priečinkov a ich načítanie, mazanie fakulty."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import ulozisko  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402
from spu_zataz.db import Databaza  # noqa: E402
from spu_zataz.models import (Projekt, ProjektUcast, Publikacia, Ucitel, Vyucba,  # noqa: E402
                              ZaverecnaPraca)


def naplnena_db() -> Databaza:
    db = Databaza(Path(tempfile.mkdtemp()) / "a.db")
    a = Ucitel(osobne_cislo="271", meno="Kosiba Ján", titul_pred="doc. Ing.", fakulta="TF", ustav="UPTDB",
               funkcia="docent", uvazok=1.0, aktivny_publikacie=0.5, orcid="0000-0002-4213-6374")
    b = Ucitel(meno="Nová Eva", fakulta="FEM", ustav="KE", uvazok=0.5)
    db.uloz(a)
    db.uloz(b)
    db.uloz(Vyucba(ucitel_id=a.id, ak_rok="2024/2025", predmet="Motory", jazyk="EN", hodiny=39, pocet_studentov=20.5))
    db.uloz(ZaverecnaPraca(ucitel_id=b.id, ak_rok="2024/2025", stupen="Ing", pocet=2))
    db.uloz(Publikacia(ucitel_id=a.id, rok=2024, kategoria="V2/V3 indexované vo WoS/Scopus", kvartil="Q2", podiel=0.2,
                       nazov="Článok", zdroj="Knižnica SPU / CREPČ", identifikator="doi:10.1/x|epca:1"))
    p = Projekt(kod="VEGA 1/0001/24", rok=2024, typ="VEGA", suma=5000, pocet_riesitelov=4)
    db.uloz(p)
    db.uloz(ProjektUcast(projekt_id=p.id, ucitel_id=a.id, hodiny=100, zodpovedny=True))
    db.uloz(ProjektUcast(projekt_id=p.id, ucitel_id=b.id, hodiny=50))
    return db


class TestUlozisko(unittest.TestCase):
    def test_ulozenie_a_nacitanie(self):
        db = naplnena_db()
        koren = Path(tempfile.mkdtemp()) / "Hodnotenie 2026"
        ulozisko.uloz(db, koren, {"ak_roky": ["2024/2025"]}, P)
        for nazov in ulozisko.ZLOZKY.values():
            self.assertTrue((koren / nazov).is_dir(), nazov)
        self.assertTrue((koren / "02 Zoznam učiteľov" / "ucitelia.xlsx").exists())
        self.assertTrue((koren / "05 Projekty" / "projekty.xlsx").exists())
        self.assertTrue((koren / "01 Podmienky hodnotenia" / "parametre.json").exists())
        self.assertTrue(ulozisko.je_priecinok_udajov(koren))

        db2 = Databaza(Path(tempfile.mkdtemp()) / "b.db")
        db2.uloz(Ucitel(meno="Starý záznam"))
        meta = ulozisko.nacitaj(db2, koren)
        self.assertEqual(meta["hodnotenie"], {"ak_roky": ["2024/2025"]})
        d1, d2 = db.nacitaj_vsetko(), db2.nacitaj_vsetko()
        self.assertEqual(d1, d2)
        self.assertEqual(ulozisko.nacitaj_podmienky(koren)["fond_hodin_rok"], 1537.5)

    def test_vymazanie_fakulty(self):
        db = naplnena_db()
        self.assertEqual(dict(db.fakulty()), {"FEM": 1, "TF": 1})
        self.assertEqual(db.vymaz_fakultu("FEM"), 1)
        d = db.nacitaj_vsetko()
        self.assertEqual([u.meno for u in d.ucitelia], ["Kosiba Ján"])
        self.assertEqual(d.zaverecne_prace, [])
        self.assertEqual(len(d.ucasti), 1)
        self.assertEqual(len(d.projekty), 1)          # projekt má ešte riešiteľa z TF
        db.vymaz_fakultu("TF")
        self.assertEqual(db.nacitaj_vsetko().projekty, [])


if __name__ == "__main__":
    unittest.main()
