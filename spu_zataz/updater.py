"""Automatické aktualizácie z GitHub Releases.

Postup: program sa pri štarte opýta GitHubu na posledné vydanie (release). Ak je novšie,
ponúkne aktualizáciu, stiahne nový .exe vedľa pôvodného, overí kontrolný súčet SHA-256
(súbor SPU-Zataz.exe.sha256 v tom istom vydaní), a malý dávkový skript po zatvorení
programu starý .exe nahradí novým a program znova spustí.
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


def nainstaluj_a_restartuj(novy: Path) -> None:
    """Spustí skript, ktorý po skončení programu nahradí exe a spustí novú verziu. Potom treba program ukončiť."""
    if not je_exe() or not sys.platform.startswith("win"):
        raise RuntimeError("Automatická výmena funguje iba pre spustiteľný súbor vo Windows. "
                           "Pri spustení zo zdrojového kódu použite 'git pull'.")
    exe = Path(sys.executable)
    bat = Path(tempfile.gettempdir()) / "spu_zataz_update.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "set /a pokus=0\r\n"
        ":wait\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        f'tasklist /FI "PID eq {os.getpid()}" 2>nul | find "{os.getpid()}" >nul && goto wait\r\n'
        ":move\r\n"
        "set /a pokus+=1\r\n"
        f'move /y "{novy}" "{exe}" >nul\r\n'
        "if errorlevel 1 (\r\n"
        "  if %pokus% lss 30 (timeout /t 1 /nobreak >nul & goto move)\r\n"
        ")\r\n"
        f'start "" "{exe}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)
