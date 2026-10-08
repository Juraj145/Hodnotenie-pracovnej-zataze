"""Testy načítania projektov z UIS. Súbory v tests/data majú štruktúru skutočných stránok is.uniag.sk/vv."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import calc, uis_web  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402
from spu_zataz.config import NEZAPOCITAT  # noqa: E402
from spu_zataz.db import Databaza  # noqa: E402
from spu_zataz.models import Ucitel  # noqa: E402

DATA = Path(__file__).parent / "data"


def subor(meno):
    return (DATA / meno).read_text(encoding="utf-8")


class TestParser(unittest.TestCase):
    def test_zoznam(self):
        z = uis_web.parsuj_zoznam_projektov(subor("uis_projekty_zoznam.html"))
        self.assertEqual(len(z), 4)
        p = z[0]
        self.assertEqual((p.uis_id, p.stav, p.od, p.do, p.kod, p.garant_id),
                         ("25426", "Ukončený", 2023, 2025, "026SPU-4/2023", "1480"))
        self.assertTrue(p.druh.startswith("KEGA (Kultúrna a edukačná"))
        self.assertTrue(p.zapocitany_stav)
        self.assertFalse(z[3].zapocitany_stav)          # zamietnutý VEGA
        self.assertEqual(z[2].kod, "")                   # bez kódu v zozname
        self.assertEqual(p.roky([2022, 2023, 2024, 2025]), [2023, 2024, 2025])

    def test_detail(self):
        p = uis_web.parsuj_zoznam_projektov(subor("uis_projekty_zoznam.html"))[0]
        uis_web.parsuj_detail_projektu(subor("uis_projekt_info.html"), subor("uis_projekt_pracovnici.html"), p)
        self.assertEqual(p.kod, "026SPU-4/2023")
        self.assertEqual(len(p.riesitelia), 7)
        self.assertEqual(p.riesitelia[0], ("1480", "doc. Ing. Ján Čimo, PhD.", ["Administratíva"]))
        riesitelia = [m for oid, m, ul in p.riesitelia if uis_web.je_riesitel(p, oid, ul)]
        # garant (aj keď má úlohu Administratíva) + 5 riešiteľov; administratíva bez garanta sa nezapočíta
        self.assertEqual(len(riesitelia), 6)
        self.assertNotIn("Ing. Andrea Matuškovičová", riesitelia)

    def test_kategorie(self):
        k = uis_web.kategoria_projektu
        self.assertEqual(k("VEGA (Vedecká grantová agentúra MŠVVaŠ SR)"), "VEGA")
        self.assertEqual(k("Všeobecné výzvy", "APVV-20-0071"), "APVV")
        self.assertEqual(k("Všeobecné výzvy", "10-GA SPU-16"), NEZAPOCITAT)
        self.assertEqual(k("GA SPU (Grantová agentúra SPU v Nitre)"), NEZAPOCITAT)
        self.assertEqual(k("Horizont Európa"), "Medzinárodný výskumný (Horizont a pod.)")
        self.assertEqual(k("Erasmus+ KA2 Európske univerzity"), "Erasmus+ KA2")
        self.assertEqual(k("Kooperačné partnerstvá"), "Erasmus+ KA2")
        self.assertEqual(k("OP Integrovaná infraštruktúra"), "Štrukturálne fondy")
        self.assertEqual(k("Plán obnovy a odolnosti Slovenska"), "Štrukturálne fondy")
        self.assertEqual(k("Dotácie MPRV SR"), "Verejná správa")
        self.assertEqual(k("Zmluvný a zákazkový výskum: domáca spolupráca s praxou"), "Iný subjekt")
        self.assertEqual(k("CEEPUS"), NEZAPOCITAT)
        self.assertEqual(k("#DUPLICITA"), NEZAPOCITAT)

    def test_pracoviska(self):
        html = ('<select name="pracoviste"><option value="1">Slovenská poľnohospodárska univerzita v Nitre</option>'
                '<option value="30">&nbsp;&nbsp;&nbsp;&nbsp;Technická fakulta</option>'
                '<option value="221">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Ústav elektrotechniky</option></select>')
        self.assertEqual(uis_web.pracoviska_projektov(html),
                         [(1, "Slovenská poľnohospodárska univerzita v Nitre", 0), (30, "Technická fakulta", 1),
                          (221, "Ústav elektrotechniky", 2)])


class TestUlozenieAVypocet(unittest.TestCase):
    def test_ulozenie(self):
        db = Databaza(Path(tempfile.mkdtemp()) / "p.db")
        db.uloz(Ucitel(osobne_cislo="1480", meno="Čimo Ján", uvazok=1))       # garant
        db.uloz(Ucitel(osobne_cislo="1272", meno="Vitázek Ivan", uvazok=1))   # riešiteľ
        db.uloz(Ucitel(meno="Matuškovičová Andrea", uvazok=1))                # administratíva
        zoznam = uis_web.parsuj_zoznam_projektov(subor("uis_projekty_zoznam.html"))
        p = uis_web.parsuj_detail_projektu(subor("uis_projekt_info.html"), subor("uis_projekt_pracovnici.html"), zoznam[0])
        gaspu = zoznam[1]
        gaspu.od, gaspu.do, gaspu.riesitelia = 2023, 2024, [("1272", "doc. Ing. Ivan Vitázek, CSc.", ["Riešiteľ"])]
        res = uis_web.uloz_projekty(db, [p, gaspu, zoznam[3]], {}, [2023, 2024, 2025])
        self.assertEqual(res.projekty_roky, 3)            # iba KEGA × 3 roky; GA SPU a zamietnutý VEGA nie
        self.assertEqual(res.ucasti_nove, 6)              # 2 učitelia × 3 roky
        proj = db.nacitaj("projekty")
        self.assertEqual({(x.kod, x.typ, x.pocet_riesitelov) for x in proj}, {("026SPU-4/2023", "KEGA", 6)})
        zodp = {(uc.ucitel_id, uc.zodpovedny) for uc in db.nacitaj("ucasti")}
        self.assertEqual(zodp, {(1, True), (2, False)})

        # suma doplnená používateľom, hodiny chýbajú → rovný diel, garant výskumného projektu 2×
        for x in proj:
            x.suma = 6000
            db.uloz(x)
        data = db.nacitaj_vsetko()
        obd = calc.Obdobie(ak_roky=[], roky_publikacie=[], roky_projekty=[2023, 2024, 2025])
        r = {v.ucitel.id: v for v in calc.vypocitaj_ucitelov(data, obd, P)}
        self.assertAlmostEqual(r[1].financie_projekty, 6000 * 2 / 6)
        self.assertAlmostEqual(r[2].financie_projekty, 6000 / 6)
        self.assertTrue(any("odhadnutý" in t for t in r[1].upozornenia))

        # opakované načítanie nemení sumy ani nevytvára duplicity
        uis_web.uloz_projekty(db, [p], {}, [2023, 2024, 2025])
        self.assertEqual(len(db.nacitaj("ucasti")), 6)
        self.assertEqual({x.suma for x in db.nacitaj("projekty")}, {6000})

        # po doplnení hodín sa použije presný výpočet podľa čl. 5 ods. 1 A
        for uc in db.nacitaj("ucasti"):
            uc.hodiny = 100 if uc.ucitel_id == 1 else 300
            db.uloz(uc)
        r = {v.ucitel.id: v for v in calc.vypocitaj_ucitelov(db.nacitaj_vsetko(), obd, P)}
        self.assertAlmostEqual(r[1].financie_projekty, 6000 * 200 / 400)
        self.assertFalse(any("odhadnutý" in t for t in r[1].upozornenia))

    def test_kategoria_zvolena_pouzivatelom(self):
        db = Databaza(Path(tempfile.mkdtemp()) / "k.db")
        db.uloz(Ucitel(osobne_cislo="1480", meno="Čimo Ján"))
        p = uis_web.parsuj_zoznam_projektov(subor("uis_projekty_zoznam.html"))[0]
        uis_web.parsuj_detail_projektu(subor("uis_projekt_info.html"), subor("uis_projekt_pracovnici.html"), p)
        res = uis_web.uloz_projekty(db, [p], {p.druh: NEZAPOCITAT}, [2024])
        self.assertEqual(res.projekty_roky, 0)


if __name__ == "__main__":
    unittest.main()


class TestSpoluriesitelia(unittest.TestCase):
    """Skutočná štruktúra stránky „Pracovníci“ projektu 27129 (KEGA, UPTDB) vrátane historických pracovníkov."""

    def setUp(self):
        html = subor("uis_projekt_pracovnici_27129.html")
        self.p = uis_web.ProjektUIS("27129", "Integrácia pokročilých technológií", "Riešený", 2025, 2027,
                                    "KEGA (Kultúrna a edukačná grantová agentúra MŠVVaŠ SR)", "196", "J. Tulík",
                                    kod="012SPU-4/2025")
        uis_web.parsuj_detail_projektu(html, html, self.p)
        self.p.nacitany_detail = True

    def test_parsovanie(self):
        self.assertEqual(len(self.p.riesitelia), 13)
        self.assertEqual(self.p.historicki, [("71515", "Ing. Rastislav Kollárik, PhD.", ["Riešiteľ"], 2024, 2026)])
        roky = {r: {m for _, m, _ in uis_web.riesitelia_v_roku(self.p, r)} for r in (2025, 2027)}
        # garant (administratíva) + metodický riešiteľ + 11 riešiteľov; historický riešiteľ iba do 2026
        self.assertEqual(len(roky[2025]), 14)
        self.assertIn("Ing. Rastislav Kollárik, PhD.", roky[2025])
        self.assertNotIn("Ing. Rastislav Kollárik, PhD.", roky[2027])
        self.assertIn("prof. Ing. Juraj Jablonický, PhD.", roky[2027])

    def test_ulozenie_spoluriesitelov(self):
        db = Databaza(Path(tempfile.mkdtemp()) / "s.db")
        for oc, meno in (("196", "Tulík Juraj"), ("1585", "Jablonický Juraj"), ("1586", "Abrahám Rudolf"),
                         ("1269", "Janoško Ivan"), ("1580", "Tkáč Zdenko")):
            db.uloz(Ucitel(osobne_cislo=oc, meno=meno, fakulta="TF", ustav="UPTDB"))
        db.uloz(Ucitel(meno="Kosiba Ján", fakulta="TF", ustav="UPTDB"))      # bez ID – podľa mena
        res = uis_web.uloz_projekty(db, [self.p], {}, [2025])
        self.assertEqual(res.riesitelov_uis, 14)
        self.assertEqual(res.riesitelov_v_db, 6)
        self.assertEqual(res.bez_pracovnikov, [])
        ucasti = {(uc.ucitel_id, uc.zodpovedny) for uc in db.nacitaj("ucasti")}
        self.assertEqual(len(ucasti), 6)
        self.assertIn((1, True), ucasti)                  # garant = zodpovedný riešiteľ
        self.assertEqual(sum(1 for _, z in ucasti if z), 1)

    def test_upozornenie_bez_pracovnikov(self):
        db = Databaza(Path(tempfile.mkdtemp()) / "b.db")
        db.uloz(Ucitel(osobne_cislo="196", meno="Tulík Juraj"))
        self.p.riesitelia, self.p.historicki = [], []
        res = uis_web.uloz_projekty(db, [self.p], {}, [2025])
        self.assertEqual(res.bez_pracovnikov, ["012SPU-4/2025"])
        self.assertIn("nepodarilo načítať zoznam pracovníkov", res.sprava())
