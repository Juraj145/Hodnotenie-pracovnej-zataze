"""Hlavné okno programu."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import calc, config, importy, updater, vystupy
from .db import Databaza
from .gui_common import ZELENA, Formular, Tabulka, fmt
from .models import (Projekt, ProjektUcast, Publikacia, Ucitel, Vyucba,
                     ZaverecnaPraca)
from .version import __version__

FARBY_STATUSU = {
    "ideal": "#C6EFCE", "pod": "#DDEBF7", "nad": "#FFF2CC", "posudenie": "#FCE4D6",
    "pretazenie": "#FFC7CE", "nezahrnuty": "#EDEDED",
}


def tag_statusu(status: str) -> str:
    if status.startswith("Ideál"):
        return "ideal"
    if status.startswith("Pod"):
        return "pod"
    if status.startswith("Nad"):
        return "nad"
    if status.startswith("Nutné"):
        return "posudenie"
    if status.startswith("Preť"):
        return "pretazenie"
    return "nezahrnuty"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.db = Databaza()
        self.params = config.load_parametre()
        self.nastavenia = config.load_nastavenia()
        self.data = self.db.nacitaj_vsetko()
        self.obdobie = calc.navrhni_obdobie(self.data, self.params)
        self.vysl_ucitelia: list[calc.VysledokUcitela] = []
        self.vysl_ustavy: calc.VysledokUstavov | None = None

        root.title(f"Hodnotenie pracovnej záťaže VŠ učiteľov – SPU v Nitre  (v{__version__})")
        root.geometry("1360x820")
        root.minsize(1000, 600)
        self._styl()
        self._menu()

        hlavicka = tk.Frame(root, bg=ZELENA)
        hlavicka.pack(fill="x")
        tk.Label(hlavicka, text="Rozvrhnutie pracovnej záťaže vysokoškolských učiteľov",
                 bg=ZELENA, fg="white", font=("Segoe UI", 14, "bold")).pack(side="left", padx=14, pady=8)
        tk.Label(hlavicka, text="Metodický pokyn 1/2023 v znení Dodatku č. 2",
                 bg=ZELENA, fg="#CFE3C4", font=("Segoe UI", 10)).pack(side="left", pady=8)

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._tab_udaje()
        self._tab_vysledky_ucitelia()
        self._tab_vysledky_ustavy()

        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, anchor="w", padding=(10, 3)).pack(fill="x", side="bottom")

        self.obnov_vsetko()
        if self.nastavenia.get("kontrolovat_aktualizacie", True):
            root.after(1500, lambda: self.kontrola_aktualizacii(tichy=True))

    # ================================================================ vzhľad a menu
    def _styl(self):
        s = ttk.Style(self.root)
        if "vista" in s.theme_names():
            s.theme_use("vista")
        elif "clam" in s.theme_names():
            s.theme_use("clam")
        s.configure("Treeview", rowheight=24)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        s.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))
        s.configure("TNotebook.Tab", padding=(14, 5))

    def _menu(self):
        m = tk.Menu(self.root)
        subor = tk.Menu(m, tearoff=0)
        subor.add_command(label="Vytvoriť prázdnu Excel šablónu…", command=self.sablona)
        subor.add_command(label="Importovať vyplnenú šablónu…", command=self.import_sablony)
        subor.add_command(label="Načítať učiteľov a ústavy z UIS (is.uniag.sk)…", command=self.import_uis_zamestnanci)
        subor.add_command(label="Načítať výučbu z UIS (rozvrhy a počty študentov)…", command=self.import_uis_vyucba)
        subor.add_command(label="Načítať záverečné práce z UIS (is.uniag.sk/zp)…", command=self.import_uis_zp)
        subor.add_command(label="Načítať projekty z UIS (is.uniag.sk/vv)…", command=self.import_uis_projekty)
        subor.add_command(label="Importovať export z UIS / CREPČ / iný súbor…", command=self.import_mapovanie)
        subor.add_command(label="Načítať publikácie zo Scopus / Web of Science…", command=self.import_biblio)
        subor.add_separator()
        subor.add_command(label="Exportovať všetky údaje (záloha / zdieľanie)…", command=self.export_udajov)
        subor.add_command(label="Exportovať výsledky do Excelu…", command=self.export_vysledkov)
        subor.add_separator()
        subor.add_command(label="Načítať ukážkové údaje", command=self.ukazka)
        subor.add_command(label="Vymazať všetky údaje…", command=self.vymazat_db)
        subor.add_separator()
        subor.add_command(label="Koniec", command=self.root.destroy)
        m.add_cascade(label="Súbor", menu=subor)

        nast = tk.Menu(m, tearoff=0)
        nast.add_command(label="Parametre metodiky…", command=self.dialog_parametre)
        nast.add_command(label="API kľúče (Scopus, WoS)…", command=self.dialog_api)
        nast.add_command(label="Otvoriť priečinok s dátami", command=self.otvor_priecinok)
        self.var_auto_upd = tk.BooleanVar(value=self.nastavenia.get("kontrolovat_aktualizacie", True))
        nast.add_checkbutton(label="Kontrolovať aktualizácie pri spustení", variable=self.var_auto_upd,
                             command=self._uloz_auto_upd)
        m.add_cascade(label="Nastavenia", menu=nast)

        pomoc = tk.Menu(m, tearoff=0)
        pomoc.add_command(label="Skontrolovať aktualizácie", command=lambda: self.kontrola_aktualizacii(tichy=False))
        pomoc.add_command(label="Stránka projektu na GitHube", command=lambda: webbrowser.open(updater.RELEASES_URL))
        pomoc.add_command(label="O programe", command=self.o_programe)
        m.add_cascade(label="Pomoc", menu=pomoc)
        self.root.config(menu=m)

    # ================================================================ záložka Údaje
    def _tab_udaje(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="  Vstupné údaje  ")
        self.nb_udaje = ttk.Notebook(tab)
        self.nb_udaje.pack(fill="both", expand=True)
        self.tabulky: dict[str, Tabulka] = {}
        self.filtre: dict[str, tk.StringVar] = {}
        for kluc, nazov, stlpce in (
            ("ucitelia", "Učitelia", [("oc", "Os. číslo", 70), ("meno", "Meno", 230), ("fak", "Fakulta", 70),
                                      ("ust", "Ústav", 220), ("fun", "Funkcia", 120), ("uv", "Úväzok", 70),
                                      ("akt", "Podiel obdobia", 90), ("ids", "Scopus / WoS / ORCID", 220)]),
            ("vyucba", "Výučba", [("uc", "Učiteľ", 220), ("ak", "Ak. rok", 90), ("pr", "Predmet", 200),
                                  ("ja", "Jazyk", 60), ("od", "Odbor", 180), ("h", "Hodiny/rok", 90),
                                  ("st", "Študenti", 80)]),
            ("zaverecne_prace", "Záverečné práce", [("uc", "Učiteľ", 240), ("ak", "Ak. rok", 90),
                                                     ("stu", "Stupeň", 70), ("po", "Počet", 70), ("na", "Názov", 300)]),
            ("publikacie", "Publikácie", [("uc", "Učiteľ", 200), ("rok", "Rok", 60), ("kat", "Kategória", 260),
                                          ("kv", "Kvartil", 60), ("pod", "Podiel", 60), ("body", "Body", 70),
                                          ("na", "Názov", 260), ("zd", "Zdroj", 70)]),
            ("projekty", "Projekty", [("kod", "Kód", 120), ("rok", "Rok", 60), ("typ", "Typ", 150),
                                      ("na", "Názov", 240), ("suma", "Suma SPU (€)", 100), ("kap", "Kapacita (h)", 80),
                                      ("uc", "Riešitelia v DB / UIS", 120), ("ries", "Riešitelia (★ zodpovedný)", 360)]),
            ("ucasti", "Účasť na projektoch", [("pr", "Projekt", 160), ("rok", "Rok", 60), ("uc", "Učiteľ", 240),
                                               ("h", "Hodiny", 80), ("zod", "Zodpovedný riešiteľ", 120)]),
        ):
            f = ttk.Frame(self.nb_udaje, padding=6)
            self.nb_udaje.add(f, text=f"  {nazov}  ")
            bar = ttk.Frame(f)
            bar.pack(fill="x", pady=(0, 6))
            ttk.Button(bar, text="➕ Pridať", command=lambda k=kluc: self.pridat(k)).pack(side="left")
            ttk.Button(bar, text="✏️ Upraviť", command=lambda k=kluc: self.upravit(k)).pack(side="left", padx=4)
            ttk.Button(bar, text="🗑 Vymazať", command=lambda k=kluc: self.vymazat(k)).pack(side="left")
            ttk.Label(bar, text="   Hľadať:").pack(side="left")
            var = tk.StringVar()
            var.trace_add("write", lambda *_, k=kluc: self.obnov_tabulku(k))
            ttk.Entry(bar, textvariable=var, width=30).pack(side="left", padx=4)
            self.filtre[kluc] = var
            t = Tabulka(f, stlpce, on_double=lambda k=kluc: self.upravit(k))
            t.pack(fill="both", expand=True)
            self.tabulky[kluc] = t

        rychly = ttk.Frame(tab)
        rychly.pack(fill="x", pady=(6, 0))
        ttk.Button(rychly, text="📄 Prázdna Excel šablóna", command=self.sablona).pack(side="left")
        ttk.Button(rychly, text="📁 Import šablóny", command=self.import_sablony).pack(side="left", padx=4)
        ttk.Button(rychly, text="👥 Učitelia z UIS", command=self.import_uis_zamestnanci).pack(side="left")
        ttk.Button(rychly, text="📅 Výučba z UIS", command=self.import_uis_vyucba).pack(side="left", padx=(4, 0))
        ttk.Button(rychly, text="🎓 Záverečné práce z UIS", command=self.import_uis_zp).pack(side="left", padx=(4, 0))
        ttk.Button(rychly, text="🔬 Projekty z UIS", command=self.import_uis_projekty).pack(side="left", padx=(4, 0))
        ttk.Button(rychly, text="🔀 Import z UIS / CREPČ", command=self.import_mapovanie).pack(side="left", padx=4)
        ttk.Button(rychly, text="🌐 Scopus / WoS", command=self.import_biblio).pack(side="left", padx=4)
        ttk.Button(rychly, text="▶ Vypočítať", style="Accent.TButton",
                   command=lambda: (self.prepocitaj(), self.nb.select(1))).pack(side="right")

    def _ctx(self):
        return ({u.id: u for u in self.data.ucitelia}, {p.id: p for p in self.data.projekty})

    def obnov_tabulku(self, kluc: str):
        ucitelia, projekty = self._ctx()
        hladat = self.filtre[kluc].get().strip().lower()
        meno = lambda uid: ucitelia[uid].cele_meno if uid in ucitelia else "?"  # noqa: E731
        riadky = []
        if kluc == "ucitelia":
            for u in self.data.ucitelia:
                ids = " / ".join(x for x in (u.scopus_id, u.wos_id, u.orcid) if x)
                tag = ("nezahrnuty",) if (u.uvazok or 0) < self.params["min_uvazok"] else ()
                riadky.append((u.id, [u.osobne_cislo, u.cele_meno, u.fakulta, u.ustav, u.funkcia, fmt(u.uvazok, 2),
                                      fmt(u.podiel_aktivny, 2), ids], tag))
        elif kluc == "vyucba":
            for v in self.data.vyucba:
                riadky.append((v.id, [meno(v.ucitel_id), v.ak_rok, v.predmet, v.jazyk, v.odbor, fmt(v.hodiny),
                                      fmt(v.pocet_studentov, 0)], ()))
        elif kluc == "zaverecne_prace":
            for z in self.data.zaverecne_prace:
                riadky.append((z.id, [meno(z.ucitel_id), z.ak_rok, z.stupen, fmt(z.pocet, 0), z.nazov], ()))
        elif kluc == "publikacie":
            for p in self.data.publikacie:
                try:
                    body = calc.body_publikacie(p, self.params)
                except ValueError:
                    body = None
                riadky.append((p.id, [meno(p.ucitel_id), p.rok, p.kategoria, p.kvartil, fmt(p.podiel, 2), fmt(body),
                                      p.nazov, p.zdroj], ()))
        elif kluc == "projekty":
            mena: dict[int, list[str]] = {}
            for uc in self.data.ucasti:
                u = ucitelia.get(uc.ucitel_id)
                if u:
                    mena.setdefault(uc.projekt_id, []).append(("★ " if uc.zodpovedny else "") + u.meno)
            for p in self.data.projekty:
                m = sorted(mena.get(p.id, []), key=lambda x: (not x.startswith("★"), x))
                pocet = f"{len(m)} / {p.pocet_riesitelov}" if p.pocet_riesitelov else str(len(m))
                riadky.append((p.id, [p.kod, p.rok, p.typ, p.nazov, fmt(p.suma, 2),
                                      fmt(p.kapacita_hodin, 0) if p.kapacita_hodin else "súčet", pocet,
                                      ", ".join(m)], ()))
        elif kluc == "ucasti":
            for uc in self.data.ucasti:
                p = projekty.get(uc.projekt_id)
                riadky.append((uc.id, [p.kod if p else "?", p.rok if p else "", meno(uc.ucitel_id), fmt(uc.hodiny),
                                       "áno" if uc.zodpovedny else ""], ()))
        if hladat:
            riadky = [r for r in riadky if hladat in " ".join(map(str, r[1])).lower()]
        t = self.tabulky[kluc]
        t.tree.tag_configure("nezahrnuty", foreground="#888")
        t.nastav(riadky)

    def _polia(self, kluc: str) -> list[tuple]:
        ucitelia = sorted(((u.id, f"{u.cele_meno}  [{u.osobne_cislo or '–'}]  {u.ustav}") for u in self.data.ucitelia),
                          key=lambda x: x[1].lower())
        ak_roky = sorted({v.ak_rok for v in self.data.vyucba} | {z.ak_rok for z in self.data.zaverecne_prace}
                         | set(self.obdobie.ak_roky))
        if kluc == "ucitelia":
            return [("osobne_cislo", "Osobné číslo", "text", None), ("titul_pred", "Titul pred menom", "text", None),
                    ("meno", "Meno a priezvisko *", "text", None), ("titul_za", "Titul za menom", "text", None),
                    ("fakulta", "Fakulta", "combo", sorted({u.fakulta for u in self.data.ucitelia if u.fakulta})),
                    ("ustav", "Ústav", "combo", sorted({u.ustav for u in self.data.ucitelia if u.ustav})),
                    ("funkcia", "Funkcia", "combo", config.FUNKCIE),
                    ("uvazok", "Prepočítaný úväzok (0–1)", "float", None),
                    ("podiel_aktivny", "Podiel obdobia v prac. pomere (0–1)", "float", None),
                    ("scopus_id", "Scopus Author ID", "text", None), ("wos_id", "WoS ResearcherID", "text", None),
                    ("orcid", "ORCID", "text", None)]
        if kluc == "vyucba":
            return [("ucitel_id", "Učiteľ *", "combo_strict", ucitelia), ("ak_rok", "Akademický rok *", "combo", ak_roky),
                    ("predmet", "Predmet", "text", None),
                    ("jazyk", "Jazyk", "combo_strict", list(config.JAZYKY_VYUCBY.items())),
                    ("odbor", "Študijný odbor (tab. 2)", "combo", list(self.params["koef_odbor"])),
                    ("hodiny", "Hodiny priamej výučby za ak. rok", "float", None),
                    ("pocet_studentov", "Počet študentov", "float", None)]
        if kluc == "zaverecne_prace":
            return [("ucitel_id", "Vedúci / školiteľ *", "combo_strict", ucitelia),
                    ("ak_rok", "Akademický rok *", "combo", ak_roky),
                    ("stupen", "Stupeň", "combo_strict", config.STUPNE_STUDIA),
                    ("pocet", "Počet úspešných študentov", "float", None), ("nazov", "Názov / poznámka", "text", None)]
        if kluc == "publikacie":
            return [("ucitel_id", "Autor (učiteľ) *", "combo_strict", ucitelia), ("rok", "Rok *", "int", None),
                    ("kategoria", "Kategória (tab. 3)", "combo_strict", config.KATEGORIE_PUBLIKACII),
                    ("kvartil", "Kvartil", "combo_strict", config.KVARTILY),
                    ("podiel", "Podiel autora (0–1)", "float", None), ("nazov", "Názov", "text", None),
                    ("zdroj", "Zdroj", "combo", ["ručne", "CREPČ", "Scopus", "WoS", "UIS"]),
                    ("identifikator", "DOI / EID / UT", "text", None)]
        if kluc == "projekty":
            return [("kod", "Kód projektu *", "text", None), ("nazov", "Názov", "text", None),
                    ("typ", "Typ", "combo", config.TYPY_PROJEKTOV), ("rok", "Kalendárny rok *", "int", None),
                    ("suma", "Suma pripísaná SPU v roku (€)", "float", None),
                    ("kapacita_hodin", "Celková riešiteľská kapacita (h, 0 = súčet)", "float", None),
                    ("pocet_riesitelov", "Počet riešiteľov v UIS (pre odhad bez hodín)", "int", None)]
        if kluc == "ucasti":
            projekty = sorted(((p.id, f"{p.kod} ({p.rok}) – {p.typ}") for p in self.data.projekty), key=lambda x: x[1])
            return [("projekt_id", "Projekt a rok *", "combo_strict", projekty),
                    ("ucitel_id", "Učiteľ *", "combo_strict", ucitelia),
                    ("hodiny", "Vykázané hodiny za rok", "float", None),
                    ("zodpovedny", "Zodpovedný riešiteľ", "bool", None)]
        raise KeyError(kluc)

    _TRIEDY = {"ucitelia": Ucitel, "vyucba": Vyucba, "zaverecne_prace": ZaverecnaPraca, "publikacie": Publikacia,
               "projekty": Projekt, "ucasti": ProjektUcast}

    def _validuj(self, kluc: str, h: dict) -> str | None:
        if kluc == "ucitelia" and not h["meno"].strip():
            return "Meno je povinné."
        if kluc == "ucitelia" and not (0 <= h["uvazok"] <= 1.5 and 0 <= h["podiel_aktivny"] <= 1):
            return "Úväzok a podiel obdobia zadajte v rozsahu 0–1."
        if "ucitel_id" in h and not h["ucitel_id"]:
            return "Vyberte učiteľa."
        if "projekt_id" in h and not h["projekt_id"]:
            return "Vyberte projekt (najprv ho založte na karte Projekty)."
        if "ak_rok" in h:
            h["ak_rok"] = importy.to_ak_rok(h["ak_rok"])
            if not h["ak_rok"]:
                return "Zadajte akademický rok, napr. 2024/2025."
        if "rok" in h and not (1990 <= h["rok"] <= 2100):
            return "Zadajte platný rok."
        if kluc == "publikacie" and not (0 < h["podiel"] <= 1):
            return "Podiel zadajte v rozsahu 0–1 (napr. 0,25)."
        if kluc == "projekty" and not h["kod"].strip():
            return "Kód projektu je povinný."
        return None

    def pridat(self, kluc: str):
        if kluc != "ucitelia" and kluc != "projekty" and not self.data.ucitelia:
            messagebox.showinfo("Najprv učitelia", "Najprv pridajte učiteľov (alebo ich importujte).")
            return
        cls = self._TRIEDY[kluc]
        predvolene = vars(cls()).copy()
        if "ak_rok" in predvolene and self.obdobie.ak_roky:
            predvolene["ak_rok"] = self.obdobie.ak_roky[-1]
        vybrany = self._vybrany_ucitel()
        if vybrany and "ucitel_id" in predvolene:
            predvolene["ucitel_id"] = vybrany

        def ok(h):
            chyba = self._validuj(kluc, h)
            if chyba:
                return chyba
            self.db.uloz(cls(**h))
            self.obnov_vsetko()
            return None
        Formular(self.root, "Nový záznam", self._polia(kluc), predvolene, ok)

    def _vybrany_ucitel(self):
        sel = self.tabulky["ucitelia"].vybrane()
        return int(sel[0]) if sel else None

    def upravit(self, kluc: str):
        sel = self.tabulky[kluc].vybrane()
        if not sel:
            return
        obj = self.db.ziskaj(kluc, int(sel[0]))
        if obj is None:
            return

        def ok(h):
            chyba = self._validuj(kluc, h)
            if chyba:
                return chyba
            for k, v in h.items():
                setattr(obj, k, v)
            self.db.uloz(obj)
            self.obnov_vsetko()
            return None
        Formular(self.root, "Upraviť záznam", self._polia(kluc), vars(obj), ok)

    def vymazat(self, kluc: str):
        sel = self.tabulky[kluc].vybrane()
        if not sel:
            return
        doplnok = " Vymažú sa aj všetky ich výučby, práce, publikácie a účasti na projektoch." if kluc == "ucitelia" else ""
        doplnok = " Vymažú sa aj účasti na projekte." if kluc == "projekty" else doplnok
        if not messagebox.askyesno("Vymazať", f"Vymazať vybrané záznamy ({len(sel)})?{doplnok}"):
            return
        for iid in sel:
            self.db.zmaz(kluc, int(iid), commit=False)
        self.db.commit()
        self.obnov_vsetko()

    # ================================================================ výsledky – učitelia
    def _tab_vysledky_ucitelia(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="  Záťaž učiteľov  ")
        obd = ttk.LabelFrame(tab, text=" Sledované obdobie ", padding=8)
        obd.pack(fill="x")
        self.var_ak = tk.StringVar()
        self.var_pub = tk.StringVar()
        self.var_prj = tk.StringVar()
        for i, (txt, var, tip) in enumerate((
            ("Akademické roky (vzdelávanie):", self.var_ak, "2 posledné ukončené, napr. 2023/2024, 2024/2025"),
            ("Roky publikácií:", self.var_pub, "3 roky s uzávierkou v CREPČ, napr. 2022, 2023, 2024"),
            ("Roky projektov:", self.var_prj, "3 posledné verifikované roky (CVTI SR)"),
        )):
            ttk.Label(obd, text=txt).grid(row=0, column=2 * i, sticky="w", padx=(0 if i == 0 else 14, 4))
            e = ttk.Entry(obd, textvariable=var, width=26)
            e.grid(row=0, column=2 * i + 1)
            ttk.Label(obd, text=tip, foreground="#777", font=("Segoe UI", 8)).grid(row=1, column=2 * i + 1, sticky="w")
        ttk.Button(obd, text="Navrhnúť podľa údajov", command=self.navrhni_obdobie).grid(row=0, column=6, padx=(14, 4))
        ttk.Button(obd, text="▶ Prepočítať", style="Accent.TButton", command=self.prepocitaj).grid(row=0, column=7)

        flt = ttk.Frame(tab)
        flt.pack(fill="x", pady=6)
        ttk.Label(flt, text="Fakulta:").pack(side="left")
        self.var_f_fak = tk.StringVar(value="(všetky)")
        self.cb_fak = ttk.Combobox(flt, textvariable=self.var_f_fak, width=14, state="readonly")
        self.cb_fak.pack(side="left", padx=4)
        ttk.Label(flt, text="Ústav:").pack(side="left", padx=(10, 0))
        self.var_f_ust = tk.StringVar(value="(všetky)")
        self.cb_ust = ttk.Combobox(flt, textvariable=self.var_f_ust, width=34, state="readonly")
        self.cb_ust.pack(side="left", padx=4)
        for cb in (self.cb_fak, self.cb_ust):
            cb.bind("<<ComboboxSelected>>", lambda e: self.zobraz_ucitelov())
        ttk.Button(flt, text="📥 Exportovať výsledky", command=self.export_vysledkov).pack(side="right")
        self.lbl_suhrn = ttk.Label(flt, text="")
        self.lbl_suhrn.pack(side="left", padx=20)

        self.t_vysl = Tabulka(tab, [
            ("meno", "Meno", 220), ("ust", "Ústav", 170), ("uv", "Úväzok", 60),
            ("vzd", "Vzdelávanie h/ak.r.", 110), ("pvzd", "% fondu", 70), ("prj", "Projekty h/r", 90),
            ("psp", "Spolu %", 70), ("status", "Status (čl. 7)", 230), ("tyz", "Výučba h/týž. (ref.)", 120),
            ("pub", "Publikácie body/r", 110), ("fin", "Projekty €/r", 100),
            ("s1", "Št. vzd.", 60), ("s2", "Št. pub.", 60), ("s3", "Št. prj.", 60), ("upo", "⚠", 30)],
            on_double=self.detail_ucitela)
        self.t_vysl.pack(fill="both", expand=True)
        for tag, farba in FARBY_STATUSU.items():
            self.t_vysl.tree.tag_configure(tag, background=farba)
        leg = ttk.Frame(tab)
        leg.pack(fill="x", pady=(4, 0))
        for tag, text in (("ideal", "40–60 % ideálny stav"), ("pod", "< 40 %"), ("nad", "60–80 %"),
                          ("posudenie", "≥ 80 % kvalitatívne posúdenie"), ("pretazenie", "> 100 % preťaženie"),
                          ("nezahrnuty", "úväzok < 25 %")):
            tk.Label(leg, text=f"  {text}  ", bg=FARBY_STATUSU[tag], font=("Segoe UI", 8)).pack(side="left", padx=2)
        ttk.Label(leg, text="   Dvojklik na riadok zobrazí rozpis výpočtu.", foreground="#666").pack(side="left")

    def _obdobie_z_poli(self) -> calc.Obdobie:
        def roky(s):
            out = []
            for p in s.replace(";", ",").split(","):
                p = p.strip()
                if "-" in p and "/" not in p:
                    a, b = p.split("-", 1)
                    out.extend(range(int(a), int(b) + 1))
                elif p:
                    out.append(int(p))
            return out
        ak = [importy.to_ak_rok(x) for x in self.var_ak.get().replace(";", ",").split(",") if x.strip()]
        return calc.Obdobie(ak_roky=ak, roky_publikacie=roky(self.var_pub.get()), roky_projekty=roky(self.var_prj.get()))

    def _zapis_obdobie(self):
        self.var_ak.set(", ".join(self.obdobie.ak_roky))
        self.var_pub.set(", ".join(map(str, self.obdobie.roky_publikacie)))
        self.var_prj.set(", ".join(map(str, self.obdobie.roky_projekty)))

    def navrhni_obdobie(self):
        self.obdobie = calc.navrhni_obdobie(self.data, self.params)
        self._zapis_obdobie()
        self.prepocitaj()

    def prepocitaj(self):
        try:
            self.obdobie = self._obdobie_z_poli()
        except ValueError:
            messagebox.showerror("Obdobie", "Roky zadajte ako čísla oddelené čiarkou, napr. 2022, 2023, 2024.")
            return
        try:
            self.vysl_ucitelia = calc.vypocitaj_ucitelov(self.data, self.obdobie, self.params)
            self.vysl_ustavy = calc.vypocitaj_ustavy(self.data, self.obdobie, self.params, self.vysl_ucitelia)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Chyba výpočtu", str(e))
            return
        fak = sorted({u.fakulta for u in self.data.ucitelia if u.fakulta})
        self.cb_fak["values"] = ["(všetky)", *fak]
        self.cb_ust["values"] = ["(všetky)", *sorted({u.ustav for u in self.data.ucitelia if u.ustav})]
        self.zobraz_ucitelov()
        self.zobraz_ustavy()
        self.status.set(f"Prepočítané. {self.obdobie.popis()}")

    def zobraz_ucitelov(self):
        fak, ust = self.var_f_fak.get(), self.var_f_ust.get()
        riadky, pocty = [], {}
        for r in self.vysl_ucitelia:
            u = r.ucitel
            if fak not in ("", "(všetky)") and u.fakulta != fak:
                continue
            if ust not in ("", "(všetky)") and u.ustav != ust:
                continue
            tag = tag_statusu(r.status)
            pocty[tag] = pocty.get(tag, 0) + 1
            ref = f" ({r.referencna_vyucba_tyzden})" if r.referencna_vyucba_tyzden else ""
            pct = lambda x: f"{fmt(x)} %"  # noqa: E731
            riadky.append((u.id, [u.cele_meno, u.ustav, fmt(u.uvazok, 2), fmt(r.h_vzdelavanie), pct(r.pct_vzdelavanie),
                                  fmt(r.h_projekty), pct(r.pct_spolu), r.status, fmt(r.vyucba_tyzden) + ref,
                                  fmt(r.body_publikacie), fmt(r.financie_projekty, 0), fmt(r.std_vzdelavanie, 2),
                                  fmt(r.std_publikacie, 2), fmt(r.std_projekty, 2), "⚠" if r.upozornenia else ""],
                           (tag,)))
        self.t_vysl.nastav(riadky)
        self.lbl_suhrn.config(text=f"Učiteľov: {len(riadky)}   ideálny stav: {pocty.get('ideal', 0)}   "
                                   f"posúdenie ≥80 %: {pocty.get('posudenie', 0)}   preťaženie: {pocty.get('pretazenie', 0)}")

    def detail_ucitela(self):
        sel = self.t_vysl.vybrane()
        if not sel:
            return
        r = next((x for x in self.vysl_ucitelia if str(x.ucitel.id) == sel[0]), None)
        if not r:
            return
        p = self.params
        txt = (
            f"{r.ucitel.cele_meno}\n{r.ucitel.fakulta} – {r.ucitel.ustav}, {r.ucitel.funkcia or 'funkcia neuvedená'}\n"
            f"Úväzok {fmt(r.ucitel.uvazok, 2)} → fond {fmt(r.fond_hodin)} h/rok\n\n"
            f"VZDELÁVANIE (priemer za {len(self.obdobie.ak_roky)} ak. roky)\n"
            f"  priama výučba × {fmt(p['koef_priprava'], 0)} (EN/MOB bonifikácia {fmt(p['koef_anglictina'], 0)}): {fmt(r.h_vyucba)} h\n"
            f"  študenti × {fmt(p['hodiny_na_studenta'], 2)} h: {fmt(r.h_studenti)} h\n"
            f"  záverečné práce (tab. 1): {fmt(r.h_zaverecne_prace)} h\n"
            f"  spolu: {fmt(r.h_vzdelavanie)} h = {fmt(r.pct_vzdelavanie)} % fondu\n\n"
            f"PROJEKTY (priemer za rok): {fmt(r.h_projekty)} h, podiel na financiách {fmt(r.financie_projekty, 2)} €\n"
            f"Vzdelávanie + projekty: {fmt(r.pct_spolu)} % fondu\n\n"
            f"PUBLIKÁCIE (priemer za rok): {fmt(r.body_publikacie, 2)} bodov\n\n"
            f"Status: {r.status}\n"
        )
        if r.upozornenia:
            txt += "\nUpozornenia:\n  • " + "\n  • ".join(r.upozornenia)
        messagebox.showinfo("Rozpis výpočtu", txt)

    # ================================================================ výsledky – ústavy
    def _tab_vysledky_ustavy(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="  Hodnotenie ústavov  ")
        pw = ttk.PanedWindow(tab, orient="vertical")
        pw.pack(fill="both", expand=True)
        hore = ttk.Frame(pw)
        self.t_ust = Tabulka(hore, [
            ("fak", "Fakulta", 60), ("ust", "Ústav", 200), ("n", "Učitelia", 60), ("uv", "Úväzky", 70),
            ("v1", "Študentohodiny", 110), ("v2", "Publ. body", 90), ("v3", "Projekty €", 100),
            ("z1", "z vzd.", 60), ("z2", "z pub.", 60), ("z3", "z prj.", 60), ("sk", "Sumárne skóre", 100),
            ("opt", "Optimálny počet", 100), ("roz", "Rozdiel", 70)], height=10)
        self.t_ust.pack(fill="both", expand=True)
        self.t_ust.tree.tag_configure("plus", background="#C6EFCE")
        self.t_ust.tree.tag_configure("minus", background="#FFC7CE")
        self.t_ust.tree.bind("<<TreeviewSelect>>", lambda e: self.kresli_graf())
        self.lbl_ust = ttk.Label(hore, text="", foreground="#8a4b00", wraplength=1200)
        self.lbl_ust.pack(fill="x", pady=4)
        pw.add(hore, weight=3)

        dole = ttk.Frame(pw)
        bar = ttk.Frame(dole)
        bar.pack(fill="x")
        ttk.Label(bar, text="Graf regresie (čl. 6, ilustračný graf 1):").pack(side="left")
        self.var_graf = tk.StringVar(value="vzdelavanie")
        for k, t in (("vzdelavanie", "Vzdelávanie"), ("publikacie", "Publikácie"), ("projekty", "Projekty")):
            ttk.Radiobutton(bar, text=t, value=k, variable=self.var_graf, command=self.kresli_graf).pack(side="left", padx=6)
        self.canvas = tk.Canvas(dole, bg="white", height=300, highlightthickness=1, highlightbackground="#ccc")
        self.canvas.pack(fill="both", expand=True, pady=4)
        self.canvas.bind("<Configure>", lambda e: self.kresli_graf())
        pw.add(dole, weight=2)

    def zobraz_ustavy(self):
        if not self.vysl_ustavy:
            return
        riadky = []
        for i, u in enumerate(self.vysl_ustavy.ustavy):
            tag = () if u.sumarne_skore is None else (("plus",) if u.sumarne_skore >= 0 else ("minus",))
            riadky.append((i, [u.fakulta, u.ustav, u.pocet_ucitelov, fmt(u.uvazky, 2), fmt(u.vykon_vzdelavanie, 0),
                               fmt(u.vykon_publikacie), fmt(u.vykon_projekty, 0), fmt(u.z_vzdelavanie, 2),
                               fmt(u.z_publikacie, 2), fmt(u.z_projekty, 2), fmt(u.sumarne_skore, 2),
                               fmt(u.opt_pedagogovia, 2),
                               ("+" if (u.rozdiel_pedagogov or 0) > 0 else "") + fmt(u.rozdiel_pedagogov, 2)], tag))
        self.t_ust.nastav(riadky)
        txt = " ".join(self.vysl_ustavy.upozornenia)
        regs = []
        for k, r in self.vysl_ustavy.regresie.items():
            regs.append(f"{k}: y = {fmt(r.b, 2)}·x" if r else f"{k}: –")
        self.lbl_ust.config(text="Regresia (bez abs. člena): " + ";  ".join(regs) + ("   ⚠ " + txt if txt else ""))
        self.kresli_graf()

    def kresli_graf(self):
        c = self.canvas
        c.delete("all")
        if not self.vysl_ustavy or not self.vysl_ustavy.ustavy:
            c.create_text(20, 20, anchor="nw", text="Graf sa zobrazí po výpočte.", fill="#777")
            return
        oblast = self.var_graf.get()
        attr = {"vzdelavanie": "vykon_vzdelavanie", "publikacie": "vykon_publikacie", "projekty": "vykon_projekty"}[oblast]
        reg = self.vysl_ustavy.regresie.get(oblast)
        body = [(u.uvazky, getattr(u, attr), u) for u in self.vysl_ustavy.ustavy]
        W, H = max(c.winfo_width(), 300), max(c.winfo_height(), 200)
        L, R, T, B = 70, 20, 15, 35
        xmax = max([x for x, _, _ in body] + [1]) * 1.1
        ymax = max([y for _, y, _ in body] + [reg.b * xmax if reg else 0, 1]) * 1.05
        sx = lambda x: L + (W - L - R) * x / xmax  # noqa: E731
        sy = lambda y: H - B - (H - T - B) * y / ymax  # noqa: E731
        for i in range(6):
            yv = ymax * i / 5
            c.create_line(L, sy(yv), W - R, sy(yv), fill="#eee")
            c.create_text(L - 6, sy(yv), text=fmt(yv, 0), anchor="e", font=("Segoe UI", 8), fill="#666")
            xv = xmax * i / 5
            c.create_line(sx(xv), T, sx(xv), H - B, fill="#eee")
            c.create_text(sx(xv), H - B + 12, text=fmt(xv, 1), font=("Segoe UI", 8), fill="#666")
        c.create_line(L, H - B, W - R, H - B)
        c.create_line(L, T, L, H - B)
        c.create_text((L + W - R) / 2, H - 8, text="Prepočítaný počet učiteľov (úväzky)", font=("Segoe UI", 8))
        if reg:
            c.create_line(sx(0), sy(0), sx(xmax), sy(reg.b * xmax), fill="#D00000", width=2)
            c.create_text(W - R - 4, sy(min(reg.b * xmax, ymax)) + 12, text=f"y = {fmt(reg.b, 2)}x",
                          anchor="e", fill="#D00000")
        sel = self.t_ust.vybrane()
        sel_u = self.vysl_ustavy.ustavy[int(sel[0])] if sel else None
        for x, y, u in body:
            farba = "#F28C00" if u is sel_u else "#2F5597"
            r = 6 if u is sel_u else 4
            c.create_oval(sx(x) - r, sy(y) - r, sx(x) + r, sy(y) + r, fill=farba, outline="")
        if sel_u and reg and reg.b > 0:
            y = getattr(sel_u, attr)
            xo = y / reg.b
            c.create_line(L, sy(y), sx(xo), sy(y), fill="#F28C00", dash=(3, 3))
            c.create_line(sx(xo), sy(y), sx(xo), H - B, fill="#F28C00", dash=(3, 3))
            c.create_text(sx(xo) + 4, H - B - 10, anchor="w", fill="#F28C00",
                          text=f"{sel_u.ustav}: optimum {fmt(xo, 2)} (stav {fmt(sel_u.uvazky, 2)})")

    # ================================================================ import / export
    def sablona(self):
        path = filedialog.asksaveasfilename(title="Uložiť šablónu", defaultextension=".xlsx",
                                            initialfile="sablona_pracovna_zataz.xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            importy.vytvor_sablonu(path, params=self.params)
            self._otvor_subor(path)

    def import_sablony(self):
        path = filedialog.askopenfilename(title="Vyplnená šablóna", filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        nahradit = messagebox.askyesno(
            "Import šablóny",
            "Nahradiť existujúce záznamy za roky obsiahnuté v súbore?\n\n"
            "Áno – opakovaný import toho istého súboru nevytvorí duplicity (odporúčané).\nNie – záznamy sa iba pridajú.")
        try:
            vysl = importy.importuj_sablonu(self.db, path, nahradit=nahradit)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import zlyhal", str(e))
            return
        self.obnov_vsetko()
        self.navrhni_obdobie()
        if not vysl:
            messagebox.showwarning("Import", "V súbore sa nenašli hárky šablóny.")
            return
        messagebox.showinfo("Import dokončený", "\n\n".join(f"{k}: {v.sprava()}" for k, v in vysl.items()))

    def import_mapovanie(self):
        from .gui_dialogy import ImportDialog
        ImportDialog(self.root, self.db, on_done=lambda: (self.obnov_vsetko(), self.navrhni_obdobie()))

    def import_uis_zamestnanci(self):
        from .gui_dialogy import UISZamestnanciDialog
        UISZamestnanciDialog(self.root, self.db, on_done=self.obnov_vsetko)

    def import_uis_vyucba(self):
        from .gui_dialogy import UISVyucbaDialog
        UISVyucbaDialog(self.root, self.db, self.params, on_done=lambda: (self.obnov_vsetko(), self.navrhni_obdobie()))

    def import_uis_zp(self):
        from .gui_dialogy import UISZaverecnePraceDialog
        try:
            roky = self._obdobie_z_poli().ak_roky
        except ValueError:
            roky = self.obdobie.ak_roky
        UISZaverecnePraceDialog(self.root, self.db, roky, self.params,
                                on_done=lambda: (self.obnov_vsetko(), self.prepocitaj()))

    def import_uis_projekty(self):
        from .gui_dialogy import UISProjektyDialog
        try:
            roky = self._obdobie_z_poli().roky_projekty
        except ValueError:
            roky = self.obdobie.roky_projekty
        if not roky:
            import datetime as dt
            r = dt.date.today().year - 1
            roky = [r - 2, r - 1, r]
        UISProjektyDialog(self.root, self.db, roky, on_done=lambda: (self.obnov_vsetko(), self.navrhni_obdobie()))

    def import_biblio(self):
        from .gui_dialogy import BiblioDialog
        BiblioDialog(self.root, self.db, self.data, self.nastavenia, on_done=self.obnov_vsetko)

    def export_udajov(self):
        path = filedialog.asksaveasfilename(title="Export údajov", defaultextension=".xlsx",
                                            initialfile="udaje_pracovna_zataz.xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            importy.vytvor_sablonu(path, self.db, self.params)
            self.status.set(f"Údaje uložené do {path}")

    def export_vysledkov(self):
        if not self.vysl_ucitelia:
            self.prepocitaj()
        if not self.vysl_ucitelia:
            return
        path = filedialog.asksaveasfilename(title="Export výsledkov", defaultextension=".xlsx",
                                            initialfile="vysledky_pracovna_zataz.xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            try:
                vystupy.export_vysledkov(path, self.vysl_ucitelia, self.vysl_ustavy, self.obdobie, self.params)
            except PermissionError:
                messagebox.showerror("Export", "Súbor sa nedá zapísať – nie je otvorený v Exceli?")
                return
            self._otvor_subor(path)

    def ukazka(self):
        if self.data.ucitelia and not messagebox.askyesno("Ukážkové údaje", "Ukážkové údaje sa pridajú k existujúcim. Pokračovať?"):
            return
        from .ukazka import napln_ukazkove_data
        napln_ukazkove_data(self.db)
        self.obnov_vsetko()
        self.navrhni_obdobie()

    def vymazat_db(self):
        if messagebox.askyesno("Vymazať všetko", "Naozaj vymazať všetky údaje? Odporúčame najprv Export údajov.",
                               icon="warning"):
            self.db.vymaz_vsetko()
            self.obnov_vsetko()
            self.prepocitaj()

    # ================================================================ nastavenia
    def dialog_parametre(self):
        from .gui_dialogy import ParametreDialog

        def ulozene(p):
            self.params = p
            self.obnov_vsetko()
            self.prepocitaj()
        ParametreDialog(self.root, self.params, on_save=ulozene)

    def dialog_api(self):
        n = self.nastavenia

        def ok(h):
            n.update(h)
            config.save_nastavenia(n)
            return None
        Formular(self.root, "API kľúče", [
            ("scopus_api_key", "Scopus API Key (dev.elsevier.com)", "text", None),
            ("scopus_insttoken", "Scopus Institutional Token (nepovinné)", "text", None),
            ("wos_api_key", "Web of Science Starter API Key", "text", None)], n, ok)

    def _uloz_auto_upd(self):
        self.nastavenia["kontrolovat_aktualizacie"] = self.var_auto_upd.get()
        config.save_nastavenia(self.nastavenia)

    def otvor_priecinok(self):
        self._otvor_subor(str(config.app_data_dir()))

    def _otvor_subor(self, path: str):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:  # noqa: BLE001
            self.status.set(f"Uložené: {path}")

    # ================================================================ aktualizácie
    def kontrola_aktualizacii(self, tichy: bool):
        q: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: q.put(updater.skontroluj()), daemon=True).start()

        def poll():
            try:
                v = q.get_nowait()
            except queue.Empty:
                self.root.after(300, poll)
                return
            if v is None:
                if not tichy:
                    messagebox.showinfo("Aktualizácie", f"Používate najnovšiu verziu ({__version__}),\n"
                                                        "alebo sa nepodarilo spojiť s GitHubom.")
                return
            if tichy and self.nastavenia.get("preskocena_verzia") == v.verzia:
                return
            from .gui_dialogy import AktualizaciaDialog
            AktualizaciaDialog(self.root, v, self.nastavenia)
        poll()

    def o_programe(self):
        messagebox.showinfo(
            "O programe",
            f"Hodnotenie pracovnej záťaže VŠ učiteľov SPU v Nitre\nVerzia {__version__}\n\n"
            "Implementácia Metodického pokynu 1/2023 v znení Dodatku č. 2 (účinný od 1. 7. 2025).\n\n"
            f"Údaje sú uložené lokálne v:\n{config.app_data_dir()}\n\n{updater.RELEASES_URL}")

    # ================================================================ obnova
    def obnov_vsetko(self):
        self.data = self.db.nacitaj_vsetko()
        for k in self.tabulky:
            self.obnov_tabulku(k)
        if not self.var_ak.get() and not self.var_pub.get():
            self.obdobie = calc.navrhni_obdobie(self.data, self.params)
            self._zapis_obdobie()
        d = self.data
        self.status.set(f"Učitelia: {len(d.ucitelia)} | výučba: {len(d.vyucba)} | záverečné práce: {len(d.zaverecne_prace)}"
                        f" | publikácie: {len(d.publikacie)} | projekty: {len(d.projekty)} | účasti: {len(d.ucasti)}"
                        f"   —   dáta: {self.db.path}")


def main():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    # po aktualizácii zmazať starú verziu (stará ešte môže pár sekúnd končiť)
    threading.Thread(target=lambda: updater.upratanie(cakat_sekund=30), daemon=True).start()
    root = tk.Tk()
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ikona = os.path.join(base, "assets", "icon.ico")
    if sys.platform.startswith("win") and os.path.exists(ikona):
        try:
            root.iconbitmap(ikona)
        except tk.TclError:
            pass
    try:
        app = App(root)
        if app.data.ucitelia:
            app.prepocitaj()
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Chyba pri spustení", f"{type(e).__name__}: {e}")
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
