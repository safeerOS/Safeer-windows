"""Safeer Player na Windows = samo Medijski center v svojem oknu, kot na Linuxu (naloga 39, 27. 10. 2026).

Prej je `SafeerOS.exe --predvajalnik` (bliznjica Safeer Player) odprl samostojni predvajalnik datotek
(safeer_predvajalnik.py), lastnik pa je zelel »locen prenos ... samo Safeer media center«.
"""
import os
import runpy
import subprocess
import sys
import tempfile
import textwrap
import types
from pathlib import Path

import pytest

KOREN = Path(__file__).resolve().parents[1]          # windows/
REPO = KOREN.parent


def _vstop(pot: Path, argv: list, monkeypatch) -> tuple:
    """Pozene vstopno tocko z nadomestnima os_app in safeer_predvajalnik; vrne (kateri main, argv ob klicu)."""
    klici = []
    # Tudi browser: brez zastavice __main__.py zazene Safeer Browser - v preizkusu nikoli pravega.
    for ime in ("os_app", "safeer_predvajalnik", "browser"):
        modul = types.ModuleType("safeer_windows." + ime)
        modul.main = (lambda ime=ime: klici.append((ime, list(sys.argv))) or 0)
        monkeypatch.setitem(sys.modules, "safeer_windows." + ime, modul)
    monkeypatch.setattr(sys, "argv", list(argv))
    try:
        g = runpy.run_path(str(pot), run_name="__main__")
        if not klici and "main" in g:
            g["main"]()
    except SystemExit:
        pass
    assert len(klici) == 1, klici
    return klici[0]


@pytest.mark.parametrize("pot", [KOREN / "launcher_os.py", KOREN / "safeer_windows" / "__main__.py"])
def test_predvajalnik_odpre_os_app(pot, monkeypatch):
    ime, argv = _vstop(pot, ["SafeerOS.exe", "--predvajalnik"], monkeypatch)
    assert ime == "os_app"
    assert "--predvajalnik" in argv          # os_app.main iz zastavice ve, da je Safeer Player


@pytest.mark.parametrize("pot", [KOREN / "launcher_os.py", KOREN / "safeer_windows" / "__main__.py"])
def test_datoteka_odpre_samostojni_predvajalnik(pot, monkeypatch):
    ime, argv = _vstop(pot, ["SafeerOS.exe", "--datoteka", "film.mkv"], monkeypatch)
    assert ime == "safeer_predvajalnik"
    assert argv[1:] == ["film.mkv"]           # argv[0] nastavi runpy


def test_os_app_pozna_zastavico_predvajalnik():
    pytest.importorskip("PySide6.QtWebEngineWidgets")
    from safeer_windows import os_app
    assert os_app._parser().parse_args(["--predvajalnik"]).predvajalnik is True
    assert os_app._parser().parse_args(["--player"]).predvajalnik is True
    assert os_app._parser().parse_args([]).predvajalnik is False


def test_okno_predvajalnika_samo_medijski_center():
    from safeer_windows import okno_razdelka as o
    assert o.okno_za("predvajalnik") == ("predvajalnik", "media")
    assert o.naslov_strani("predvajalnik", "sl") == "os/index.html?predvajalnik=1&jezik=sl"
    assert all(o.naslov_okna("predvajalnik", j) == "Safeer Player" for j in o.NASLOVI)
    assert o.okno_za("media") == ("", "media")          # Medijski center iz Safeer OS ostane v glavnem oknu


def test_os_js_nacin_predvajalnika():
    js = (REPO / "assets" / "os" / "os.js").read_text(encoding="utf-8")
    assert "var PREDVAJALNIK = /[?&]predvajalnik=1(?:&|$)/.test(location.search);" in js
    assert 'var RAZDELEK = PREDVAJALNIK ? "media" :' in js
    assert 'if (PREDVAJALNIK && kam.split("#")[0] !== "media") return;' in js


def _okolje(tmp: str) -> dict:
    # Enolicno ime primerka (kot test_en_primerek.py): nikoli ne govorimo s pravim Safeer OS na tem racunalniku.
    return {**os.environ, "QT_QPA_PLATFORM": "offscreen", "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp,
            "SAFEER_PREIZKUS_IME": "SafeerOS-player-%d-%s" % (os.getpid(), os.path.basename(tmp)),
            "PYTHONPATH": str(KOREN)}


def test_player_zahteva_okno_medijskega_centra_in_ne_zapre_safeer_os():
    """Safeer OS tece (druga koda): Player ga ne sme zapreti (»umikam«) ne prebuditi domacega okna."""
    pytest.importorskip("PySide6")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        okolje = _okolje(tmp)
        prva = subprocess.Popen([sys.executable, "-c", textwrap.dedent("""
            import sys
            from PySide6.QtCore import QObject, QTimer
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek
            en_primerek.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            en_primerek.ZAGNANA_KODA = "tekoca"
            app = QApplication(sys.argv)
            zaklep = en_primerek.zakleni()
            assert zaklep is not None
            okno = QObject()
            okno.koncaj_za_posodobitev = lambda: print("UMIK", flush=True)
            okno.prebudi = lambda r: print("PREBUJENO", r, flush=True)
            def player():
                print("PLAYER", flush=True); QTimer.singleShot(500, app.quit)
            okno.odpri_predvajalnik = player
            s = en_primerek.streznik(okno)
            print("PRIPRAVLJENA", flush=True)
            QTimer.singleShot(20000, app.quit)
            app.exec()
        """)], cwd=str(KOREN), env=okolje, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            assert prva.stdout.readline().strip() == "PRIPRAVLJENA"
            druga = subprocess.run([sys.executable, "-c", textwrap.dedent("""
                import sys
                from PySide6.QtWidgets import QApplication
                from safeer_windows import en_primerek
                en_primerek.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
                en_primerek.ZAGNANA_KODA = "nova"
                app = QApplication(sys.argv)
                assert en_primerek.zakleni() is None
                print("IZID", en_primerek.vprasaj_prvo("media", False, predvajalnik=True))
            """)], cwd=str(KOREN), env=okolje, capture_output=True, text=True, timeout=40)
            assert "IZID ok" in druga.stdout, druga.stdout + druga.stderr
            izpis, _ = prva.communicate(timeout=20)
            assert "PLAYER" in izpis and "UMIK" not in izpis and "PREBUJENO" not in izpis, izpis
        finally:
            if prva.poll() is None:
                prva.kill()
