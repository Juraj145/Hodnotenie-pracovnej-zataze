"""Automatické aktualizácie z GitHub Releases.

Postup: program sa pri štarte opýta GitHubu na posledné vydanie (release). Ak je novšie,
ponúkne aktualizáciu, stiahne nový .exe vedľa pôvodného, overí kontrolný súčet SHA-256
(súbor SPU-Zataz.exe.sha256 v tom istom vydaní), bežiaci .exe premenuje, nový presunie
na jeho miesto a spustí ho. Stará verzia sa zmaže pri ďalšom štarte.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .version import EXE_ASSET_NAME, GITHUB_OWNER, GITHUB_REPO, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


@dataclass
class Vydanie:
    verzia: str
    poznamky: str
    url_exe: Optional[str]
    velkost: int
    url_sha256: Optional[str]
    url_stranky: str


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


def _request(url: str, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"SPU-Zataz/{__version__}"})
    return urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context())


def posledne_vydanie() -> Optional[Vydanie]:
    with _request(API_URL) as r:
        d = json.loads(r.read().decode("utf-8"))
    exe = next((a for a in d.get("assets", []) if a.get("name") == EXE_ASSET_NAME), None)
    sha = next((a for a in d.get("assets", []) if a.get("name") == EXE_ASSET_NAME + ".sha256"), None)
    return Vydanie(
        verzia=d.get("tag_name", "0"),
        poznamky=d.get("body", "") or "",
        url_exe=exe.get("browser_download_url") if exe else None,
        velkost=int(exe.get("size", 0)) if exe else 0,
        url_sha256=sha.get("browser_download_url") if sha else None,
        url_stranky=d.get("html_url", RELEASES_URL),
    )


def skontroluj() -> Optional[Vydanie]:
    """Vráti vydanie, ak je novšie ako bežiaca verzia, inak None. Chyby siete ticho ignoruje."""
    try:
        v = posledne_vydanie()
    except Exception:  # noqa: BLE001 – bez internetu program normálne beží ďalej
        return None
    if v and je_novsia(v.verzia):
        return v
    return None


def stiahni(v: Vydanie, progress: Optional[Callable[[int, int], None]] = None) -> Path:
    if not v.url_exe:
        raise RuntimeError("Vydanie neobsahuje súbor " + EXE_ASSET_NAME)
    ciel_dir = Path(sys.executable).parent if je_exe() else Path(tempfile.gettempdir())
    ciel = ciel_dir / (EXE_ASSET_NAME + ".new")
    h = hashlib.sha256()
    with _request(v.url_exe, "application/octet-stream") as r, open(ciel, "wb") as f:
        total = int(r.headers.get("Content-Length") or v.velkost or 0)
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
    if v.velkost and ciel.stat().st_size != v.velkost:
        ciel.unlink(missing_ok=True)
        raise RuntimeError("Stiahnutý súbor má nesprávnu veľkosť, aktualizácia bola zrušená.")
    if v.url_sha256:
        with _request(v.url_sha256, "text/plain") as r:
            ocakavany = r.read().decode("utf-8").split()[0].strip().lower()
        if ocakavany != h.hexdigest():
            ciel.unlink(missing_ok=True)
            raise RuntimeError("Kontrolný súčet SHA-256 nesedí, aktualizácia bola zrušená.")
    return ciel


def _stara_cesta(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".old" + exe.suffix)


def nainstaluj_a_restartuj(novy: Path, argumenty: Optional[list[str]] = None) -> None:
    """Vymení exe a spustí novú verziu. Potom treba program hneď ukončiť.

    Windows nedovolí bežiaci .exe prepísať ani zmazať, ale dovolí ho premenovať. Bežiaci súbor sa
    preto premenuje na SPU-Zataz.old.exe, nový sa presunie na jeho miesto a spustí sa. Starý súbor
    zmaže nová verzia pri štarte (funkcia upratanie). Nepoužíva sa žiadny dávkový skript ani okno konzoly.
    """
    if not je_exe() or not sys.platform.startswith("win"):
        raise RuntimeError("Automatická výmena funguje iba pre spustiteľný súbor vo Windows. "
                           "Pri spustení zo zdrojového kódu použite 'git pull'.")
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
        os.replace(stary, exe)   # vrátiť pôvodný stav
        raise RuntimeError(f"Novú verziu sa nepodarilo presunúť na miesto: {e}") from e
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEI", "_PYI", "_PYINSTALLER"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"   # nová verzia si rozbalí vlastné súbory
    flags = 0x00000008 | 0x00000200              # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), *(argumenty or [])], cwd=str(exe.parent), env=env,
                     creationflags=flags, close_fds=True)


def upratanie(cakat_sekund: float = 0.0) -> bool:
    """Zmaže starú verziu po aktualizácii (a nedokončené sťahovanie). Vráti True, ak nič nezostalo."""
    if not je_exe():
        return True
    import time
    exe = Path(sys.executable)
    zostatky = [_stara_cesta(exe), exe.with_name(exe.name + ".new")]
    koniec = time.time() + cakat_sekund
    while True:
        for f in zostatky:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        if not any(f.exists() for f in zostatky) or time.time() >= koniec:
            return not any(f.exists() for f in zostatky)
        time.sleep(0.5)


def samotest(argv: list[str]) -> int:
    """Test výmeny exe na Windows (spúšťa ho GitHub Actions po zostavení).

    SPU-Zataz.exe --test-aktualizacie <súbor>  → skopíruje sa ako „nová verzia“ a vymení sa
    SPU-Zataz.exe --test-aktualizacie <súbor> --pokracovanie → zapíše výsledok upratania do súboru
    """
    import shutil
    vystup = Path(argv[argv.index("--test-aktualizacie") + 1])
    if "--pokracovanie" in argv:
        ok = upratanie(cakat_sekund=20)
        vystup.write_text(f"verzia={__version__}\nupratane={ok}\n", encoding="utf-8")
        return 0
    novy = Path(sys.executable).with_name(EXE_ASSET_NAME + ".new")
    shutil.copy2(sys.executable, novy)
    nainstaluj_a_restartuj(novy, ["--test-aktualizacie", str(vystup), "--pokracovanie"])
    return 0
