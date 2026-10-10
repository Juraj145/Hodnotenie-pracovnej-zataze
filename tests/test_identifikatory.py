"""Doplnenie ORCID, Scopus Author ID a ResearcherID. tests/data/identifikatory_vzorka.json obsahuje skutočné
odpovede autorít knižnice SPU (SpuUsAuth) a registra ORCID."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import identifikatory as ids  # noqa: E402
from spu_zataz.models import Ucitel  # noqa: E402

FX = json.loads((Path(__file__).parent / "data" / "identifikatory_vzorka.json").read_text(encoding="utf-8"))


def falosne_autority(priezvisko, limit=300):
    return [ids.parsuj_autoritu(r) for r in FX["auth"].get(priezvisko, [])]


def falosny_get(url):
    if "expanded-search" in url:
        return FX["orcid_search_kosiba"] if "Kosiba" in url else {"expanded-result": None, "num-found": 0}
    if "0000-0002-4213-6374" in url:
        return FX["orcid_ext_kosiba"]
    if "0000-0003-4512-4675" in url:
        return FX["orcid_ext_jablonicky"]
    return {}


class TestIdentifikatory(unittest.TestCase):
    def setUp(self):
        self.p1 = mock.patch.object(ids, "autority", side_effect=falosne_autority)
        self.p2 = mock.patch.object(ids, "_get_json", side_effect=falosny_get)
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_autorita(self):
        a = ids.parsuj_autoritu(FX["auth"]["Kosiba"][1])
        self.assertEqual((a.meno, a.orcid, a.crepc, a.spu), ("Kosiba, Ján", "0000-0002-4213-6374", "person/118141", True))
        self.assertFalse(ids.parsuj_autoritu(FX["auth"]["Kosiba"][0]).spu)

    def test_z_kniznice_a_orcid(self):
        r = ids.najdi(Ucitel(id=1, meno="Kosiba Ján", titul_pred="doc. Ing."))
        self.assertEqual((r.orcid, r.scopus, r.wos), ("0000-0002-4213-6374", "36486690100", "F-5386-2017"))
        self.assertIn("knižnica SPU", r.zdroje)
        r = ids.najdi(Ucitel(id=2, meno="Jablonický Juraj"))
        self.assertEqual((r.orcid, r.scopus, r.wos), ("0000-0003-4512-4675", "36126184100", ""))

    def test_existujuce_sa_neprepisuju(self):
        r = ids.najdi(Ucitel(id=1, meno="Kosiba Ján", orcid="0000-0002-4213-6374", scopus_id="1"))
        self.assertEqual((r.orcid, r.scopus, r.wos), ("", "", "F-5386-2017"))

    def test_bez_zhody(self):
        r = ids.najdi(Ucitel(id=3, meno="Gálik Roman"))
        self.assertFalse(r.nieco)                 # autorita bez ORCID, v registri ORCID nikto
        self.assertEqual(ids.chybajuce_id(Ucitel(orcid="x")), ["Scopus ID", "ResearcherID"])

    def test_zhoda_mena(self):
        self.assertTrue(ids.zhoda_mena("Kosiba Ján", "Kosiba, Ján"))
        self.assertTrue(ids.zhoda_mena("Ján Kosiba", "Kosiba, Ján"))
        self.assertFalse(ids.zhoda_mena("Kosiba Ján", "Kosiba, Rudolf"))


if __name__ == "__main__":
    unittest.main()
