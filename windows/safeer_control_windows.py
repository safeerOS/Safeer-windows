#!/usr/bin/env python3
"""Safeer Control za Windows — vstopna točka v enotni program Safeer OS (razdelek Control)."""

from __future__ import annotations

import os
import sys

# Dodaj pot do paketa windows/
KOREN = os.path.dirname(os.path.abspath(__file__))
if KOREN not in sys.path:
    sys.path.insert(0, KOREN)

from safeer_windows.os_app import main


def main_control() -> int:
    args = sys.argv[1:]
    if "--control" not in args and "-c" not in args:
        args = ["--control", "--okno"] + args
    return main(args)


if __name__ == "__main__":
    sys.exit(main_control())

