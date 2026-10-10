"""Podmienky hodnotenia: vyčítanie parametrov z dokumentu metodiky a ich použitie vo výpočte."""

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SPU_ZATAZ_DATA"] = tempfile.mkdtemp()

from spu_zataz import config, metodika  # noqa: E402
from spu_zataz.config import DEFAULT_PARAMETRE as P  # noqa: E402

# Skrátený vymyslený dodatok so zmenenými hodnotami (štruktúra ako text vyčítaný z PDF pokynu).
DODATOK_3 = """
METODICKÝ POKYN 1/2023
Konsolidované znenie v znení Dodatku č. 3
Do výpočtov na úrovni pracovníkov nevstupujú tí pedagógovia, ktorých prepočítaný stav úväzku je menší
ako 30 % v ktorejkoľvek oblasti.
• výkony na úrovni ústavov a pracovná záťaž učiteľov vo vzdelávacej činnosti
sledovaná v posledných troch ukončených akademických rokoch,
• výkony na úrovni ústavov a pracovná záťaž učiteľov v publikačnej činnosti
v posledných troch kalendárnych rokoch, za ktoré existovala časová uzávierka
• výkony na úrovni ústavov a pracovná záťaž učiteľov v projektovej činnosti
v 3 posledných kalendárnych rokoch zverejnených CVTI SR.
o priama výučba vyjadrená v hodinách za akademický rok (ako
dvojnásobok danej hodnoty zohľadňujúc prípravu na priamu výučbu)
o počet študentov na priamej výučbe na vysokoškolského učiteľa (0,3
hodiny/1 študent).
1 Referenčný počet priamej výučby na týždeň v hodinách: profesor 6, docent 8, odborný asistent 12, lektor 16 (UIS)
Tabuľka 1
Počet hodín / koeficient Stupeň štúdia
26 / 1 I. stupeň (Bc.)
39 / 1,5 II. stupeň (Ing.)
312 / 12 III. stupeň (PhD.)
Zdroj: Metodika rozpisu dotácií
Tabuľka 2
Koeficient Študijný odbor
1,5 biotechnológie, biológia, potravinárstvo,
strojárstvo
1,7 poľnohospodárstvo a krajinárstvo
1,1 ekonómia a manažment
Zdroj: Metodika rozpisu dotácií
a anglického jazyka, ktorá prebieha v anglickom jazyku, sa bonifikuje koeficientom
2,5, okrem ohodnotenia záverečných prác a počtu študentov.
Tabuľka 3
Skupiny a kategórie / Kvartil5 Bez Q Q1 Q2 Q3 Q4
V1: monografia 15 200 120 60 15
V1: editovaná kniha, kritická edícia, kritický preklad 5 60 40 20 5
V2/V3 indexované vo WoS/Scopus 42,5 510 340 170 42,5
V2/V3 ostatné 5 x
Zdroj: Metodika rozpisu dotácií
Zodpovedný riešiteľ výskumného projektu je bonifikovaný dvojnásobkom hodín alokovaných na projekte.
vzdelávacia činnosť 50 %
publikačná činnosť 30 %
projektová činnosť 20 %
1.2 Vypočítaná hodinová záťaž by nemala predstavovať viac ako 100 % ročného
pracovného času učiteľa (pri plnom úväzku sa počíta s 1600 h/1 rok), pričom v ideálnom stave
by sa zaťaženie vzdelávacou činnosťou malo pohybovať v intervale <35 %, 60 %>.
1.3 V prípade, že záťaž vzdelávacou činnosťou dosahuje 75 % celkového úväzku
s účinnosťou od 30.03. 2023.
s účinnosťou od 1.9.2026.
"""


class TestExtrakcia(unittest.TestCase):
    def test_dodatok_zmeny(self):
        n = metodika.extrahuj_parametre(DODATOK_3)
        zmeny = {z.kluc: (z.stara, z.nova) for z in metodika.porovnaj(P, n)}
        self.assertEqual(zmeny, {
            "min_uvazok": (0.25, 0.30),
            "pocet_akad_rokov": (2, 3),
            "hodiny_na_studenta": (0.25, 0.3),
            "referencna_vyucba_tyzden|lektor": (18, 16.0),
            "hodiny_zaverecna_praca|Ing": (26.0, 39.0),
            "koef_odbor|poľnohospodárstvo a krajinárstvo": (1.6, 1.7),
            "koef_odbor|ekonómia a manažment": (1.0, 1.1),
            "koef_anglictina": (3.0, 2.5),
            "body_publikacie|V1: monografia|Q1": (180, 200.0),
            "vahy|vzdelavanie": (0.4, 0.5),
            "vahy|publikacie": (0.4, 0.3),
            "fond_hodin_rok": (1537.5, 1600.0),
            "ideal_od": (40.0, 35.0),
            "hranica_posudenia": (80.0, 75.0),
        })
        self.assertEqual(metodika.nenajdene(n), [])
        self.assertEqual(metodika.ucinnost(DODATOK_3), "1.9.2026")
        self.assertEqual(metodika.nazov_dokumentu(DODATOK_3), "Metodický pokyn 1/2023 v znení Dodatku č. 3")

    def test_pouzitie_vo_vypocte(self):
        nove = metodika.pouzi(P, metodika.extrahuj_parametre(DODATOK_3))
        self.assertEqual(nove["fond_hodin_rok"], 1600)
        self.assertEqual(nove["vahy_ucitelia"]["vzdelavanie"], 0.5)
        self.assertEqual(nove["koef_odbor"]["biológia"], 1.5)
        self.assertIsNone(nove["body_publikacie"]["V2/V3 ostatné"]["Q1"])
        from spu_zataz import calc
        from spu_zataz.models import Publikacia
        self.assertEqual(calc.body_publikacie(Publikacia(kategoria=config.KATEGORIE_PUBLIKACII[0], kvartil="Q1"), nove), 200)

    def test_docx_a_ulozenie(self):
        tmp = Path(tempfile.mkdtemp())
        docx = tmp / "dodatok3.docx"
        body = "".join(f"<w:p><w:r><w:t>{r.replace('<', '&lt;').replace('>', '&gt;')}</w:t></w:r></w:p>"
                       for r in DODATOK_3.splitlines())
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
        doc, _ = metodika.pridaj_dokument(docx)
        self.assertTrue((metodika.priecinok() / doc.subor).exists())
        self.assertEqual(doc.ucinnost, "1.9.2026")
        metodika.aktivuj(doc.subor)
        self.assertEqual(metodika.aktivny().subor, doc.subor)
        self.assertIn("Dodatku č. 3", metodika.popis_aktivnej_metodiky())

    @unittest.skipUnless(os.environ.get("SPU_MP_PDF"), "cesta k PDF pokynu v premennej SPU_MP_PDF")
    def test_skutocny_pokyn(self):
        n = metodika.extrahuj_parametre(metodika.nacitaj_text(os.environ["SPU_MP_PDF"]))
        self.assertEqual(metodika.nenajdene(n), [])
        self.assertEqual(metodika.porovnaj(P, n), [])


if __name__ == "__main__":
    unittest.main()
