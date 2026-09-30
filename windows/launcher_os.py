"""PyInstaller entry point for SafeerOS.exe."""
import sys

# libmpv (pravilo 6): runtime iz paketa vendor/mpv/runtime v proces PRED PySide6; brez paketa no-op.
try:
    from safeer_windows.safeer_mpv_pogon import predpripravi_runtime
    predpripravi_runtime()
except Exception:
    pass

from safeer_windows.os_app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
