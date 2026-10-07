"""Lokálna databáza (SQLite) v priečinku s dátami používateľa."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional

from .config import app_data_dir
from .models import (Data, Projekt, ProjektUcast, Publikacia, Ucitel, Vyucba,
                     ZaverecnaPraca)

TABULKY = {
    "ucitelia": Ucitel,
    "vyucba": Vyucba,
    "zaverecne_prace": ZaverecnaPraca,
    "publikacie": Publikacia,
    "projekty": Projekt,
    "ucasti": ProjektUcast,
}

# závislé tabuľky, ktoré sa mažú spolu s nadradeným záznamom
_ZAVISLOSTI = {
    "ucitelia": [("vyucba", "ucitel_id"), ("zaverecne_prace", "ucitel_id"),
                 ("publikacie", "ucitel_id"), ("ucasti", "ucitel_id")],
    "projekty": [("ucasti", "projekt_id")],
}


def _sql_type(py_type) -> str:
    t = str(py_type)
    if "bool" in t or "int" in t:
        return "INTEGER"
    if "float" in t:
        return "REAL"
    return "TEXT"


def tabulka_pre(obj) -> str:
    for name, cls in TABULKY.items():
        if isinstance(obj, cls):
            return name
    raise TypeError(type(obj))


class Databaza:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else app_data_dir() / "data.db"
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        for name, cls in TABULKY.items():
            cols = []
            for f in fields(cls):
                if f.name == "id":
                    cols.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
                else:
                    cols.append(f"{f.name} {_sql_type(f.type)}")
            cur.execute(f"CREATE TABLE IF NOT EXISTS {name} ({', '.join(cols)})")
            # doplnenie stĺpcov pridaných v novších verziách
            existing = {r[1] for r in cur.execute(f"PRAGMA table_info({name})")}
            for f in fields(cls):
                if f.name not in existing:
                    cur.execute(f"ALTER TABLE {name} ADD COLUMN {f.name} {_sql_type(f.type)}")
        self.conn.commit()

    # ------------------------------------------------------------ čítanie
    def nacitaj(self, tabulka: str) -> list:
        return self.nacitaj_where(tabulka, "1 = 1 ORDER BY id", ())

    def nacitaj_vsetko(self) -> Data:
        return Data(**{name: self.nacitaj(name) for name in TABULKY})

    def najdi_ucitela(self, osobne_cislo: str = "", meno: str = "") -> Optional[Ucitel]:
        if osobne_cislo:
            r = self.conn.execute("SELECT id FROM ucitelia WHERE osobne_cislo = ?", (str(osobne_cislo).strip(),)).fetchone()
            if r:
                return self.ziskaj("ucitelia", r["id"])
            # osobné číslo je jednoznačné – menovci s iným číslom sú iné osoby;
            # podľa mena sa doplní iba učiteľ, ktorý osobné číslo ešte nemá
            if meno:
                r = self.conn.execute(
                    "SELECT id FROM ucitelia WHERE lower(trim(meno)) = lower(trim(?)) AND coalesce(osobne_cislo, '') = ''",
                    (meno,)).fetchone()
                return self.ziskaj("ucitelia", r["id"]) if r else None
            return None
        if meno:
            r = self.conn.execute("SELECT id FROM ucitelia WHERE lower(trim(meno)) = lower(trim(?))", (meno,)).fetchone()
            if r:
                return self.ziskaj("ucitelia", r["id"])
        return None

    def najdi_projekt(self, kod: str, rok: int) -> Optional[Projekt]:
        r = self.conn.execute("SELECT id FROM projekty WHERE kod = ? AND rok = ?", (kod, int(rok))).fetchone()
        return self.ziskaj("projekty", r["id"]) if r else None

    def ziskaj(self, tabulka: str, id_: int):
        for o in self.nacitaj_where(tabulka, "id = ?", (id_,)):
            return o
        return None

    def nacitaj_where(self, tabulka: str, where: str, args: tuple) -> list:
        cls = TABULKY[tabulka]
        out = []
        for row in self.conn.execute(f"SELECT * FROM {tabulka} WHERE {where}", args):
            keys = row.keys()
            kw = {f.name: row[f.name] for f in fields(cls) if f.name in keys and row[f.name] is not None}
            for f in fields(cls):
                if f.type in ("bool", bool) and f.name in kw:
                    kw[f.name] = bool(kw[f.name])
            out.append(cls(**kw))
        return out

    # ------------------------------------------------------------ zápis
    def uloz(self, obj, commit: bool = True):
        """Vloží nový záznam (id=None) alebo aktualizuje existujúci. Vráti id."""
        tab = tabulka_pre(obj)
        d = asdict(obj)
        id_ = d.pop("id")
        if id_ is None:
            cols = ", ".join(d)
            cur = self.conn.execute(f"INSERT INTO {tab} ({cols}) VALUES ({', '.join('?' * len(d))})", tuple(d.values()))
            obj.id = cur.lastrowid
        else:
            sets = ", ".join(f"{k} = ?" for k in d)
            self.conn.execute(f"UPDATE {tab} SET {sets} WHERE id = ?", (*d.values(), id_))
        if commit:
            self.conn.commit()
        return obj.id

    def zmaz(self, tabulka: str, id_: int, commit: bool = True):
        for dep, col in _ZAVISLOSTI.get(tabulka, []):
            self.conn.execute(f"DELETE FROM {dep} WHERE {col} = ?", (id_,))
        self.conn.execute(f"DELETE FROM {tabulka} WHERE id = ?", (id_,))
        if commit:
            self.conn.commit()

    def vymaz_vsetko(self):
        for name in TABULKY:
            self.conn.execute(f"DELETE FROM {name}")
        self.conn.commit()

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()
