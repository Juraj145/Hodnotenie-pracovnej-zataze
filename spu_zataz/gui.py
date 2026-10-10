"""Hlavné okno programu.

Rozloženie zodpovedá postupu hodnotenia (bočná navigácia):
  Prehľad → 1 Podmienky hodnotenia → 2 Obdobie → 3–7 Údaje (učitelia, výučba, záverečné práce, projekty,
  publikácie) → 8 Kontrola údajov → 9 Hodnotenie učiteľov → 10 Hodnotenie ústavov.
"""

from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import calc, config, importy, kontrola, metodika, ulozisko, updater, vystupy
from .config import NAZVY_OBLASTI, OBLASTI
from .db import Databaza
from .gui_common import ZELENA, Formular, Tabulka, fmt
from .models import (Projekt, ProjektUcast, Publikacia, Ucitel, Vyucba,
                     ZaverecnaPraca)
from .version import __version__

FARBY_STATUSU = {
    "ideal": "#C6EFCE", "pod": "#DDEBF7", "nad": "#FFF2CC", "posudenie": "#FCE4D6",
    "pretazenie": "#FFC7CE", "nezahrnuty": "#EDEDED",
}
NAZVY_STATUSU = {"ideal": "40–60 % ideálny stav", "pod": "< 40 %", "nad": "60–80 %",
                 "posudenie": "≥ 80 % posúdenie", "pretazenie": "> 100 % preťaženie", "nezahrnuty": "nezahrnutí"}
BG_NAV = "#F2F5EF"
BG_OBSAH = "#FFFFFF"
CERVENA, ORANZOVA, MODRA, SIVA = "#B42318", "#B54708", "#1F4E9E", "#667085"

STRANKY = [
    # (kľúč, ikona, názov, sekcia)
    ("prehlad", "🏠", "Prehľad", ""),
    ("podmienky", "📘", "Podmienky hodnotenia", "NASTAVENIE"),
    ("obdobie", "📅", "Obdobie hodnotenia", ""),
    ("ucitelia", "👥", "Zoznam učiteľov", "ÚDAJE"),
    ("vyucba", "📚", "Výučba", ""),
    ("zaverecne_prace", "🎓", "Záverečné práce", ""),
    ("projekty", "🔬", "Projekty", ""),
    ("publikacie", "📰", "Publikácie", ""),
    ("kontrola", "✅", "Kontrola údajov", "VÝSLEDKY"),
    ("vysledky_ucitelia", "📊", "Hodnotenie učiteľov", ""),
    ("vysledky_ustavy", "🏛", "Hodnotenie ústavov", ""),
]


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


def _roky(text: str) -> list[int]:
    out = []
    for p in text.replace(";", ",").split(","):
        p = p.strip()
        if "-" in p and "/" not in p:
            a, b = p.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif p:
            out.append(int(p))
    return sorted(set(out))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.db = Databaza()
        self.params = config.load_parametre()
        self.nastavenia = config.load_nastavenia()
        self.data = self.db.nacitaj_vsetko()
        self.vysl_ucitelia: list[calc.VysledokUcitela] = []
        self.vysl_ustavy: calc.VysledokUstavov | None = None
        self.problemy: list[kontrola.Problem] = []
        self.priecinok: Path | None = Path(self.nastavenia["pracovny_priecinok"]) if self.nastavenia.get(
            "pracovny_priecinok") else None
        self._zmeny_pri_ulozeni = self.db.conn.total_changes
        self.aktivna = ""
        self._nacitaj_obdobie()

        root.title(f"Hodnotenie pracovnej záťaže VŠ učiteľov – SPU v Nitre  (v{__version__})")
        root.geometry("1440x880")
        root.minsize(1100, 660)
        root.configure(bg=BG_OBSAH)
        self._styl()
        self._menu()
        self._hlavicka()
        telo = tk.Frame(root, bg=BG_OBSAH)
        telo.pack(fill="both", expand=True)
        self._navigacia(telo)
        self.obsah = tk.Frame(telo, bg=BG_OBSAH)
        self.obsah.pack(side="left", fill="both", expand=True)
        self.status = tk.StringVar()
        tk.Label(root, textvariable=self.status, anchor="w", bg="#F7F7F7", fg="#444", padx=10, pady=3,
                 font=("Segoe UI", 9)).pack(fill="x", side="bottom")

        self.stranky: dict[str, tk.Frame] = {}
        self.tabulky: dict[str, Tabulka] = {}
        self.filtre: dict[str, dict[str, tk.StringVar]] = {}
        self._stranka_prehlad()
        self._stranka_podmienky()
        self._stranka_obdobie()
        self._stranka_ucitelia()
        self._stranka_vyucba()
        self._stranka_zaverecne_prace()
        self._stranka_projekty()
        self._stranka_publikacie()
        self._stranka_kontrola()
        self._stranka_vysledky_ucitelia()
        self._stranka_vysledky_ustavy()

        root.protocol("WM_DELETE_WINDOW", self.zatvor)
        self.obnov_vsetko(prepocitat=True)
        self.ukaz("prehlad")
        if self.nastavenia.get("kontrolovat_aktualizacie", True):
            root.after(1500, lambda: self.kontrola_aktualizacii(tichy=True))

    # ================================================================ vzhľad
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
        s.configure("Biele.TFrame", background=BG_OBSAH)
        s.configure("Biele.TLabel", background=BG_OBSAH)
        s.configure("Biele.TRadiobutton", background=BG_OBSAH)
        s.configure("Biele.TCheckbutton", background=BG_OBSAH)
        s.configure("Biele.TLabelframe", background=BG_OBSAH)
        s.configure("Biele.TLabelframe.Label", background=BG_OBSAH, font=("Segoe UI", 10, "bold"), foreground=ZELENA)

    def _menu(self):
        m = tk.Menu(self.root)
        subor = tk.Menu(m, tearoff=0)
        subor.add_command(label="Uložiť údaje", accelerator="Ctrl+S", command=self.uloz_udaje)
        subor.add_command(label="Uložiť údaje ako… (nový priečinok)", command=lambda: self.uloz_udaje(novy=True))
        subor.add_command(label="Načítať údaje z priečinka…", accelerator="Ctrl+O", command=self.nacitaj_udaje)
        subor.add_command(label="Otvoriť priečinok s údajmi", command=self.otvor_priecinok_udajov)
        subor.add_separator()
        subor.add_command(label="Exportovať výsledky do Excelu…", command=self.export_vysledkov)
        subor.add_separator()
        subor.add_command(label="Vytvoriť prázdnu Excel šablónu…", command=self.sablona)
        subor.add_command(label="Importovať vyplnenú šablónu…", command=self.import_sablony)
        subor.add_command(label="Importovať export z UIS / CREPČ / iný súbor…", command=self.import_mapovanie)
        subor.add_separator()
        subor.add_command(label="Vymazať fakultu…", command=self.vymaz_fakultu)
        subor.add_command(label="Nové hodnotenie (vymazať všetky údaje)…", command=self.vymazat_db)
        subor.add_command(label="Načítať ukážkové údaje", command=self.ukazka)
        subor.add_separator()
        subor.add_command(label="Koniec", command=self.zatvor)
        m.add_cascade(label="Súbor", menu=subor)

        nast = tk.Menu(m, tearoff=0)
        nast.add_command(label="Podmienky hodnotenia (metodika)…", command=lambda: self.ukaz("podmienky"))
        nast.add_command(label="Parametre metodiky – ručná úprava…", command=self.dialog_parametre)
        nast.add_command(label="API kľúče (Scopus, WoS)…", command=self.dialog_api)
        nast.add_command(label="Otvoriť priečinok programu", command=self.otvor_priecinok)
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
        self.root.bind_all("<Control-s>", lambda e: self.uloz_udaje())
        self.root.bind_all("<Control-o>", lambda e: self.nacitaj_udaje())

    def _hlavicka(self):
        h = tk.Frame(self.root, bg=ZELENA)
        h.pack(fill="x")
        lavo = tk.Frame(h, bg=ZELENA)
        lavo.pack(side="left", padx=14, pady=6)
        tk.Label(lavo, text="Hodnotenie pracovnej záťaže VŠ učiteľov", bg=ZELENA, fg="white",
                 font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.lbl_metodika = tk.Label(lavo, text="", bg=ZELENA, fg="#CFE3C4", font=("Segoe UI", 9))
        self.lbl_metodika.pack(anchor="w")
        pravo = tk.Frame(h, bg=ZELENA)
        pravo.pack(side="right", padx=12)
        for text, cmd in (("📂 Načítať údaje", self.nacitaj_udaje), ("💾 Uložiť údaje", self.uloz_udaje),
                          ("▶ Vypočítať", self.vypocitaj_a_ukaz)):
            tk.Button(pravo, text=text, command=cmd, bg="#2E6B31" if not text.startswith("▶") else "#F2B705",
                      fg="white" if not text.startswith("▶") else "#1E1E1E", activebackground="#3F8A43",
                      relief="flat", padx=12, pady=5, font=("Segoe UI", 9, "bold"), cursor="hand2").pack(
                side="left", padx=4)
        self.lbl_priecinok = tk.Label(h, text="", bg=ZELENA, fg="#CFE3C4", font=("Segoe UI", 9))
        self.lbl_priecinok.pack(side="right", padx=10)

    def _navigacia(self, telo):
        nav = tk.Frame(telo, bg=BG_NAV, width=250)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        self.nav_polozky: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        cislo = 0
        for kluc, ikona, nazov, sekcia in STRANKY:
            if sekcia:
                tk.Label(nav, text=sekcia, bg=BG_NAV, fg="#7A8679", font=("Segoe UI", 8, "bold"),
                         anchor="w").pack(fill="x", padx=16, pady=(14, 2))
            if kluc != "prehlad":
                cislo += 1
            f = tk.Frame(nav, bg=BG_NAV, cursor="hand2")
            f.pack(fill="x", padx=6, pady=1)
            text = f"{ikona}  {cislo}  {nazov}" if kluc != "prehlad" else f"{ikona}  {nazov}"
            lbl = tk.Label(f, text=text, bg=BG_NAV, fg="#1D2B1C", font=("Segoe UI", 10), anchor="w", padx=10, pady=6)
            lbl.pack(side="left", fill="x", expand=True)
            badge = tk.Label(f, text="", bg=BG_NAV, fg=SIVA, font=("Segoe UI", 8), padx=8)
            badge.pack(side="right")
            for w in (f, lbl, badge):
                w.bind("<Button-1>", lambda e, k=kluc: self.ukaz(k))
            self.nav_polozky[kluc] = (f, lbl, badge)

    def ukaz(self, kluc: str):
        for k, fr in self.stranky.items():
            if k != kluc:
                fr.pack_forget()
        self.stranky[kluc].pack(fill="both", expand=True)
        self.aktivna = kluc
        for k, (f, lbl, badge) in self.nav_polozky.items():
            bg = ZELENA if k == kluc else BG_NAV
            f.configure(bg=bg)
            lbl.configure(bg=bg, fg="white" if k == kluc else "#1D2B1C",
                          font=("Segoe UI", 10, "bold" if k == kluc else "normal"))
            badge.configure(bg=bg)
        self.obnov_navigaciu()
        if kluc == "prehlad":
            self.obnov_prehlad()
        elif kluc == "kontrola":
            self.zobraz_kontrolu()

    def _stranka(self, kluc: str, titulok: str, popis: str = "") -> tk.Frame:
        fr = tk.Frame(self.obsah, bg=BG_OBSAH)
        hl = tk.Frame(fr, bg=BG_OBSAH)
        hl.pack(fill="x", padx=18, pady=(14, 4))
        tk.Label(hl, text=titulok, bg=BG_OBSAH, fg=ZELENA, font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x")
        if popis:
            tk.Label(hl, text=popis, bg=BG_OBSAH, fg="#555", font=("Segoe UI", 9), anchor="w", justify="left",
                     wraplength=1100).pack(fill="x", pady=(2, 0))
        self.stranky[kluc] = fr
        return fr

    def _telo(self, fr: tk.Frame) -> ttk.Frame:
        t = ttk.Frame(fr, style="Biele.TFrame", padding=(18, 6, 18, 12))
        t.pack(fill="both", expand=True)
        return t

    # ================================================================ obdobie (stav)
    def _nacitaj_obdobie(self):
        o = self.nastavenia.get("obdobie") or {}
        self.rezim_obdobia = o.get("rezim", "pokyn")
        self.jeden_ak_rok = o.get("jeden_ak_rok", "")
        try:
            self.datum_hodnotenia = dt.date.fromisoformat(o.get("datum", "")) if o.get("datum") else dt.date.today()
        except ValueError:
            self.datum_hodnotenia = dt.date.today()
        if self.rezim_obdobia == "vlastne" and o.get("ak_roky") is not None:
            self.obdobie = calc.Obdobie(ak_roky=list(o.get("ak_roky", [])),
                                        roky_publikacie=[int(x) for x in o.get("roky_publikacie", [])],
                                        roky_projekty=[int(x) for x in o.get("roky_projekty", [])])
        elif self.rezim_obdobia == "udaje":
            self.obdobie = calc.navrhni_obdobie(self.data, self.params)
        else:
            self.rezim_obdobia = "pokyn"
            self.obdobie = calc.obdobie_podla_pokynu(self.params, self.datum_hodnotenia)

    def _uloz_obdobie(self):
        self.nastavenia["obdobie"] = {
            "rezim": self.rezim_obdobia, "jeden_ak_rok": self.jeden_ak_rok, "datum": self.datum_hodnotenia.isoformat(),
            "ak_roky": self.obdobie.ak_roky, "roky_publikacie": self.obdobie.roky_publikacie,
            "roky_projekty": self.obdobie.roky_projekty}
        config.save_nastavenia(self.nastavenia)

    def efektivne_obdobie(self) -> calc.Obdobie:
        ak = [self.jeden_ak_rok] if self.jeden_ak_rok else list(self.obdobie.ak_roky)
        return calc.Obdobie(ak_roky=ak, roky_publikacie=list(self.obdobie.roky_publikacie),
                            roky_projekty=list(self.obdobie.roky_projekty))

    # ================================================================ 0 Prehľad
    def _stranka_prehlad(self):
        fr = self._stranka("prehlad", "Prehľad hodnotenia",
                           "Postupujte zhora nadol: podmienky hodnotenia → obdobie → údaje → kontrola → výsledky. "
                           "Kliknutím na krok sa presuniete na príslušnú časť.")
        t = self._telo(fr)
        t.columnconfigure(0, weight=3)
        t.columnconfigure(1, weight=2)
        self.pr_kroky = ttk.LabelFrame(t, text=" Postup hodnotenia ", style="Biele.TLabelframe", padding=10)
        self.pr_kroky.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 12))
        self.pr_vysledky = ttk.LabelFrame(t, text=" Výsledky ", style="Biele.TLabelframe", padding=10)
        self.pr_vysledky.grid(row=0, column=1, sticky="nsew")
        self.pr_kontrola = ttk.LabelFrame(t, text=" Kontrola údajov ", style="Biele.TLabelframe", padding=10)
        self.pr_kontrola.grid(row=1, column=1, sticky="nsew", pady=(12, 0))
        t.rowconfigure(0, weight=1)
        t.rowconfigure(1, weight=1)

    def _kroky(self) -> list[tuple[str, str, str, str]]:
        """(stav ok/warn/todo, názov, detail, stránka)"""
        d, obd = self.data, self.efektivne_obdobie()
        doc = metodika.aktivny()
        out = [("ok" if doc else "warn", "Podmienky hodnotenia",
                metodika.popis_aktivnej_metodiky() + ("" if doc else " – nahrajte dokument metodiky"), "podmienky")]
        out.append(("ok" if obd.ak_roky and obd.roky_publikacie and obd.roky_projekty else "todo", "Obdobie hodnotenia",
                    obd.popis(), "obdobie"))
        ak, pub, prj = set(obd.ak_roky), set(obd.roky_publikacie), set(obd.roky_projekty)
        bez_id = sum(1 for u in d.ucitelia if not (u.orcid and u.scopus_id and u.wos_id))
        fak = sorted({u.fakulta for u in d.ucitelia if u.fakulta})
        out.append(("ok" if d.ucitelia else "todo", "Zoznam učiteľov",
                    f"{len(d.ucitelia)} učiteľov, fakulty: {', '.join(fak) or '–'}"
                    + (f"; {bez_id} bez úplných identifikátorov ORCID/Scopus/WoS" if bez_id else ""), "ucitelia"))
        for kluc, nazov, zaznamy, roky_set, roky_obd, text in (
            ("vyucba", "Výučba", d.vyucba, {v.ak_rok for v in d.vyucba}, obd.ak_roky, "ak. roky"),
            ("zaverecne_prace", "Záverečné práce", d.zaverecne_prace, {z.ak_rok for z in d.zaverecne_prace},
             obd.ak_roky, "ak. roky"),
            ("projekty", "Projekty", d.projekty, {p.rok for p in d.projekty}, obd.roky_projekty, "roky"),
            ("publikacie", "Publikácie", d.publikacie, {p.rok for p in d.publikacie}, obd.roky_publikacie, "roky"),
        ):
            chyba = [str(r) for r in roky_obd if r not in roky_set]
            v_obd = sum(1 for z in zaznamy if (getattr(z, "ak_rok", None) in ak) or (
                kluc == "projekty" and z.rok in prj) or (kluc == "publikacie" and z.rok in pub))
            stav = "todo" if not zaznamy else ("warn" if chyba else "ok")
            out.append((stav, nazov, f"{v_obd} záznamov v sledovanom období" +
                        (f"; chýbajú {text}: {', '.join(chyba)}" if chyba else ""), kluc))
        n_ch = sum(1 for p in self.problemy if p.zavaznost == kontrola.CHYBA)
        n_up = sum(1 for p in self.problemy if p.zavaznost == kontrola.UPOZORNENIE)
        out.append(("ok" if not n_ch else "warn", "Kontrola údajov", f"{n_ch} chýb, {n_up} upozornení", "kontrola"))
        zahr = [r for r in self.vysl_ucitelia if r.zahrnuty]
        out.append(("ok" if zahr else "todo", "Hodnotenie učiteľov",
                    f"{len(zahr)} hodnotených učiteľov" if zahr else "zatiaľ nevypočítané", "vysledky_ucitelia"))
        n_ust = len(self.vysl_ustavy.ustavy) if self.vysl_ustavy else 0
        out.append(("ok" if n_ust >= 3 else ("warn" if n_ust else "todo"), "Hodnotenie ústavov",
                    f"{n_ust} ústavov" + (" (regresia potrebuje aspoň 3)" if 0 < n_ust < 3 else ""), "vysledky_ustavy"))
        return out

    def obnov_prehlad(self):
        for w in self.pr_kroky.winfo_children():
            w.destroy()
        ikony = {"ok": ("✔", "#1E7B34"), "warn": ("!", ORANZOVA), "todo": ("○", SIVA)}
        for i, (stav, nazov, detail, stranka) in enumerate(self._kroky(), 1):
            riadok = tk.Frame(self.pr_kroky, bg=BG_OBSAH, cursor="hand2")
            riadok.pack(fill="x", pady=3)
            ik, farba = ikony[stav]
            tk.Label(riadok, text=ik, bg=farba, fg="white", width=3, font=("Segoe UI", 10, "bold")).pack(
                side="left", padx=(0, 10), ipady=4)
            txt = tk.Frame(riadok, bg=BG_OBSAH)
            txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=f"{i}. {nazov}", bg=BG_OBSAH, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
            tk.Label(txt, text=detail, bg=BG_OBSAH, fg="#555", font=("Segoe UI", 9), anchor="w", justify="left",
                     wraplength=620).pack(fill="x")
            ttk.Button(riadok, text="Prejsť →", command=lambda s=stranka: self.ukaz(s)).pack(side="right")
            for w in (riadok, txt):
                w.bind("<Button-1>", lambda e, s=stranka: self.ukaz(s))

        for w in self.pr_vysledky.winfo_children():
            w.destroy()
        zahr = [r for r in self.vysl_ucitelia if r.zahrnuty]
        if not zahr:
            tk.Label(self.pr_vysledky, text="Výsledky sa zobrazia po načítaní údajov a výpočte (▶ Vypočítať).",
                     bg=BG_OBSAH, fg="#666", wraplength=420, justify="left").pack(anchor="w")
        else:
            pocty = {}
            for r in self.vysl_ucitelia:
                pocty[tag_statusu(r.status)] = pocty.get(tag_statusu(r.status), 0) + 1
            tk.Label(self.pr_vysledky, text=f"Záťaž vzdelávaním (čl. 7) – {len(self.vysl_ucitelia)} učiteľov",
                     bg=BG_OBSAH, font=("Segoe UI", 9, "bold")).pack(anchor="w")
            c = tk.Canvas(self.pr_vysledky, height=150, bg=BG_OBSAH, highlightthickness=0)
            c.pack(fill="x", pady=4)
            mx = max(pocty.values())
            self.root.update_idletasks()
            sirka = max(self.pr_vysledky.winfo_width() - 230, 80)
            for i, tag in enumerate(("ideal", "pod", "nad", "posudenie", "pretazenie", "nezahrnuty")):
                n = pocty.get(tag, 0)
                y = 6 + i * 24
                dlzka = sirka * n / mx
                c.create_text(4, y + 8, text=NAZVY_STATUSU[tag], anchor="w", font=("Segoe UI", 8))
                c.create_rectangle(140, y, 140 + dlzka, y + 16, fill=FARBY_STATUSU[tag], outline="#999")
                c.create_text(146 + dlzka, y + 8, text=str(n), anchor="w", font=("Segoe UI", 8, "bold"))
            naj = sorted(zahr, key=lambda r: -(r.celkove_skore or 0))[:5]
            tk.Label(self.pr_vysledky, text="Najvyššie celkové skóre (čl. 7 ods. 1.5):", bg=BG_OBSAH,
                     font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 0))
            for r in naj:
                tk.Label(self.pr_vysledky, text=f"  {fmt(r.celkove_skore)}   {r.ucitel.cele_meno} ({r.ucitel.ustav})",
                         bg=BG_OBSAH, anchor="w").pack(anchor="w")
            if self.vysl_ustavy and self.vysl_ustavy.ustavy:
                us = [u for u in self.vysl_ustavy.ustavy if u.sumarne_skore is not None]
                if us:
                    b = max(us, key=lambda u: u.sumarne_skore)
                    tk.Label(self.pr_vysledky, text=f"Ústavy: {len(self.vysl_ustavy.ustavy)}, najvyššie sumárne skóre "
                                                    f"{b.ustav} ({fmt(b.sumarne_skore, 2)})", bg=BG_OBSAH).pack(
                        anchor="w", pady=(6, 0))

        for w in self.pr_kontrola.winfo_children():
            w.destroy()
        s = kontrola.suhrn(self.problemy)
        if not self.problemy:
            tk.Label(self.pr_kontrola, text="Bez nálezov.", bg=BG_OBSAH).pack(anchor="w")
        for oblast in ("Podmienky", "Obdobie", "Učitelia", "Výučba", "Záverečné práce", "Projekty", "Publikácie"):
            if oblast not in s:
                continue
            x = s[oblast]
            casti = []
            if x.get(kontrola.CHYBA):
                casti.append(f"{x[kontrola.CHYBA]} chýb")
            if x.get(kontrola.UPOZORNENIE):
                casti.append(f"{x[kontrola.UPOZORNENIE]} upozornení")
            if x.get(kontrola.INFO):
                casti.append(f"{x[kontrola.INFO]} informácií")
            tk.Label(self.pr_kontrola, text=f"{oblast}: " + ", ".join(casti), bg=BG_OBSAH,
                     fg=CERVENA if x.get(kontrola.CHYBA) else (ORANZOVA if x.get(kontrola.UPOZORNENIE) else "#444"),
                     anchor="w").pack(anchor="w")
        ttk.Button(self.pr_kontrola, text="Zobraziť kontrolu údajov →", command=lambda: self.ukaz("kontrola")).pack(
            anchor="w", pady=(8, 0))

    # ================================================================ 1 Podmienky hodnotenia
    def _stranka_podmienky(self):
        fr = self._stranka("podmienky", "1  Podmienky hodnotenia",
                           "Dokument metodiky (metodický pokyn a jeho dodatky), podľa ktorého program počíta. Po nahratí "
                           "nového alebo aktualizovaného dokumentu program vyčíta parametre (fond, koeficienty, tabuľky "
                           "1–3, váhy, hranice záťaže, dĺžky období), ukáže zmeny a po potvrdení podľa nich prepočíta "
                           "výsledky. Dokumenty sa ukladajú do zložky „Podmienky hodnotenia“.")
        t = self._telo(fr)
        bar = ttk.Frame(t, style="Biele.TFrame")
        bar.pack(fill="x")
        ttk.Button(bar, text="📄 Nahrať dokument metodiky (PDF / DOCX)…", style="Accent.TButton",
                   command=self.nahraj_metodiku).pack(side="left")
        ttk.Button(bar, text="Otvoriť dokument", command=self.otvor_metodiku).pack(side="left", padx=4)
        ttk.Button(bar, text="✔ Použiť vybraný dokument", command=self.pouzi_vybranu_metodiku).pack(side="left")
        ttk.Button(bar, text="Odstrániť", command=self.odstran_metodiku).pack(side="left", padx=4)
        ttk.Button(bar, text="✏️ Upraviť parametre ručne…", command=self.dialog_parametre).pack(side="right")
        self.lbl_akt_metodika = ttk.Label(t, text="", style="Biele.TLabel", font=("Segoe UI", 10, "bold"),
                                          foreground=ZELENA)
        self.lbl_akt_metodika.pack(fill="x", pady=(10, 4))
        self.t_dok = Tabulka(t, [("n", "Dokument", 420), ("s", "Súbor", 300), ("u", "Účinnosť", 90),
                                 ("d", "Nahraté", 130), ("a", "Používa sa", 80)], height=4,
                             on_double=self.zobraz_parametre_dokumentu)
        self.t_dok.pack(fill="x")
        self.t_dok.tree.bind("<<TreeviewSelect>>", lambda e: self.zobraz_parametre_dokumentu())
        self.t_dok.tree.tag_configure("akt", background="#E3F1DD")
        ttk.Label(t, text="Parametre výpočtu (zvýraznené = hodnota v dokumente sa líši od hodnoty, s ktorou program počíta)",
                  style="Biele.TLabel", font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(12, 2))
        self.t_par = Tabulka(t, [("p", "Parameter", 420), ("v", "V programe", 110), ("d", "V dokumente", 110),
                                 ("c", "Úryvok z dokumentu", 560)], height=14)
        self.t_par.pack(fill="both", expand=True)
        self.t_par.tree.tag_configure("rozdiel", background="#FFF2CC")
        self.t_par.tree.tag_configure("chyba", foreground=SIVA)

    def obnov_podmienky(self):
        docs = metodika.zoznam()
        self.t_dok.nastav([(d.subor, [d.nazov, d.subor, d.ucinnost or "–", d.nahrate.replace("T", " ")[:16],
                                      "✔ áno" if d.aktivny else ""], ("akt",) if d.aktivny else ()) for d in docs])
        akt = metodika.aktivny()
        self.lbl_akt_metodika.config(text="Program počíta podľa: " + metodika.popis_aktivnej_metodiky())
        if akt and not self.t_dok.vybrane():
            self.t_dok.tree.selection_set(akt.subor)
        self.zobraz_parametre_dokumentu()

    def _vybrany_dokument(self) -> metodika.Dokument | None:
        sel = self.t_dok.vybrane()
        if not sel:
            return None
        return next((d for d in metodika.zoznam() if d.subor == sel[0]), None)

    def zobraz_parametre_dokumentu(self):
        doc = self._vybrany_dokument()
        nalezy = {n.kluc: n for n in doc.nalezy_obj()} if doc else {}
        kluce = list(dict.fromkeys(list(metodika.OCAKAVANE) + list(nalezy) + [
            f"referencna_vyucba_tyzden|{f}" for f in self.params["referencna_vyucba_tyzden"]] + [
            f"koef_odbor|{o}" for o in self.params["koef_odbor"]] + [
            f"body_publikacie|{k}|{q}" for k in self.params["body_publikacie"] for q in config.KVARTILY] + [
            f"hodiny_zaverecna_praca|{s}" for s in config.STUPNE_STUDIA]))
        riadky = []
        for i, k in enumerate(kluce):
            v = metodika._ziskaj(self.params, k)
            n = nalezy.get(k)
            if n is None and v is None:
                continue
            if n is None:
                riadky.append((i, [metodika.nazov_parametra(k), fmt(v, 3) if v is not None else "–",
                                   "nenájdené" if doc else "", ""], ("chyba",) if doc else ()))
            else:
                rozdiel = not metodika._rovnake(v, n.hodnota)
                riadky.append((i, [metodika.nazov_parametra(k), fmt(v, 3) if v is not None else "–",
                                   fmt(n.hodnota, 3) if n.hodnota is not None else "x", n.citat],
                               ("rozdiel",) if rozdiel else ()))
        self.t_par.nastav(riadky)

    def nahraj_metodiku(self):
        path = filedialog.askopenfilename(title="Dokument metodiky", filetypes=[
            ("Dokumenty", "*.pdf *.docx *.txt"), ("PDF", "*.pdf"), ("Word", "*.docx"), ("Všetky súbory", "*.*")])
        if not path:
            return
        try:
            doc, _ = metodika.pridaj_dokument(path)
        except metodika.MetodikaChyba as e:
            messagebox.showerror("Podmienky hodnotenia", str(e))
            return
        nalezy = doc.nalezy_obj()
        zmeny = metodika.porovnaj(self.params, nalezy)
        from .gui_nove import ZmenyMetodikyDialog
        self.obnov_podmienky()
        self.t_dok.tree.selection_set(doc.subor)
        ZmenyMetodikyDialog(self.root, doc, zmeny, metodika.nenajdene(nalezy),
                            on_pouzi=lambda: self._pouzi_metodiku(doc))

    def _pouzi_metodiku(self, doc: metodika.Dokument):
        self.params = metodika.pouzi(self.params, doc.nalezy_obj())
        config.save_parametre(self.params)
        metodika.aktivuj(doc.subor)
        if self.rezim_obdobia == "pokyn":
            self.obdobie = calc.obdobie_podla_pokynu(self.params, self.datum_hodnotenia)
            self._uloz_obdobie()
        self.obnov_vsetko(prepocitat=True)
        self.obnov_podmienky()
        self.status.set(f"Použité podmienky hodnotenia: {doc.nazov}. Výsledky sú prepočítané.")

    def pouzi_vybranu_metodiku(self):
        doc = self._vybrany_dokument()
        if not doc:
            messagebox.showinfo("Podmienky hodnotenia", "Vyberte dokument v zozname.")
            return
        zmeny = metodika.porovnaj(self.params, doc.nalezy_obj())
        if messagebox.askyesno("Podmienky hodnotenia", f"Počítať podľa dokumentu „{doc.nazov}“?\n\n"
                                                       f"Zmenených parametrov: {len(zmeny)}."):
            self._pouzi_metodiku(doc)

    def otvor_metodiku(self):
        doc = self._vybrany_dokument()
        if doc:
            self._otvor_subor(str(metodika.priecinok() / doc.subor))

    def odstran_metodiku(self):
        doc = self._vybrany_dokument()
        if doc and messagebox.askyesno("Odstrániť", f"Odstrániť dokument „{doc.nazov}“ z podmienok hodnotenia?\n"
                                                     "Parametre výpočtu sa nezmenia."):
            metodika.odstran(doc.subor)
            self.obnov_podmienky()
            self.obnov_hlavicku()

    # ================================================================ 2 Obdobie
    def _stranka_obdobie(self):
        fr = self._stranka("obdobie", "2  Obdobie hodnotenia",
                           "Vzdelávanie sa hodnotí za akademické roky (čl. 3: dva posledné ukončené), publikácie za "
                           "kalendárne roky s uzávierkou v CREPČ (čl. 4: tri) a projekty za verifikované kalendárne roky "
                           "(čl. 5: tri). Výsledkom je aritmetický priemer za zvolené roky. Roky môžete zvoliť podľa "
                           "pokynu, podľa načítaných údajov alebo ľubovoľne – aj jeden akademický rok.")
        t = self._telo(fr)
        rez = ttk.LabelFrame(t, text=" Spôsob určenia rokov ", style="Biele.TLabelframe", padding=10)
        rez.pack(fill="x")
        self.var_rezim = tk.StringVar(value=self.rezim_obdobia)
        r1 = ttk.Frame(rez, style="Biele.TFrame")
        r1.pack(fill="x")
        ttk.Radiobutton(r1, text="Podľa metodického pokynu k dátumu hodnotenia:", value="pokyn", variable=self.var_rezim,
                        style="Biele.TRadiobutton", command=self.zmen_rezim_obdobia).pack(side="left")
        self.var_datum = tk.StringVar(value=self.datum_hodnotenia.strftime("%d.%m.%Y"))
        e = ttk.Entry(r1, textvariable=self.var_datum, width=12)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda ev: self.zmen_rezim_obdobia())
        e.bind("<FocusOut>", lambda ev: self.zmen_rezim_obdobia() if self.var_rezim.get() == "pokyn" else None)
        ttk.Label(r1, text="(posledný rok publikácií = rok hodnotenia − "
                           f"{self.params.get('posun_rokov_publikacie', 2)}, projektov − "
                           f"{self.params.get('posun_rokov_projekty', 2)}; mení sa v parametroch)",
                  style="Biele.TLabel", foreground="#777").pack(side="left")
        ttk.Radiobutton(rez, text="Podľa načítaných údajov (najnovšie roky, za ktoré sú v programe údaje)", value="udaje",
                        variable=self.var_rezim, style="Biele.TRadiobutton", command=self.zmen_rezim_obdobia).pack(anchor="w")
        ttk.Radiobutton(rez, text="Vlastný výber rokov (zaškrtnite nižšie)", value="vlastne", variable=self.var_rezim,
                        style="Biele.TRadiobutton", command=self.zmen_rezim_obdobia).pack(anchor="w")

        stl = ttk.Frame(t, style="Biele.TFrame")
        stl.pack(fill="both", expand=True, pady=10)
        self.ob_ramce = {}
        for i, (kluc, nazov) in enumerate((("ak", "Akademické roky – vzdelávanie a záverečné práce"),
                                           ("pub", "Kalendárne roky – publikácie"),
                                           ("prj", "Kalendárne roky – projekty"))):
            lf = ttk.LabelFrame(stl, text=f" {nazov} ", style="Biele.TLabelframe", padding=8)
            lf.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            stl.columnconfigure(i, weight=1)
            vnutro = ttk.Frame(lf, style="Biele.TFrame")
            vnutro.pack(fill="both", expand=True)
            pridaj = ttk.Frame(lf, style="Biele.TFrame")
            pridaj.pack(fill="x", pady=(6, 0))
            var = tk.StringVar()
            ttk.Entry(pridaj, textvariable=var, width=12).pack(side="left")
            ttk.Button(pridaj, text="Pridať rok", command=lambda k=kluc, v=var: self._pridaj_rok(k, v)).pack(
                side="left", padx=4)
            self.ob_ramce[kluc] = (vnutro, {})
        stl.rowconfigure(0, weight=1)

        jed = ttk.LabelFrame(t, text=" Výpočet vzdelávania ", style="Biele.TLabelframe", padding=10)
        jed.pack(fill="x")
        self.var_jeden = tk.StringVar(value="jeden" if self.jeden_ak_rok else "vsetky")
        ttk.Radiobutton(jed, text="Za všetky zvolené akademické roky (aritmetický priemer, čl. 3 ods. 1)", value="vsetky",
                        variable=self.var_jeden, style="Biele.TRadiobutton", command=self._zmen_jeden).pack(anchor="w")
        r2 = ttk.Frame(jed, style="Biele.TFrame")
        r2.pack(fill="x")
        ttk.Radiobutton(r2, text="Iba za jeden akademický rok:", value="jeden", variable=self.var_jeden,
                        style="Biele.TRadiobutton", command=self._zmen_jeden).pack(side="left")
        self.cb_jeden = ttk.Combobox(r2, state="readonly", width=14)
        self.cb_jeden.pack(side="left", padx=6)
        self.cb_jeden.bind("<<ComboboxSelected>>", lambda e: self._zmen_jeden())
        dole = ttk.Frame(t, style="Biele.TFrame")
        dole.pack(fill="x", pady=(10, 0))
        self.lbl_obdobie = ttk.Label(dole, text="", style="Biele.TLabel", font=("Segoe UI", 10, "bold"),
                                     foreground=ZELENA, wraplength=900, justify="left")
        self.lbl_obdobie.pack(side="left")
        ttk.Button(dole, text="▶ Vypočítať", style="Accent.TButton", command=self.vypocitaj_a_ukaz).pack(side="right")
        self._extra_roky = {"ak": set(), "pub": set(), "prj": set()}

    def _kandidati_rokov(self) -> dict[str, list]:
        d = calc.roky_v_udajoch(self.data)
        mp = calc.obdobie_podla_pokynu(self.params, self.datum_hodnotenia)
        rok = dt.date.today().year
        ak = set(d["ak_roky"]) | set(mp.ak_roky) | set(self.obdobie.ak_roky) | self._extra_roky["ak"] | {
            calc.ak_rok_text(r) for r in range(rok - 5, rok)}
        pub = set(d["publikacie"]) | set(mp.roky_publikacie) | set(self.obdobie.roky_publikacie) | \
            self._extra_roky["pub"] | set(range(rok - 6, rok))
        prj = set(d["projekty"]) | set(mp.roky_projekty) | set(self.obdobie.roky_projekty) | \
            self._extra_roky["prj"] | set(range(rok - 6, rok))
        return {"ak": sorted(ak, key=calc.ak_rok_start), "pub": sorted(pub), "prj": sorted(prj)}

    def obnov_obdobie(self):
        kand = self._kandidati_rokov()
        d = self.data
        pocty = {
            "ak": lambda r: (f"výučba {sum(1 for v in d.vyucba if v.ak_rok == r)}, "
                             f"ZP {sum(int(z.pocet) for z in d.zaverecne_prace if z.ak_rok == r)}"),
            "pub": lambda r: f"publikácií {sum(1 for p in d.publikacie if p.rok == r)}",
            "prj": lambda r: f"projektov {sum(1 for p in d.projekty if p.rok == r)}",
        }
        vybrane = {"ak": set(self.obdobie.ak_roky), "pub": set(self.obdobie.roky_publikacie),
                   "prj": set(self.obdobie.roky_projekty)}
        for k, (ramec, premenne) in self.ob_ramce.items():
            for w in ramec.winfo_children():
                w.destroy()
            premenne.clear()
            for r in kand[k]:
                var = tk.BooleanVar(value=r in vybrane[k])
                premenne[r] = var
                ttk.Checkbutton(ramec, text=f"{r}    ({pocty[k](r)})", variable=var, style="Biele.TCheckbutton",
                                command=self._zmen_roky).pack(anchor="w")
        self.cb_jeden["values"] = kand["ak"]
        if self.jeden_ak_rok:
            self.cb_jeden.set(self.jeden_ak_rok)
        elif self.obdobie.ak_roky:
            self.cb_jeden.set(self.obdobie.ak_roky[-1])
        self.var_rezim.set(self.rezim_obdobia)
        eo = self.efektivne_obdobie()
        self.lbl_obdobie.config(text="Počíta sa: " + eo.popis() +
                                ("   (vzdelávanie iba za jeden akademický rok)" if self.jeden_ak_rok else ""))

    def _pridaj_rok(self, kluc: str, var: tk.StringVar):
        t = var.get().strip()
        try:
            if kluc == "ak":
                r = importy.to_ak_rok(t)
                if calc.ak_rok_start(r) < 1990:
                    raise ValueError
            else:
                r = int(t)
                if not 1990 <= r <= 2100:
                    raise ValueError
        except ValueError:
            messagebox.showerror("Obdobie", "Zadajte rok, napr. 2025 alebo akademický rok 2024/2025.")
            return
        self._extra_roky[kluc].add(r)
        var.set("")
        self.obnov_obdobie()

    def zmen_rezim_obdobia(self):
        self.rezim_obdobia = self.var_rezim.get()
        if self.rezim_obdobia == "pokyn":
            try:
                self.datum_hodnotenia = dt.datetime.strptime(self.var_datum.get().strip(), "%d.%m.%Y").date()
            except ValueError:
                messagebox.showerror("Obdobie", "Dátum zadajte v tvare 10.10.2026.")
                return
            self.obdobie = calc.obdobie_podla_pokynu(self.params, self.datum_hodnotenia)
        elif self.rezim_obdobia == "udaje":
            self.obdobie = calc.navrhni_obdobie(self.data, self.params)
        self._po_zmene_obdobia()

    def _zmen_roky(self):
        def vyber(k):
            return [r for r, v in self.ob_ramce[k][1].items() if v.get()]
        self.obdobie = calc.Obdobie(ak_roky=vyber("ak"), roky_publikacie=vyber("pub"), roky_projekty=vyber("prj"))
        self.rezim_obdobia = "vlastne"
        self._po_zmene_obdobia()

    def _zmen_jeden(self):
        self.jeden_ak_rok = self.cb_jeden.get() if self.var_jeden.get() == "jeden" else ""
        self._po_zmene_obdobia()

    def _po_zmene_obdobia(self):
        self._uloz_obdobie()
        self.obnov_obdobie()
        self.prepocitaj()

    # ================================================================ 3–7 údaje
    def _datova_stranka(self, kluc: str, titulok: str, popis: str, stlpce, akcie, filter_rokov: str = "",
                        nadradeny=None) -> ttk.Frame:
        if nadradeny is None:
            fr = self._stranka(kluc, titulok, popis)
            t = self._telo(fr)
        else:
            t = nadradeny
        bar = ttk.Frame(t, style="Biele.TFrame")
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="➕ Pridať", command=lambda: self.pridat(kluc)).pack(side="left")
        ttk.Button(bar, text="✏️ Upraviť", command=lambda: self.upravit(kluc)).pack(side="left", padx=4)
        ttk.Button(bar, text="🗑 Vymazať", command=lambda: self.vymazat(kluc)).pack(side="left")
        for text, cmd, styl in akcie:
            ttk.Button(bar, text=text, command=cmd, style=styl or "TButton").pack(side="right", padx=(4, 0))
        flt = ttk.Frame(t, style="Biele.TFrame")
        flt.pack(fill="x", pady=(0, 6))
        self.filtre[kluc] = {}
        ttk.Label(flt, text="Hľadať:", style="Biele.TLabel").pack(side="left")
        var = tk.StringVar()
        var.trace_add("write", lambda *_: self.obnov_tabulku(kluc))
        ttk.Entry(flt, textvariable=var, width=28).pack(side="left", padx=(4, 12))
        self.filtre[kluc]["text"] = var
        for nazov, f in (("Fakulta", "fakulta"), ("Ústav", "ustav")) + ((filter_rokov, "rok"),) if filter_rokov else (
                ("Fakulta", "fakulta"), ("Ústav", "ustav")):
            ttk.Label(flt, text=f"{nazov}:", style="Biele.TLabel").pack(side="left")
            v = tk.StringVar(value="(všetky)")
            cb = ttk.Combobox(flt, textvariable=v, state="readonly", width=26 if f == "ustav" else 12)
            cb.pack(side="left", padx=(4, 12))
            cb.bind("<<ComboboxSelected>>", lambda e, k=kluc: self.obnov_tabulku(k))
            self.filtre[kluc][f] = v
            self.filtre[kluc][f + "_cb"] = cb
        lbl = ttk.Label(flt, text="", style="Biele.TLabel", foreground=SIVA)
        lbl.pack(side="right")
        self.filtre[kluc]["lbl"] = lbl
        tab = Tabulka(t, stlpce, on_double=lambda: self.upravit(kluc))
        tab.pack(fill="both", expand=True)
        tab.tree.tag_configure("chyba", background="#FFE4E1")
        tab.tree.tag_configure("id", background="#FFF6D5")
        tab.tree.tag_configure("nezahrnuty", foreground="#888")
        tab.tree.tag_configure("mimo", foreground="#999")
        self.tabulky[kluc] = tab
        return t

    def _stranka_ucitelia(self):
        t = self._datova_stranka(
            "ucitelia", "3  Zoznam učiteľov",
            "Učitelia, ich fakulta, ústav, funkcia a prepočítaný úväzok. „Aktívny“ = časť sledovaného obdobia oblasti, "
            "keď bol učiteľ zamestnancom SPU mimo materskej/rodičovskej (chýbajúca časť sa nahradí priemerom fakulty). "
            "Červený riadok = chýbajú údaje potrebné na výpočet, žltý = chýba ORCID / Scopus Author ID / ResearcherID.",
            [("oc", "ID UIS", 60), ("meno", "Meno", 230), ("fak", "Fakulta", 60), ("ust", "Ústav", 160),
             ("fun", "Funkcia", 110), ("uv", "Úväzok", 60), ("av", "Aktív. vzd.", 70), ("ap", "Aktív. pub.", 70),
             ("aj", "Aktív. prj.", 70), ("orc", "ORCID", 150), ("sc", "Scopus ID", 100), ("wos", "ResearcherID", 100),
             ("ch", "Chýba", 220)],
            [("🆔 Doplniť ORCID / Scopus / WoS", self.dopln_identifikatory, None),
             ("🗑 Vymazať fakultu…", self.vymaz_fakultu, None),
             ("📁 Zo súboru (Excel/CSV)…", lambda: self.import_mapovanie("ucitelia"), None),
             ("👥 Načítať z UIS", self.import_uis_zamestnanci, "Accent.TButton")])
        _ = t

    def _stranka_vyucba(self):
        self._datova_stranka(
            "vyucba", "4  Výučba",
            "Priama výučba v akreditovaných študijných programoch za akademický rok (UIS – rozvrhy a počty študentov). "
            "Do záťaže sa počíta 2 × hodiny (EN / mobilitní študenti 2 × 3), 0,25 h na študenta; pre ústav študentohodiny "
            "× koeficient odboru (tab. 2). Sivé riadky sú mimo sledovaného obdobia.",
            [("uc", "Učiteľ", 220), ("ak", "Ak. rok", 80), ("pr", "Predmet", 260), ("ja", "Jazyk", 55),
             ("od", "Odbor (tab. 2)", 170), ("h", "Hodiny/rok", 80), ("st", "Študenti", 70), ("sh", "Študentohod.", 90)],
            [("📁 Zo súboru…", lambda: self.import_mapovanie("vyucba"), None),
             ("📅 Načítať z UIS (rozvrhy)", self.import_uis_vyucba, "Accent.TButton")], filter_rokov="Ak. rok")

    def _stranka_zaverecne_prace(self):
        self._datova_stranka(
            "zaverecne_prace", "5  Záverečné práce",
            "Úspešne obhájené záverečné práce podľa vedúceho / školiteľa (tab. 1: Bc 26 h, Ing 26 h, PhD 312 h).",
            [("uc", "Učiteľ", 240), ("ak", "Ak. rok", 90), ("stu", "Stupeň", 70), ("po", "Počet", 60),
             ("h", "Hodiny", 70), ("na", "Názov", 420)],
            [("📁 Zo súboru…", lambda: self.import_mapovanie("zaverecne_prace"), None),
             ("🎓 Načítať z UIS", self.import_uis_zp, "Accent.TButton")], filter_rokov="Ak. rok")

    def _stranka_projekty(self):
        fr = self._stranka("projekty", "6  Projekty",
                           "Externé projekty (pozn. 8) po kalendárnych rokoch: suma pripísaná na účet SPU (Sofia/SAP), "
                           "riešiteľská kapacita a účasť učiteľov s vykázanými hodinami (UIS). Podiel učiteľa = suma × "
                           "jeho hodiny / kapacita; zodpovedný riešiteľ výskumného projektu 2 × hodiny.")
        t = self._telo(fr)
        nb = ttk.Notebook(t)
        nb.pack(fill="both", expand=True)
        f1 = ttk.Frame(nb, padding=6)
        f2 = ttk.Frame(nb, padding=6)
        nb.add(f1, text="  Projekty  ")
        nb.add(f2, text="  Účasť učiteľov na projektoch  ")
        self._datova_stranka(
            "projekty", "", "",
            [("kod", "Kód", 130), ("rok", "Rok", 55), ("typ", "Typ", 150), ("na", "Názov", 260),
             ("suma", "Suma SPU (€)", 100), ("kap", "Kapacita (h)", 80), ("uc", "Riešitelia v DB / UIS", 110),
             ("ries", "Riešitelia (★ zodpovedný)", 330)],
            [("📁 Zo súboru…", lambda: self.import_mapovanie("projekty"), None),
             ("🔬 Načítať z UIS", self.import_uis_projekty, "Accent.TButton")], filter_rokov="Rok", nadradeny=f1)
        self._datova_stranka(
            "ucasti", "", "",
            [("pr", "Projekt", 160), ("rok", "Rok", 60), ("uc", "Učiteľ", 240), ("h", "Hodiny", 80),
             ("zod", "Zodpovedný riešiteľ", 120)],
            [("📁 Zo súboru…", lambda: self.import_mapovanie("ucasti"), None)], filter_rokov="Rok", nadradeny=f2)

    def _stranka_publikacie(self):
        self._datova_stranka(
            "publikacie", "7  Publikácie",
            "Vedecké výstupy V1–V3 s kategóriou a kvartilom podľa tab. 3 a podielom autora (CREPČ). Odporúčaný zdroj je "
            "evidencia knižnice SPU (záznamy CREPČ); publikácie zo Scopus / WoS sa s ňou porovnajú a duplicity sa "
            "nahradia záznamom knižnice.",
            [("uc", "Učiteľ", 200), ("rok", "Rok", 55), ("kat", "Kategória", 250), ("kv", "Kvartil", 60),
             ("pod", "Podiel", 60), ("body", "Body", 70), ("na", "Názov", 300), ("zd", "Zdroj", 130)],
            [("📁 Zo súboru…", lambda: self.import_mapovanie("publikacie"), None),
             ("🌐 Scopus / WoS", self.import_biblio, None),
             ("📚 Z knižnice SPU / CREPČ", self.import_epca, "Accent.TButton")], filter_rokov="Rok")

    def _ctx(self):
        return ({u.id: u for u in self.data.ucitelia}, {p.id: p for p in self.data.projekty})

    def _obnov_filtre(self):
        fak = ["(všetky)"] + sorted({u.fakulta for u in self.data.ucitelia if u.fakulta})
        ust = ["(všetky)"] + sorted({u.ustav for u in self.data.ucitelia if u.ustav})
        roky = {
            "vyucba": sorted({v.ak_rok for v in self.data.vyucba}, key=calc.ak_rok_start),
            "zaverecne_prace": sorted({z.ak_rok for z in self.data.zaverecne_prace}, key=calc.ak_rok_start),
            "publikacie": sorted({p.rok for p in self.data.publikacie}),
            "projekty": sorted({p.rok for p in self.data.projekty}),
            "ucasti": sorted({p.rok for p in self.data.projekty}),
        }
        for k, f in self.filtre.items():
            if "fakulta_cb" in f:
                f["fakulta_cb"]["values"] = fak
                f["ustav_cb"]["values"] = ust
            if "rok_cb" in f:
                f["rok_cb"]["values"] = ["(všetky)", "(sledované obdobie)"] + [str(r) for r in roky.get(k, [])]

    def obnov_tabulku(self, kluc: str):
        ucitelia, projekty = self._ctx()
        f = self.filtre[kluc]
        hladat = f["text"].get().strip().lower()
        fak, ust = f["fakulta"].get(), f["ustav"].get()
        rok_f = f["rok"].get() if "rok" in f else "(všetky)"
        obd = self.efektivne_obdobie()
        ak, pub, prj = set(obd.ak_roky), set(obd.roky_publikacie), set(obd.roky_projekty)
        meno = lambda uid: ucitelia[uid].cele_meno if uid in ucitelia else "?"  # noqa: E731

        def ok_ucitel(uid) -> bool:
            u = ucitelia.get(uid)
            if fak not in ("", "(všetky)") and (not u or u.fakulta != fak):
                return False
            if ust not in ("", "(všetky)") and (not u or u.ustav != ust):
                return False
            return True

        def ok_rok(r, v_obdobi: bool) -> bool:
            if rok_f in ("", "(všetky)"):
                return True
            if rok_f == "(sledované obdobie)":
                return v_obdobi
            return str(r) == rok_f

        riadky = []
        if kluc == "ucitelia":
            prob = kontrola.podla_ucitela([p for p in self.problemy if p.oblast == "Učitelia"])
            for u in self.data.ucitelia:
                if not ok_ucitel(u.id):
                    continue
                chyba = [p for p in prob.get(u.id, []) if p.zavaznost == kontrola.CHYBA]
                bez_id = [n for n, v in (("ORCID", u.orcid), ("Scopus", u.scopus_id), ("WoS", u.wos_id)) if not v]
                ch = ([p.popis.split(": ", 1)[-1].replace("chýba ", "").split(" (")[0] for p in chyba] + bez_id)
                tag = ("chyba",) if chyba else (("id",) if bez_id else ())
                if (u.uvazok or 0) < self.params["min_uvazok"]:
                    tag = tag + ("nezahrnuty",)
                riadky.append((u.id, [u.osobne_cislo, u.cele_meno, u.fakulta, u.ustav, u.funkcia, fmt(u.uvazok, 2),
                                      fmt(u.aktivny_vzdelavanie, 2), fmt(u.aktivny_publikacie, 2),
                                      fmt(u.aktivny_projekty, 2), u.orcid, u.scopus_id, u.wos_id, ", ".join(ch)], tag))
        elif kluc == "vyucba":
            for v in self.data.vyucba:
                if not ok_ucitel(v.ucitel_id) or not ok_rok(v.ak_rok, v.ak_rok in ak):
                    continue
                tag = ("mimo",) if v.ak_rok not in ak else (("id",) if not v.odbor else ())
                riadky.append((v.id, [meno(v.ucitel_id), v.ak_rok, v.predmet, v.jazyk, v.odbor, fmt(v.hodiny),
                                      fmt(v.pocet_studentov, 0), fmt(v.studentohodiny, 0)], tag))
        elif kluc == "zaverecne_prace":
            for z in self.data.zaverecne_prace:
                if not ok_ucitel(z.ucitel_id) or not ok_rok(z.ak_rok, z.ak_rok in ak):
                    continue
                h = self.params["hodiny_zaverecna_praca"].get(z.stupen, 0) * z.pocet
                riadky.append((z.id, [meno(z.ucitel_id), z.ak_rok, z.stupen, fmt(z.pocet, 0), fmt(h, 0), z.nazov],
                               ("mimo",) if z.ak_rok not in ak else ()))
        elif kluc == "publikacie":
            for p in self.data.publikacie:
                if not ok_ucitel(p.ucitel_id) or not ok_rok(p.rok, p.rok in pub):
                    continue
                try:
                    body = calc.body_publikacie(p, self.params)
                except ValueError:
                    body = None
                tag = ("mimo",) if p.rok not in pub else (("chyba",) if body is None else ())
                riadky.append((p.id, [meno(p.ucitel_id), p.rok, p.kategoria, p.kvartil, fmt(p.podiel, 2), fmt(body),
                                      p.nazov, p.zdroj], tag))
        elif kluc == "projekty":
            mena: dict[int, list[str]] = {}
            ucitelia_proj: dict[int, list[int]] = {}
            for uc in self.data.ucasti:
                u = ucitelia.get(uc.ucitel_id)
                ucitelia_proj.setdefault(uc.projekt_id, []).append(uc.ucitel_id)
                if u:
                    mena.setdefault(uc.projekt_id, []).append(("★ " if uc.zodpovedny else "") + u.meno)
            for p in self.data.projekty:
                if not ok_rok(p.rok, p.rok in prj):
                    continue
                if (fak not in ("", "(všetky)") or ust not in ("", "(všetky)")) and not any(
                        ok_ucitel(uid) for uid in ucitelia_proj.get(p.id, [])):
                    continue
                m = sorted(mena.get(p.id, []), key=lambda x: (not x.startswith("★"), x))
                pocet = f"{len(m)} / {p.pocet_riesitelov}" if p.pocet_riesitelov else str(len(m))
                tag = ("mimo",) if p.rok not in prj else (("chyba",) if not p.suma else ())
                riadky.append((p.id, [p.kod, p.rok, p.typ, p.nazov, fmt(p.suma, 2),
                                      fmt(p.kapacita_hodin, 0) if p.kapacita_hodin else "súčet", pocet,
                                      ", ".join(m)], tag))
        elif kluc == "ucasti":
            for uc in self.data.ucasti:
                p = projekty.get(uc.projekt_id)
                if not ok_ucitel(uc.ucitel_id) or not ok_rok(p.rok if p else "", bool(p) and p.rok in prj):
                    continue
                riadky.append((uc.id, [p.kod if p else "?", p.rok if p else "", meno(uc.ucitel_id), fmt(uc.hodiny),
                                       "áno" if uc.zodpovedny else ""], ("mimo",) if p and p.rok not in prj else ()))
        spolu = len(riadky)
        if hladat:
            riadky = [r for r in riadky if hladat in " ".join(map(str, r[1])).lower()]
        self.tabulky[kluc].nastav(riadky)
        f["lbl"].config(text=f"Zobrazených {len(riadky)} z {spolu}")

    _NAZVY_TABULIEK = {"ucitelia": "učiteľov", "vyucba": "výučbu", "zaverecne_prace": "záverečné práce",
                       "publikacie": "publikácie", "projekty": "projekty", "ucasti": "účasti"}

    def _polia(self, kluc: str) -> list[tuple]:
        ucitelia = sorted(((u.id, f"{u.cele_meno}  [{u.osobne_cislo or '–'}]  {u.ustav}") for u in self.data.ucitelia),
                          key=lambda x: x[1].lower())
        ak_roky = self._kandidati_rokov()["ak"]
        if kluc == "ucitelia":
            return [("osobne_cislo", "ID osoby v UIS / osobné číslo", "text", None),
                    ("titul_pred", "Titul pred menom", "text", None),
                    ("meno", "Priezvisko a meno *", "text", None), ("titul_za", "Titul za menom", "text", None),
                    ("fakulta", "Fakulta *", "combo", sorted({u.fakulta for u in self.data.ucitelia if u.fakulta})),
                    ("ustav", "Ústav *", "combo", sorted({u.ustav for u in self.data.ucitelia if u.ustav})),
                    ("funkcia", "Funkcia", "combo", config.FUNKCIE),
                    ("uvazok", "Prepočítaný úväzok (0–1) *", "float", None),
                    ("aktivny_vzdelavanie", "Aktívny počas obdobia – vzdelávanie (0–1)", "float", None),
                    ("aktivny_publikacie", "Aktívny počas obdobia – publikácie (0–1)", "float", None),
                    ("aktivny_projekty", "Aktívny počas obdobia – projekty (0–1)", "float", None),
                    ("orcid", "ORCID", "text", None), ("scopus_id", "Scopus Author ID", "text", None),
                    ("wos_id", "WoS ResearcherID", "text", None), ("poznamka", "Poznámka", "text", None)]
        if kluc == "vyucba":
            return [("ucitel_id", "Učiteľ *", "combo_strict", ucitelia), ("ak_rok", "Akademický rok *", "combo", ak_roky),
                    ("predmet", "Predmet", "text", None),
                    ("jazyk", "Jazyk", "combo_strict", list(config.JAZYKY_VYUCBY.items())),
                    ("odbor", "Študijný odbor (tab. 2)", "combo", list(self.params["koef_odbor"])),
                    ("hodiny", "Hodiny priamej výučby za ak. rok", "float", None),
                    ("pocet_studentov", "Počet študentov", "float", None),
                    ("studentohodiny", "Študentohodiny (0 = hodiny × študenti)", "float", None)]
        if kluc == "zaverecne_prace":
            return [("ucitel_id", "Vedúci / školiteľ *", "combo_strict", ucitelia),
                    ("ak_rok", "Akademický rok *", "combo", ak_roky),
                    ("stupen", "Stupeň", "combo_strict", config.STUPNE_STUDIA),
                    ("pocet", "Počet úspešných študentov", "float", None), ("nazov", "Názov / poznámka", "text", None)]
        if kluc == "publikacie":
            return [("ucitel_id", "Autor (učiteľ) *", "combo_strict", ucitelia), ("rok", "Rok *", "int", None),
                    ("kategoria", "Kategória (tab. 3)", "combo_strict", list(self.params["body_publikacie"])),
                    ("kvartil", "Kvartil", "combo_strict", config.KVARTILY),
                    ("podiel", "Podiel autora (0–1)", "float", None), ("nazov", "Názov", "text", None),
                    ("zdroj", "Zdroj", "combo", ["ručne", "Knižnica SPU / CREPČ", "Scopus", "WoS", "UIS"]),
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
        if kluc == "ucitelia":
            if not h["meno"].strip():
                return "Meno je povinné."
            if not 0 <= h["uvazok"] <= 1.5:
                return "Úväzok zadajte v rozsahu 0–1."
            for o in OBLASTI:
                if not 0 <= h[f"aktivny_{o}"] <= 1:
                    return "Podiel aktívneho obdobia zadajte v rozsahu 0–1."
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
        if kluc not in ("ucitelia", "projekty") and not self.data.ucitelia:
            messagebox.showinfo("Najprv učitelia", "Najprv pridajte učiteľov (alebo ich načítajte z UIS).")
            return
        cls = self._TRIEDY[kluc]
        predvolene = vars(cls()).copy()
        obd = self.efektivne_obdobie()
        if "ak_rok" in predvolene and obd.ak_roky:
            predvolene["ak_rok"] = obd.ak_roky[-1]
        if kluc == "publikacie" and obd.roky_publikacie:
            predvolene["rok"] = obd.roky_publikacie[-1]
        if kluc == "projekty" and obd.roky_projekty:
            predvolene["rok"] = obd.roky_projekty[-1]
        if kluc == "ucitelia":
            f = self.filtre["ucitelia"]
            if f["fakulta"].get() not in ("", "(všetky)"):
                predvolene["fakulta"] = f["fakulta"].get()
            if f["ustav"].get() not in ("", "(všetky)"):
                predvolene["ustav"] = f["ustav"].get()

        def ok(h):
            chyba = self._validuj(kluc, h)
            if chyba:
                return chyba
            self.db.uloz(cls(**h))
            self.obnov_vsetko(prepocitat=True)
            return None
        Formular(self.root, "Nový záznam", self._polia(kluc), predvolene, ok)

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
            self.obnov_vsetko(prepocitat=True)
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
        self.obnov_vsetko(prepocitat=True)

    def vymaz_fakultu(self):
        from .gui_nove import VymazFakultuDialog
        if not self.data.ucitelia:
            messagebox.showinfo("Vymazať fakultu", "V programe nie sú žiadni učitelia.")
            return
        VymazFakultuDialog(self.root, self.db, on_done=lambda: self.obnov_vsetko(prepocitat=True))

    def dopln_identifikatory(self):
        from .gui_nove import IdentifikatoryDialog
        sel = self.tabulky["ucitelia"].vybrane()
        ucitelia = [u for u in self.data.ucitelia if str(u.id) in sel] if len(sel) > 1 else list(self.data.ucitelia)
        IdentifikatoryDialog(self.root, self.db, ucitelia, on_done=lambda: self.obnov_vsetko(prepocitat=True))

    # ================================================================ 8 Kontrola
    def _stranka_kontrola(self):
        fr = self._stranka("kontrola", "8  Kontrola údajov",
                           "Údaje, ktoré chýbajú alebo sú neúplné pre výpočet a analýzu. Chyba = výsledok bude nesprávny; "
                           "upozornenie = výsledok môže byť skreslený; informácia na vedomie. Dvojklik prejde na záznam.")
        t = self._telo(fr)
        bar = ttk.Frame(t, style="Biele.TFrame")
        bar.pack(fill="x", pady=(0, 6))
        self.var_k = {z: tk.BooleanVar(value=True) for z in (kontrola.CHYBA, kontrola.UPOZORNENIE, kontrola.INFO)}
        for z, txt in ((kontrola.CHYBA, "chyby"), (kontrola.UPOZORNENIE, "upozornenia"), (kontrola.INFO, "informácie")):
            ttk.Checkbutton(bar, text=txt, variable=self.var_k[z], style="Biele.TCheckbutton",
                            command=self.zobraz_kontrolu).pack(side="left", padx=(0, 10))
        ttk.Label(bar, text="Oblasť:", style="Biele.TLabel").pack(side="left", padx=(10, 4))
        self.var_k_obl = tk.StringVar(value="(všetky)")
        cb = ttk.Combobox(bar, textvariable=self.var_k_obl, state="readonly", width=18, values=[
            "(všetky)", "Podmienky", "Obdobie", "Učitelia", "Výučba", "Záverečné práce", "Projekty", "Publikácie"])
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.zobraz_kontrolu())
        ttk.Button(bar, text="🔄 Skontrolovať znova", command=lambda: (self.prepocitaj(), self.zobraz_kontrolu())).pack(
            side="right")
        self.lbl_k = ttk.Label(t, text="", style="Biele.TLabel", font=("Segoe UI", 10, "bold"))
        self.lbl_k.pack(fill="x", pady=(0, 6))
        self.t_k = Tabulka(t, [("z", "Závažnosť", 100), ("o", "Oblasť", 120), ("p", "Popis", 900)],
                           on_double=self.prejdi_na_problem)
        self.t_k.pack(fill="both", expand=True)
        self.t_k.tree.tag_configure(kontrola.CHYBA, background="#FFE4E1")
        self.t_k.tree.tag_configure(kontrola.UPOZORNENIE, background="#FFF6D5")
        self.t_k.tree.tag_configure(kontrola.INFO, foreground="#555")

    def zobraz_kontrolu(self):
        obl = self.var_k_obl.get()
        riadky = []
        for i, p in enumerate(self.problemy):
            if not self.var_k[p.zavaznost].get() or (obl != "(všetky)" and p.oblast != obl):
                continue
            ikona = {"chyba": "⛔ chyba", "upozornenie": "⚠ upozornenie", "info": "ℹ info"}[p.zavaznost]
            riadky.append((i, [ikona, p.oblast, p.popis], (p.zavaznost,)))
        self.t_k.nastav(riadky)
        n = {z: sum(1 for p in self.problemy if p.zavaznost == z) for z in self.var_k}
        self.lbl_k.config(text=f"Chyby: {n[kontrola.CHYBA]}    Upozornenia: {n[kontrola.UPOZORNENIE]}    "
                               f"Informácie: {n[kontrola.INFO]}",
                          foreground=CERVENA if n[kontrola.CHYBA] else (ORANZOVA if n[kontrola.UPOZORNENIE] else ZELENA))

    def prejdi_na_problem(self):
        sel = self.t_k.vybrane()
        if not sel:
            return
        p = self.problemy[int(sel[0])]
        cie = {"Podmienky": "podmienky", "Obdobie": "obdobie"}.get(p.oblast)
        if cie:
            self.ukaz(cie)
            return
        tab = p.tabulka or {"Výučba": "vyucba", "Záverečné práce": "zaverecne_prace", "Projekty": "projekty",
                            "Publikácie": "publikacie", "Učitelia": "ucitelia"}.get(p.oblast, "ucitelia")
        stranka = "projekty" if tab == "ucasti" else tab
        self.ukaz(stranka)
        f = self.filtre[tab]
        for k in ("fakulta", "ustav"):
            f[k].set("(všetky)")
        if "rok" in f:
            f["rok"].set("(všetky)")
        if p.id is not None:
            f["text"].set("")
            self.obnov_tabulku(tab)
            if self.tabulky[tab].tree.exists(str(p.id)):
                self.tabulky[tab].tree.selection_set(str(p.id))
                self.tabulky[tab].tree.see(str(p.id))
        elif p.ucitel_id is not None:
            u = next((x for x in self.data.ucitelia if x.id == p.ucitel_id), None)
            f["text"].set(u.meno if u else "")

    # ================================================================ 9 Hodnotenie učiteľov
    def _stranka_vysledky_ucitelia(self):
        fr = self._stranka("vysledky_ucitelia", "9  Hodnotenie učiteľov",
                           "Záťaž vzdelávaním a projektmi v % fondu pracovného času (čl. 7 ods. 1.1–1.3) a porovnateľné "
                           "skóre (čl. 7 ods. 1.5): (x − min)/(max − min) × 100 z prepočítaných hodnôt v rámci fakulty, "
                           "celkové skóre 40 % vzdelávanie + 40 % publikácie + 20 % projekty. Dvojklik = rozpis výpočtu.")
        t = self._telo(fr)
        flt = ttk.Frame(t, style="Biele.TFrame")
        flt.pack(fill="x", pady=(0, 6))
        ttk.Label(flt, text="Fakulta:", style="Biele.TLabel").pack(side="left")
        self.var_f_fak = tk.StringVar(value="(všetky)")
        self.cb_fak = ttk.Combobox(flt, textvariable=self.var_f_fak, width=12, state="readonly")
        self.cb_fak.pack(side="left", padx=4)
        ttk.Label(flt, text="Ústav:", style="Biele.TLabel").pack(side="left", padx=(10, 0))
        self.var_f_ust = tk.StringVar(value="(všetky)")
        self.cb_ust = ttk.Combobox(flt, textvariable=self.var_f_ust, width=30, state="readonly")
        self.cb_ust.pack(side="left", padx=4)
        for cb in (self.cb_fak, self.cb_ust):
            cb.bind("<<ComboboxSelected>>", lambda e: self.zobraz_ucitelov())
        ttk.Button(flt, text="📥 Export do Excelu", command=self.export_vysledkov).pack(side="right")
        self.lbl_obd_u = ttk.Label(flt, text="", style="Biele.TLabel", foreground=SIVA)
        self.lbl_obd_u.pack(side="right", padx=12)
        self.lbl_suhrn = ttk.Label(t, text="", style="Biele.TLabel")
        self.lbl_suhrn.pack(fill="x", pady=(0, 4))
        nb = ttk.Notebook(t)
        nb.pack(fill="both", expand=True)
        f1, f2 = ttk.Frame(nb, padding=4), ttk.Frame(nb, padding=4)
        nb.add(f1, text="  Záťaž (čl. 7 ods. 1.1–1.3)  ")
        nb.add(f2, text="  Skóre a poradie (čl. 7 ods. 1.5)  ")
        self.t_vysl = Tabulka(f1, [
            ("meno", "Meno", 220), ("ust", "Ústav", 160), ("uv", "Úväzok", 55),
            ("vyu", "Výučba ×2 (h)", 85), ("stu", "Študenti (h)", 80), ("zp", "ZP (h)", 60),
            ("vzd", "Vzdelávanie h/ak.r.", 110), ("pvzd", "% fondu", 65), ("prj", "Projekty h/r", 80),
            ("psp", "Spolu %", 65), ("status", "Status", 220), ("tyz", "Výučba h/týž. (ref.)", 110), ("upo", "⚠", 30)],
            on_double=lambda: self.detail_ucitela(self.t_vysl))
        self.t_vysl.pack(fill="both", expand=True)
        for tag, farba in FARBY_STATUSU.items():
            self.t_vysl.tree.tag_configure(tag, background=farba)
        leg = tk.Frame(f1)
        leg.pack(fill="x", pady=(4, 0))
        for tag in ("ideal", "pod", "nad", "posudenie", "pretazenie", "nezahrnuty"):
            tk.Label(leg, text=f"  {NAZVY_STATUSU[tag]}  ", bg=FARBY_STATUSU[tag], font=("Segoe UI", 8)).pack(
                side="left", padx=2)
        self.t_skore = Tabulka(f2, [
            ("por", "Poradie", 55), ("meno", "Meno", 210), ("fak", "Fakulta", 60), ("ust", "Ústav", 150),
            ("s1", "Skóre vzd.", 75), ("s2", "Skóre pub.", 75), ("s3", "Skóre prj.", 75), ("sc", "Celkové skóre", 95),
            ("v1", "Vzdel. h (pôv.)", 90), ("v2", "Publ. body (pôv.)", 100), ("v3", "Projekty € (pôv.)", 105),
            ("p1", "Vzdel. (prep.)", 90), ("p2", "Publ. (prep.)", 90), ("p3", "Projekty (prep.)", 100)],
            on_double=lambda: self.detail_ucitela(self.t_skore))
        self.t_skore.pack(fill="both", expand=True)
        self.t_skore.tree.tag_configure("prep", foreground=MODRA)
        tk.Label(f2, text="Modrým písmom: učiteľ nebol aktívny celé obdobie – prepočítané hodnoty obsahujú priemer fakulty "
                          "za chýbajúcu časť (čl. 3 ods. 1, čl. 4 ods. 2, čl. 5 ods. 1 B).", fg=MODRA,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

    def zobraz_ucitelov(self):
        fak, ust = self.var_f_fak.get(), self.var_f_ust.get()
        riadky, riadky_s, pocty = [], [], {}
        for r in self.vysl_ucitelia:
            u = r.ucitel
            if fak not in ("", "(všetky)") and u.fakulta != fak:
                continue
            if ust not in ("", "(všetky)") and u.ustav != ust:
                continue
            tag = tag_statusu(r.status)
            pocty[tag] = pocty.get(tag, 0) + 1
            ref = f" ({fmt(r.referencna_vyucba_tyzden, 0)})" if r.referencna_vyucba_tyzden else ""
            pct = lambda x: f"{fmt(x)} %"  # noqa: E731
            riadky.append((u.id, [u.cele_meno, u.ustav, fmt(u.uvazok, 2), fmt(r.h_vyucba), fmt(r.h_studenti),
                                  fmt(r.h_zaverecne_prace), fmt(r.h_vzdelavanie), pct(r.pct_vzdelavanie),
                                  fmt(r.h_projekty), pct(r.pct_spolu), r.status, fmt(r.vyucba_tyzden) + ref,
                                  "⚠" if r.upozornenia else ""], (tag,)))
            if r.zahrnuty:
                prep = any(a < 1 for a in r.aktivita.values())
                riadky_s.append((u.id, [r.poradie, u.cele_meno, u.fakulta, u.ustav] + [fmt(r.skore.get(o), 2) for o in OBLASTI] +
                                 [fmt(r.celkove_skore, 2)] + [fmt(r.povodne[o], 0 if o != "publikacie" else 1)
                                                              for o in OBLASTI] +
                                 [fmt(r.prepocitane[o], 0 if o != "publikacie" else 1) for o in OBLASTI],
                                 ("prep",) if prep else ()))
        self.t_vysl.nastav(riadky)
        self.t_skore.nastav(sorted(riadky_s, key=lambda x: (x[1][2], x[1][0] is None, x[1][0] or 0)))
        self.lbl_suhrn.config(text=f"Učiteľov: {len(riadky)}   hodnotených (úväzok ≥ 25 %): {len(riadky_s)}   "
                                   f"ideálny stav: {pocty.get('ideal', 0)}   posúdenie ≥ 80 %: {pocty.get('posudenie', 0)}"
                                   f"   preťaženie: {pocty.get('pretazenie', 0)}")
        self.lbl_obd_u.config(text=self.efektivne_obdobie().popis())

    def detail_ucitela(self, tab: Tabulka):
        sel = tab.vybrane()
        if not sel:
            return
        r = next((x for x in self.vysl_ucitelia if str(x.ucitel.id) == sel[0]), None)
        if not r:
            return
        p = self.params
        obd = self.efektivne_obdobie()
        txt = (
            f"{r.ucitel.cele_meno}\n{r.ucitel.fakulta} – {r.ucitel.ustav}, {r.ucitel.funkcia or 'funkcia neuvedená'}\n"
            f"Úväzok {fmt(r.ucitel.uvazok, 2)} → fond {fmt(r.fond_hodin)} h/rok; aktívny: "
            + ", ".join(f"{NAZVY_OBLASTI[o].lower()} {fmt(r.aktivita[o] * 100, 0)} %" for o in OBLASTI) + "\n\n"
            f"VZDELÁVANIE (priemer za {len(obd.ak_roky)} ak. r.: {', '.join(obd.ak_roky)})\n"
            f"  priama výučba {fmt(r.hodiny_priamej_vyucby)} h × {fmt(p['koef_priprava'], 0)} "
            f"(EN/MOB × {fmt(p['koef_anglictina'], 0)}): {fmt(r.h_vyucba)} h\n"
            f"  študenti {fmt(r.pocet_studentov, 0)} × {fmt(p['hodiny_na_studenta'], 2)} h: {fmt(r.h_studenti)} h\n"
            f"  záverečné práce (tab. 1): {fmt(r.h_zaverecne_prace)} h\n"
            f"  spolu: {fmt(r.h_vzdelavanie)} h = {fmt(r.pct_vzdelavanie)} % fondu\n\n"
            f"PROJEKTY (priemer za rok): {fmt(r.h_projekty)} h, podiel na financiách {fmt(r.financie_projekty, 2)} €\n"
            f"Vzdelávanie + projekty: {fmt(r.pct_spolu)} % fondu\n\n"
            f"PUBLIKÁCIE (priemer za rok): {r.pocet_publikacii} publikácií, {fmt(r.body_publikacie, 2)} bodov\n\n"
            f"Status: {r.status}\n"
        )
        if r.zahrnuty:
            txt += "\nSKÓRE (čl. 7 ods. 1.5)          pôvodné        prepočítané     skóre\n"
            for o in OBLASTI:
                txt += (f"  {NAZVY_OBLASTI[o]:<14} {fmt(r.povodne[o], 1):>14} {fmt(r.prepocitane[o], 1):>16} "
                        f"{fmt(r.skore.get(o), 2):>10}\n")
            txt += f"  Celkové skóre: {fmt(r.celkove_skore, 2)}   poradie: {r.poradie}\n"
        if r.upozornenia:
            txt += "\nUpozornenia:\n  • " + "\n  • ".join(r.upozornenia)
        messagebox.showinfo("Rozpis výpočtu", txt)

    # ================================================================ 10 Hodnotenie ústavov
    def _stranka_vysledky_ustavy(self):
        fr = self._stranka("vysledky_ustavy", "10  Hodnotenie ústavov",
                           "Regresia bez absolútneho člena (y = b·x) výkonu ústavu voči prepočítaným úväzkom, štandardizované "
                           "rezíduá (z-skóre), sumárne skóre 40/40/20 a optimálny počet pedagógov (čl. 3–6).")
        t = self._telo(fr)
        pw = ttk.PanedWindow(t, orient="vertical")
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
        self.lbl_ust = ttk.Label(hore, text="", foreground="#8a4b00", wraplength=1100)
        self.lbl_ust.pack(fill="x", pady=4)
        pw.add(hore, weight=3)
        dole = ttk.Frame(pw)
        bar = ttk.Frame(dole)
        bar.pack(fill="x")
        ttk.Label(bar, text="Graf regresie (čl. 6, ilustračný graf 1):").pack(side="left")
        self.var_graf = tk.StringVar(value="vzdelavanie")
        for k in OBLASTI:
            ttk.Radiobutton(bar, text=NAZVY_OBLASTI[k], value=k, variable=self.var_graf,
                            command=self.kresli_graf).pack(side="left", padx=6)
        ttk.Button(bar, text="📥 Export do Excelu", command=self.export_vysledkov).pack(side="right")
        self.canvas = tk.Canvas(dole, bg="white", height=280, highlightthickness=1, highlightbackground="#ccc")
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
        regs = [f"{NAZVY_OBLASTI[k].lower()}: y = {fmt(r.b, 2)}·x" if r else f"{NAZVY_OBLASTI[k].lower()}: –"
                for k, r in self.vysl_ustavy.regresie.items()]
        self.lbl_ust.config(text="Regresia (bez abs. člena): " + ";  ".join(regs) + ("   ⚠ " + txt if txt else ""))
        self.kresli_graf()

    def kresli_graf(self):
        c = self.canvas
        c.delete("all")
        if not self.vysl_ustavy or not self.vysl_ustavy.ustavy:
            c.create_text(20, 20, anchor="nw", text="Graf sa zobrazí po výpočte.", fill="#777")
            return
        oblast = self.var_graf.get()
        reg = self.vysl_ustavy.regresie.get(oblast)
        body = [(u.uvazky_oblasti.get(oblast, u.uvazky), getattr(u, f"vykon_{oblast}"), u)
                for u in self.vysl_ustavy.ustavy]
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
            y = getattr(sel_u, f"vykon_{oblast}")
            xo = y / reg.b
            c.create_line(L, sy(y), sx(xo), sy(y), fill="#F28C00", dash=(3, 3))
            c.create_line(sx(xo), sy(y), sx(xo), H - B, fill="#F28C00", dash=(3, 3))
            c.create_text(sx(xo) + 4, H - B - 10, anchor="w", fill="#F28C00",
                          text=f"{sel_u.ustav}: optimum {fmt(xo, 2)} (stav {fmt(sel_u.uvazky_oblasti.get(oblast), 2)})")

    # ================================================================ výpočet a obnova
    def prepocitaj(self):
        obd = self.efektivne_obdobie()
        try:
            self.vysl_ucitelia = calc.vypocitaj_ucitelov(self.data, obd, self.params)
            self.vysl_ustavy = calc.vypocitaj_ustavy(self.data, obd, self.params, self.vysl_ucitelia)
        except Exception as e:  # noqa: BLE001
            self.vysl_ucitelia, self.vysl_ustavy = [], None
            messagebox.showerror("Chyba výpočtu", str(e))
        self.problemy = kontrola.skontroluj(self.data, obd, self.params, metodika_nahrata=metodika.aktivny() is not None)
        self.cb_fak["values"] = ["(všetky)", *sorted({u.fakulta for u in self.data.ucitelia if u.fakulta})]
        self.cb_ust["values"] = ["(všetky)", *sorted({u.ustav for u in self.data.ucitelia if u.ustav})]
        self.zobraz_ucitelov()
        self.zobraz_ustavy()
        for k in self.tabulky:
            self.obnov_tabulku(k)
        self.obnov_navigaciu()
        if self.aktivna == "prehlad":
            self.obnov_prehlad()
        elif self.aktivna == "kontrola":
            self.zobraz_kontrolu()

    def vypocitaj_a_ukaz(self):
        self.prepocitaj()
        n_ch = sum(1 for p in self.problemy if p.zavaznost == kontrola.CHYBA)
        self.ukaz("vysledky_ucitelia" if self.vysl_ucitelia else "kontrola")
        self.status.set(f"Vypočítané: {self.efektivne_obdobie().popis()}"
                        + (f"   ⚠ kontrola údajov našla {n_ch} chýb" if n_ch else ""))

    def obnov_navigaciu(self):
        d = self.data
        pocty = {"ucitelia": len(d.ucitelia), "vyucba": len(d.vyucba), "zaverecne_prace": len(d.zaverecne_prace),
                 "projekty": len(d.projekty), "publikacie": len(d.publikacie)}
        chyby = {}
        mapa = {"Učitelia": "ucitelia", "Výučba": "vyucba", "Záverečné práce": "zaverecne_prace",
                "Projekty": "projekty", "Publikácie": "publikacie", "Podmienky": "podmienky", "Obdobie": "obdobie"}
        for p in self.problemy:
            if p.zavaznost == kontrola.CHYBA:
                k = mapa.get(p.oblast)
                chyby[k] = chyby.get(k, 0) + 1
        for k, (f, lbl, badge) in self.nav_polozky.items():
            text, farba = "", SIVA
            if k in pocty:
                text = str(pocty[k])
            if chyby.get(k):
                text = (text + "  " if text else "") + f"⛔{chyby[k]}"
                farba = CERVENA
            if k == "kontrola":
                n = sum(1 for p in self.problemy if p.zavaznost == kontrola.CHYBA)
                text, farba = (f"⛔ {n}", CERVENA) if n else ("✔", "#1E7B34")
            if k == "podmienky" and not metodika.aktivny():
                text, farba = "!", ORANZOVA
            badge.configure(text=text, fg="white" if k == self.aktivna else farba)

    def obnov_hlavicku(self):
        self.lbl_metodika.config(text="Podmienky hodnotenia: " + metodika.popis_aktivnej_metodiky())
        zmeny = self.db.conn.total_changes != self._zmeny_pri_ulozeni
        if self.priecinok:
            self.lbl_priecinok.config(text=f"Údaje: {self.priecinok}" + ("  • neuložené zmeny" if zmeny else ""))
        else:
            self.lbl_priecinok.config(text="Údaje zatiaľ neuložené do priečinka" if self.data.ucitelia else "")

    def obnov_vsetko(self, prepocitat: bool = False):
        self.data = self.db.nacitaj_vsetko()
        if self.rezim_obdobia == "udaje":
            self.obdobie = calc.navrhni_obdobie(self.data, self.params)
        self._obnov_filtre()
        if prepocitat:
            self.prepocitaj()
        else:
            for k in self.tabulky:
                self.obnov_tabulku(k)
            self.obnov_navigaciu()
        self.obnov_obdobie()
        self.obnov_podmienky()
        self.obnov_hlavicku()
        d = self.data
        self.status.set(f"Učitelia: {len(d.ucitelia)} | výučba: {len(d.vyucba)} | záverečné práce: "
                        f"{len(d.zaverecne_prace)} | publikácie: {len(d.publikacie)} | projekty: {len(d.projekty)} | "
                        f"účasti: {len(d.ucasti)}   —   {self.efektivne_obdobie().popis()}")

    # ================================================================ uloženie / načítanie
    def uloz_udaje(self, novy: bool = False):
        ciel = self.priecinok
        if novy or not ciel:
            zaklad = ulozisko.predvoleny_priecinok()
            vybrany = filedialog.askdirectory(title="Priečinok na uloženie údajov (vytvoria sa v ňom zložky)",
                                              initialdir=str(zaklad.parent if not zaklad.exists() else zaklad),
                                              mustexist=False)
            if not vybrany:
                return
            ciel = Path(vybrany)
            if any(ciel.iterdir()) if ciel.exists() else False:
                if not ulozisko.je_priecinok_udajov(ciel):
                    ciel = ciel / "SPU-Zataz údaje"
        try:
            ulozisko.uloz(self.db, ciel, self.nastavenia.get("obdobie"), self.params)
        except PermissionError:
            messagebox.showerror("Uloženie", "Súbor sa nedá zapísať – nie je otvorený v Exceli?")
            return
        except OSError as e:
            messagebox.showerror("Uloženie", str(e))
            return
        self.priecinok = ciel
        self.nastavenia["pracovny_priecinok"] = str(ciel)
        config.save_nastavenia(self.nastavenia)
        self._zmeny_pri_ulozeni = self.db.conn.total_changes
        self.obnov_hlavicku()
        self.status.set(f"Údaje uložené do {ciel}")
        messagebox.showinfo("Uložené", f"Údaje sú uložené v priečinku\n{ciel}\n\nZložky: " +
                            ", ".join(ulozisko.ZLOZKY.values()))

    def nacitaj_udaje(self):
        vybrany = filedialog.askdirectory(title="Priečinok s uloženými údajmi",
                                          initialdir=str(self.priecinok or ulozisko.predvoleny_priecinok().parent))
        if not vybrany:
            return
        koren = Path(vybrany)
        if not ulozisko.je_priecinok_udajov(koren):
            podpriecinky = [p for p in koren.iterdir() if p.is_dir() and ulozisko.je_priecinok_udajov(p)] \
                if koren.exists() else []
            if len(podpriecinky) == 1:
                koren = podpriecinky[0]
            else:
                messagebox.showerror("Načítanie", "V priečinku nie sú uložené údaje programu "
                                                  f"(chýba zložka „{ulozisko.ZLOZKY['ucitelia']}“).")
                return
        if self.data.ucitelia and not messagebox.askyesno(
                "Načítať údaje", "Načítaním sa nahradia všetky údaje v programe údajmi z priečinka\n"
                                 f"{koren}\n\nPokračovať?"):
            return
        try:
            meta = ulozisko.nacitaj(self.db, koren)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Načítanie", f"Údaje sa nepodarilo načítať: {e}")
            return
        params = ulozisko.nacitaj_podmienky(koren)
        if params and params != self.params and messagebox.askyesno(
                "Podmienky hodnotenia", "S údajmi sú uložené aj parametre metodiky, ktoré sa líšia od aktuálnych. "
                                        "Použiť parametre uložené s údajmi?"):
            self.params = params
            config.save_parametre(params)
        o = meta.get("hodnotenie") or {}
        if o:
            self.nastavenia["obdobie"] = o
            self._nacitaj_obdobie()
        self.priecinok = koren
        self.nastavenia["pracovny_priecinok"] = str(koren)
        config.save_nastavenia(self.nastavenia)
        self._zmeny_pri_ulozeni = self.db.conn.total_changes
        self.obnov_vsetko(prepocitat=True)
        n = meta.get("nacitane", {})
        self.ukaz("prehlad")
        messagebox.showinfo("Načítané", f"Načítané z {koren}:\nučitelia {n.get('ucitelia', 0)}, výučba "
                                        f"{n.get('vyucba', 0)}, záverečné práce {n.get('zaverecne_prace', 0)}, projekty "
                                        f"{n.get('projekty', 0)}, účasti {n.get('ucasti', 0)}, publikácie "
                                        f"{n.get('publikacie', 0)}")

    def otvor_priecinok_udajov(self):
        if self.priecinok and self.priecinok.exists():
            self._otvor_subor(str(self.priecinok))
        else:
            messagebox.showinfo("Priečinok s údajmi", "Údaje ešte neboli uložené do priečinka (Súbor → Uložiť údaje).")

    def zatvor(self):
        if self.priecinok and self.db.conn.total_changes != self._zmeny_pri_ulozeni:
            odp = messagebox.askyesnocancel("Koniec", "Uložiť zmeny aj do priečinka s údajmi?\n"
                                                      f"{self.priecinok}\n\n(V programe zostanú uložené v každom prípade.)")
            if odp is None:
                return
            if odp:
                self.uloz_udaje()
        self.root.destroy()

    # ================================================================ importy
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
        self.obnov_vsetko(prepocitat=True)
        if not vysl:
            messagebox.showwarning("Import", "V súbore sa nenašli hárky šablóny.")
            return
        messagebox.showinfo("Import dokončený", "\n\n".join(f"{k}: {v.sprava()}" for k, v in vysl.items()))

    def import_mapovanie(self, typ: str = ""):
        from .gui_dialogy import ImportDialog
        d = ImportDialog(self.root, self.db, on_done=lambda: self.obnov_vsetko(prepocitat=True))
        if typ and typ in importy.TYPY:
            d.var_typ.set(importy.TYPY[typ].nazov)
            d.postav_mapovanie()

    def import_epca(self):
        from .gui_dialogy import EPCADialog
        roky = self.efektivne_obdobie().roky_publikacie or calc.obdobie_podla_pokynu(self.params).roky_publikacie
        EPCADialog(self.root, self.db, roky, on_done=lambda: self.obnov_vsetko(prepocitat=True),
                   otvor_subor=lambda: self.import_mapovanie("publikacie"))

    def import_uis_zamestnanci(self):
        from .gui_dialogy import UISZamestnanciDialog
        UISZamestnanciDialog(self.root, self.db, on_done=lambda: self.obnov_vsetko(prepocitat=True))

    def import_uis_vyucba(self):
        from .gui_dialogy import UISVyucbaDialog
        UISVyucbaDialog(self.root, self.db, self.params, on_done=lambda: self.obnov_vsetko(prepocitat=True))

    def import_uis_zp(self):
        from .gui_dialogy import UISZaverecnePraceDialog
        roky = self.efektivne_obdobie().ak_roky or calc.obdobie_podla_pokynu(self.params).ak_roky
        UISZaverecnePraceDialog(self.root, self.db, roky, self.params,
                                on_done=lambda: self.obnov_vsetko(prepocitat=True))

    def import_uis_projekty(self):
        from .gui_dialogy import UISProjektyDialog
        roky = self.efektivne_obdobie().roky_projekty or calc.obdobie_podla_pokynu(self.params).roky_projekty
        UISProjektyDialog(self.root, self.db, roky, on_done=lambda: self.obnov_vsetko(prepocitat=True))

    def import_biblio(self):
        from .gui_dialogy import BiblioDialog
        BiblioDialog(self.root, self.db, self.data, self.nastavenia, on_done=lambda: self.obnov_vsetko(prepocitat=True))

    def export_vysledkov(self):
        if not self.vysl_ucitelia:
            self.prepocitaj()
        if not self.vysl_ucitelia:
            messagebox.showinfo("Export", "Nie sú žiadne výsledky – najprv načítajte údaje.")
            return
        zaklad = (ulozisko.zlozka(self.priecinok, "vysledky") if self.priecinok else Path.home())
        path = filedialog.asksaveasfilename(
            title="Export výsledkov", defaultextension=".xlsx", initialdir=str(zaklad),
            initialfile=f"vysledky_hodnotenia_{dt.date.today():%Y-%m-%d}.xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            try:
                vystupy.export_vysledkov(path, self.vysl_ucitelia, self.vysl_ustavy, self.efektivne_obdobie(),
                                         self.params, metodika.popis_aktivnej_metodiky())
            except PermissionError:
                messagebox.showerror("Export", "Súbor sa nedá zapísať – nie je otvorený v Exceli?")
                return
            self._otvor_subor(path)

    def ukazka(self):
        if self.data.ucitelia and not messagebox.askyesno("Ukážkové údaje", "Ukážkové údaje sa pridajú k existujúcim. Pokračovať?"):
            return
        from .ukazka import napln_ukazkove_data
        napln_ukazkove_data(self.db)
        self.rezim_obdobia = "udaje"
        self.obnov_vsetko(prepocitat=True)
        self._uloz_obdobie()

    def vymazat_db(self):
        if messagebox.askyesno("Nové hodnotenie", "Naozaj vymazať všetky údaje v programe?\n\n"
                                                  "Odporúčame ich najprv uložiť do priečinka (Súbor → Uložiť údaje).",
                               icon="warning"):
            self.db.vymaz_vsetko()
            self.priecinok = None
            self.nastavenia["pracovny_priecinok"] = ""
            config.save_nastavenia(self.nastavenia)
            self.obnov_vsetko(prepocitat=True)

    # ================================================================ nastavenia
    def dialog_parametre(self):
        from .gui_dialogy import ParametreDialog

        def ulozene(p):
            self.params = p
            self.obnov_vsetko(prepocitat=True)
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
            f"Podmienky hodnotenia: {metodika.popis_aktivnej_metodiky()}\n\n"
            f"Databáza programu:\n{config.app_data_dir()}\n"
            f"Priečinok s údajmi: {self.priecinok or '–'}\n\n{updater.RELEASES_URL}")


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
        App(root)
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Chyba pri spustení", f"{type(e).__name__}: {e}")
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
