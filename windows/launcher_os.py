"""PyInstaller entry point for SafeerOS.exe."""
import sys

# libmpv (pravilo 6): runtime iz paketa vendor/mpv/runtime v proces PRED PySide6; brez paketa no-op.
try:
    from safeer_windows.safeer_mpv_pogon import predpripravi_runtime
    predpripravi_runtime()
except Exception:
    pass

# Safeer Player (namestitveni program SafeerPlayer, bliznjica »SafeerOS.exe --predvajalnik«): enako kot __main__.py.
# CI 40371933757 (26. 10. 2026): os_app.main zastavice ne pozna - argparse je koncal s kodo 2 pred oknom.
if "--predvajalnik" in sys.argv:
    sys.argv.remove("--predvajalnik")
    from safeer_windows.safeer_predvajalnik import main  # noqa: E402
else:
    from safeer_windows.os_app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
