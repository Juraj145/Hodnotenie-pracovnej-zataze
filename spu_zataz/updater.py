"""Automatické aktualizácie z GitHub Releases.

Program beží v jednom z troch režimov:
  * „python“ – rozbalený balík SPU-Zataz-python.zip spúšťaný cez nainštalovaný Python
               (súbor SPU-Zataz.pyw). Tento spôsob neblokuje inteligentné riadenie aplikácií,
               lebo Python je podpísaný. Aktualizácia stiahne nový zip a vymení priečinky.
  * „exe“    – zostavený SPU-Zataz.exe. Bežiaci exe sa premenuje, nový sa dá na jeho miesto.
  * „zdroj“  – spustenie z git repozitára (vývoj) – aktualizuje sa cez git pull.

Pred výmenou sa vždy overí kontrolný súčet SHA-256 (súbor <názov>.sha256 v tom istom vydaní).
Staré verzie sa zmažú pri ďalšom štarte (funkcia upratanie).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .version import EXE_ASSET_NAME, GITHUB_OWNER, GITHUB_REPO, ZIP_ASSET_NAME, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

KOREN = Path(__file__).resolve().parent.parent       # priečinok s programom
SPUSTAC = "SPU-Zataz.pyw"
POLOZKY_BALIKA = ("spu_zataz", "lib", "assets", SPUSTAC, "NAVOD.txt")
STARA_PRIPONA = ".stara"


@dataclass
class Subor:
    url: str
    velkost: int
    url_sha256: Optional[str]


@dataclass
class Vydanie:
    verzia: str
    poznamky: str
    url_stranky: str
    subory: dict[str, Subor] = field(default_factory=dict)

    @property
    def url_exe(self) -> Optional[str]:   # spätná kompatibilita
        s = self.subory.get(EXE_ASSET_NAME)
        return s.url if s else None


def parse_verzia(v: str) -> tuple:
    v = v.strip().lstrip("vV")
    out = []
    for part in v.split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def je_novsia(nova: str, aktualna: str = __version__) -> bool:
    return parse_verzia(nova) > parse_verzia(aktualna)


def je_exe() -> bool:
    return bool(getattr(sys, "frozen", False))


def rezim() -> str:
    if je_exe():
        return "exe"
    if (KOREN / ".git").exists():
        return "zdroj"
    if (KOREN / SPUSTAC).exists():
        return "python"
    return "zdroj"


def potrebny_subor() -> Optional[str]:
    return {"exe": EXE_ASSET_NAME, "python": ZIP_ASSET_NAME}.get(rezim())


def vie_aktualizovat(v: Vydanie) -> bool:
    n = potrebny_subor()
    return bool(n and n in v.subory and (rezim() == "python" or sys.platform.startswith("win")))


def _request(url: str, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"SPU-Zataz/{__version__}"})
    return urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context())


def posledne_vydanie() -> Optional[Vydanie]:
    with _request(API_URL) as r:
        d = json.loads(r.read().decode("utf-8"))
    assets = {a.get("name"): a for a in d.get("assets", [])}
    v = Vydanie(verzia=d.get("tag_name", "0"), poznamky=d.get("body", "") or "",
                url_stranky=d.get("html_url", RELEASES_URL))
    for name, a in assets.items():
        if name and not name.endswith(".sha256"):
            sha = assets.get(name + ".sha256")
            v.subory[name] = Subor(a.get("browser_download_url"), int(a.get("size", 0)),
                                   sha.get("browser_download_url") if sha else None)
    return v


def skontroluj() -> Optional[Vydanie]:
    """Vráti vydanie, ak je novšie ako bežiaca verzia, inak None. Chyby siete ticho ignoruje."""
    try:
        v = posledne_vydanie()
    except Exception:  # noqa: BLE001 – bez internetu program normálne beží ďalej
        return None
    if v and je_novsia(v.verzia):
        return v
    return None


def _ciel_stahovania(nazov: str) -> Path:
    if rezim() == "exe":
        return Path(sys.executable).with_name(nazov + ".new")
    if rezim() == "python":
        return KOREN / (nazov + ".new")
    return Path(tempfile.gettempdir()) / (nazov + ".new")


def stiahni(v: Vydanie, progress: Optional[Callable[[int, int], None]] = None) -> Path:
    nazov = potrebny_subor() or EXE_ASSET_NAME
    s = v.subory.get(nazov)
    if not s:
        raise RuntimeError("Vydanie neobsahuje súbor " + nazov)
    ciel = _ciel_stahovania(nazov)
    h = hashlib.sha256()
    with _request(s.url, "application/octet-stream") as r, open(ciel, "wb") as f:
        total = int(r.headers.get("Content-Length") or s.velkost or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if s.velkost and ciel.stat().st_size != s.velkost:
        ciel.unlink(missing_ok=True)
        raise RuntimeError("Stiahnutý súbor má nesprávnu veľkosť, aktualizácia bola zrušená.")
    if s.url_sha256:
        with _request(s.url_sha256, "text/plain") as r:
            ocakavany = r.read().decode("utf-8").split()[0].strip().lower()
        if ocakavany != h.hexdigest():
            ciel.unlink(missing_ok=True)
            raise RuntimeError("Kontrolný súčet SHA-256 nesedí, aktualizácia bola zrušená.")
    return ciel


# ------------------------------------------------------------------ výmena a reštart

def _stara_cesta(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".old" + exe.suffix)


def _spusti_odpojene(prikaz: list[str], cwd: Path, env: Optional[dict] = None):
    kw: dict = {"cwd": str(cwd), "close_fds": True}
    if env is not None:
        kw["env"] = env
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(prikaz, **kw)


def _pythonw() -> str:
    exe = Path(sys.executable)
    if sys.platform.startswith("win") and exe.name.lower() == "python.exe":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def nainstaluj_a_restartuj(novy: Path, argumenty: Optional[list[str]] = None) -> None:
    """Vymení program za stiahnutú verziu a spustí ju. Potom treba bežiaci program hneď ukončiť."""
    r = rezim()
    if r == "exe":
        _vymen_exe(novy, argumenty)
    elif r == "python":
        _vymen_balik(novy)
        _spusti_odpojene([_pythonw(), str(KOREN / SPUSTAC), *(argumenty or [])], KOREN)
    else:
        raise RuntimeError("Program beží zo zdrojového kódu (git) – aktualizujte ho príkazom 'git pull'.")


def _vymen_exe(novy: Path, argumenty: Optional[list[str]]) -> None:
    """Windows nedovolí bežiaci .exe prepísať ani zmazať, ale dovolí ho premenovať."""
    if not sys.platform.startswith("win"):
        raise RuntimeError("Výmena .exe je možná iba vo Windows.")
    exe = Path(sys.executable)
    stary = _stara_cesta(exe)
    try:
        stary.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        os.replace(exe, stary)
    except OSError as e:
        raise RuntimeError(f"Program sa nedá premenovať ({e}). Ak je v priečinku bez práva zápisu "
                           f"(napr. Program Files), presuňte ho napr. do Dokumentov.") from e
    try:
        os.replace(novy, exe)
    except OSError as e:
        os.replace(stary, exe)
        raise RuntimeError(f"Novú verziu sa nepodarilo presunúť na miesto: {e}") from e
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEI", "_PYI", "_PYINSTALLER"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    _spusti_odpojene([str(exe), *(argumenty or [])], exe.parent, env)


def _vymen_balik(zip_cesta: Path) -> None:
    """Rozbalí nový balík a vymení priečinky programu. Bežiaci Python má moduly už načítané,
    takže súbory sa dajú premenovať; staré kópie (*.stara) sa zmažú pri ďalšom štarte."""
    docasny = KOREN / "_aktualizacia"
    shutil.rmtree(docasny, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_cesta) as z:
            for meno in z.namelist():   # ochrana pred cestami mimo priečinka
                cesta = (docasny / meno).resolve()
                if not str(cesta).startswith(str(docasny.resolve())):
                    raise RuntimeError("Neplatný obsah balíka aktualizácie.")
            z.extractall(docasny)
    except zipfile.BadZipFile as e:
        raise RuntimeError("Stiahnutý balík je poškodený.") from e
    if not (docasny / "spu_zataz").is_dir() or not (docasny / SPUSTAC).exists():
        shutil.rmtree(docasny, ignore_errors=True)
        raise RuntimeError("Balík aktualizácie nemá očakávaný obsah.")

    hotove: list[tuple[Path, Optional[Path]]] = []   # (cieľ, stará kópia) – na vrátenie pri chybe
    try:
        for meno in POLOZKY_BALIKA:
            novy = docasny / meno
            if not novy.exists():
                continue
            ciel = KOREN / meno
            stara = None
            if ciel.exists():
                stara = KOREN / f"{meno}{STARA_PRIPONA}{int(time.time())}"
                os.replace(ciel, stara)
            os.replace(novy, ciel)
            hotove.append((ciel, stara))
    except OSError as e:
        for ciel, stara in reversed(hotove):
            try:
                if ciel.is_dir():
                    shutil.rmtree(ciel, ignore_errors=True)
                else:
                    ciel.unlink(missing_ok=True)
                if stara:
                    os.replace(stara, ciel)
            except OSError:
                pass
        raise RuntimeError(f"Aktualizáciu sa nepodarilo dokončiť, pôvodná verzia zostala: {e}") from e
    finally:
        shutil.rmtree(docasny, ignore_errors=True)
        try:
            zip_cesta.unlink(missing_ok=True)
        except OSError:
            pass


def upratanie(cakat_sekund: float = 0.0) -> bool:
    """Zmaže pozostatky po aktualizácii. Vráti True, ak nič nezostalo."""
    r = rezim()
    if r == "exe":
        exe = Path(sys.executable)
        zostatky = [_stara_cesta(exe), exe.with_name(exe.name + ".new")]
    elif r == "python":
        zostatky = [p for p in KOREN.iterdir() if STARA_PRIPONA in p.name or p.name.endswith(".new")]
    else:
        return True
    koniec = time.time() + cakat_sekund
    while True:
        for f in zostatky:
            try:
                if f.is_dir():
                    shutil.rmtree(f)
                else:
                    f.unlink(missing_ok=True)
            except OSError:
                pass
        if not any(f.exists() for f in zostatky) or time.time() >= koniec:
            return not any(f.exists() for f in zostatky)
        time.sleep(0.5)


def samotest(argv: list[str]) -> int:
    """Test výmeny programu (spúšťa ho GitHub Actions po zostavení).

    … --test-aktualizacie <súbor> [<balík.zip>]  → nainštaluje „novú verziu“ (kópiu exe alebo zadaný zip)
    … --test-aktualizacie <súbor> --pokracovanie → nová verzia zapíše výsledok upratania do súboru
    """
    i = argv.index("--test-aktualizacie")
    vystup = Path(argv[i + 1])
    if "--pokracovanie" in argv:
        ok = upratanie(cakat_sekund=20)
        vystup.write_text(f"verzia={__version__}\nrezim={rezim()}\nupratane={ok}\n", encoding="utf-8")
        return 0
    if rezim() == "exe":
        novy = Path(sys.executable).with_name(EXE_ASSET_NAME + ".new")
        shutil.copy2(sys.executable, novy)
    else:
        zdroj = Path(argv[i + 2])
        novy = _ciel_stahovania(ZIP_ASSET_NAME)
        shutil.copy2(zdroj, novy)
    nainstaluj_a_restartuj(novy, ["--test-aktualizacie", str(vystup), "--pokracovanie"])
    return 0
