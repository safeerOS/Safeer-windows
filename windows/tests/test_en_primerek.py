"""Safeer OS na Windows tece v eni sami kopiji (27. 9. se jih je ob hkratnem zagonu pognalo sest)."""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

KOREN = Path(__file__).resolve().parents[1]


def _pozeni(koda: str, okolje: dict) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(koda)], cwd=str(KOREN), env=okolje,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def test_druga_kopija_preda_razdelek_prvi_in_se_konca():
    with tempfile.TemporaryDirectory() as tmp:
        okolje = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp,
                  "USER": "preizkus-en-primerek", "USERNAME": "preizkus-en-primerek", "PYTHONPATH": str(KOREN)}
        prva = _pozeni("""
            import sys
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek as os_app
            app = QApplication(sys.argv)
            zaklep = os_app.zakleni()
            assert zaklep is not None
            class Okno:
                def prebudi(self, r):
                    print("PREBUJENO", r, flush=True); app.quit()
            from PySide6.QtCore import QObject
            okno = QObject(); okno.prebudi = Okno().prebudi
            s = os_app.streznik(okno)
            print("PRIPRAVLJENA", flush=True)
            QTimer.singleShot(15000, app.quit)
            app.exec()
        """, okolje)
        assert prva.stdout.readline().strip() == "PRIPRAVLJENA"
        druga = subprocess.run([sys.executable, "-c", textwrap.dedent("""
            import sys
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek as os_app
            app = QApplication(sys.argv)
            assert os_app.zakleni() is None, "druga kopija ne sme dobiti zaklepa"
            print("PREDANO" if os_app.predaj_prvemu("naprave", False) else "NI")
        """)], cwd=str(KOREN), env=okolje, capture_output=True, text=True, timeout=30)
        assert "PREDANO" in druga.stdout, druga.stdout + druga.stderr
        izpis, _ = prva.communicate(timeout=20)
        assert "PREBUJENO naprave" in izpis
