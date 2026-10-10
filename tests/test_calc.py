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
        d = Data(ucitelia=[Ucitel(id=1, fakulta="F", uvazok=1.0, aktivny_vzdelavanie=0.5),
                           Ucitel(id=2, fakulta="F", uvazok=0.5)])
        # priemer fakulty 0,75 → 1×0,5 + 0,75×0,5 = 0,875
        self.assertAlmostEqual(calc.efektivne_uvazky(d)[1], 0.875)


# Výsledky ústavu UPTDB TF podľa metodického pokynu (súbor UPTDB.xlsx od používateľa, bez mien):
UPTDB = [  # (skóre vzd, pub, prj, celkové, pôvodné vzd, pub, prj, prepočítané vzd, pub, prj)
    (91.76397, 44.680266, 3.243193, 55.226333, 2143, 389, 33514, 2143, 389, 33514),
    (63.375422, 71.534707, 4.536535, 54.871359, 1576, 621, 46730, 1576, 621, 46730),
    (69.878735, 18.776696, 2.260669, 35.914306, 1706, 165, 23474, 1706, 165, 23474),
    (49.84373, 38.863597, 0.528466, 35.588624, 1305, 339, 5774, 1305, 339, 5774),
    (36.227028, 46.60265, 0.393299, 33.210531, 1033, 406, 4393, 1033, 406, 4393),
    (61.390174, 20.702262, 0.178887, 32.872752, 1536, 182, 2202, 1536, 182, 2202),
    (60.327541, 20.330796, 1.761334, 32.615602, 1515, 97, 3085, 1515, 178, 18372),
    (45.088136, 29.284936, 1.768507, 30.10293, 1210, 256, 18445, 1210, 256, 18445),
    (58.382298, 15.204536, 2.447048, 29.924143, 1476, 103, 19524, 1476, 134, 25378),
    (46.680835, 22.635001, 2.252025, 28.176739, 1242, 198, 23386, 1242, 198, 23386),
    (50.143768, 17.034559, 0.919758, 27.055282, 1311, 150, 9772, 1311, 150, 9772),
    (51.943993, 12.286704, 0.319329, 25.756145, 1347, 109, 3637, 1347, 109, 3637),
    (39.354919, 24.590141, 0.377439, 25.653512, 1095, 208, 2930, 1095, 215, 4230),
    (35.526066, 27.003206, 2.546129, 25.520934, 333, 141, 8503, 1019, 236, 26391),
    (48.565721, 11.913311, 1.233446, 24.438302, 1254, 106, 12977, 1279, 106, 12977),
    (51.383923, 8.775184, 0.935514, 24.250746, 1336, 79, 9933, 1336, 79, 9933),
    (39.349919, 15.579278, 1.760477, 22.323774, 1095, 137, 18363, 1095, 137, 18363),
    (50.118765, 3.222002, 1.024507, 21.541208, 1310, 31, 10842, 1310, 31, 10842),
    (24.08301, 26.927148, 0.173938, 20.438851, 790, 235, 2151, 790, 235, 2151),
    (35.04188, 13.668926, 0.419354, 19.568193, 1009, 121, 4659, 1009, 121, 4659),
    (21.51769, 26.443443, 0.242575, 19.232968, 739, 231, 2852, 739, 231, 2852),
    (27.350919, 12.269061, 0.328994, 15.913791, 855, 109, 3735, 855, 109, 3735),
    (37.154644, 2.464224, 0.124759, 15.872499, 1051, 24, 1649, 1051, 24, 1649),
    (34.441805, 3.85252, 0.006095, 15.318949, 997, 36, 436, 997, 36, 436),
    (10.101263, 5.483767, 0, 6.234012, 510, 50, 374, 510, 50, 374),
]
# Krajné hodnoty fakulty (učitelia iných ústavov TF) odvodené z lineárneho vzťahu skóre a prepočítaných hodnôt
TF_MIN_MAX = {"vzdelavanie": (308.2417, 2308.0867), "publikacie": (2.73667, 867.08278), "projekty": (373.68946, 1022212.18325)}


def _vysledok(fakulta, povodne, aktivita=None):
    r = calc.VysledokUcitela(ucitel=Ucitel(fakulta=fakulta), zahrnuty=True, fond_hodin=1537.5)
    r.povodne = dict(zip(("vzdelavanie", "publikacie", "projekty"), povodne))
    r.aktivita = aktivita or {"vzdelavanie": 1.0, "publikacie": 1.0, "projekty": 1.0}
    return r


class TestPorovnanieSExcelomUPTDB(unittest.TestCase):
    """Skóre učiteľov sa zhoduje s výsledkami ústavu UPTDB vypočítanými podľa pokynu."""

    def test_skore_a_celkove_skore(self):
        res = [_vysledok("TF", r[7:10]) for r in UPTDB]
        extremy = [_vysledok("TF", [TF_MIN_MAX[o][i] for o in ("vzdelavanie", "publikacie", "projekty")]) for i in (0, 1)]
        calc._prepocitaj_chybajuce_obdobie(res + extremy, P)
        calc._standardizuj(res + extremy, P)
        for r, xl in zip(res, UPTDB):
            self.assertAlmostEqual(r.skore["vzdelavanie"], xl[0], delta=0.1)
            self.assertAlmostEqual(r.skore["publikacie"], xl[1], delta=0.1)
            self.assertAlmostEqual(r.skore["projekty"], xl[2], delta=0.1)
            self.assertAlmostEqual(r.celkove_skore, xl[3], delta=0.1)
            self.assertAlmostEqual(0.4 * xl[0] + 0.4 * xl[1] + 0.2 * xl[2], xl[3], places=5)
        self.assertIs(min(res, key=lambda r: r.poradie), res[0])       # najvyššie celkové skóre ústavu

    def test_prepocet_chybajuceho_obdobia(self):
        """Prepočítaná = pôvodná + chýbajúca časť × priemer fakulty; rovnaký podiel pre publikácie aj projekty
        (v Exceli UPTDB je pomer prírastkov projekty/publikácie u všetkých učiteľov s prepočtom ≈ 188)."""
        plni = [_vysledok("TF", (1000, 100, 20000)), _vysledok("TF", (1400, 300, 60000))]
        cast = _vysledok("TF", (300, 50, 5000), {"vzdelavanie": 0.4, "publikacie": 0.5, "projekty": 0.5})
        ina_fakulta = _vysledok("FEM", (9999, 9999, 9999))
        vsetci = plni + [cast, ina_fakulta]
        calc._prepocitaj_chybajuce_obdobie(vsetci, P)
        self.assertAlmostEqual(cast.prepocitane["vzdelavanie"], 300 + 0.6 * 1200)
        self.assertAlmostEqual(cast.prepocitane["publikacie"], 50 + 0.5 * 200)
        self.assertAlmostEqual(cast.prepocitane["projekty"], 5000 + 0.5 * 40000)
        self.assertEqual(plni[0].prepocitane, plni[0].povodne)
        for r, xl in zip(UPTDB, UPTDB):
            if xl[8] != xl[5] and xl[9] != xl[6]:
                self.assertAlmostEqual((xl[9] - xl[6]) / (xl[8] - xl[5]), 188, delta=4)

    def test_vylucenie_pod_25_v_ktorejkolvek_oblasti(self):
        d = Data(ucitelia=[Ucitel(id=1, uvazok=1.0, aktivny_publikacie=0.2), Ucitel(id=2, uvazok=0.5, aktivny_projekty=0.6)])
        res = {r.ucitel.id: r for r in calc.vypocitaj_ucitelov(d, OBD, P)}
        self.assertFalse(res[1].zahrnuty)
        self.assertIn("publikacie", res[1].dovod_vylucenia)
        self.assertTrue(res[2].zahrnuty)        # 0,5 × 0,6 = 30 %


class TestObdobie(unittest.TestCase):
    def test_podla_pokynu(self):
        import datetime as dt
        o = calc.obdobie_podla_pokynu(P, dt.date(2026, 10, 10))
        self.assertEqual(o.ak_roky, ["2024/2025", "2025/2026"])
        self.assertEqual(o.roky_publikacie, [2022, 2023, 2024])
        self.assertEqual(o.roky_projekty, [2022, 2023, 2024])
        o = calc.obdobie_podla_pokynu(P, dt.date(2026, 3, 1))
        self.assertEqual(o.ak_roky, ["2023/2024", "2024/2025"])

    def test_jeden_akademicky_rok(self):
        obd = calc.Obdobie(ak_roky=["2024/2025"], roky_publikacie=[2024], roky_projekty=[2024])
        a = {r.ucitel.id: r for r in calc.vypocitaj_ucitelov(vzorove_data(), obd, P)}[1]
        self.assertAlmostEqual(a.h_vzdelavanie, 431)


if __name__ == "__main__":
    unittest.main()
