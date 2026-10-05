"""PyInstaller entry point for SafeerBrowser.exe."""
import sys

from safeer_windows import knjiznice

# Zagon iz zaganjalnika Safeer OS (--browser): knjiznice preveri program sam; v SafeerBrowser.exe se ne preverja nic.
knjiznice.preveri_ob_zagonu()

from safeer_windows.browser import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
