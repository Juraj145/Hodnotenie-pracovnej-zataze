"""Dialógy: identifikátory autorov, zmeny metodiky, vymazanie fakulty."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import identifikatory, metodika
from .db import Databaza
from .gui_common import Tabulka, fmt
from .gui_dialogy import _centruj


# ====================================================================== ORCID / Scopus / WoS
class IdentifikatoryDialog(tk.Toplevel):
    """Doplní učiteľom chýbajúce ORCID, Scopus Author ID a ResearcherID."""

    def __init__(self, master, db: Databaza, ucitelia: list, on_done):
        super().__init__(master)
        self.title("ORCID, Scopus Author ID, WoS ResearcherID")
        self.geometry("1150x640")
        self.transient(master)
        self.db, self.on_done = db, on_done
        self.ucitelia = [u for u in ucitelia if identifikatory.chybajuce_id(u)]
        self.vysledky: list[identifikatory.NajdeneId] = []
        self.q: queue.Queue = queue.Queue()

        ttk.Label(self, padding=10, wraplength=1110, justify="left", text=(
            f"Učitelia s chýbajúcim identifikátorom: {len(self.ucitelia)}. Program ich vyhľadá v menných autoritách "
            "Slovenskej poľnohospodárskej knižnice (ORCID) a v registri ORCID (podľa mena a pracoviska SPU); Scopus "
            "Author ID a ResearcherID prevezme z profilu ORCID, ak ich tam autor prepojil. Doplnia sa iba prázdne polia. "
            "Ak má viac osôb rovnaké meno, nič sa nedoplní – identifikátor zadajte ručne (Upraviť).")).pack(fill="x")
        self.tab = Tabulka(self, [("m", "Učiteľ", 240), ("o", "ORCID", 160), ("s", "Scopus Author ID", 130),
                                  ("w", "ResearcherID", 120), ("z", "Zdroj", 220), ("p", "Poznámka", 260)])
        self.tab.pack(fill="both", expand=True, padx=10)
        self.tab.tree.tag_configure("nic", foreground="#999")
        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        self.pb = ttk.Progressbar(dole, length=220, maximum=max(len(self.ucitelia), 1))
        self.pb.pack(side="left")
        self.lbl = ttk.Label(dole, text="")
        self.lbl.pack(side="left", padx=8)
        ttk.Button(dole, text="Zavrieť", command=self.destroy).pack(side="right")
        self.btn = ttk.Button(dole, text="💾 Uložiť nájdené", style="Accent.TButton", command=self.uloz, state="disabled")
        self.btn.pack(side="right", padx=6)
        _centruj(self, master)
        if self.ucitelia:
            threading.Thread(target=self._praca, daemon=True).start()
            self._poll()
        else:
            self.lbl.config(text="Všetci učitelia majú vyplnené ORCID, Scopus Author ID aj ResearcherID.")

    def _praca(self):
        cache: dict = {}
        for i, u in enumerate(self.ucitelia, 1):
            try:
                r = identifikatory.najdi(u, cache)
            except Exception as e:  # noqa: BLE001
                r = identifikatory.NajdeneId(ucitel_id=u.id, meno=u.cele_meno, poznamka=str(e))
            self.q.put(("r", i, r))
        self.q.put(("done", 0, None))

    def _poll(self):
        try:
            while True:
                druh, i, r = self.q.get_nowait()
                if druh == "done":
                    n = sum(1 for x in self.vysledky if x.nieco)
                    self.lbl.config(text=f"Hotovo. Nové identifikátory pre {n} z {len(self.ucitelia)} učiteľov.")
                    self.btn.config(state="normal" if n else "disabled")
                    return
                self.vysledky.append(r)
                self.pb["value"] = i
                self.lbl.config(text=f"Hľadám… {i} / {len(self.ucitelia)}: {r.meno}")
                self.tab.tree.insert("", "end", iid=str(len(self.vysledky) - 1), tags=() if r.nieco else ("nic",),
                                     values=[r.meno, r.orcid or "–", r.scopus or "–", r.wos or "–",
                                             ", ".join(r.zdroje), r.poznamka])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(200, self._poll)

    def uloz(self):
        n = 0
        for r in self.vysledky:
            if not r.nieco:
                continue
            u = self.db.ziskaj("ucitelia", r.ucitel_id)
            if not u:
                continue
            if r.orcid and not u.orcid:
                u.orcid = r.orcid
            if r.scopus and not u.scopus_id:
                u.scopus_id = r.scopus
            if r.wos and not u.wos_id:
                u.wos_id = r.wos
            self.db.uloz(u, commit=False)
            n += 1
        self.db.commit()
        self.on_done()
        self.btn.config(state="disabled")
        messagebox.showinfo("Identifikátory", f"Doplnené identifikátory pre {n} učiteľov.", parent=self)


# ====================================================================== zmeny metodiky
class ZmenyMetodikyDialog(tk.Toplevel):
    """Po nahratí dokumentu: prehľad zmien parametrov a potvrdenie ich použitia."""

    def __init__(self, master, doc: metodika.Dokument, zmeny: list[metodika.Zmena], nenajdene: list[str], on_pouzi):
        super().__init__(master)
        self.title("Nový dokument metodiky")
        self.geometry("1100x620")
        self.transient(master)
        self.on_pouzi = on_pouzi
        hl = ttk.Frame(self, padding=10)
        hl.pack(fill="x")
        ttk.Label(hl, text=doc.nazov, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(hl, text=f"Súbor: {doc.subor}   Účinnosť: {doc.ucinnost or 'neuvedená'}   "
                           f"Nájdených parametrov: {len(doc.nalezy)}", foreground="#555").pack(anchor="w")
        if zmeny:
            text = (f"Dokument mení {len(zmeny)} parametrov výpočtu oproti hodnotám, s ktorými program teraz počíta. "
                    "Po použití sa výsledky prepočítajú podľa novej metodiky.")
        else:
            text = "Hodnoty v dokumente sa zhodujú s parametrami, s ktorými program počíta – výsledky sa nezmenia."
        ttk.Label(hl, text=text, wraplength=1060).pack(anchor="w", pady=(6, 0))
        if nenajdene:
            ttk.Label(hl, foreground="#8a4b00", wraplength=1060, text=(
                "V dokumente sa nenašli (ostanú doterajšie hodnoty): " + ", ".join(metodika.nazov_parametra(k)
                                                                                  for k in nenajdene))).pack(anchor="w")
        tab = Tabulka(self, [("p", "Parameter", 380), ("s", "Doteraz", 90), ("n", "Podľa dokumentu", 110),
                             ("c", "Úryvok z dokumentu", 480)])
        tab.pack(fill="both", expand=True, padx=10)
        tab.nastav([(i, [z.nazov, fmt(z.stara, 3) if z.stara is not None else "–",
                         fmt(z.nova, 3) if z.nova is not None else "nepoužíva sa", z.citat], ())
                    for i, z in enumerate(zmeny)])
        ttk.Label(self, padding=(10, 4), foreground="#555", wraplength=1060, text=(
            "Program preberá číselné hodnoty (koeficienty, tabuľky 1–3, váhy, hranice, fond, dĺžky období). "
            "Ak dodatok mení samotný postup výpočtu, treba aktualizovať program.")).pack(fill="x")
        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        ttk.Button(dole, text="Iba uložiť dokument", command=self.destroy).pack(side="right")
        ttk.Button(dole, text="✔ Použiť parametre z dokumentu", style="Accent.TButton",
                   command=self._pouzi).pack(side="right", padx=6)
        _centruj(self, master)
        self.grab_set()

    def _pouzi(self):
        self.on_pouzi()
        self.destroy()


# ====================================================================== vymazanie fakulty
class VymazFakultuDialog(tk.Toplevel):
    def __init__(self, master, db: Databaza, on_done):
        super().__init__(master)
        self.title("Vymazať fakultu")
        self.transient(master)
        self.resizable(False, False)
        self.db, self.on_done = db, on_done
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, wraplength=420, text=(
            "Vymaže sa fakulta a všetci jej učitelia vrátane ich výučby, záverečných prác, publikácií a účastí na "
            "projektoch. Projekty, na ktorých nezostane žiadny riešiteľ, sa vymažú tiež.")).pack(anchor="w")
        self.fakulty = db.fakulty()
        self.lb = tk.Listbox(frm, height=min(max(len(self.fakulty), 3), 12), selectmode="extended", width=50,
                             font=("Segoe UI", 10))
        for f, n in self.fakulty:
            self.lb.insert("end", f"{f or '(bez fakulty)'}   –   {n} učiteľov")
        self.lb.pack(fill="x", pady=10)
        b = ttk.Frame(frm)
        b.pack(fill="x")
        ttk.Button(b, text="Zrušiť", command=self.destroy).pack(side="right")
        ttk.Button(b, text="🗑 Vymazať vybrané", command=self.vymaz).pack(side="right", padx=6)
        _centruj(self, master)
        self.grab_set()

    def vymaz(self):
        sel = [self.fakulty[i] for i in self.lb.curselection()]
        if not sel:
            return
        mena = ", ".join(f or "(bez fakulty)" for f, _ in sel)
        spolu = sum(n for _, n in sel)
        if not messagebox.askyesno("Vymazať fakultu", f"Naozaj vymazať {mena} ({spolu} učiteľov) so všetkými údajmi?\n\n"
                                                      "Odporúčame najprv uložiť údaje do priečinka.", icon="warning",
                                   parent=self):
            return
        for f, _ in sel:
            self.db.vymaz_fakultu(f)
        self.on_done()
        self.destroy()
