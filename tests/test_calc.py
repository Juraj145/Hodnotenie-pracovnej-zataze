"""Testy výpočtov proti ručne spočítaným príkladom.

Spustenie:  python -m unittest discover -s tests   (alebo pytest)
"""

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import calc  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402
from spu_zataz.models import (Data, Projekt, ProjektUcast, Publikacia, Ucitel,  # noqa: E402
                              Vyucba, ZaverecnaPraca)


def vzorove_data() -> Data:
    d = Data()
    d.ucitelia = [
        Ucitel(id=1, meno="Anna A", fakulta="FEM", ustav="U1", funkcia="docent", uvazok=1.0),
        Ucitel(id=2, meno="Boris B", fakulta="FEM", ustav="U1", funkcia="odborný asistent", uvazok=1.0),
        Ucitel(id=3, meno="Cyril C", fakulta="FEM", ustav="U2", funkcia="lektor", uvazok=0.2),
    ]
    d.vyucba = [
        Vyucba(ucitel_id=1, ak_rok="2023/2024", jazyk="SK", odbor="ekonómia a manažment", hodiny=52, pocet_studentov=40),
        Vyucba(ucitel_id=1, ak_rok="2023/2024", jazyk="EN", odbor="ekonómia a manažment", hodiny=26, pocet_studentov=10),
        Vyucba(ucitel_id=1, ak_rok="2024/2025", jazyk="SK", odbor="ekonómia a manažment", hodiny=52, pocet_studentov=60),
        Vyucba(ucitel_id=1, ak_rok="2022/2023", jazyk="SK", odbor="ekonómia a manažment", hodiny=999, pocet_studentov=999),
    ]
    d.zaverecne_prace = [
        ZaverecnaPraca(ucitel_id=1, ak_rok="2023/2024", stupen="Bc", pocet=2),
        ZaverecnaPraca(ucitel_id=1, ak_rok="2024/2025", stupen="PhD", pocet=1),
    ]
    d.publikacie = [
        Publikacia(ucitel_id=1, rok=2023, kategoria="V2/V3 indexované vo WoS/Scopus", kvartil="Q1", podiel=0.5),
        Publikacia(ucitel_id=1, rok=2024, kategoria="V1: monografia", kvartil="Q3", podiel=1.0),
        Publikacia(ucitel_id=1, rok=2020, kategoria="V1: monografia", kvartil="Q1", podiel=1.0),
    ]
    d.projekty = [Projekt(id=10, kod="1/0001/24", typ="VEGA", rok=2024, suma=9000)]
    d.ucasti = [
        ProjektUcast(projekt_id=10, ucitel_id=1, hodiny=100, zodpovedny=True),
        ProjektUcast(projekt_id=10, ucitel_id=2, hodiny=200),
    ]
    return d


OBD = calc.Obdobie(ak_roky=["2023/2024", "2024/2025"], roky_publikacie=[2022, 2023, 2024],
                   roky_projekty=[2022, 2023, 2024])


class TestUcitel(unittest.TestCase):
    def setUp(self):
        self.res = {r.ucitel.id: r for r in calc.vypocitaj_ucitelov(vzorove_data(), OBD, P)}

    def test_vzdelavanie(self):
        a = self.res[1]
        # 2023/24: 2×52 + 6×26 (EN: 2×3) + 0,25×50 + 2×26 = 324,5
        # 2024/25: 2×52 + 0,25×60 + 312 = 431 ; priemer 377,75
        self.assertAlmostEqual(a.h_vzdelavanie, 377.75)
        self.assertAlmostEqual(a.pct_vzdelavanie, 377.75 / 1537.5 * 100)
        self.assertAlmostEqual(a.vyucba_tyzden, (78 + 52) / 2 / 26)
        self.assertEqual(a.status, "Pod ideálnym intervalom (< 40 %)")

    def test_anglictina_bez_nasobenia(self):
        p = dict(P, en_koef_nasobi_pripravu=False)
        a = {r.ucitel.id: r for r in calc.vypocitaj_ucitelov(vzorove_data(), OBD, p)}[1]
        self.assertAlmostEqual(a.h_vyucba, (2 * 52 + 3 * 26 + 2 * 52) / 2)

    def test_publikacie(self):
        # (510 × 0,5 + 60) / 3 roky; rok 2020 mimo obdobia
        self.assertAlmostEqual(self.res[1].body_publikacie, 105.0)

    def test_projekty(self):
        a, b = self.res[1], self.res[2]
        # kapacita = 300 h; A je zodpovedný riešiteľ VEGA → 2×100 h
        self.assertAlmostEqual(a.financie_projekty, 9000 * 200 / 300 / 3)
        self.assertAlmostEqual(b.financie_projekty, 9000 * 200 / 300 / 3)
        # záťaž v hodinách bez bonifikácie
        self.assertAlmostEqual(a.h_projekty, 100 / 3)

    def test_nezahrnuty_pod_25(self):
        self.assertFalse(self.res[3].zahrnuty)
        self.assertIsNone(self.res[3].std_vzdelavanie)

    def test_minmax(self):
        self.assertEqual(self.res[1].std_vzdelavanie, 1.0)
        self.assertEqual(self.res[2].std_vzdelavanie, 0.0)

    def test_status_hranice(self):
        self.assertTrue(calc.status_zataze(50, 50, P).startswith("Ideálny"))
        self.assertTrue(calc.status_zataze(70, 70, P).startswith("Nad ideálnym"))
        self.assertTrue(calc.status_zataze(80, 80, P).startswith("Nutné"))
        self.assertTrue(calc.status_zataze(50, 101, P).startswith("Preťaženie"))

    def test_v2v3_ostatne_iba_bez_q(self):
        p = Publikacia(kategoria="V2/V3 ostatné", kvartil="Q1", podiel=1)
        self.assertEqual(calc.body_publikacie(p, P), 5)


class TestRegresia(unittest.TestCase):
    def test_cez_pociatok(self):
        r = calc.regresia_cez_pociatok([1, 2, 3], [4, 8, 15])
        self.assertAlmostEqual(r.b, 65 / 14)
        sse = sum((y - 65 / 14 * x) ** 2 for x, y in zip([1, 2, 3], [4, 8, 15]))
        self.assertAlmostEqual(r.s, math.sqrt(sse / 2))
        self.assertAlmostEqual(r.z(1, 4), (4 - 65 / 14) / math.sqrt(sse / 2))

    def test_ilustracny_graf(self):
        # Ilustračný graf 1: y = 4x, skóre 80 → optimálne 20 pracovníkov
        self.assertEqual(calc.Regresia(b=4, s=1).optimalny_pocet(80), 20)


class TestUstavy(unittest.TestCase):
    def test_ustavy(self):
        d = vzorove_data()
        d.ucitelia.append(Ucitel(id=4, meno="Dana D", fakulta="FEM", ustav="U3", uvazok=1.0))
        d.vyucba.append(Vyucba(ucitel_id=4, ak_rok="2024/2025", odbor="biológia", hodiny=26, pocet_studentov=20))
        res = calc.vypocitaj_ustavy(d, OBD, P)
        u = {x.ustav: x for x in res.ustavy}
        # U1: (52×40 + 26×10 + 52×60) × 1,0 / 2 = 2730
        self.assertAlmostEqual(u["U1"].vykon_vzdelavanie, 2730)
        # U3: 26×20×1,5 / 2 = 390
        self.assertAlmostEqual(u["U3"].vykon_vzdelavanie, 390)
        self.assertIsNotNone(u["U1"].sumarne_skore)
        # vážený optimálny počet = 0,4·opt_vzd + 0,4·opt_pub + 0,2·opt_prj
        exp = 0.4 * u["U1"].opt_vzdelavanie + 0.4 * u["U1"].opt_publikacie + 0.2 * u["U1"].opt_projekty
        self.assertAlmostEqual(u["U1"].opt_pedagogovia, exp)

    def test_efektivny_uvazok_materska(self):
        d = Data(ucitelia=[Ucitel(id=1, fakulta="F", uvazok=1.0, podiel_aktivny=0.5),
                           Ucitel(id=2, fakulta="F", uvazok=0.5)])
        # priemer fakulty 0,75 → 1×0,5 + 0,75×0,5 = 0,875
        self.assertAlmostEqual(calc.efektivne_uvazky(d)[1], 0.875)


if __name__ == "__main__":
    unittest.main()
