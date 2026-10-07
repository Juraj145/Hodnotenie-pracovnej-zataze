"""Dialógy: import s mapovaním stĺpcov, Scopus/WoS, parametre, aktualizácia."""

from __future__ import annotations

import json
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
        if updater.je_exe() and v.url_exe:
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
                        self.master_root.after(300, self.master_root.destroy)
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
