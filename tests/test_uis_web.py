"""Testy načítania zamestnancov z UIS. HTML má rovnakú štruktúru ako is.uniag.sk, mená sú vymyslené."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SPU_ZATAZ_DATA", tempfile.mkdtemp())

from spu_zataz import uis_web  # noqa: E402
from spu_zataz.db import Databaza  # noqa: E402
from spu_zataz.models import Ucitel  # noqa: E402


def _riadok(uid, meno, zar):
    return (f'<tr class=" uis-hl-table lbn" ><td class="odsazena" nowrap="1" align="left">'
            f'<a href="/lide/clovek.pl?id={uid}" target="_blank">{meno}</a></td>'
            f'<td class="odsazena" align="left">{zar}</td><td class="odsazena" nowrap="1" align="left">AC_0_1</td>'
            f'<td class="odsazena" align="left">+421&nbsp;37&nbsp;641&nbsp;0000</td>'
            f'<td class="odsazena" align="left"><a href="/posta/nova_zprava.pl?uzivatel={uid}">x [at] uniag.sk</a></td></tr>')


HLAVICKA = ('<table><thead><tr class="zahlavi"><th class="zahlavi" >Meno</th><th class="zahlavi" >Zaradenie</th>'
            '<th class="zahlavi" >Kancelária</th><th class="zahlavi" >Telefón</th><th class="zahlavi" >E-mail</th></tr></thead><tbody >')

ZAMESTNANCI_HTML = (
    "<html><body><big><b>Zamestnanci</b></big><p /><form method=\"post\">" + HLAVICKA
    + _riadok(101, "Testová Anna, prof. Ing., PhD.", "profesorka")
    + _riadok(102, "Vzorový Ján, Ing., PhD.", "odborný asistent")
    + _riadok(103, "Pokusný Peter, doc. Ing., CSc.", "docent")
    + _riadok(104, "Skúšková Eva", "administratíva")
    + _riadok(105, "Novák Kováč Juraj, doc. RNDr., PhD., MBA", "docent")
    + "</tbody></table></form><big><b>Externí pracovníci</b></big><form>" + HLAVICKA
    + _riadok(201, "Externý Karol, prof. Ing., DrSc.", "Externý spolupracovník")
    + "</tbody></table></form></body></html>")

FAKULTA_HTML = (
    '<ol><li class="breadcrumb-item"><a href="/" title="">x</a></li>'
    '<li class="breadcrumb-item"><a href="/pracoviste/pracoviste.pl" title="">Pracoviská</a></li>'
    '<li class="breadcrumb-item active" aria-current="page"><span >TF</span></li></ol>'
    '<a href="pracoviste.pl?id=30#53">DTF</a>|<a href="pracoviste.pl?id=30#220">UKST</a>'
    '<tr><td><a name="53"></a><b><font size="+1">Dekanát TF</font></b><br /></td></tr>'
    '<tr><td><a name="220"></a><b><font size="+1">Ústav konštruovania a&nbsp;strojárskych technológií</font></b></td></tr>')

USTAV_HTML = (
    '<ol><li class="breadcrumb-item"><a href="/pracoviste/pracoviste.pl" title="">Pracoviská</a></li>'
    '<li class="breadcrumb-item"><a href="/pracoviste/pracoviste.pl?id=30" title="">TF</a></li>'
    '<li class="breadcrumb-item active" aria-current="page"><span >UEAIF</span></li></ol>')

ROOT_HTML = ('<a name="30"></a><img src="/img/loga/spu/tf.png" alt="" /></td><td class="odsazena" valign="top">'
             '<b><font size="+1">Technická fakulta</font></b><br />Dekanát')


class TestParser(unittest.TestCase):
    def test_zamestnanci(self):
        z = uis_web.zamestnanci(ZAMESTNANCI_HTML)
        self.assertEqual(len(z), 6)
        a = z[0]
        self.assertEqual((a.uis_id, a.meno, a.titul_pred, a.titul_za, a.funkcia),
                         ("101", "Testová Anna", "prof. Ing.", "PhD.", "profesor"))
        self.assertEqual(z[1].funkcia, "odborný asistent")
        self.assertFalse(z[3].je_pedagog)
        self.assertEqual((z[4].meno, z[4].titul_pred, z[4].titul_za), ("Novák Kováč Juraj", "doc. RNDr.", "PhD., MBA"))
        self.assertTrue(z[5].externy)
        self.assertFalse(z[0].externy)

    def test_fakulta(self):
        prac = uis_web.podpracoviska(FAKULTA_HTML)
        self.assertEqual([(p.id, p.nazov) for p in prac],
                         [(53, "Dekanát TF"), (220, "Ústav konštruovania a strojárskych technológií")])
        self.assertEqual(uis_web.drobcekova_navigacia(FAKULTA_HTML)[-1], ("TF", None))
        self.assertEqual(uis_web.drobcekova_navigacia(USTAV_HTML)[-2], ("TF", 30))
        self.assertEqual([(p.id, p.nazov) for p in uis_web.podpracoviska(ROOT_HTML)], [(30, "Technická fakulta")])

    def test_id_z_odkazu(self):
        self.assertEqual(uis_web.id_z_odkazu(
            "is.uniag.sk/pracoviste/zamestnanci.pl?zpet=https://is.uniag.sk/pracoviste/pracoviste.pl?id=30;id=222"), 222)
        self.assertEqual(uis_web.id_z_odkazu("https://is.uniag.sk/pracoviste/zamestnanci.pl?id=221"), 221)
        self.assertEqual(uis_web.id_z_odkazu("220"), 220)


class TestZlucenie(unittest.TestCase):
    def test_zluc(self):
        db = Databaza(Path(tempfile.mkdtemp()) / "u.db")
        db.uloz(Ucitel(meno="Vzorový Ján", uvazok=0.5, ustav="Starý ústav", fakulta="TF"))
        db.uloz(Ucitel(osobne_cislo="999", meno="Odišiel Ignác", ustav="UEAIF", fakulta="TF"))
        z = [x for x in uis_web.zamestnanci(ZAMESTNANCI_HTML) if x.je_pedagog and not x.externy]
        res = uis_web.zluc_do_databazy(db, [(x, "TF", "UEAIF") for x in z])
        self.assertEqual(len(res.novi), 3)
        self.assertEqual(res.aktualizovani, ["Vzorový Ján"])
        self.assertEqual(len(res.presunuti), 1)
        self.assertEqual(res.chybajuci, ["Odišiel Ignác"])
        jan = db.najdi_ucitela("102")
        self.assertEqual((jan.uvazok, jan.ustav, jan.titul_pred), (0.5, "UEAIF", "Ing."))
        # opakované načítanie nevytvorí duplicity
        uis_web.zluc_do_databazy(db, [(x, "TF", "UEAIF") for x in z])
        self.assertEqual(len(db.nacitaj("ucitelia")), 5)


if __name__ == "__main__":
    unittest.main()


def _zp(zp, stav, typ, rok, ved_id, ved):
    return (f'<tr class=""><td class="odsazena">TF</td><td class="odsazena">{stav}</td><td class="odsazena">{typ}</td>'
            f'<td class="odsazena"><a href="/lide/clovek.pl?id=9{zp}">Bc. Študent {zp}</a></td>'
            f'<td class="odsazena">Názov práce {zp}</td><td class="odsazena">{rok}</td>'
            f'<td class="odsazena"><a href="/lide/clovek.pl?id={ved_id}">{ved}</a></td>'
            f'<td class="odsazena"><a href="../pracoviste/pracoviste.pl?id=221;nerozbaluj=1">UEAIF TF</a></td>'
            f'<td class="odsazena"></td><td class="odsazena"><a href="/zp/portal_zp.pl?zp={zp};zpet=;prehled=pracoviste">'
            f'<span>Vstup</span></a></td></tr>')


ZP_HTML = ('<table><tr><td><input type="checkbox" name="typ" value="1"> Bakalárska práca</td></tr></table>'
           '<table><thead><tr><th>Fak.</th><th>Stav</th><th>Typ</th><th>Autor</th><th>Názov práce</th><th>Rok</th>'
           '<th class="zahlavi" ><a href="/zp/portal_zp.pl?razeni=vedouci;prehled=pracoviste">Vedúci práce</a></th><th>Pracovisko</th><th>Odkladná lehota</th><th>Vstup</th></tr></thead><tbody>'
           + _zp(1, "obhájená", "BP", 2024, 101, "prof. Ing. Anna Testová, PhD.")
           + _zp(2, "obhájená", "DP", 2024, 101, "prof. Ing. Anna Testová, PhD.")
           + _zp(3, "obhájená", "DP", 2025, 101, "prof. Ing. Anna Testová, PhD.")
           + _zp(4, "nekompletné", "DP", 2025, 101, "prof. Ing. Anna Testová, PhD.")
           + _zp(5, "obhájená", "DizP", 2025, 555, "doc. Ing. Ján Vzorový, PhD.")
           + _zp(6, "obhájená", "BP", 2025, 777, "Ing. Cudzí Vedúci, PhD.")
           + "</tbody></table>")


class TestZaverecnePrace(unittest.TestCase):
    def test_parsovanie_a_priradenie(self):
        prace = uis_web.parsuj_zaverecne_prace(ZP_HTML)
        self.assertEqual(len(prace), 6)
        self.assertEqual((prace[0].ak_rok, prace[0].stupen, prace[0].veduci_id, prace[0].zp_id), ("2023/2024", "Bc", "101", "1"))
        self.assertEqual(uis_web.obdobie_zo_ak_roku("2023/2024"), 2024)
        db = Databaza(Path(tempfile.mkdtemp()) / "z.db")
        db.uloz(Ucitel(osobne_cislo="101", meno="Testová Anna"))
        db.uloz(Ucitel(meno="Vzorový Ján"))          # bez ID – nájde sa podľa mena
        pr, mimo = uis_web.prirad_ucitelom(prace, db.nacitaj("ucitelia"))
        self.assertEqual([(s.ak_rok, s.stupen, len(s.prace)) for s in pr if s.ucitel_id == 1],
                         [("2023/2024", "Bc", 1), ("2023/2024", "Ing", 1), ("2024/2025", "Ing", 1)])
        self.assertEqual([(s.stupen, len(s.prace)) for s in pr if s.ucitel_id == 2], [("PhD", 1)])
        self.assertEqual(mimo, {"Ing. Cudzí Vedúci, PhD.": 1})
        self.assertEqual(uis_web.uloz_zaverecne_prace(db, pr), 4)
        uis_web.uloz_zaverecne_prace(db, pr)       # opakovane bez duplicít
        self.assertEqual(len(db.nacitaj("zaverecne_prace")), 4)
