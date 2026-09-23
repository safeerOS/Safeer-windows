"""PyInstaller entry point for SafeerOS.exe."""
import sys

from safeer_windows.os_app import main

if __name__ == "__main__":
    sys.exit(main())
