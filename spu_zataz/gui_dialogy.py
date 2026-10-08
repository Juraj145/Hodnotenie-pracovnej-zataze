"""Dialógy: import s mapovaním stĺpcov, Scopus/WoS, parametre, aktualizácia."""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from . import biblio, config, importy, updater
from .db import Databaza
from .gui_common import Formular, Tabulka, fmt
from .models import Data, Publikacia

NEPOUZIT = "– nepoužiť –"


def _centruj(win: tk.Toplevel, master):
    win.update_idletasks()
    x = master.winfo_rootx() + max((master.winfo_width() - win.winfo_width()) // 2, 0)
    y = master.winfo_rooty() + max((master.winfo_height() - win.winfo_height()) // 4, 0)
    win.geometry(f"+{x}+{y}")


# ====================================================================== import s mapovaním
class ImportDialog(tk.Toplevel):
    """Import ľubovoľného XLSX/CSV (export z UIS, CREPČ, Sofia…) s priradením stĺpcov."""

    def __init__(self, master, db: Databaza, on_done):
        super().__init__(master)
        self.title("Import zo súboru (UIS, CREPČ, iný export)")
        self.geometry("980x680")
        self.transient(master)
        self.db, self.on_done = db, on_done
        self.path: Path | None = None
        self.hlavicky: list[str] = []
        self.riadky: list[dict] = []
        self.combo: dict[str, ttk.Combobox] = {}

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Button(top, text="📂 Vybrať súbor…", command=self.vyber_subor).grid(row=0, column=0, sticky="w")
        self.lbl_subor = ttk.Label(top, text="žiadny súbor", foreground="#666")
        self.lbl_subor.grid(row=0, column=1, columnspan=4, sticky="w", padx=8)
        ttk.Label(top, text="Hárok:").grid(row=1, column=0, sticky="w", pady=6)
        self.var_harok = tk.StringVar()
        self.cb_harok = ttk.Combobox(top, textvariable=self.var_harok, state="readonly", width=28)
        self.cb_harok.grid(row=1, column=1, sticky="w")
        self.cb_harok.bind("<<ComboboxSelected>>", lambda e: self.nacitaj())
        ttk.Label(top, text="Typ údajov:").grid(row=1, column=2, sticky="e", padx=(16, 4))
        self.var_typ = tk.StringVar(value=importy.TYPY["vyucba"].nazov)
        cb_typ = ttk.Combobox(top, textvariable=self.var_typ, state="readonly", width=24,
                              values=[t.nazov for t in importy.TYPY.values()])
        cb_typ.grid(row=1, column=3, sticky="w")
        cb_typ.bind("<<ComboboxSelected>>", lambda e: self.postav_mapovanie())
        ttk.Label(top, text="Uložený profil:").grid(row=2, column=0, sticky="w")
        self.var_profil = tk.StringVar()
        self.cb_profil = ttk.Combobox(top, textvariable=self.var_profil, state="readonly", width=28)
        self.cb_profil.grid(row=2, column=1, sticky="w")
        self.cb_profil.bind("<<ComboboxSelected>>", lambda e: self.pouzi_profil())
        self._obnov_profily()

        self.lbl_popis = ttk.Label(self, padding=(10, 0), foreground="#1E4620")
        self.lbl_popis.pack(fill="x")
        stred = ttk.Frame(self, padding=10)
        stred.pack(fill="both", expand=True)
        self.map_frame = ttk.LabelFrame(stred, text=" Priradenie stĺpcov (pole v programe ← stĺpec v súbore) ", padding=8)
        self.map_frame.pack(side="left", fill="y")
        nahlad_f = ttk.LabelFrame(stred, text=" Náhľad súboru (prvých 30 riadkov) ", padding=4)
        nahlad_f.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.nahlad = ttk.Treeview(nahlad_f, show="headings", height=12)
        xs = ttk.Scrollbar(nahlad_f, orient="horizontal", command=self.nahlad.xview)
        self.nahlad.configure(xscrollcommand=xs.set)
        self.nahlad.pack(fill="both", expand=True)
        xs.pack(fill="x")

        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        self.var_nahradit = tk.BooleanVar(value=True)
        ttk.Checkbutton(dole, text="Nahradiť existujúce záznamy za roky obsiahnuté v súbore (bez duplicít)",
                        variable=self.var_nahradit).pack(side="left")
        ttk.Button(dole, text="Zavrieť", command=self.destroy).pack(side="right")
        ttk.Button(dole, text="⬇ Importovať", style="Accent.TButton", command=self.importuj).pack(side="right", padx=6)
        ttk.Button(dole, text="💾 Uložiť mapovanie ako profil", command=self.uloz_profil).pack(side="right")
        self.postav_mapovanie()
        _centruj(self, master)

    def _typ(self) -> importy.TypImportu:
        return next(t for t in importy.TYPY.values() if t.nazov == self.var_typ.get())

    def _obnov_profily(self):
        self.profily = importy.nacitaj_profily()
        self.cb_profil["values"] = list(self.profily)

    def vyber_subor(self):
        p = filedialog.askopenfilename(parent=self, title="Súbor na import",
                                       filetypes=[("Excel / CSV", "*.xlsx *.xlsm *.csv *.txt"), ("Všetky", "*.*")])
        if not p:
            return
        self.path = Path(p)
        self.lbl_subor.config(text=str(self.path))
        harky = importy.harky_suboru(self.path)
        self.cb_harok["values"] = harky
        self.var_harok.set(harky[0] if harky else "")
        # odhad typu podľa názvu hárku
        for t in importy.TYPY.values():
            if self.var_harok.get() and importy.norm(t.nazov) == importy.norm(self.var_harok.get()):
                self.var_typ.set(t.nazov)
        self.nacitaj()

    def nacitaj(self):
        if not self.path:
            return
        try:
            self.hlavicky, self.riadky = importy.nacitaj_subor(self.path, self.var_harok.get() or None)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Súbor", f"Súbor sa nepodarilo načítať: {e}", parent=self)
            return
        self.nahlad.delete(*self.nahlad.get_children())
        ids = [f"c{i}" for i in range(len(self.hlavicky))]
        self.nahlad["columns"] = ids
        for cid, h in zip(ids, self.hlavicky):
            self.nahlad.heading(cid, text=h)
            self.nahlad.column(cid, width=110, stretch=False)
        for r in self.riadky[:30]:
            self.nahlad.insert("", "end", values=[importy.to_str(r.get(h)) for h in self.hlavicky])
        self.postav_mapovanie()

    def postav_mapovanie(self, mapovanie: dict | None = None):
        for w in self.map_frame.winfo_children():
            w.destroy()
        typ = self._typ()
        self.lbl_popis.config(text=typ.popis + "  Povinné polia sú označené *.")
        mapovanie = mapovanie or importy.automaticke_mapovanie(typ, self.hlavicky)
        self.combo = {}
        hodnoty = [NEPOUZIT, *self.hlavicky]
        for i, s in enumerate(typ.stlpce):
            ttk.Label(self.map_frame, text=s.hlavicka + (" *" if s.povinny else "")).grid(row=i, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(self.map_frame, values=hodnoty, state="readonly", width=28)
            m = mapovanie.get(s.pole)
            cb.set(m if m in self.hlavicky else NEPOUZIT)
            cb.grid(row=i, column=1, padx=6)
            self.combo[s.pole] = cb
        if typ.kluc not in ("ucitelia", "projekty"):
            ttk.Label(self.map_frame, text="Učiteľa identifikuje osobné číslo, inak meno.\n"
                                           "Neznámi učitelia sa založia automaticky.",
                      foreground="#666").grid(row=len(typ.stlpce), column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _mapovanie(self) -> dict:
        return {k: (cb.get() if cb.get() != NEPOUZIT else None) for k, cb in self.combo.items()}

    def pouzi_profil(self):
        p = self.profily.get(self.var_profil.get())
        if not p:
            return
        self.var_typ.set(importy.TYPY[p["typ"]].nazov)
        self.postav_mapovanie(p["mapovanie"])

    def uloz_profil(self):
        nazov = simpledialog.askstring("Profil mapovania", "Názov profilu (napr. „UIS – rozvrh“):", parent=self)
        if nazov:
            importy.uloz_profil(nazov, self._typ().kluc, self._mapovanie())
            self._obnov_profily()
            self.var_profil.set(nazov)

    def importuj(self):
        if not self.riadky:
            messagebox.showwarning("Import", "Najprv vyberte súbor s údajmi.", parent=self)
            return
        typ, m = self._typ(), self._mapovanie()
        chyba = [s.hlavicka for s in typ.stlpce if s.povinny and not m.get(s.pole)]
        if typ.kluc not in ("ucitelia", "projekty") and not (m.get("osobne_cislo") or m.get("meno")):
            chyba.append("Osobné číslo alebo Meno")
        if chyba:
            messagebox.showwarning("Mapovanie", "Priraďte povinné polia: " + ", ".join(chyba), parent=self)
            return
        zdroj = "UIS" if "uis" in str(self.path).lower() else ("CREPČ" if "crep" in str(self.path).lower() else "súbor")
        res = importy.importuj(self.db, typ.kluc, self.riadky, m, nahradit=self.var_nahradit.get(), zdroj=zdroj)
        self.on_done()
        messagebox.showinfo("Import dokončený", res.sprava(), parent=self)


# ====================================================================== Scopus / WoS
class BiblioDialog(tk.Toplevel):
    def __init__(self, master, db: Databaza, data: Data, nastavenia: dict, on_done):
        super().__init__(master)
        self.title("Publikácie zo Scopus / Web of Science")
        self.geometry("1150x640")
        self.transient(master)
        self.db, self.data, self.nastavenia, self.on_done = db, data, nastavenia, on_done
        self.najdene: list[tuple[int, biblio.NajdenaPublikacia]] = []
        self.q: queue.Queue = queue.Queue()

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Učiteľ:").grid(row=0, column=0, sticky="w")
        self.ucitelia = [(u.id, f"{u.cele_meno} – Scopus: {u.scopus_id or '–'}, WoS: {u.wos_id or u.orcid or '–'}")
                         for u in data.ucitelia]
        self.var_uc = tk.StringVar(value="(všetci s vyplneným Scopus / WoS ID)")
        ttk.Combobox(top, textvariable=self.var_uc, state="readonly", width=70,
                     values=["(všetci s vyplneným Scopus / WoS ID)", *[t for _, t in self.ucitelia]]).grid(row=0, column=1, columnspan=5, sticky="w")
        ttk.Label(top, text="Roky od – do:").grid(row=1, column=0, sticky="w", pady=6)
        import datetime as dt
        r = dt.date.today().year - 1
        self.var_od, self.var_do = tk.StringVar(value=str(r - 2)), tk.StringVar(value=str(r))
        ttk.Entry(top, textvariable=self.var_od, width=6).grid(row=1, column=1, sticky="w")
        ttk.Entry(top, textvariable=self.var_do, width=6).grid(row=1, column=2, sticky="w")
        self.var_sc, self.var_wos, self.var_q = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar()
        ttk.Checkbutton(top, text="Scopus", variable=self.var_sc).grid(row=1, column=3, padx=8)
        ttk.Checkbutton(top, text="Web of Science", variable=self.var_wos).grid(row=1, column=4)
        ttk.Checkbutton(top, text="Navrhnúť kvartil podľa CiteScore (len orientačne)", variable=self.var_q).grid(row=1, column=5, padx=8)
        ttk.Button(top, text="🔎 Vyhľadať", style="Accent.TButton", command=self.hladaj).grid(row=0, column=6, rowspan=2, padx=10)

        ttk.Label(self, padding=(10, 0), foreground="#8a4b00", wraplength=1100, text=(
            "Pozor: metodika určuje kvartil V2/V3 podľa AIS (JCR) a podiel autora podľa CREPČ. API tieto údaje "
            "neposkytuje v požadovanej podobe – pred importom skontrolujte kategóriu, kvartil a podiel (dvojklik na riadok). "
            "Podiel je predvyplnený ako 1 / počet autorov.")).pack(fill="x")
        self.tab = Tabulka(self, [("uc", "Učiteľ", 170), ("rok", "Rok", 50), ("na", "Názov", 300), ("cas", "Časopis", 180),
                                  ("typ", "Typ", 90), ("kat", "Kategória", 200), ("kv", "Kvartil", 60),
                                  ("pod", "Podiel", 60), ("zd", "Zdroj", 60), ("dup", "V databáze", 80)],
                           on_double=self.uprav)
        self.tab.pack(fill="both", expand=True, padx=10, pady=6)
        self.tab.tree.tag_configure("dup", foreground="#999")
        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        self.lbl = ttk.Label(dole, text="")
        self.lbl.pack(side="left")
        ttk.Button(dole, text="Zavrieť", command=self.destroy).pack(side="right")
        ttk.Button(dole, text="⬇ Importovať vybrané", style="Accent.TButton", command=self.importuj).pack(side="right", padx=6)
        ttk.Button(dole, text="Vybrať nové", command=self.vyber_nove).pack(side="right")
        _centruj(self, master)

    def _existujuce_id(self) -> set:
        return {(p.ucitel_id, (p.identifikator or "").lower()) for p in self.data.publikacie if p.identifikator}

    def hladaj(self):
        try:
            od, do = int(self.var_od.get()), int(self.var_do.get())
        except ValueError:
            messagebox.showerror("Roky", "Zadajte roky ako čísla.", parent=self)
            return
        vyber = self.var_uc.get()
        if vyber.startswith("("):
            ucitelia = [u for u in self.data.ucitelia if u.scopus_id or u.wos_id or u.orcid]
        else:
            uid = next(i for i, t in self.ucitelia if t == vyber)
            ucitelia = [u for u in self.data.ucitelia if u.id == uid]
        if not ucitelia:
            messagebox.showinfo("Scopus / WoS", "Žiadny učiteľ nemá vyplnené Scopus Author ID, ResearcherID ani ORCID "
                                                "(karta Učitelia → Upraviť).", parent=self)
            return
        n = self.nastavenia
        sc, wos, navrh = self.var_sc.get(), self.var_wos.get(), self.var_q.get()

        def praca():
            vysl, chyby = [], []
            for u in ucitelia:
                pubs = []
                try:
                    if sc and u.scopus_id:
                        pubs += biblio.scopus_publikacie(u.scopus_id, od, do, n.get("scopus_api_key", ""),
                                                         n.get("scopus_insttoken", ""), navrh,
                                                         progress=lambda t: self.q.put(("msg", f"{u.meno}: {t}")))
                    wid = u.wos_id or u.orcid
                    if wos and wid:
                        pubs += biblio.wos_publikacie(wid, od, do, n.get("wos_api_key", ""),
                                                      progress=lambda t: self.q.put(("msg", f"{u.meno}: {t}")))
                except biblio.BiblioChyba as e:
                    chyby.append(f"{u.meno}: {e}")
                for p in biblio.odstran_duplicity(pubs):
                    vysl.append((u.id, p))
            self.q.put(("done", (vysl, chyby)))

        self.lbl.config(text="Hľadám…")
        threading.Thread(target=praca, daemon=True).start()
        self._poll()

    def _poll(self):
        try:
            while True:
                druh, obsah = self.q.get_nowait()
                if druh == "msg":
                    self.lbl.config(text=obsah)
                else:
                    self.najdene, chyby = obsah
                    self.zobraz()
                    if chyby:
                        messagebox.showwarning("Scopus / WoS", "\n".join(chyby), parent=self)
                    return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(250, self._poll)

    def zobraz(self):
        meno = {u.id: u.cele_meno for u in self.data.ucitelia}
        exist = self._existujuce_id()
        riadky = []
        for i, (uid, p) in enumerate(self.najdene):
            dup = (uid, (p.identifikator or "").lower()) in exist or (uid, (p.doi or "").lower()) in exist
            riadky.append((i, [meno.get(uid, "?"), p.rok, p.nazov, p.casopis, p.typ, p.kategoria, p.kvartil,
                               fmt(p.podiel, 2), p.zdroj, "áno" if dup else ""], ("dup",) if dup else ()))
        self.tab.nastav(riadky)
        self.vyber_nove()
        self.lbl.config(text=f"Nájdených {len(self.najdene)} publikácií.")

    def vyber_nove(self):
        nove = [iid for iid in self.tab.tree.get_children() if "dup" not in self.tab.tree.item(iid, "tags")]
        self.tab.tree.selection_set(nove)

    def uprav(self):
        sel = self.tab.vybrane()
        if not sel:
            return
        i = int(sel[0])
        uid, p = self.najdene[i]

        def ok(h):
            if not (0 < h["podiel"] <= 1):
                return "Podiel zadajte v rozsahu 0–1."
            p.kategoria, p.kvartil, p.podiel = h["kategoria"], h["kvartil"], h["podiel"]
            self.zobraz()
            self.tab.tree.selection_set(sel)
            return None
        Formular(self, "Upraviť pred importom", [
            ("kategoria", "Kategória (tab. 3)", "combo_strict", config.KATEGORIE_PUBLIKACII),
            ("kvartil", "Kvartil (podľa AIS)", "combo_strict", config.KVARTILY),
            ("podiel", "Podiel autora (0–1, podľa CREPČ)", "float", None)],
            {"kategoria": p.kategoria, "kvartil": p.kvartil, "podiel": p.podiel}, ok)

    def importuj(self):
        sel = self.tab.vybrane()
        if not sel:
            return
        for iid in sel:
            uid, p = self.najdene[int(iid)]
            self.db.uloz(Publikacia(ucitel_id=uid, rok=p.rok, kategoria=p.kategoria, kvartil=p.kvartil, podiel=p.podiel,
                                    nazov=p.nazov, zdroj=p.zdroj, identifikator=p.doi or p.identifikator), commit=False)
        self.db.commit()
        self.on_done()
        self.data = self.db.nacitaj_vsetko()
        self.zobraz()
        messagebox.showinfo("Import", f"Importovaných {len(sel)} publikácií.", parent=self)


# ====================================================================== parametre
class ParametreDialog(tk.Toplevel):
    def __init__(self, master, params: dict, on_save):
        super().__init__(master)
        self.title("Parametre metodiky")
        self.geometry("820x640")
        self.transient(master)
        self.on_save = on_save
        ttk.Label(self, padding=10, wraplength=780, text=(
            "Hodnoty podľa Metodického pokynu 1/2023 v znení Dodatku č. 2. Pri ďalšom dodatku ich môžete upraviť tu – "
            "uložia sa do súboru parametre.json v priečinku s dátami. Tlačidlom „Predvolené“ sa vrátite k hodnotám pokynu.\n"
            "en_koef_nasobi_pripravu: true = hodina výučby v EN sa počíta 2 × 3 = 6 h; false = 3 h.")).pack(fill="x")
        self.text = scrolledtext.ScrolledText(self, font=("Consolas", 10), undo=True)
        self.text.pack(fill="both", expand=True, padx=10)
        self.text.insert("1.0", json.dumps(params, ensure_ascii=False, indent=2))
        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        ttk.Button(dole, text="Predvolené", command=self.predvolene).pack(side="left")
        ttk.Button(dole, text="Zrušiť", command=self.destroy).pack(side="right")
        ttk.Button(dole, text="Uložiť", style="Accent.TButton", command=self.uloz).pack(side="right", padx=6)
        _centruj(self, master)

    def predvolene(self):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", json.dumps(config.DEFAULT_PARAMETRE, ensure_ascii=False, indent=2))

    def uloz(self):
        try:
            p = json.loads(self.text.get("1.0", "end"))
            p = config._merge(config.DEFAULT_PARAMETRE, p)
            float(p["fond_hodin_rok"])
            assert abs(sum(p["vahy"].values()) - 1) < 1e-6, "Súčet váh musí byť 1."
        except (ValueError, KeyError, AssertionError) as e:
            messagebox.showerror("Parametre", f"Neplatné parametre: {e}", parent=self)
            return
        config.save_parametre(p)
        self.on_save(p)
        self.destroy()


# ====================================================================== aktualizácia
class AktualizaciaDialog(tk.Toplevel):
    def __init__(self, master, v: updater.Vydanie, nastavenia: dict):
        super().__init__(master)
        self.title("Nová verzia programu")
        self.transient(master)
        self.resizable(False, False)
        self.master_root, self.v, self.nastavenia = master, v, nastavenia
        f = ttk.Frame(self, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"Je dostupná verzia {v.verzia} (používate {updater.__version__}).",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        if v.poznamky:
            t = scrolledtext.ScrolledText(f, height=10, width=70, wrap="word")
            t.insert("1.0", v.poznamky)
            t.config(state="disabled")
            t.pack(fill="both", pady=8)
        self.pb = ttk.Progressbar(f, length=480, mode="determinate")
        self.pb.pack(fill="x", pady=6)
        self.lbl = ttk.Label(f, text="")
        self.lbl.pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(8, 0))
        if updater.vie_aktualizovat(v):
            self.btn = ttk.Button(b, text="Aktualizovať teraz", style="Accent.TButton", command=self.aktualizuj)
        else:
            self.btn = ttk.Button(b, text="Otvoriť stránku na stiahnutie", style="Accent.TButton",
                                  command=lambda: webbrowser.open(v.url_stranky))
        self.btn.pack(side="right")
        ttk.Button(b, text="Neskôr", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(b, text="Preskočiť túto verziu", command=self.preskocit).pack(side="left")
        _centruj(self, master)
        self.grab_set()

    def preskocit(self):
        self.nastavenia["preskocena_verzia"] = self.v.verzia
        config.save_nastavenia(self.nastavenia)
        self.destroy()

    def aktualizuj(self):
        self.btn.config(state="disabled")
        q: queue.Queue = queue.Queue()

        def praca():
            try:
                novy = updater.stiahni(self.v, progress=lambda d, t: q.put(("p", d, t)))
                q.put(("ok", novy, 0))
            except Exception as e:  # noqa: BLE001
                q.put(("err", str(e), 0))

        def poll():
            try:
                while True:
                    druh, a, b = q.get_nowait()
                    if druh == "p":
                        if b:
                            self.pb["value"] = 100 * a / b
                        self.lbl.config(text=f"Sťahujem… {a / 1e6:.1f} MB" + (f" z {b / 1e6:.1f} MB" if b else ""))
                    elif druh == "ok":
                        self.lbl.config(text="Inštalujem a reštartujem…")
                        try:
                            updater.nainstaluj_a_restartuj(a)
                        except Exception as e:  # noqa: BLE001
                            messagebox.showerror("Aktualizácia", str(e), parent=self)
                            return
                        # nová verzia už beží – táto sa musí hneď ukončiť
                        self.master_root.after(200, lambda: (self.master_root.destroy(), os._exit(0)))
                        return
                    else:
                        messagebox.showerror("Aktualizácia zlyhala", a, parent=self)
                        self.btn.config(state="normal")
                        return
            except queue.Empty:
                pass
            self.after(200, poll)

        threading.Thread(target=praca, daemon=True).start()
        poll()


# ====================================================================== zamestnanci z UIS
class UISZamestnanciDialog(tk.Toplevel):
    """Načítanie učiteľov a ich priradenia k ústavom z verejného zoznamu zamestnancov v UIS."""

    def __init__(self, master, db: Databaza, on_done):
        from . import uis_web
        self.uis = uis_web
        super().__init__(master)
        self.title("Učitelia a ústavy z UIS (is.uniag.sk)")
        self.geometry("1180x700")
        self.transient(master)
        self.db, self.on_done = db, on_done
        self.q: queue.Queue = queue.Queue()
        self.fakulty: list = []
        self.pracoviska: list = []           # Pracovisko
        self.fakulta_skratka = ""
        self.nacitani: list = []             # (Zamestnanec, fakulta, ústav)

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Fakulta:").grid(row=0, column=0, sticky="w")
        self.var_fak = tk.StringVar()
        self.cb_fak = ttk.Combobox(top, textvariable=self.var_fak, state="readonly", width=48)
        self.cb_fak.grid(row=0, column=1, sticky="w")
        self.cb_fak.bind("<<ComboboxSelected>>", lambda e: self.nacitaj_pracoviska())
        ttk.Label(top, text="alebo odkaz / ID pracoviska z UIS:").grid(row=0, column=2, sticky="e", padx=(18, 4))
        self.var_odkaz = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_odkaz, width=40).grid(row=0, column=3, sticky="w")
        ttk.Button(top, text="Pridať", command=self.pridaj_odkaz).grid(row=0, column=4, padx=4)
        ttk.Button(top, text="Zo súboru HTML…", command=self.zo_suboru).grid(row=0, column=5, padx=(14, 0))

        opt = ttk.Frame(self, padding=(10, 0))
        opt.pack(fill="x")
        self.var_ped = tk.BooleanVar(value=True)
        self.var_ext = tk.BooleanVar(value=False)
        self.var_nazov = tk.StringVar(value="plny")
        ttk.Checkbutton(opt, text="iba pedagógovia (profesor, docent, odborný asistent, lektor)",
                        variable=self.var_ped, command=self.zobraz).pack(side="left")
        ttk.Checkbutton(opt, text="aj externí pracovníci", variable=self.var_ext, command=self.zobraz).pack(side="left", padx=12)
        ttk.Label(opt, text="Názov ústavu:").pack(side="left", padx=(20, 4))
        ttk.Radiobutton(opt, text="plný", value="plny", variable=self.var_nazov, command=self.zobraz).pack(side="left")
        ttk.Radiobutton(opt, text="skratka", value="skratka", variable=self.var_nazov, command=self.zobraz).pack(side="left")

        stred = ttk.Frame(self, padding=10)
        stred.pack(fill="both", expand=True)
        lf = ttk.LabelFrame(stred, text=" Pracoviská (vyberte jedno alebo viac) ", padding=4)
        lf.pack(side="left", fill="y")
        self.t_prac = Tabulka(lf, [("id", "ID", 50), ("sk", "Skratka", 70), ("na", "Názov", 260)], height=18)
        self.t_prac.pack(fill="both", expand=True)
        ttk.Button(lf, text="⬇ Načítať zamestnancov", style="Accent.TButton",
                   command=self.nacitaj_zamestnancov).pack(fill="x", pady=(6, 0))
        rf = ttk.LabelFrame(stred, text=" Zamestnanci (vybrané riadky sa uložia) ", padding=4)
        rf.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.t_zam = Tabulka(rf, [("id", "ID v UIS", 70), ("meno", "Priezvisko a meno", 190), ("tp", "Titul pred", 90),
                                  ("tz", "Titul za", 80), ("zar", "Zaradenie", 140), ("ust", "Ústav", 220),
                                  ("stav", "V databáze", 150)], height=18)
        self.t_zam.pack(fill="both", expand=True)
        self.t_zam.tree.tag_configure("novy", background="#C6EFCE")
        self.t_zam.tree.tag_configure("zmena", background="#FFF2CC")

        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        self.lbl = ttk.Label(dole, text="Načítavam zoznam fakúlt…")
        self.lbl.pack(side="left")
        ttk.Button(dole, text="Zavrieť", command=self.destroy).pack(side="right")
        ttk.Button(dole, text="💾 Uložiť vybraných do databázy", style="Accent.TButton",
                   command=self.uloz).pack(side="right", padx=6)
        _centruj(self, master)
        self._spusti(self.uis.fakulty, self._fakulty_hotove)

    # ---------------------------------------------------------------- vlákna
    def _spusti(self, funkcia, hotovo, *args):
        def praca():
            try:
                self.q.put(("ok", hotovo, funkcia(*args)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", hotovo, e))
        threading.Thread(target=praca, daemon=True).start()
        self._poll()

    def _poll(self):
        try:
            druh, hotovo, vysl = self.q.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(200, self._poll)
            return
        if druh == "err":
            self.lbl.config(text="Chyba pri načítaní.")
            messagebox.showerror("UIS", f"{vysl}\n\nAk nie ste v sieti univerzity alebo UIS stránku nevydá, "
                                        "uložte zoznam zamestnancov v prehliadači (Ctrl+S) a použite „Zo súboru HTML…“.",
                                 parent=self)
            return
        hotovo(vysl)

    # ---------------------------------------------------------------- fakulty a pracoviská
    def _fakulty_hotove(self, fakulty):
        self.fakulty = fakulty
        self.cb_fak["values"] = [p.nazov for p in fakulty]
        self.lbl.config(text="Vyberte fakultu.")
        tf = next((i for i, p in enumerate(fakulty) if p.id == 30), None)
        if tf is not None:
            self.cb_fak.current(tf)
            self.nacitaj_pracoviska()

    def nacitaj_pracoviska(self):
        p = next((f for f in self.fakulty if f.nazov == self.var_fak.get()), None)
        if not p:
            return
        self.lbl.config(text="Načítavam pracoviská…")
        self._spusti(self.uis.fakulta_a_pracoviska, self._pracoviska_hotove, p.id)

    def _pracoviska_hotove(self, vysl):
        self.fakulta_skratka, prac = vysl
        self.pracoviska = prac
        self.t_prac.nastav([(p.id, [p.id, p.skratka, p.nazov], ()) for p in prac])
        ustavy = [str(p.id) for p in prac if p.nazov.lower().startswith(("ústav", "katedra"))]
        self.t_prac.tree.selection_set(ustavy)
        self.lbl.config(text=f"{self.fakulta_skratka}: {len(prac)} pracovísk. Označené sú ústavy.")

    def pridaj_odkaz(self):
        pid = self.uis.id_z_odkazu(self.var_odkaz.get())
        if not pid:
            messagebox.showwarning("UIS", "Zadajte odkaz na pracovisko alebo zoznam zamestnancov, alebo číslo ID.", parent=self)
            return

        def zisti(pid):
            fak_id, fak_sk, sk = self.uis.info_o_pracovisku(pid)
            nazov = sk
            if fak_id:
                _, prac = self.uis.fakulta_a_pracoviska(fak_id)
                nazov = next((p.nazov for p in prac if p.id == pid), sk)
            return fak_sk, self.uis.Pracovisko(id=pid, nazov=nazov, skratka=sk)

        def hotovo(vysl):
            fak_sk, p = vysl
            self.fakulta_skratka = self.fakulta_skratka or fak_sk
            if all(x.id != p.id for x in self.pracoviska):
                self.pracoviska.append(p)
                self.t_prac.tree.insert("", "end", iid=str(p.id), values=[p.id, p.skratka, p.nazov])
            self.t_prac.tree.selection_add(str(p.id))
            self.lbl.config(text=f"Pridané: {p.nazov}")
        self._spusti(zisti, hotovo, pid)

    # ---------------------------------------------------------------- zamestnanci
    def _nazov_ustavu(self, p) -> str:
        if isinstance(p, str):
            return p
        return (p.skratka or p.nazov) if self.var_nazov.get() == "skratka" else p.nazov

    def nacitaj_zamestnancov(self):
        vybrane = [p for p in self.pracoviska if str(p.id) in self.t_prac.vybrane()]
        if not vybrane:
            messagebox.showinfo("UIS", "Vyberte aspoň jedno pracovisko.", parent=self)
            return
        fak = self.fakulta_skratka

        def praca():
            out = []
            for p in vybrane:
                for z in self.uis.zamestnanci_pracoviska(p.id):
                    out.append((z, fak, p))
            return out

        def hotovo(vysl):
            self.nacitani = vysl
            self.zobraz()
        self.lbl.config(text=f"Načítavam zamestnancov ({len(vybrane)} pracovísk)…")
        self._spusti(praca, hotovo)

    def zo_suboru(self):
        path = filedialog.askopenfilename(parent=self, title="Uložená stránka „Zoznam zamestnancov“ z UIS",
                                          filetypes=[("Webová stránka", "*.html *.htm"), ("Všetky", "*.*")])
        if not path:
            return
        html = Path(path).read_bytes().decode("utf-8", errors="replace")
        zoznam = self.uis.zamestnanci(html)
        if not zoznam:
            messagebox.showwarning("UIS", "V súbore sa nenašiel zoznam zamestnancov z UIS.", parent=self)
            return
        fak = simpledialog.askstring("Fakulta", "Skratka fakulty (napr. TF):", parent=self,
                                     initialvalue=self.fakulta_skratka or "")
        ustav = simpledialog.askstring("Ústav", "Názov ústavu, ku ktorému patria:", parent=self)
        if not ustav:
            return
        self.nacitani = [(z, fak or "", ustav) for z in zoznam]
        self.zobraz()

    def _viditelni(self):
        out = []
        for i, (z, fak, ust) in enumerate(self.nacitani):
            if self.var_ped.get() and not z.je_pedagog and not (self.var_ext.get() and z.externy):
                continue
            if z.externy and not self.var_ext.get():
                continue
            out.append((i, z, fak, self._nazov_ustavu(ust)))
        return out

    def zobraz(self):
        existujuci = {u.osobne_cislo: u for u in self.db.nacitaj("ucitelia") if u.osobne_cislo}
        riadky = []
        for i, z, fak, ust in self._viditelni():
            u = existujuci.get(z.uis_id)
            if u is None:
                stav, tag = "nový", ("novy",)
            elif u.ustav != ust:
                stav, tag = f"zmena ústavu (z {u.ustav or '–'})", ("zmena",)
            else:
                stav, tag = "už je, aktualizuje sa", ()
            riadky.append((i, [z.uis_id, z.meno, z.titul_pred, z.titul_za, z.zaradenie, ust, stav], tag))
        self.t_zam.nastav(riadky)
        self.t_zam.tree.selection_set(self.t_zam.tree.get_children())
        self.lbl.config(text=f"Zobrazených {len(riadky)} z {len(self.nacitani)} načítaných osôb.")

    def uloz(self):
        sel = self.t_zam.vybrane()
        if not sel:
            messagebox.showinfo("UIS", "Najprv načítajte zamestnancov a vyberte, koho uložiť.", parent=self)
            return
        polozky = [(z, fak, self._nazov_ustavu(p)) for z, fak, p in (self.nacitani[int(i)] for i in sel)]
        res = self.uis.zluc_do_databazy(self.db, polozky)
        self.on_done()
        self.zobraz()
        messagebox.showinfo("Uložené", res.sprava(), parent=self)


# ====================================================================== záverečné práce z UIS
class UISZaverecnePraceDialog(tk.Toplevel):
    """Obhájené záverečné práce zo zoznamu na is.uniag.sk/zp/ priradené vedúcim (učiteľom v databáze)."""

    def __init__(self, master, db: Databaza, ak_roky: list[str], params: dict, on_done):
        from . import uis_web
        self.uis = uis_web
        super().__init__(master)
        self.title("Záverečné práce z UIS (is.uniag.sk/zp)")
        self.geometry("980x640")
        self.transient(master)
        self.db, self.params, self.on_done = db, params, on_done
        self.q: queue.Queue = queue.Queue()
        self.fakulty: list = []
        self.priradenia: list = []
        self.mimo: dict = {}

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Fakulta:").grid(row=0, column=0, sticky="w")
        self.var_fak = tk.StringVar()
        self.cb_fak = ttk.Combobox(top, textvariable=self.var_fak, state="readonly", width=44)
        self.cb_fak.grid(row=0, column=1, sticky="w")
        ttk.Label(top, text="Akademické roky:").grid(row=0, column=2, sticky="e", padx=(16, 4))
        self.var_roky = tk.StringVar(value=", ".join(ak_roky))
        ttk.Entry(top, textvariable=self.var_roky, width=26).grid(row=0, column=3, sticky="w")
        ttk.Button(top, text="⬇ Načítať práce", style="Accent.TButton", command=self.nacitaj).grid(row=0, column=4, padx=10)
        ttk.Label(top, foreground="#666", text=(
            "Započítajú sa iba obhájené bakalárske, diplomové a dizertačné práce, ktorých vedúci je v databáze učiteľov "
            "(podľa ID v UIS alebo mena). Roky sú prevzaté zo sledovaného obdobia.")).grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        self.tab = Tabulka(self, [("uc", "Učiteľ (vedúci)", 280), ("ak", "Ak. rok", 90), ("st", "Stupeň", 70),
                                  ("n", "Počet prác", 80), ("h", "Hodiny (tab. 1)", 100)], height=18)
        self.tab.pack(fill="both", expand=True, padx=10)
        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        self.lbl = ttk.Label(dole, text="Načítavam zoznam fakúlt…")
        self.lbl.pack(side="left")
        ttk.Button(dole, text="Zavrieť", command=self.destroy).pack(side="right")
        ttk.Button(dole, text="💾 Uložiť do databázy", style="Accent.TButton", command=self.uloz).pack(side="right", padx=6)
        self.btn_mimo = ttk.Button(dole, text="Vedúci mimo databázy…", command=self.ukaz_mimo, state="disabled")
        self.btn_mimo.pack(side="right")
        _centruj(self, master)
        self._spusti(self.uis.fakulty, self._fakulty_hotove)

    def _spusti(self, funkcia, hotovo, *args):
        def praca():
            try:
                self.q.put((True, hotovo, funkcia(*args)))
            except Exception as e:  # noqa: BLE001
                self.q.put((False, hotovo, e))
        threading.Thread(target=praca, daemon=True).start()
        self._poll()

    def _poll(self):
        try:
            ok, hotovo, vysl = self.q.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(200, self._poll)
            return
        if not ok:
            self.lbl.config(text="Chyba pri načítaní.")
            messagebox.showerror("UIS", str(vysl), parent=self)
            return
        hotovo(vysl)

    def _fakulty_hotove(self, fakulty):
        self.fakulty = fakulty
        self.cb_fak["values"] = [f.nazov for f in fakulty]
        tf = next((i for i, f in enumerate(fakulty) if f.id == 30), 0 if fakulty else None)
        if tf is not None:
            self.cb_fak.current(tf)
        self.lbl.config(text="Skontrolujte roky a kliknite na Načítať práce.")

    def nacitaj(self):
        f = next((x for x in self.fakulty if x.nazov == self.var_fak.get()), None)
        roky = [importy.to_ak_rok(x) for x in self.var_roky.get().replace(";", ",").split(",") if x.strip()]
        if not f or not roky:
            messagebox.showwarning("UIS", "Vyberte fakultu a zadajte akademické roky (napr. 2023/2024, 2024/2025).", parent=self)
            return
        ucitelia = self.db.nacitaj("ucitelia")
        if not ucitelia:
            messagebox.showinfo("UIS", "V databáze nie sú učitelia. Najprv ich načítajte (Učitelia z UIS).", parent=self)
            return

        def praca():
            prace = self.uis.zaverecne_prace(f.id, roky)
            return prace, self.uis.prirad_ucitelom(prace, ucitelia)

        self.lbl.config(text="Načítavam záverečné práce…")
        self._spusti(praca, self._hotovo)

    def _hotovo(self, vysl):
        prace, (self.priradenia, self.mimo) = vysl
        hod = self.params["hodiny_zaverecna_praca"]
        self.tab.nastav([(i, [s.ucitel, s.ak_rok, s.stupen, len(s.prace), fmt(len(s.prace) * hod.get(s.stupen, 0), 0)], ())
                         for i, s in enumerate(self.priradenia)])
        obh = sum(1 for p in prace if p.obhajena and p.stupen)
        prir = sum(len(s.prace) for s in self.priradenia)
        self.lbl.config(text=f"Obhájených prác: {obh}, priradených učiteľom v databáze: {prir}, "
                             f"vedúci mimo databázy: {len(self.mimo)}.")
        self.btn_mimo.config(state="normal" if self.mimo else "disabled")

    def ukaz_mimo(self):
        t = "\n".join(f"{m}: {n}" for m, n in sorted(self.mimo.items(), key=lambda x: -x[1]))
        messagebox.showinfo("Vedúci mimo databázy",
                            "Tieto práce viedli osoby, ktoré nie sú medzi učiteľmi v databáze "
                            "(napr. z iných ústavov alebo externí):\n\n" + t, parent=self)

    def uloz(self):
        if not self.priradenia:
            return
        n = self.uis.uloz_zaverecne_prace(self.db, self.priradenia)
        self.on_done()
        messagebox.showinfo("Uložené", f"Uložených {n} záverečných prác. Práce načítané z UIS skôr pre tých istých "
                                       "učiteľov a roky boli nahradené, ručne zadané zostali.", parent=self)


# ====================================================================== projekty z UIS
class UISProjektyDialog(tk.Toplevel):
    """Projekty pracoviska z is.uniag.sk/vv/projekty.pl priradené učiteľom podľa čl. 5 metodického pokynu."""

    def __init__(self, master, db: Databaza, roky: list[int], on_done):
        from . import uis_web
        self.uis = uis_web
        super().__init__(master)
        self.title("Projekty z UIS (is.uniag.sk/vv)")
        self.geometry("1100x700")
        self.transient(master)
        self.db, self.on_done = db, on_done
        self.q: queue.Queue = queue.Queue()
        self.pracoviska: list = []
        self.projekty: list = []          # ProjektUIS v sledovaných rokoch so započítaným stavom
        self.kategorie: dict[str, str] = {}

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Pracovisko:").grid(row=0, column=0, sticky="w")
        self.var_prac = tk.StringVar()
        self.cb_prac = ttk.Combobox(top, textvariable=self.var_prac, state="readonly", width=58)
        self.cb_prac.grid(row=0, column=1, sticky="w")
        ttk.Label(top, text="Kalendárne roky:").grid(row=0, column=2, sticky="e", padx=(16, 4))
        self.var_roky = tk.StringVar(value=", ".join(map(str, roky)))
        ttk.Entry(top, textvariable=self.var_roky, width=20).grid(row=0, column=3, sticky="w")
        ttk.Button(top, text="1 ⬇ Načítať zoznam projektov", command=self.nacitaj_zoznam).grid(row=0, column=4, padx=10)
        ttk.Label(top, foreground="#555", wraplength=1060, justify="left", text=(
            "Podľa čl. 5 sa berú 3 posledné verifikované kalendárne roky a externé projekty podľa pozn. 8 (výskumné, "
            "štrukturálne fondy, Erasmus+ KA2, APVV, VEGA, KEGA, verejná správa, iné subjekty). Započítajú sa projekty "
            "v stave riešený alebo ukončený. Zodpovedný riešiteľ = garant v UIS; riešitelia = úloha Riešiteľ alebo "
            "Metodický riešiteľ. Kategóriu druhu zmeníte dvojklikom.")).grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=6)
        f1 = ttk.LabelFrame(pw, text=" Druhy projektov a ich zaradenie podľa pokynu ", padding=4)
        self.t_druhy = Tabulka(f1, [("druh", "Druh projektu v UIS", 470), ("n", "Projektov", 70),
                                    ("kat", "Kategória podľa pokynu", 300), ("vys", "Výskumný (2× zodp. riešiteľ)", 170)],
                               height=9, on_double=self.zmen_kategoriu)
        self.t_druhy.pack(fill="both", expand=True)
        self.t_druhy.tree.tag_configure("vyl", foreground="#999")
        pw.add(f1, weight=2)
        f2 = ttk.LabelFrame(pw, text=" Projekty ", padding=4)
        self.t_proj = Tabulka(f2, [("kod", "Kód", 120), ("na", "Názov", 380), ("od", "Od", 50), ("do", "Do", 50),
                                   ("stav", "Stav", 80), ("kat", "Kategória", 220), ("gar", "Garant", 140)], height=9)
        self.t_proj.pack(fill="both", expand=True)
        self.t_proj.tree.tag_configure("vyl", foreground="#999")
        pw.add(f2, weight=3)

        dole = ttk.Frame(self, padding=10)
        dole.pack(fill="x")
        self.pb = ttk.Progressbar(dole, length=200, mode="determinate")
        self.pb.pack(side="left")
        self.lbl = ttk.Label(dole, text="Načítavam zoznam pracovísk…")
        self.lbl.pack(side="left", padx=8)
        ttk.Button(dole, text="Zavrieť", command=self.destroy).pack(side="right")
        self.btn_uloz = ttk.Button(dole, text="2 💾 Načítať riešiteľov a uložiť", style="Accent.TButton",
                                   command=self.uloz, state="disabled")
        self.btn_uloz.pack(side="right", padx=6)
        _centruj(self, master)
        self._spusti(self.uis.pracoviska_projektov, self._pracoviska_hotove)

    # ---------------------------------------------------------------- vlákna
    def _spusti(self, funkcia, hotovo, *args):
        def praca():
            try:
                self.q.put(("ok", hotovo, funkcia(*args)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", hotovo, e))
        threading.Thread(target=praca, daemon=True).start()
        self._poll()

    def _poll(self):
        try:
            while True:
                druh, a, b = self.q.get_nowait()
                if druh == "p":
                    self.pb["maximum"], self.pb["value"] = b, a
                    self.lbl.config(text=f"Načítavam riešiteľov… {a} / {b}")
                    continue
                if druh == "err":
                    self.lbl.config(text="Chyba pri načítaní.")
                    self.btn_uloz.config(state="normal" if self.projekty else "disabled")
                    messagebox.showerror("UIS", str(b), parent=self)
                    return
                a(b)
                return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(200, self._poll)

    # ---------------------------------------------------------------- pracoviská a zoznam
    def _pracoviska_hotove(self, prac):
        self.pracoviska = prac
        self.cb_prac["values"] = [("      " * uroven) + nazov for _, nazov, uroven in prac]
        tf = next((i for i, (pid, _, _) in enumerate(prac) if pid == 30), 0 if prac else None)
        if tf is not None:
            self.cb_prac.current(tf)
        self.lbl.config(text="Vyberte pracovisko (fakultu alebo ústav) a načítajte zoznam projektov.")

    def _roky(self) -> list[int]:
        out = []
        for x in self.var_roky.get().replace(";", ",").split(","):
            x = x.strip()
            if "-" in x:
                a, b = x.split("-", 1)
                out.extend(range(int(a), int(b) + 1))
            elif x:
                out.append(int(x))
        return sorted(set(out))

    def nacitaj_zoznam(self):
        i = self.cb_prac.current()
        try:
            roky = self._roky()
        except ValueError:
            roky = []
        if i < 0 or not roky:
            messagebox.showwarning("UIS", "Vyberte pracovisko a zadajte kalendárne roky (napr. 2023, 2024, 2025).", parent=self)
            return
        pid = self.pracoviska[i][0]
        self.lbl.config(text="Načítavam zoznam projektov…")
        self.btn_uloz.config(state="disabled")
        self._spusti(self.uis.zoznam_projektov, self._zoznam_hotovy, pid)

    def _zoznam_hotovy(self, zoznam):
        roky = self._roky()
        self.projekty = [p for p in zoznam if p.zapocitany_stav and p.roky(roky)]
        for p in self.projekty:
            self.kategorie.setdefault(p.druh, self.uis.kategoria_projektu(p.druh))
        self.zobraz()
        self.lbl.config(text=f"V UIS {len(zoznam)} projektov pracoviska, v rokoch {', '.join(map(str, roky))} "
                             f"riešených alebo ukončených: {len(self.projekty)}.")
        self.btn_uloz.config(state="normal" if self.projekty else "disabled")

    def _kat(self, p) -> str:
        return config.NEZAPOCITAT if self.uis.je_interny_grant(p.kod) else self.kategorie.get(p.druh, "")

    def zobraz(self):
        from collections import Counter
        vys = set(config.load_parametre()["vyskumne_typy_projektov"])
        pocty = Counter(p.druh for p in self.projekty)
        riadky = []
        for i, (druh, n) in enumerate(sorted(pocty.items(), key=lambda x: (-x[1], x[0]))):
            kat = self.kategorie.get(druh, "")
            riadky.append((i, [druh, n, kat, "áno" if kat in vys else ""], ("vyl",) if kat == config.NEZAPOCITAT else ()))
        self._druhy_poradie = [r[1][0] for r in riadky]
        self.t_druhy.nastav(riadky)
        self.t_proj.nastav([(i, [p.kod, p.nazov, p.od, p.do, p.stav, self._kat(p), p.garant_meno],
                             ("vyl",) if self._kat(p) == config.NEZAPOCITAT else ())
                            for i, p in enumerate(self.projekty)])

    def zmen_kategoriu(self):
        sel = self.t_druhy.vybrane()
        if not sel:
            return
        druh = self._druhy_poradie[int(sel[0])]

        def ok(h):
            self.kategorie[druh] = h["kat"]
            self.zobraz()
            return None
        Formular(self, "Kategória podľa pokynu", [("kat", druh[:60], "combo_strict",
                                                   [config.NEZAPOCITAT, *config.TYPY_PROJEKTOV])],
                 {"kat": self.kategorie.get(druh, "")}, ok)

    # ---------------------------------------------------------------- uloženie
    def uloz(self):
        if not self.db.nacitaj("ucitelia"):
            messagebox.showinfo("UIS", "V databáze nie sú učitelia. Najprv ich načítajte (Učitelia z UIS).", parent=self)
            return
        vybrane = [p for p in self.projekty if self._kat(p) != config.NEZAPOCITAT]
        roky, kategorie = self._roky(), dict(self.kategorie)
        self.btn_uloz.config(state="disabled")

        def praca():   # vo vlákne iba sťahovanie; databáza sa zapisuje v hlavnom vlákne
            for i, p in enumerate(vybrane, start=1):
                self.uis.detail_projektu(p)
                self.q.put(("p", i, len(vybrane)))
            return vybrane

        def hotovo(nacitane):
            res = self.uis.uloz_projekty(self.db, nacitane, kategorie, roky)
            self.pb["value"] = 0
            self.btn_uloz.config(state="normal")
            self.lbl.config(text=f"Hotovo – {res.projekty_roky} záznamov projekt × rok.")
            self.on_done()
            messagebox.showinfo("Projekty uložené", res.sprava(), parent=self)
        self._spusti(praca, hotovo)
