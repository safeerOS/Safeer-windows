"""PyInstaller entry point for SafeerOS.exe."""
import sys

# libmpv (pravilo 6): runtime iz paketa vendor/mpv/runtime v proces PRED PySide6; brez paketa no-op.
try:
    from safeer_windows.safeer_mpv_pogon import predpripravi_runtime
    predpripravi_runtime()
except Exception:
    pass

# Safeer Player (bliznjica »SafeerOS.exe --predvajalnik«): os_app.main odpre samo Medijski center (naloga 39, 27. 10.
# 2026 - prej je ta zastavica odprla samostojni predvajalnik datotek). Ta je zdaj pod »--datoteka [pot|URL ...]«.
if "--datoteka" in sys.argv:
    sys.argv.remove("--datoteka")
    from safeer_windows.safeer_predvajalnik import main  # noqa: E402
else:
    from safeer_windows.os_app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
