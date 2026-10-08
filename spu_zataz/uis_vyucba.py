"""Prepočet priamej výučby z rozvrhov UIS podľa čl. 3 a čl. 7 ods. 1.1 metodického pokynu.

Vstup je súbor JSON z exportéra (tools/uis_export.js – záložka v prehliadači, spúšťa ju prihlásený
používateľ UIS). Obsahuje rozvrhové akcie fakulty po semestroch a počty študentov predmetov.

Pravidlá (zdokumentované aj v README – časť „Výklad“):
  * hodiny akcie = trvanie (Od–Do v hodinách) × počet týždňov semestra (týždenná akcia, max. 13),
    pri poznámke „párny/nepárny týždeň“ × 0,5; akcia s dátumom (bloková výučba) sa započíta raz,
  * pri viacerých vyučujúcich (poznámka „Ďalej vyučujú“) sa hodiny akcie delia rovným dielom,
  * študenti predmetu (Úspešnosť študentov v predmetoch) sa rozdelia medzi skupiny prednášok a medzi
    skupiny cvičení podľa kapacity skupín; učiteľ má „odučených študentov“ = väčšia z hodnôt
    (študenti jeho prednášok, študenti jeho cvičení) – ten istý študent sa v predmete neráta dvakrát,
  * jazyk: poznámka „Výučba v AJ“ → EN, mobilitní študenti (obmedzenie „mob“, poznámka erasmus) → MOB,
  * študentohodiny ústavu = Σ hodiny akcie × študenti skupiny (delené medzi vyučujúcich).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .uis_web import kluc_mena

ZNACKA = " [UIS rozvrh]"


class VyucbaChyba(Exception):
    pass


def nacitaj_subor(path: str | Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise VyucbaChyba(f"Súbor sa nepodarilo načítať: {e}") from e
    if d.get("format") != "spu-zataz-uis-vyucba":
        raise VyucbaChyba("Súbor nie je export výučby z UIS (vytvorte ho záložkou „SPU záťaž – export z UIS“).")
    return d


def trvanie_hodin(od: str, do: str) -> float:
    def h(t):
        m = re.match(r"(\d{1,2}):(\d{2})", t or "")
        return int(m.group(1)) + int(m.group(2)) / 60 if m else None
    a, b = h(od), h(do)
    return max(b - a, 0.0) if a is not None and b is not None else 0.0


def je_datovana(den: str) -> bool:
    return bool(re.search(r"\d{1,2}\.\s?\d{1,2}\.\s?\d{4}", den or ""))


def jazyk_akcie(akcia: dict) -> str:
    pozn = " ".join(akcia.get("poznamky", []))
    if re.search(r"\bv\s*AJ\b|anglick|english|\bEN\b", pozn, re.I):
        return "EN"
    if re.search(r"\bmob", akcia.get("obmedzenie", ""), re.I) or re.search(r"eras|eraz|mobilit", pozn, re.I):
        return "MOB"
    return "SK"


def _tyzdne(rozvrh: dict, max_tyzdnov: int) -> int:
    from datetime import datetime
    try:
        z = datetime.strptime(rozvrh.get("zaciatok", ""), "%d.%m.%Y")
        k = datetime.strptime(rozvrh.get("koniec", ""), "%d.%m.%Y")
        return max(1, min(max_tyzdnov, round(((k - z).days + 1) / 7)))
    except ValueError:
        return max_tyzdnov


@dataclass
class RiadokVyucby:
    """Výučba jedného učiteľa v jednom predmete, semestri a jazyku."""
    uis_id: str
    meno: str
    ak_rok: str
    semester: str
    predmet_id: str
    predmet: str
    kod: str
    jazyk: str
    hodiny: float = 0.0
    studenti: float = 0.0
    studentohodiny: float = 0.0
    bez_studentov: bool = False        # predmet nemá počet študentov v UIS (napr. doktorandský)
    _pred: float = 0.0                 # študenti prednášok
    _cvic: float = 0.0                 # študenti cvičení
    _skupiny: set = field(default_factory=set)


@dataclass
class Prepocet:
    riadky: list[RiadokVyucby] = field(default_factory=list)
    upozornenia: list[str] = field(default_factory=list)


def prepocitaj(data: dict, tyzdne_semestra: int = 13) -> Prepocet:
    predmety = data.get("predmety", {})
    out = Prepocet()
    # akcie po predmetoch (inštancia predmetu = jeden semester)
    akcie_predmetu: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for rz in data.get("rozvrhy", []):
        for a in rz.get("akcie", []):
            if not a.get("akcia") or not a.get("predmet_id") or not a.get("ucitelia"):
                continue                                   # bloková rezervácia bez typu výučby
            akcie_predmetu[a["predmet_id"]].append((rz, a))

    riadky: dict[tuple, RiadokVyucby] = {}
    bez_poctu = set()
    for pid, zoznam in akcie_predmetu.items():
        info = predmety.get(pid)
        N = float(info["studentov"]) if info else 0.0
        if not info:
            bez_poctu.add(zoznam[0][1]["predmet"])
        # skupiny = rovnaký typ, obmedzenie, kapacita a forma (opakované dátumy tej istej skupiny sa zlúčia)
        skupiny: dict[tuple, int] = {}
        for rz, a in zoznam:
            typ = "P" if a["akcia"].lower().startswith("predn") else "C"
            skupiny.setdefault((typ, a.get("obmedzenie", ""), a.get("kapacita", 0), rz.get("forma", "")), a.get("kapacita", 0))
        sucet = defaultdict(float)
        pocet = defaultdict(int)
        for (typ, *_), kap in skupiny.items():
            sucet[typ] += kap
            pocet[typ] += 1

        def studenti_skupiny(kluc):
            typ, kap = kluc[0], skupiny[kluc]
            if sucet[typ] > 0:
                return N * kap / sucet[typ]
            return N / pocet[typ] if pocet[typ] else 0.0

        for rz, a in zoznam:
            typ = "P" if a["akcia"].lower().startswith("predn") else "C"
            kluc = (typ, a.get("obmedzenie", ""), a.get("kapacita", 0), rz.get("forma", ""))
            dur = trvanie_hodin(a.get("od"), a.get("do"))
            if je_datovana(a.get("den", "")):
                hod = dur
            else:
                hod = dur * _tyzdne(rz, tyzdne_semestra)
                if any(re.search(r"(ne)?párny týždeň", p, re.I) for p in a.get("poznamky", [])):
                    hod *= 0.5
            stud = studenti_skupiny(kluc)
            ucitelia = list(dict.fromkeys(tuple(u) for u in a["ucitelia"]))
            k = len(ucitelia)
            jaz = jazyk_akcie(a)
            for uid, meno in ucitelia:
                r = riadky.get((uid, pid, jaz))
                if r is None:
                    r = RiadokVyucby(uis_id=uid, meno=meno, ak_rok=rz.get("ak_rok", ""), semester=rz.get("semester", ""),
                                     predmet_id=pid, predmet=a["predmet"], kod=info["kod"] if info else "", jazyk=jaz,
                                     bez_studentov=not info)
                    riadky[(uid, pid, jaz)] = r
                r.hodiny += hod / k
                r.studentohodiny += hod * stud / k
                if kluc not in r._skupiny:                 # skupina sa ráta raz, aj keď má viac termínov
                    r._skupiny.add(kluc)
                    if typ == "P":
                        r._pred += stud / k
                    else:
                        r._cvic += stud / k
    for r in riadky.values():
        r.studenti = max(r._pred, r._cvic)
    out.riadky = sorted(riadky.values(), key=lambda r: (r.meno, r.ak_rok, r.semester, r.predmet))
    if bez_poctu:
        out.upozornenia.append(f"Predmety bez počtu študentov v UIS (najmä doktorandské) – započítajú sa iba hodiny: "
                               f"{len(bez_poctu)} (napr. {', '.join(sorted(bez_poctu)[:5])}).")
    return out


# ------------------------------------------------------------------ uloženie

@dataclass
class VysledokUlozenia:
    riadkov: int = 0
    ucitelia: set = field(default_factory=set)
    mimo_db: dict = field(default_factory=dict)     # meno -> hodiny
    ak_roky: set = field(default_factory=set)

    def sprava(self) -> str:
        t = (f"Uložených {self.riadkov} záznamov výučby pre {len(self.ucitelia)} učiteľov "
             f"(akademické roky {', '.join(sorted(self.ak_roky))}). Výučba načítaná z UIS skôr pre tieto roky "
             f"bola nahradená, ručne zadané záznamy zostali.")
        if self.mimo_db:
            naj = sorted(self.mimo_db.items(), key=lambda x: -x[1])[:10]
            t += ("\n\nVyučujúci, ktorí nie sú v databáze učiteľov (ich výučba sa neuložila): "
                  + ", ".join(f"{m} ({h:.0f} h)" for m, h in naj) + (" …" if len(self.mimo_db) > 10 else ""))
        return t


def najdi_ucitela(ucitelia, uis_id: str, meno: str):
    for u in ucitelia:
        if u.osobne_cislo and u.osobne_cislo == uis_id:
            return u
    # „J. Kosiba“ → priezvisko + začiatočné písmeno mena
    casti = meno.replace(".", ". ").split()
    if len(casti) >= 2:
        priezvisko = kluc_mena(casti[-1])
        inic = kluc_mena(casti[0])[:1]
        kand = [u for u in ucitelia if priezvisko in kluc_mena(u.meno).split()
                and any(w.startswith(inic) for w in kluc_mena(u.meno).split() if w != priezvisko)]
        if len(kand) == 1:
            return kand[0]
    return None


def uloz(db, prepocet: Prepocet, odbor_predmetu: dict[str, str], vybrane: Optional[set] = None) -> VysledokUlozenia:
    """Uloží riadky do tabuľky výučby. odbor_predmetu: predmet_id -> študijný odbor (tab. 2)."""
    from .models import Vyucba
    ucitelia = db.nacitaj("ucitelia")
    res = VysledokUlozenia()
    na_ulozenie = []
    for r in prepocet.riadky:
        if vybrane is not None and r.predmet_id not in vybrane:
            continue
        u = najdi_ucitela(ucitelia, r.uis_id, r.meno)
        if u is None:
            res.mimo_db[r.meno] = res.mimo_db.get(r.meno, 0) + r.hodiny
            continue
        na_ulozenie.append((u, r))
        res.ak_roky.add(r.ak_rok)
    for ak in res.ak_roky:
        db.conn.execute("DELETE FROM vyucba WHERE ak_rok = ? AND predmet LIKE ?", (ak, f"%{ZNACKA}%"))
    for u, r in na_ulozenie:
        nazov = f"{r.kod + ' ' if r.kod else ''}{r.predmet} ({r.semester}){ZNACKA}"
        db.uloz(Vyucba(ucitel_id=u.id, ak_rok=r.ak_rok, predmet=nazov, jazyk=r.jazyk,
                       odbor=odbor_predmetu.get(r.predmet_id, ""), hodiny=round(r.hodiny, 2),
                       pocet_studentov=round(r.studenti, 2), studentohodiny=round(r.studentohodiny, 2)), commit=False)
        res.riadkov += 1
        res.ucitelia.add(u.id)
    db.commit()
    return res


# ------------------------------------------------------------------ záložka (bookmarklet) pre prehliadač

def _zdroj_exportera() -> str:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for p in (Path(__file__).resolve().parent / "uis_export.js", base / "spu_zataz" / "uis_export.js"):
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise VyucbaChyba("Chýba súbor uis_export.js")


def bookmarklet() -> str:
    """URL záložky „javascript:…“, ktorá spustí export v prihlásenej relácii UIS."""
    import urllib.parse
    zdroj = _zdroj_exportera()
    zdroj = re.sub(r"/\*[\s\S]*?\*/", "", zdroj)                    # blokové komentáre
    riadky = [r for r in zdroj.splitlines() if not r.strip().startswith("//")]
    kod = "\n".join(r.rstrip() for r in riadky if r.strip())
    return "javascript:" + urllib.parse.quote("(async()=>{" + kod + "\nawait spuExportSpusti();})();", safe="")


def stranka_so_zalozkou(path: Path) -> Path:
    """Vytvorí HTML stránku, z ktorej sa záložka pretiahne na lištu záložiek."""
    import html
    url = bookmarklet()
    path.write_text(f"""<!doctype html><html lang="sk"><head><meta charset="utf-8">
<title>SPU záťaž – záložka pre export z UIS</title>
<style>body{{font:16px/1.5 Segoe UI,Arial,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#222}}
a.btn{{display:inline-block;background:#1E4620;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:bold}}
ol li{{margin:6px 0}} textarea{{width:100%;height:90px;font:12px monospace}} .tip{{color:#555;font-size:14px}}</style></head><body>
<h2>Export výučby z UIS pre program „Hodnotenie pracovnej záťaže“</h2>
<p><a class="btn" href="{html.escape(url, quote=True)}">SPU záťaž – export z UIS</a></p>
<ol>
<li>Zobrazte lištu záložiek (Ctrl+Shift+B) a <b>pretiahnite zelené tlačidlo</b> myšou na lištu záložiek.</li>
<li>Prihláste sa do UIS (is.uniag.sk) – stačí byť na ľubovoľnej stránke UIS po prihlásení.</li>
<li>Kliknite na záložku <b>SPU záťaž – export z UIS</b>, zadajte fakultu (napr. TF) a akademické roky.</li>
<li>Po asi pol minúte sa stiahne súbor <i>uis_vyucba_….json</i>. V programe ho načítate cez
<b>Súbor → Načítať výučbu z UIS</b>.</li></ol>
<p class="tip">Záložka v UIS iba číta rozvrhy fakulty a počty študentov predmetov (Úspešnosť študentov v predmetoch),
nič nemení a nikam neodosiela – súbor sa uloží len do vášho počítača. Funguje s oprávneniami, ktoré máte v UIS.</p>
<p class="tip">Ak sa tlačidlo nedá pretiahnuť: vytvorte novú záložku (Ctrl+D → Upraviť), ako názov zadajte
„SPU záťaž – export z UIS“ a do poľa URL vložte text nižšie.</p>
<textarea readonly onclick="this.select()">{html.escape(url)}</textarea>
</body></html>""", encoding="utf-8")
    return path
