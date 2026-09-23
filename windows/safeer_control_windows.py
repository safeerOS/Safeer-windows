#!/usr/bin/env python3
"""Safeer Control za Windows — samostojen zagon upravljanja naprav in Safeer Linka."""

from __future__ import annotations

import argparse
import os
import sys

# Dodaj pot do paketa
KOREN = os.path.dirname(os.path.abspath(__file__))
if KOREN not in sys.path:
    sys.path.insert(0, KOREN)

from PySide6.QtWidgets import QApplication
from safeer_windows.control_backend import get_backend
from safeer_windows.control_window import SafeerControlWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Safeer Control za Windows")
    parser.add_argument("--ozadje", action="store_true", help="Zazeni v ozadju")
    parser.add_argument("--razdelek", type=str, default="", help="Zacetni razdelek (npr. novaNaprava, daljinec)")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SafeerControl")
    app.setOrganizationName("Safeer")

    backend = get_backend()
    window = SafeerControlWindow(backend=backend)

    if args.razdelek:
        window.pojdi_na_razdelek(args.razdelek)

    if not args.ozadje:
        window.show()
    else:
        backend.povezi_se()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
