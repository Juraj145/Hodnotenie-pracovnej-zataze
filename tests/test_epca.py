"""Testy importu publikácií z knižnice SPU (EPCA / CREPČ). tests/data/epca_vzorka.json obsahuje skutočné
záznamy webovej služby arl4.library.sk (databáza SpuUsEpca, formát LINEMARC)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import calc, epca  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402
from spu_zataz.config import KATEGORIE_PUBLIKACII as K  # noqa: E402
from spu_zataz.db import Databaza  # noqa: E402
from spu_zataz.models import Publikacia, Ucitel  # noqa: E402

VZORKA = json.loads((Path(__file__).parent / "data" / "epca_vzorka.json").read_text(encoding="utf-8"))
ZAZNAMY = {r["t001"]: r for r in VZORKA["records"]}


def falosne_hladanie(query, limit=1000):
    """Náhrada webovej služby: vráti záznamy vzorky, v ktorých sa vyskytuje hľadané slovo mena autora."""
    slovo = query.split("'")[1]
    if slovo in ("Ján", "Juraj"):
        return None                    # krstné meno – príliš veľa záznamov
    return [r for r in VZORKA["records"] if any(slovo in d for d in r["data"] if d[:3] in ("100", "700"))]


class TestZaznam(unittest.TestCase):
    def test_clanok_wos_scopus(self):
        z = epca.parsuj(ZAZNAMY["165785"])
        self.assertEqual((z.rok, z.rok_vydania, z.kategoria, z.typ), (2024, 2024, "V3", "CLA"))
        self.assertTrue(z.nazov.startswith("Comparison of Effect of Conventional Fuel"))
        self.assertEqual(z.ids["doi"], "10.2478/ata-2024-0007")
        self.assertEqual(z.ids["wos"], "001171920300006")
        self.assertEqual(z.ids["scopus"], "2-s2.0-85186234407")
        self.assertEqual(z.ids["crepc"], "biblio/1168801")
        self.assertEqual(z.kategoria_tab3(), K[2])
        self.assertEqual(z.kvartil_ais(), "Q4")
        self.assertEqual([(a.uis_id, a.podiel) for a in z.autori],
                         [("196", 0.24), ("1585", 0.24), ("2016", 0.12), ("1580", 0.2), ("271", 0.2)])
        self.assertAlmostEqual(sum(a.podiel for a in z.autori), 1.0)
        self.assertEqual(z.podiel("1585"), (0.24, False))
        self.assertEqual(z.podiel("", "Jablonický Juraj"), (0.24, False))

    def test_kategorie_vzorky(self):
        zs = [epca.parsuj(r) for r in VZORKA["records"]]
        for z in zs:
            if z.kategoria in ("V2", "V3"):
                self.assertEqual(z.kategoria_tab3(), K[2] if z.indexovane & {"WOS", "SCOPUS"} else K[3])
            elif z.kategoria == "V1":
                self.assertIn(z.kategoria_tab3(), K[:2])
            else:
                self.assertIsNone(z.kategoria_tab3())      # O, P, I… pokyn nehodnotí
        self.assertTrue(any(z.kvartil_ais() == "Q2" for z in zs))


class TestUcitel(unittest.TestCase):
    def test_publikacie_podla_uis_id(self):
        u = Ucitel(id=1, osobne_cislo="1585", meno="Jablonický Juraj", titul_pred="doc. Ing.", titul_za="PhD.")
        with mock.patch.object(epca, "vsetky_zaznamy", side_effect=falosne_hladanie):
            pubs = epca.publikacie_ucitela(u, [2022, 2023, 2024])
        self.assertTrue(pubs)
        for p in pubs:
            self.assertIn(p.zaznam.rok, (2022, 2023, 2024))
            self.assertIn(p.zaznam.kategoria, ("V1", "V2", "V3"))
            self.assertEqual(p.zaznam.najdi_autora("1585").uis_id, "1585")
            self.assertTrue(0 < p.podiel <= 1)
        self.assertEqual(len({p.zaznam.id for p in pubs}), len(pubs))
        p = next(p for p in pubs if p.zaznam.id == "165785")
        self.assertEqual((p.kategoria, p.kvartil, p.podiel), (K[2], "Q4", 0.24))

    def test_publikacie_podla_mena(self):
        """Učiteľ zadaný ručne (bez ID z UIS) v tvare „Meno Priezvisko“."""
        u = Ucitel(id=2, osobne_cislo="", meno="Ján Kosiba")
        with mock.patch.object(epca, "vsetky_zaznamy", side_effect=falosne_hladanie):
            pubs = epca.publikacie_ucitela(u, [2024])
        self.assertTrue(pubs)
        self.assertTrue(all(p.zaznam.najdi_autora("271") for p in pubs))
        self.assertEqual(next(p for p in pubs if p.zaznam.id == "165785").podiel, 0.2)

    def test_priezviska(self):
        self.assertEqual(epca.priezviska("Kosiba Ján"), ["Kosiba", "Ján"])
        self.assertEqual(epca.priezviska("J. Kosiba"), ["Kosiba"])
        self.assertEqual(epca.priezviska("Kosiba, Ján"), ["Kosiba"])
        self.assertIn("'Kosiba'", epca.dotaz_autor("Kosiba", [2023, 2024]))
        self.assertTrue(epca.dotaz_autor("Kosiba", [2023, 2024]).startswith("@and @attr 1=1003"))


class TestUlozenie(unittest.TestCase):
    def setUp(self):
        self.db = Databaza(Path(tempfile.mkdtemp()) / "t.db")
        self.u = Ucitel(osobne_cislo="1585", meno="Jablonický Juraj")
        self.db.uloz(self.u)
        self.iny = Ucitel(osobne_cislo="999", meno="Iný Učiteľ")
        self.db.uloz(self.iny)

    def test_duplicity_scopus_wos_a_podiely(self):
        z = epca.parsuj(ZAZNAMY["165785"])
        # tá istá publikácia zo Scopusu (DOI) a z WoS (UT) s podielom 1/5 a kvartilom podľa CiteScore
        self.db.uloz(Publikacia(ucitel_id=self.u.id, rok=2024, kategoria=K[2], kvartil="Q2", podiel=0.2,
                                nazov=z.nazov, zdroj="Scopus", identifikator="10.2478/ATA-2024-0007"))
        self.db.uloz(Publikacia(ucitel_id=self.u.id, rok=2024, kategoria=K[2], kvartil="Bez Q", podiel=0.2,
                                nazov=z.nazov.upper(), zdroj="WoS", identifikator="WOS:001171920300006"))
        # iná publikácia zo Scopusu ostáva; tá istá publikácia u iného učiteľa sa nemení
        self.db.uloz(Publikacia(ucitel_id=self.u.id, rok=2024, kategoria=K[2], kvartil="Q1", podiel=0.5,
                                nazov="Úplne iný článok o niečom inom", zdroj="Scopus", identifikator="10.1/xyz"))
        self.db.uloz(Publikacia(ucitel_id=self.iny.id, rok=2024, kategoria=K[2], kvartil="Q2", podiel=0.2,
                                nazov=z.nazov, zdroj="Scopus", identifikator="10.2478/ata-2024-0007"))
        with mock.patch.object(epca, "vsetky_zaznamy", side_effect=falosne_hladanie):
            najdene = epca.publikacie_ucitela(self.u, [2024])
        res = epca.uloz(self.db, najdene, [2024])
        self.assertEqual(res.nahradene, {"Scopus": 1, "WoS": 1})
        pubs = [p for p in self.db.nacitaj("publikacie") if p.ucitel_id == self.u.id]
        self.assertEqual(len(pubs), res.pridane + 1)
        p = next(p for p in pubs if "epca:165785" in p.identifikator)
        self.assertEqual((p.zdroj, p.kvartil, p.podiel), (epca.ZDROJ, "Q4", 0.24))
        self.assertAlmostEqual(calc.body_publikacie(p, P), 42.5 * 0.24)
        self.assertEqual(len([p for p in self.db.nacitaj("publikacie") if p.ucitel_id == self.iny.id]), 1)

        # opakovaný import nevytvorí duplicity
        res2 = epca.uloz(self.db, najdene, [2024])
        self.assertEqual(res2.nahradene, {})
        self.assertEqual(len([p for p in self.db.nacitaj("publikacie") if p.ucitel_id == self.u.id]), len(pubs))

    def test_je_v_kniznici(self):
        with mock.patch.object(epca, "vsetky_zaznamy", side_effect=falosne_hladanie):
            epca.uloz(self.db, epca.publikacie_ucitela(self.u, [2024]), [2024])
        pubs = self.db.nacitaj("publikacie")
        self.assertTrue(epca.je_v_kniznici(pubs, self.u.id, doi="10.2478/ata-2024-0007"))
        self.assertTrue(epca.je_v_kniznici(pubs, self.u.id, identifikator="2-s2.0-85186234407"))
        self.assertFalse(epca.je_v_kniznici(pubs, self.iny.id, doi="10.2478/ata-2024-0007"))
        self.assertFalse(epca.je_v_kniznici(pubs, self.u.id, doi="10.1/nie"))


if __name__ == "__main__":
    unittest.main()
