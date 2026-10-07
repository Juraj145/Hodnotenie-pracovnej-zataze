"""Zostaví balík SPU-Zataz-python.zip (spustenie cez nainštalovaný Python).

Použitie:  python tools/zostav_balik.py <priečinok s knižnicami> <výstupný zip>
Knižnice pripravíte príkazom:  pip install --target build/lib openpyxl
"""

import sys
import zipfile
from pathlib import Path

KOREN = Path(__file__).resolve().parent.parent


def pridaj(z: zipfile.ZipFile, zdroj: Path, nazov: str):
    if zdroj.is_dir():
        for f in sorted(zdroj.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix not in (".pyc", ".exe"):
                z.write(f, f"{nazov}/{f.relative_to(zdroj).as_posix()}")
    else:
        z.write(zdroj, nazov)


def main(lib: Path, vystup: Path):
    if not (lib / "openpyxl").is_dir():
        raise SystemExit(f"V {lib} chýba openpyxl")
    vystup.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(vystup, "w", zipfile.ZIP_DEFLATED) as z:
        pridaj(z, KOREN / "SPU-Zataz.pyw", "SPU-Zataz.pyw")
        pridaj(z, KOREN / "NAVOD.txt", "NAVOD.txt")
        pridaj(z, KOREN / "spu_zataz", "spu_zataz")
        pridaj(z, KOREN / "assets", "assets")
        pridaj(z, lib, "lib")
    print(f"{vystup} ({vystup.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
