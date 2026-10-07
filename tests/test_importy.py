import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import calc, importy, vystupy  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402
from spu_zataz.db import Databaza  # noqa: E402
from spu_zataz.ukazka import napln_ukazkove_data  # noqa: E402


class TestPrevody(unittest.TestCase):
    def test_cisla(self):
        self.assertEqual(importy.to_float("1 234,5"), 1234.5)
        self.assertEqual(importy.to_float("1.234,5"), 1234.5)
        self.assertEqual(importy.to_uvazok("50"), 0.5)
        self.assertEqual(importy.to_podiel("25"), 0.25)

    def test_ciselniky(self):
        self.assertEqual(importy.to_ak_rok("2024/25"), "2024/2025")
        self.assertEqual(importy.to_ak_rok(2024), "2024/2025")
        self.assertEqual(importy.to_jazyk("anglický"), "EN")
        self.assertEqual(importy.to_stupen("dizertačná práca"), "PhD")
        self.assertEqual(importy.to_stupen("diplomová práca"), "Ing")
        self.assertEqual(importy.to_kvartil("Q2"), "Q2")
        self.assertEqual(importy.to_kategoria("V3 – indexované WoS"), "V2/V3 indexované vo WoS/Scopus")

    def test_automaticke_mapovanie_uis(self):
        hl = ["Osobné číslo", "Vyučujúci", "Akad. rok", "Názov predmetu", "Jazyk výučby", "Odučené hodiny", "Študenti"]
        m = importy.automaticke_mapovanie(importy.TYPY["vyucba"], hl)
        self.assertEqual(m["meno"], "Vyučujúci")
        self.assertEqual(m["hodiny"], "Odučené hodiny")
        self.assertEqual(m["ak_rok"], "Akad. rok")


class TestSablona(unittest.TestCase):
    def test_round_trip(self):
        tmp = Path(tempfile.mkdtemp())
        db1 = Databaza(tmp / "a.db")
        napln_ukazkove_data(db1)
        d1 = db1.nacitaj_vsetko()
        importy.vytvor_sablonu(tmp / "export.xlsx", db1)

        db2 = Databaza(tmp / "b.db")
        res = importy.importuj_sablonu(db2, tmp / "export.xlsx")
        self.assertTrue(all(not r.chyby for r in res.values()), {k: r.chyby[:3] for k, r in res.items()})
        d2 = db2.nacitaj_vsetko()
        for t in ("ucitelia", "vyucba", "zaverecne_prace", "publikacie", "projekty", "ucasti"):
            self.assertEqual(len(getattr(d1, t)), len(getattr(d2, t)), t)

        obd = calc.navrhni_obdobie(d1, P)
        r1 = calc.vypocitaj_ucitelov(d1, obd, P)
        r2 = calc.vypocitaj_ucitelov(d2, obd, P)
        for a, b in zip(r1, r2):
            self.assertAlmostEqual(a.h_vzdelavanie, b.h_vzdelavanie)
            self.assertAlmostEqual(a.financie_projekty, b.financie_projekty)
            self.assertAlmostEqual(a.body_publikacie, b.body_publikacie)

        # opakovaný import s nahradením nesmie vytvoriť duplicity
        importy.importuj_sablonu(db2, tmp / "export.xlsx")
        self.assertEqual(len(db2.nacitaj("vyucba")), len(d1.vyucba))

        ust = calc.vypocitaj_ustavy(d1, obd, P, r1)
        self.assertEqual(len(ust.ustavy), 7)
        vystupy.export_vysledkov(tmp / "vysledky.xlsx", r1, ust, obd, P)
        self.assertTrue((tmp / "vysledky.xlsx").stat().st_size > 5000)

    def test_csv_import(self):
        tmp = Path(tempfile.mkdtemp())
        db = Databaza(tmp / "c.db")
        (tmp / "uis.csv").write_text(
            "Os. číslo;Vyučujúci;Akad. rok;Predmet;Jazyk;Odbor;Odučené hodiny;Študenti\n"
            "123;Ján Test;2024/25;Ekonómia;slovenský;ekonómia a manažment;52;40\n"
            "123;Ján Test;2024/25;Economics;anglický;ekonómia a manažment;26;12\n", encoding="cp1250")
        hl, rows = importy.nacitaj_subor(tmp / "uis.csv")
        m = importy.automaticke_mapovanie(importy.TYPY["vyucba"], hl)
        res = importy.importuj(db, "vyucba", rows, m)
        self.assertEqual(res.pridane, 2)
        self.assertEqual(res.novi_ucitelia, ["Ján Test"])
        v = db.nacitaj("vyucba")
        self.assertEqual([x.jazyk for x in v], ["SK", "EN"])


if __name__ == "__main__":
    unittest.main()
