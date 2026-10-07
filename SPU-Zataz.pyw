"""Spúšťač programu Hodnotenie pracovnej záťaže VŠ učiteľov SPU v Nitre.

Spustite dvojklikom (otvorí sa cez nainštalovaný Python bez okna konzoly).
Python 3.10 alebo novší stiahnete z https://www.python.org/downloads/
"""

import os
import sys
import traceback

KOREN = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(KOREN, "lib"))
sys.path.insert(0, KOREN)


def chyba(text):
    try:
        import tkinter
        from tkinter import messagebox
        r = tkinter.Tk()
        r.withdraw()
        messagebox.showerror("SPU – pracovná záťaž", text)
        r.destroy()
    except Exception:
        pass
    try:
        with open(os.path.join(KOREN, "chyba.log"), "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    except OSError:
        pass


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        chyba("Program potrebuje Python 3.10 alebo novší.\nStiahnite ho z https://www.python.org/downloads/")
        sys.exit(1)
    try:
        if "--test-aktualizacie" in sys.argv:
            from spu_zataz.updater import samotest
            sys.exit(samotest(sys.argv))
        from spu_zataz.gui import main
        main()
    except SystemExit:
        raise
    except Exception:
        chyba("Program sa nepodarilo spustiť:\n\n" + traceback.format_exc())
        sys.exit(1)
