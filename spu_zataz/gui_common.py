"""Spoločné prvky grafického rozhrania."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

ZELENA = "#1E4620"
SVETLA = "#EEF4EA"


def fmt(v, des: int = 1) -> str:
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "áno" if v else "nie"
    if isinstance(v, (int, float)):
        s = f"{v:,.{des}f}".replace(",", " ").replace(".", ",")
        return s
    return str(v)


class Tabulka(ttk.Frame):
    """Treeview so scrollbarmi a triedením kliknutím na hlavičku."""

    def __init__(self, master, stlpce: list[tuple[str, str, int]], height: int = 15, on_double: Optional[Callable] = None):
        super().__init__(master)
        self.stlpce = stlpce
        ids = [c[0] for c in stlpce]
        self.tree = ttk.Treeview(self, columns=ids, show="headings", height=height, selectmode="extended")
        for cid, nadpis, sirka in stlpce:
            self.tree.heading(cid, text=nadpis, command=lambda c=cid: self._sort(c))
            self.tree.column(cid, width=sirka, anchor="w" if sirka >= 120 else "center", stretch=sirka >= 120)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._sort_desc: dict[str, bool] = {}
        if on_double:
            self.tree.bind("<Double-1>", lambda e: on_double())

    def nastav(self, riadky: list[tuple[str, list, tuple]]):
        """riadky: (iid, hodnoty, tagy)"""
        self.tree.delete(*self.tree.get_children())
        for iid, vals, tags in riadky:
            self.tree.insert("", "end", iid=str(iid), values=vals, tags=tags)

    def vybrane(self) -> list[str]:
        return list(self.tree.selection())

    def _sort(self, col: str):
        desc = not self._sort_desc.get(col, True)
        self._sort_desc[col] = desc

        def key(iid):
            v = self.tree.set(iid, col)
            try:
                return (0, float(v.replace(" ", "").replace(",", ".").replace("%", "").replace("€", "")))
            except ValueError:
                return (1, v.lower())
        items = sorted(self.tree.get_children(), key=key, reverse=desc)
        for i, iid in enumerate(items):
            self.tree.move(iid, "", i)


class Formular(tk.Toplevel):
    """Dialóg na úpravu záznamu podľa zoznamu polí.

    polia: (kľúč, popis, druh, možnosti) – druh: text, float, int, bool, combo, combo_strict
    combo možnosti: zoznam hodnôt alebo zoznam (hodnota, popis)
    """

    def __init__(self, master, titulok: str, polia: list[tuple], hodnoty: dict, on_ok: Callable[[dict], Optional[str]]):
        super().__init__(master)
        self.title(titulok)
        self.transient(master)
        self.resizable(False, False)
        self.on_ok = on_ok
        self.polia = polia
        self.premenne: dict[str, tk.Variable] = {}
        self.mapy: dict[str, dict] = {}
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        for i, (kluc, popis, druh, moznosti) in enumerate(polia):
            ttk.Label(frm, text=popis).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            val = hodnoty.get(kluc)
            if druh == "bool":
                var = tk.BooleanVar(value=bool(val))
                ttk.Checkbutton(frm, variable=var).grid(row=i, column=1, sticky="w")
            elif druh in ("combo", "combo_strict"):
                if moznosti and isinstance(moznosti[0], tuple):
                    m = {popis_: hodnota for hodnota, popis_ in moznosti}
                    self.mapy[kluc] = m
                    zobrazit = next((p for h, p in moznosti if h == val), "")
                    var = tk.StringVar(value=zobrazit)
                    values = [p for _, p in moznosti]
                else:
                    var = tk.StringVar(value="" if val is None else str(val))
                    values = list(moznosti or [])
                cb = ttk.Combobox(frm, textvariable=var, values=values, width=44,
                                  state="readonly" if druh == "combo_strict" else "normal")
                cb.grid(row=i, column=1, sticky="we")
            else:
                if druh == "float" and isinstance(val, float):
                    val = (f"{val:.4f}".rstrip("0").rstrip(".")).replace(".", ",")
                var = tk.StringVar(value="" if val is None else str(val))
                ttk.Entry(frm, textvariable=var, width=46).grid(row=i, column=1, sticky="we")
            self.premenne[kluc] = var
        btns = ttk.Frame(frm)
        btns.grid(row=len(polia), column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btns, text="Zrušiť", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Uložiť", style="Accent.TButton", command=self._ok).pack(side="right")
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _ok(self):
        from .importy import to_float, to_int
        out = {}
        for kluc, popis, druh, _ in self.polia:
            v = self.premenne[kluc].get()
            if kluc in self.mapy:
                v = self.mapy[kluc].get(v)
            elif druh == "float":
                if str(v).strip() and to_float(v, float("nan")) != to_float(v, float("nan")):
                    messagebox.showerror("Chybná hodnota", f"„{popis}“ musí byť číslo.", parent=self)
                    return
                v = to_float(v)
            elif druh == "int":
                v = to_int(v)
            out[kluc] = v
        chyba = self.on_ok(out)
        if chyba:
            messagebox.showerror("Chyba", chyba, parent=self)
            return
        self.destroy()
