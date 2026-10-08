"""Testy prepočtu výučby z rozvrhov UIS. tests/data/uis_vyucba_vzorka.json je skutočný export TF
(rozvrhové akcie 12 predmetov, 2023/2024 a 2024/2025)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import calc  # noqa: E402
from spu_zataz import uis_vyucba as V  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402
from spu_zataz.db import Databaza  # noqa: E402
from spu_zataz.models import Ucitel  # noqa: E402

VZORKA = Path(__file__).parent / "data" / "uis_vyucba_vzorka.json"


def riadky(prep, uid, nazov, ak_rok):
    return [r for r in prep.riadky if r.uis_id == uid and r.predmet.startswith(nazov) and r.ak_rok == ak_rok]


class TestPrepocet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = V.nacitaj_subor(VZORKA)
        cls.prep = V.prepocitaj(cls.data)

    def test_pomocne(self):
        self.assertEqual(V.trvanie_hodin("13:30", "17:30"), 4)
        self.assertTrue(V.je_datovana("So 21.09.2024"))
        self.assertFalse(V.je_datovana("Ut"))
        self.assertEqual(V.jazyk_akcie({"poznamky": ["Výučba v AJ"], "obmedzenie": ""}), "EN")
        self.assertEqual(V.jazyk_akcie({"poznamky": [], "obmedzenie": "z-mob"}), "MOB")
        self.assertEqual(V.jazyk_akcie({"poznamky": ["Párny týždeň (podľa kalendára)"], "obmedzenie": "1b-adb"}), "SK")

    def test_motory_kosiba_zs_2024(self):
        """Ručne overené z rozvrhu: kombinovaná 15 h (bloky), denná 71,5 h (párny/nepárny týždeň, spoločné cvičenie)."""
        r = riadky(self.prep, "271", "Motory na alternatívne palivá", "2024/2025")
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0].hodiny, 86.5)
        self.assertAlmostEqual(r[0].studenti, 75)       # učí všetky prednášky → všetci študenti predmetu
        self.assertEqual(r[0].kod, "T15-0023-B")
        self.assertEqual(r[0].jazyk, "SK")

    def test_spolocne_cvicenie_nagy(self):
        nagy = [x for x in self.prep.riadky if x.meno == "M. Nagy" and x.predmet.startswith("Motory na alternatívne")
                and x.ak_rok == "2024/2025"]
        self.assertEqual(len(nagy), 1)
        self.assertAlmostEqual(nagy[0].hodiny, 6.5)    # 2 h × 13 týž. × ½ (párny týždeň) / 2 vyučujúci
        self.assertAlmostEqual(nagy[0].studenti, 75 * 24 / 120 / 2)

    def test_mobilitni_studenti(self):
        mob = riadky(self.prep, "271", "Motory na alternatívne palivá", "2023/2024")
        self.assertEqual({x.jazyk for x in mob}, {"SK", "MOB"})

    def test_studentohodiny_konzistentne(self):
        """Súčet študentohodín predmetu nezávisí od toho, ako sa delí medzi vyučujúcich."""
        pid = next(k for k, v in self.data["predmety"].items() if v["kod"] == "T15-0023-B" and v["ak_rok"] == "2024/2025")
        sh = sum(r.studentohodiny for r in self.prep.riadky if r.predmet_id == pid)
        self.assertGreater(sh, 0)
        h = sum(r.hodiny for r in self.prep.riadky if r.predmet_id == pid)
        self.assertAlmostEqual(h, 86.5 + 6.5)


class TestUlozenie(unittest.TestCase):
    def test_ulozenie_a_vypocet(self):
        db = Databaza(Path(tempfile.mkdtemp()) / "v.db")
        db.uloz(Ucitel(osobne_cislo="271", meno="Kosiba Ján", funkcia="docent", uvazok=1, fakulta="TF", ustav="UPTDB"))
        db.uloz(Ucitel(meno="Nagy Martin", uvazok=1, fakulta="TF", ustav="UPTDB"))   # bez ID – podľa mena „M. Nagy“
        prep = V.prepocitaj(V.nacitaj_subor(VZORKA))
        res = V.uloz(db, prep, {})
        self.assertEqual(len(res.ucitelia), 2)
        self.assertIn("J. Jablonický", res.mimo_db)
        v = [x for x in db.nacitaj("vyucba") if x.ucitel_id == 1 and x.ak_rok == "2024/2025"]
        self.assertAlmostEqual(sum(x.hodiny for x in v), 205.5, places=1)
        # opakované načítanie nahradí riadky z UIS, ručné zostanú
        from spu_zataz.models import Vyucba
        db.uloz(Vyucba(ucitel_id=1, ak_rok="2024/2025", predmet="Ručne zadaný seminár", hodiny=10))
        V.uloz(db, prep, {})
        v2 = [x for x in db.nacitaj("vyucba") if x.ucitel_id == 1 and x.ak_rok == "2024/2025"]
        self.assertEqual(len(v2), len(v) + 1)

        obd = calc.Obdobie(ak_roky=["2023/2024", "2024/2025"], roky_publikacie=[], roky_projekty=[])
        data = db.nacitaj_vsetko()
        r = {x.ucitel.id: x for x in calc.vypocitaj_ucitelov(data, obd, P)}
        self.assertGreater(r[1].h_vyucba, 0)
        self.assertGreater(r[1].h_studenti, 0)
        u = calc.vypocitaj_ustavy(data, obd, P, list(r.values()))
        self.assertGreater(u.ustavy[0].vykon_vzdelavanie, 0)

    def test_zalozka(self):
        url = V.bookmarklet()
        self.assertTrue(url.startswith("javascript:"))
        self.assertLess(len(url), 20000)
        p = V.stranka_so_zalozkou(Path(tempfile.mkdtemp()) / "z.html")
        self.assertIn("SPU záťaž – export z UIS", p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
