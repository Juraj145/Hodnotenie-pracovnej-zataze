"""Spúšťač programu Hodnotenie pracovnej záťaže VŠ učiteľov SPU v Nitre."""

import sys

if __name__ == "__main__":
    if "--test-aktualizacie" in sys.argv:
        # samotest výmeny exe (GitHub Actions), bez grafického rozhrania
        from spu_zataz.updater import samotest
        sys.exit(samotest(sys.argv))
    from spu_zataz.gui import main
    main()
