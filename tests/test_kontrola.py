"""Kontrola chýbajúcich údajov."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import calc, kontrola  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402
from tests.test_ulozisko import naplnena_db  # noqa: E402


class TestKontrola(unittest.TestCase):
    def test_problemy(self):
        d = naplnena_db().nacitaj_vsetko()
        obd = calc.Obdobie(ak_roky=["2023/2024", "2024/2025"], roky_publikacie=[2024], roky_projekty=[2024])
        pr = kontrola.skontroluj(d, obd, P, metodika_nahrata=False)
        texty = [(p.zavaznost, p.oblast, p.popis) for p in pr]
        self.assertIn((kontrola.CHYBA, "Výučba", "Za akademický rok 2023/2024 nie je načítaná výučba."), texty)
        self.assertTrue(any(z == kontrola.UPOZORNENIE and "Nová Eva" in t and "ORCID" in t for z, _, t in texty))
        # Kosiba má ORCID, chýba mu Scopus a ResearcherID
        self.assertTrue(any("Kosiba" in t and "Scopus Author ID, WoS ResearcherID" in t for _, _, t in texty))
        self.assertTrue(any(o == "Podmienky" for _, o, _ in texty))
        self.assertTrue(any("bez študijného odboru" in t for _, _, t in texty))
        uc = kontrola.podla_ucitela(pr)
        self.assertTrue(uc[d.ucitelia[1].id])
        self.assertIn("Učitelia", kontrola.suhrn(pr))


if __name__ == "__main__":
    unittest.main()
